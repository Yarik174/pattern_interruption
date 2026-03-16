"""
API-Sports loader for hockey odds and upcoming games.

Provides ``APISportsOddsLoader`` which fetches odds and match data from
the API-Sports hockey endpoint with built-in daily request-limit tracking
(free tier = 100 req/day) and in-memory caching.

Also contains ``MultiLeagueLoader`` for loading historical season data
from the same API.

Migrated from ``src/apisports_odds_loader.py`` and ``src/multi_league_loader.py``
during the loader consolidation.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from src.loaders.base import BaseLoader

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants shared between both loaders
# ---------------------------------------------------------------------------
API_SPORTS_KEY: str = os.environ.get("API_SPORTS_KEY", "").strip()
ODDS_API_KEY: str = os.environ.get("ODDS_API_KEY", "").strip()
BASE_URL: str = "https://v1.hockey.api-sports.io"

LEAGUES: Dict[str, Dict[str, Any]] = {
    "NHL": {"id": 57, "name": "NHL", "country": "USA", "odds_key": "icehockey_nhl"},
    "KHL": {"id": 35, "name": "KHL", "country": "Russia", "odds_key": None},
    "SHL": {"id": 47, "name": "SHL", "country": "Sweden", "odds_key": "icehockey_sweden_hockey_league"},
    "Liiga": {"id": 16, "name": "Liiga", "country": "Finland", "odds_key": "icehockey_liiga"},
    "DEL": {"id": 19, "name": "DEL", "country": "Germany", "odds_key": None},
    "Czech": {"id": 10, "name": "Extraliga", "country": "Czech Republic", "odds_key": None},
    "Swiss": {"id": 52, "name": "NL", "country": "Switzerland", "odds_key": None},
}

CACHE_DIR: Path = Path("data/cache/leagues")


# ---------------------------------------------------------------------------
# APISportsOddsLoader
# ---------------------------------------------------------------------------
class APISportsOddsLoader(BaseLoader):
    """Odds and upcoming-games loader backed by the API-Sports hockey API.

    IMPORTANT: The free tier allows only 100 requests per day. This class
    maintains an in-memory counter and a 2-hour cache to stay within limits.
    """

    SOURCE_NAME = "apisports"
    DEFAULT_CACHE_DIR = "data/cache"

    def __init__(self, api_key: Optional[str] = None, cache_dir: str | None = None) -> None:
        super().__init__(cache_dir=cache_dir)
        self.api_key: str = api_key or API_SPORTS_KEY
        self._games_cache: Dict[str, tuple[List[Dict], datetime]] = {}
        self._odds_cache: Dict[str, Any] = {}  # game_id -> (odds_data, timestamp)
        self._odds_cache_ttl: int = 3600  # 1 hour
        self._cache_time: Optional[datetime] = None
        self._cache_ttl: int = 7200  # 2 hours
        self._daily_requests: int = 0
        self._daily_limit: int = 95
        self._last_reset_date: Optional[Any] = None

    # -- BaseLoader interface -----------------------------------------------

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def get_upcoming_games(
        self,
        leagues: Optional[List[str]] = None,
        hours_ahead: int = 24,
        **kwargs: Any,
    ) -> List[Dict]:
        """Return upcoming NHL (default) games with in-memory caching."""
        if leagues is None:
            leagues = ["NHL"]

        cache_key = f"games_{'-'.join(sorted(leagues))}"
        now = datetime.utcnow()

        if cache_key in self._games_cache:
            cache_data, cache_time = self._games_cache[cache_key]
            if (now - cache_time).total_seconds() < self._cache_ttl:
                logger.info(
                    "API-Sports: using cache (%d games, age %ds)",
                    len(cache_data),
                    int((now - cache_time).total_seconds()),
                )
                return cache_data

        date_from = now.strftime("%Y-%m-%d")
        all_games: List[Dict] = []

        for league_code in leagues:
            if league_code not in LEAGUES:
                continue
            if self.get_requests_remaining() <= 0:
                logger.warning("API-Sports: daily limit exhausted, using partial data")
                break

            league_info = LEAGUES[league_code]
            league_id: int = league_info["id"]

            data = self._make_request("games", {
                "league": league_id,
                "season": 2025,
                "date": date_from,
                "timezone": "UTC",
            })

            if data and "response" in data:
                games_count = len(data["response"])
                statuses: Dict[str, int] = {}
                for game in data["response"]:
                    status = game.get("status", {}).get("short", "")
                    statuses[status] = statuses.get(status, 0) + 1
                    if status in ["NS", "TBD", "SUSP", "POST", "PST", "CANC", ""] or status is None:
                        game_info = self._parse_game(game, league_code)
                        if game_info:
                            all_games.append(game_info)
                logger.info("API-Sports %s: %d games, statuses: %s", league_code, games_count, statuses)

        all_games.sort(key=lambda x: x.get("match_date") or datetime.max)
        self._games_cache[cache_key] = (all_games, now)
        logger.info("API-Sports: found %d games, cached for %ds", len(all_games), self._cache_ttl)
        return all_games

    def load_historical_data(self, **kwargs: Any) -> List[Dict]:
        """APISportsOddsLoader is live-only; historical loading is done by MultiLeagueLoader."""
        return []

    # -- Original public API (preserved) ------------------------------------

    def _check_daily_limit(self) -> None:
        today = datetime.utcnow().date()
        if self._last_reset_date != today:
            self._daily_requests = 0
            self._last_reset_date = today
            logger.info("API-Sports: daily counter reset")

    def get_requests_remaining(self) -> int:
        self._check_daily_limit()
        return max(0, self._daily_limit - self._daily_requests)

    def _make_request(self, endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
        if not self.api_key:
            logger.warning("API_SPORTS_KEY not set")
            return None
        self._check_daily_limit()
        if self._daily_requests >= self._daily_limit:
            logger.warning("API-Sports: daily limit exhausted (%d requests)", self._daily_limit)
            return None

        headers = {"x-apisports-key": self.api_key.strip()}
        url = f"{BASE_URL}/{endpoint}"

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            self._daily_requests += 1
            if response.status_code == 200:
                data = response.json()
                remaining = response.headers.get("x-ratelimit-requests-remaining", "N/A")
                logger.info(
                    "API-Sports: %s - API remaining: %s, local limit: %d",
                    endpoint, remaining, self._daily_limit - self._daily_requests,
                )
                return data
            else:
                logger.error("API-Sports error: %d - %s", response.status_code, response.text[:200])
                return None
        except Exception as exc:
            logger.error("API-Sports request error: %s", exc)
            return None

    def _parse_game(self, game: dict, league_code: str) -> Optional[Dict]:
        try:
            game_id = game.get("id")
            date_str = game.get("date")
            home_team = game.get("teams", {}).get("home", {})
            away_team = game.get("teams", {}).get("away", {})

            match_date: Optional[datetime] = None
            if date_str:
                try:
                    match_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    match_date = match_date.replace(tzinfo=None)
                except Exception:
                    pass

            return {
                "event_id": f"apisports_{game_id}",
                "game_id": game_id,
                "league": league_code,
                "home_team": home_team.get("name", ""),
                "home_team_id": home_team.get("id"),
                "away_team": away_team.get("name", ""),
                "away_team_id": away_team.get("id"),
                "match_date": match_date,
                "status": game.get("status", {}).get("long", "Scheduled"),
                "venue": game.get("venue", {}).get("name", ""),
            }
        except Exception as exc:
            logger.error("Error parsing game: %s", exc)
            return None

    def get_odds_for_game(self, game_id: int) -> Optional[Dict]:
        import time as _time
        cache_key = str(game_id)
        if cache_key in self._odds_cache:
            cached_data, cached_ts = self._odds_cache[cache_key]
            if _time.time() - cached_ts < self._odds_cache_ttl:
                logger.info("API-Sports: odds cache hit for game %s", game_id)
                return cached_data

        data = self._make_request("odds", {"game": game_id})
        if not data or "response" not in data:
            return None
        odds_list = data["response"]
        if not odds_list:
            return None
        result = self._parse_odds(odds_list[0])
        self._odds_cache[cache_key] = (result, _time.time())
        return result

    def _parse_odds(self, odds_data: dict) -> Dict:
        result: Dict[str, Any] = {
            "bookmakers": [],
            "best_home_odds": None,
            "best_away_odds": None,
            "best_draw_odds": None,
        }
        bookmakers = odds_data.get("bookmakers", [])

        for bm in bookmakers:
            bm_name = bm.get("name", "")
            bm_bets = bm.get("bets", [])
            for bet in bm_bets:
                bet_name = bet.get("name", "")
                if bet_name in ["Match Winner", "Home/Away", "1X2"]:
                    values = bet.get("values", [])
                    odds_info: Dict[str, Any] = {
                        "bookmaker": bm_name,
                        "market": bet_name,
                        "home_odds": None,
                        "away_odds": None,
                        "draw_odds": None,
                    }
                    for v in values:
                        value = v.get("value", "")
                        odd = self._parse_odd(v.get("odd"))
                        if value in ["Home", "1", "home"]:
                            odds_info["home_odds"] = odd
                            if odd and (result["best_home_odds"] is None or odd > result["best_home_odds"]):
                                result["best_home_odds"] = odd
                        elif value in ["Away", "2", "away"]:
                            odds_info["away_odds"] = odd
                            if odd and (result["best_away_odds"] is None or odd > result["best_away_odds"]):
                                result["best_away_odds"] = odd
                        elif value in ["Draw", "X", "draw"]:
                            odds_info["draw_odds"] = odd
                            if odd and (result["best_draw_odds"] is None or odd > result["best_draw_odds"]):
                                result["best_draw_odds"] = odd
                    result["bookmakers"].append(odds_info)

        return result

    @staticmethod
    def _parse_odd(odd: Any) -> Optional[float]:
        if odd is None:
            return None
        try:
            return float(odd)
        except (ValueError, TypeError):
            return None

    def get_upcoming_matches(self, hours_ahead: int = 48) -> List[Dict]:
        """Fetch upcoming matches with odds (OddsMonitor-compatible interface)."""
        games = self.get_upcoming_games(hours_ahead=hours_ahead)
        matches_with_odds: List[Dict] = []

        for game in games[:20]:
            game_id = game.get("game_id")
            if not game_id:
                continue
            odds = self.get_odds_for_game(game_id)

            match: Dict[str, Any] = {
                "event_id": game.get("event_id"),
                "game_id": game_id,
                "league": game.get("league"),
                "home_team": game.get("home_team"),
                "away_team": game.get("away_team"),
                "match_date": game.get("match_date"),
                "market": "moneyline",
                "bookmaker": "API-Sports",
                "home_odds": None,
                "away_odds": None,
                "draw_odds": None,
                "value_percent": 0,
            }
            if odds:
                match["home_odds"] = odds.get("best_home_odds")
                match["away_odds"] = odds.get("best_away_odds")
                match["draw_odds"] = odds.get("best_draw_odds")
                match["bookmakers"] = odds.get("bookmakers", [])
            matches_with_odds.append(match)

        logger.info("API-Sports: %d matches with odds", len(matches_with_odds))
        return matches_with_odds

    def get_live_games(self) -> List[Dict]:
        data = self._make_request("games", {"live": "all"})
        if not data or "response" not in data:
            return []
        games: List[Dict] = []
        for game in data["response"]:
            league_id = game.get("league", {}).get("id")
            league_code: Optional[str] = None
            for code, info in LEAGUES.items():
                if info["id"] == league_id:
                    league_code = code
                    break
            if league_code:
                game_info = self._parse_game(game, league_code)
                if game_info:
                    game_info["is_live"] = True
                    game_info["current_period"] = game.get("periods", {}).get("current")
                    game_info["home_score"] = game.get("scores", {}).get("home")
                    game_info["away_score"] = game.get("scores", {}).get("away")
                    games.append(game_info)
        return games


# ---------------------------------------------------------------------------
# MultiLeagueLoader (from multi_league_loader.py)
# ---------------------------------------------------------------------------
class MultiLeagueLoader(BaseLoader):
    """Multi-league historical data loader via API-Sports."""

    SOURCE_NAME = "multi_league"
    DEFAULT_CACHE_DIR = "data/cache/leagues"

    def __init__(self, cache_dir: str | None = None) -> None:
        super().__init__(cache_dir=cache_dir or str(CACHE_DIR))
        self.api_key: str = API_SPORTS_KEY

    def _resolve_cache_dir(self) -> Path:
        """Return the effective cache directory.

        Checks the legacy ``src.multi_league_loader.CACHE_DIR`` first so that
        tests that monkeypatch that module-level variable still work.
        Falls back to ``src.loaders.apisports.CACHE_DIR``, then ``self.cache_dir``.
        """
        import sys
        wrapper = sys.modules.get("src.multi_league_loader")
        if wrapper is not None:
            wrapper_dir = wrapper.__dict__.get("CACHE_DIR")
            if wrapper_dir is not None and wrapper_dir != CACHE_DIR:
                return Path(wrapper_dir)
        return CACHE_DIR

    # -- BaseLoader interface -----------------------------------------------

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def get_upcoming_games(self, league_name: Optional[str] = None, **kwargs: Any) -> List[Dict]:
        """Wrapper: get upcoming matches for a single league."""
        if not league_name:
            return self.get_all_upcoming()
        return self._get_upcoming_games_for_league(league_name)

    def load_historical_data(
        self,
        league_name: Optional[str] = None,
        n_seasons: int = 5,
        **kwargs: Any,
    ) -> List[Dict]:
        if league_name:
            return self.load_league_data(league_name, n_seasons=n_seasons)
        all_data: List[Dict] = []
        for ln in LEAGUES:
            all_data.extend(self.load_league_data(ln, n_seasons=n_seasons))
        return all_data

    # -- Original public API (preserved) ------------------------------------

    def _get_cached_game_seasons(self, league_id: int) -> List[int]:
        seasons: List[int] = []
        cache = self._resolve_cache_dir()
        for path in cache.glob(f"games_{league_id}_*.json"):
            try:
                season = int(path.stem.split("_")[-1])
                seasons.append(season)
            except (ValueError, IndexError):
                continue
        return sorted(set(seasons), reverse=True)

    def get_games_cache_path(self, league_id: int, season: int) -> Path:
        return self._resolve_cache_dir() / f"games_{league_id}_{season}.json"

    def _make_request(self, endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
        if not self.api_key:
            logger.warning("API_SPORTS_KEY not set")
            return None
        headers = {"x-apisports-key": self.api_key}
        url = f"{BASE_URL}/{endpoint}"
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error("API error: %d", response.status_code)
                return None
        except Exception as exc:
            logger.error("Request error: %s", exc, exc_info=True)
            return None

    def get_available_seasons(self, league_id: int) -> List[int]:
        cache_file = self._resolve_cache_dir() / f"seasons_{league_id}.json"
        if cache_file.exists():
            with open(cache_file, "r") as fh:
                return json.load(fh)

        cached_seasons = self._get_cached_game_seasons(league_id)
        if cached_seasons:
            return cached_seasons

        data = self._make_request("leagues", {"id": league_id})
        if data and data.get("response"):
            seasons = data["response"][0].get("seasons", [])
            season_list = [s["season"] for s in seasons]
            with open(cache_file, "w") as fh:
                json.dump(season_list, fh)
            return season_list
        return []

    def get_teams(self, league_id: int, season: int) -> List[Dict]:
        cache_file = self._resolve_cache_dir() / f"teams_{league_id}_{season}.json"
        if cache_file.exists():
            with open(cache_file, "r") as fh:
                return json.load(fh)
        data = self._make_request("teams", {"league": league_id, "season": season})
        if data and data.get("response"):
            teams = data["response"]
            with open(cache_file, "w") as fh:
                json.dump(teams, fh)
            return teams
        return []

    def get_games(self, league_id: int, season: int, force_refresh: bool = False) -> List[Dict]:
        cache_file = self.get_games_cache_path(league_id, season)
        if cache_file.exists() and not force_refresh:
            with open(cache_file, "r") as fh:
                cached = json.load(fh)
                logger.info("Loaded from cache: %d games", len(cached))
                return cached

        if not self.api_key:
            return []

        data = self._make_request("games", {"league": league_id, "season": season})
        if data and data.get("response"):
            games: List[Dict] = []
            for game in data["response"]:
                if game.get("status", {}).get("short") in ["FT", "AOT", "AP"]:
                    home_team = game.get("teams", {}).get("home", {})
                    away_team = game.get("teams", {}).get("away", {})
                    scores = game.get("scores", {})
                    home_score = scores.get("home")
                    away_score = scores.get("away")
                    if home_score is not None and away_score is not None:
                        games.append({
                            "id": game.get("id"),
                            "date": game.get("date"),
                            "home_team": home_team.get("name"),
                            "home_team_id": home_team.get("id"),
                            "away_team": away_team.get("name"),
                            "away_team_id": away_team.get("id"),
                            "home_score": home_score,
                            "away_score": away_score,
                            "home_win": home_score > away_score,
                            "league_id": league_id,
                            "season": season,
                        })
            with open(cache_file, "w") as fh:
                json.dump(games, fh)
            logger.info("Loaded: %d games", len(games))
            return games
        return []

    def load_league_data(
        self,
        league_name: str,
        n_seasons: int = 5,
        refresh_current_season: bool = False,
    ) -> List[Dict]:
        if league_name not in LEAGUES:
            logger.warning("Unknown league: %s", league_name)
            return []

        league_info = LEAGUES[league_name]
        league_id: int = league_info["id"]

        logger.info("Loading %s (%s)", league_name, league_info['country'])

        seasons = self.get_available_seasons(league_id)
        if not seasons:
            logger.warning("No seasons found for %s", league_name)
            return []

        cached_seasons = self._get_cached_game_seasons(league_id)
        seasons = sorted(set(seasons) | set(cached_seasons), reverse=True)
        logger.info("Candidate seasons: %s", seasons)

        all_games: List[Dict] = []
        requested_seasons = n_seasons if n_seasons and n_seasons > 0 else None
        loaded_seasons = 0
        current_season = max(seasons) if seasons else None

        for season in seasons:
            if requested_seasons is not None and loaded_seasons >= requested_seasons:
                break
            target_label: Any = requested_seasons if requested_seasons is not None else "all"
            logger.info("[%d/%s] Season %s", loaded_seasons + 1, target_label, season)
            games = self.get_games(
                league_id,
                season,
                force_refresh=bool(refresh_current_season and season == current_season),
            )
            if not games:
                continue
            all_games.extend(games)
            loaded_seasons += 1

        logger.info("Total: %d games", len(all_games))
        return all_games

    def load_multiple_leagues(
        self,
        league_names: List[str],
        n_seasons: int = 5,
    ) -> Dict[str, List[Dict]]:
        all_data: Dict[str, List[Dict]] = {}
        for league_name in league_names:
            games = self.load_league_data(league_name, n_seasons)
            all_data[league_name] = games
        total = sum(len(g) for g in all_data.values())
        logger.info("Total loaded: %d games from %d leagues", total, len(league_names))
        return all_data

    def _get_upcoming_games_for_league(self, league_name: str) -> List[Dict]:
        if league_name not in LEAGUES:
            return []
        league_id: int = LEAGUES[league_name]["id"]
        today = datetime.now().strftime("%Y-%m-%d")
        data = self._make_request("games", {"league": league_id, "date": today})
        if data and data.get("response"):
            games: List[Dict] = []
            for game in data["response"]:
                status = game.get("status", {}).get("short", "")
                if status in ["NS", "TBD"]:
                    home_team = game.get("teams", {}).get("home", {})
                    away_team = game.get("teams", {}).get("away", {})
                    games.append({
                        "id": game.get("id"),
                        "date": game.get("date"),
                        "time": game.get("time"),
                        "home_team": home_team.get("name"),
                        "home_team_id": home_team.get("id"),
                        "away_team": away_team.get("name"),
                        "away_team_id": away_team.get("id"),
                        "league": league_name,
                        "league_id": league_id,
                    })
            return games
        return []

    def get_all_upcoming(self, league_names: Optional[List[str]] = None) -> List[Dict]:
        if league_names is None:
            league_names = list(LEAGUES.keys())
        all_upcoming: List[Dict] = []
        for league_name in league_names:
            games = self._get_upcoming_games_for_league(league_name)
            all_upcoming.extend(games)
            logger.info("%s: %d upcoming games", league_name, len(games))
        return all_upcoming

    def fetch_odds(self, league_name: str) -> Dict[str, Dict]:
        if league_name not in LEAGUES:
            return {}
        odds_key = LEAGUES[league_name].get("odds_key")
        if not odds_key:
            return {}
        if not ODDS_API_KEY:
            logger.warning("ODDS_API_KEY not set")
            return {}
        try:
            url = f"https://api.the-odds-api.com/v4/sports/{odds_key}/odds"
            params = {
                "apiKey": ODDS_API_KEY,
                "regions": "us,eu",
                "markets": "h2h",
                "oddsFormat": "decimal",
            }
            response = requests.get(url, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                logger.info("%s: loaded %d games with odds", league_name, len(data))
                odds_dict: Dict[str, Dict] = {}
                for game in data:
                    home_team = game.get("home_team", "")
                    away_team = game.get("away_team", "")
                    game_key = f"{home_team}_{away_team}"
                    best_home_odds = 0.0
                    best_away_odds = 0.0
                    bookmaker_name: Optional[str] = None
                    for bookmaker in game.get("bookmakers", []):
                        for market in bookmaker.get("markets", []):
                            if market.get("key") == "h2h":
                                for outcome in market.get("outcomes", []):
                                    price = outcome.get("price", 0)
                                    name = outcome.get("name", "")
                                    if name == home_team and price > best_home_odds:
                                        best_home_odds = price
                                        bookmaker_name = bookmaker.get("title")
                                    elif name == away_team and price > best_away_odds:
                                        best_away_odds = price
                    if best_home_odds > 0 or best_away_odds > 0:
                        odds_dict[game_key] = {
                            "home_odds": best_home_odds,
                            "away_odds": best_away_odds,
                            "bookmaker": bookmaker_name,
                            "home_team": home_team,
                            "away_team": away_team,
                            "commence_time": game.get("commence_time"),
                        }
                return odds_dict
            else:
                logger.error("Odds API error: %d", response.status_code)
                return {}
        except Exception as exc:
            logger.error("Error loading odds: %s", exc, exc_info=True)
            return {}

    def fetch_all_odds(self, league_names: Optional[List[str]] = None) -> Dict[str, Dict]:
        if league_names is None:
            league_names = [l for l, info in LEAGUES.items() if info.get("odds_key")]
        all_odds: Dict[str, Dict] = {}
        for league_name in league_names:
            odds = self.fetch_odds(league_name)
            if odds:
                all_odds[league_name] = odds
        return all_odds


# ---------------------------------------------------------------------------
# Demo helper
# ---------------------------------------------------------------------------
def get_demo_odds() -> List[Dict]:
    """Demo odds for testing without an API key."""
    now = datetime.utcnow()
    return [
        {
            "event_id": "demo_1",
            "league": "NHL",
            "home_team": "Boston Bruins",
            "away_team": "Toronto Maple Leafs",
            "match_date": now + timedelta(hours=2),
            "market": "moneyline",
            "bookmaker": "Demo",
            "home_odds": 1.85,
            "away_odds": 2.10,
            "draw_odds": None,
            "value_percent": 0,
        },
        {
            "event_id": "demo_2",
            "league": "KHL",
            "home_team": "CSKA Moscow",
            "away_team": "SKA St. Petersburg",
            "match_date": now + timedelta(hours=5),
            "market": "moneyline",
            "bookmaker": "Demo",
            "home_odds": 2.20,
            "away_odds": 1.75,
            "draw_odds": 3.80,
            "value_percent": 0,
        },
        {
            "event_id": "demo_3",
            "league": "SHL",
            "home_team": "Frolunda HC",
            "away_team": "Lulea HF",
            "match_date": now + timedelta(hours=8),
            "market": "moneyline",
            "bookmaker": "Demo",
            "home_odds": 1.95,
            "away_odds": 1.95,
            "draw_odds": 3.60,
            "value_percent": 0,
        },
    ]
