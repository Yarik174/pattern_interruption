"""
Odds fetching service: FlashLive, The Odds API, NHL schedule.

Extracted from app.py to reduce monolith size.
"""
import os
import requests
from datetime import datetime
from typing import Optional

from src.sports_config import SportType, get_leagues_for_sport
from src.nhl_teams import (
    resolve_sport_type, get_sport_slug, get_abbrev_from_full_name,
    build_odds_key, normalize_flash_match,
)

# ── Module state ─────────────────────────────────────────────────────────────

ODDS_API_KEY = os.environ.get('ODDS_API_KEY')

odds_cache = {}
odds_cache_time = None

euro_odds_cache = {}
euro_odds_cache_time = None


# ── FlashLive loader access ──────────────────────────────────────────────────

_flashlive_loader_getter = None


def set_flashlive_loader_getter(getter):
    """Set the callable that returns a FlashLive loader for a sport type."""
    global _flashlive_loader_getter
    _flashlive_loader_getter = getter


def _get_flashlive_loader(sport_type=None):
    if _flashlive_loader_getter is None:
        return None
    return _flashlive_loader_getter(sport_type)


# ── Legacy NHL odds ──────────────────────────────────────────────────────────

def _fetch_legacy_nhl_odds():
    """Legacy fallback: получить коэффициенты NHL из The Odds API."""
    global odds_cache, odds_cache_time

    if odds_cache_time and (datetime.now() - odds_cache_time).seconds < 300:
        return odds_cache

    if not ODDS_API_KEY:
        print("⚠️ ODDS_API_KEY не установлен")
        return {}

    try:
        url = "https://api.the-odds-api.com/v4/sports/icehockey_nhl/odds"
        params = {
            'apiKey': ODDS_API_KEY,
            'regions': 'us,eu',
            'markets': 'h2h',
            'oddsFormat': 'decimal',
        }

        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 200:
            data = response.json()
            print(f"📊 Загружено {len(data)} матчей с коэффициентами")

            odds_dict = {}
            for game in data:
                home_abbrev = get_abbrev_from_full_name(game.get('home_team', ''))
                away_abbrev = get_abbrev_from_full_name(game.get('away_team', ''))

                if not home_abbrev or not away_abbrev:
                    continue

                game_key = f"{home_abbrev}_{away_abbrev}"

                best_home_odds = 0
                best_away_odds = 0
                bookmaker_name = None

                for bookmaker in game.get('bookmakers', []):
                    for market in bookmaker.get('markets', []):
                        if market.get('key') == 'h2h':
                            outcomes = market.get('outcomes', [])
                            for outcome in outcomes:
                                price = outcome.get('price', 0)
                                name = outcome.get('name', '')

                                home_match = get_abbrev_from_full_name(name) == home_abbrev
                                away_match = get_abbrev_from_full_name(name) == away_abbrev

                                if home_match and price > best_home_odds:
                                    best_home_odds = price
                                    bookmaker_name = bookmaker.get('title')
                                elif away_match and price > best_away_odds:
                                    best_away_odds = price

                if best_home_odds > 0 or best_away_odds > 0:
                    odds_dict[game_key] = {
                        'home_odds': best_home_odds,
                        'away_odds': best_away_odds,
                        'bookmaker': bookmaker_name,
                        'home_team_full': game.get('home_team'),
                        'away_team_full': game.get('away_team'),
                        'commence_time': game.get('commence_time'),
                    }

            odds_cache = odds_dict
            odds_cache_time = datetime.now()
            print(f"✅ Кэшировано {len(odds_dict)} матчей с коэффициентами")
            return odds_dict
        else:
            print(f"❌ Ошибка API коэффициентов: {response.status_code}")
            return {}
    except Exception as e:
        print(f"❌ Ошибка загрузки коэффициентов: {e}")
        return {}


# ── FlashLive odds ───────────────────────────────────────────────────────────

def _fetch_flash_odds_for_sport(sport: Optional[str], leagues=None, days_ahead: int = 1):
    """Получить коэффициенты через FlashLive для выбранного вида спорта."""
    sport_type = resolve_sport_type(sport)
    loader = _get_flashlive_loader(sport_type)

    if not loader or not loader.is_configured():
        return {}

    target_leagues = leagues or get_leagues_for_sport(sport_type)
    matches = loader.get_matches_with_odds(days_ahead=days_ahead, leagues=target_leagues)

    odds_dict = {}
    for match in matches:
        key = build_odds_key(
            match.get('home_team', ''),
            match.get('away_team', ''),
            match.get('league'),
            sport_type,
        )
        odds_dict[key] = {
            'home_odds': match.get('home_odds'),
            'away_odds': match.get('away_odds'),
            'draw_odds': match.get('draw_odds'),
            'bookmaker': match.get('bookmaker'),
            'home_team': match.get('home_team'),
            'away_team': match.get('away_team'),
            'league': match.get('league'),
            'match_date': match.get('match_date').isoformat() if isinstance(match.get('match_date'), datetime) else match.get('match_date'),
            'event_id': match.get('event_id'),
            'sport': get_sport_slug(sport_type),
        }

    return odds_dict


def fetch_odds(sport: Optional[str] = None, leagues=None, days_ahead: int = 1):
    """Получить коэффициенты.

    Без sport — legacy-поведение для NHL-аналитики.
    Со sport — FlashLive как единый live-source.
    """
    global odds_cache, odds_cache_time

    if sport:
        return _fetch_flash_odds_for_sport(sport=sport, leagues=leagues, days_ahead=days_ahead)

    if odds_cache_time and (datetime.now() - odds_cache_time).seconds < 300:
        return odds_cache

    loader = _get_flashlive_loader(SportType.HOCKEY)
    if loader is not None:
        odds_data = _fetch_flash_odds_for_sport(sport='hockey', leagues=['NHL'], days_ahead=days_ahead)
        if odds_data:
            odds_cache = odds_data
            odds_cache_time = datetime.now()
            return odds_data

    return _fetch_legacy_nhl_odds()


# ── Upcoming games ───────────────────────────────────────────────────────────

def get_nhl_upcoming_games():
    """Получить предстоящие матчи NHL из официального NHL schedule API."""
    today = datetime.now().strftime("%Y-%m-%d")
    url = f"https://api-web.nhle.com/v1/schedule/{today}"

    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            games = []

            for game_week in data.get('gameWeek', []):
                for game in game_week.get('games', []):
                    if game.get('gameState') in ['FUT', 'PRE']:
                        games.append({
                            'id': game.get('id'),
                            'date': game_week.get('date'),
                            'time': game.get('startTimeUTC'),
                            'home_team': game.get('homeTeam', {}).get('abbrev'),
                            'home_team_name': game.get('homeTeam', {}).get('placeName', {}).get('default', ''),
                            'away_team': game.get('awayTeam', {}).get('abbrev'),
                            'away_team_name': game.get('awayTeam', {}).get('placeName', {}).get('default', ''),
                            'venue': game.get('venue', {}).get('default', ''),
                        })

            return games
    except Exception as e:
        print(f"Ошибка загрузки расписания: {e}")

    return []


def get_upcoming_games(sport: Optional[str] = None, leagues=None, days_ahead: int = 1):
    """Получить предстоящие матчи.

    Без sport: legacy NHL schedule.
    Со sport: FlashLive для мультиспорта.
    """
    if not sport:
        return get_nhl_upcoming_games()

    sport_type = resolve_sport_type(sport, default=None)
    if sport_type is None:
        return []

    if str(sport).strip().lower() == 'nhl':
        return get_nhl_upcoming_games()

    loader = _get_flashlive_loader(sport_type)
    if not loader or not loader.is_configured():
        return []

    target_leagues = leagues or get_leagues_for_sport(sport_type)
    matches = loader.get_upcoming_games(leagues=target_leagues, days_ahead=days_ahead)
    return [normalize_flash_match(match, sport_type) for match in matches]


# ── European odds ────────────────────────────────────────────────────────────

def fetch_european_odds():
    """Получить коэффициенты для Liiga и SHL."""
    global euro_odds_cache, euro_odds_cache_time

    if euro_odds_cache_time and (datetime.now() - euro_odds_cache_time).seconds < 300:
        return euro_odds_cache

    if not ODDS_API_KEY:
        print("⚠️ ODDS_API_KEY не установлен")
        return {}

    leagues = {
        'Liiga': 'icehockey_liiga',
        'SHL': 'icehockey_sweden_hockey_league',
    }

    all_odds = {}

    for league_name, sport_key in leagues.items():
        try:
            url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
            params = {
                'apiKey': ODDS_API_KEY,
                'regions': 'eu',
                'markets': 'h2h',
                'oddsFormat': 'decimal',
            }

            response = requests.get(url, params=params, timeout=15)

            if response.status_code == 200:
                data = response.json()
                print(f"📊 {league_name}: {len(data)} матчей с odds")

                league_odds = {}
                for game in data:
                    home_team = game.get('home_team', '')
                    away_team = game.get('away_team', '')

                    best_home = 0
                    best_away = 0
                    bookmaker = None

                    for bm in game.get('bookmakers', []):
                        for market in bm.get('markets', []):
                            if market.get('key') == 'h2h':
                                for outcome in market.get('outcomes', []):
                                    price = outcome.get('price', 0)
                                    name = outcome.get('name', '')
                                    if name == home_team and price > best_home:
                                        best_home = price
                                        bookmaker = bm.get('title')
                                    elif name == away_team and price > best_away:
                                        best_away = price

                    if best_home > 0 or best_away > 0:
                        league_odds[f"{home_team}_{away_team}"] = {
                            'home_odds': best_home,
                            'away_odds': best_away,
                            'bookmaker': bookmaker,
                            'home_team': home_team,
                            'away_team': away_team,
                            'commence_time': game.get('commence_time'),
                        }

                all_odds[league_name] = league_odds

            elif response.status_code == 404:
                print(f"⚠️ {league_name}: нет матчей")
                all_odds[league_name] = {}
            else:
                print(f"❌ {league_name}: ошибка {response.status_code}")
                all_odds[league_name] = {}

        except Exception as e:
            print(f"❌ Ошибка {league_name}: {e}")
            all_odds[league_name] = {}

    euro_odds_cache = all_odds
    euro_odds_cache_time = datetime.now()
    return all_odds


def match_euro_odds(home_team, away_team, league_odds):
    """Найти коэффициенты для матча."""
    if not league_odds:
        return None

    home_lower = home_team.lower()
    away_lower = away_team.lower()

    for key, odds in league_odds.items():
        odds_home = odds.get('home_team', '').lower()
        odds_away = odds.get('away_team', '').lower()

        if (home_lower in odds_home or odds_home in home_lower) and \
           (away_lower in odds_away or odds_away in away_lower):
            return odds

        home_parts = home_lower.split()
        away_parts = away_lower.split()

        for part in home_parts:
            if len(part) > 3 and part in odds_home:
                for apart in away_parts:
                    if len(apart) > 3 and apart in odds_away:
                        return odds

    return None
