"""
European Hockey Leagues Data Loader
Загрузчик данных для европейских хоккейных лиг из кэша
"""

import json
import os
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

CACHE_DIR = Path("data/cache/leagues")

EURO_LEAGUES = {
    'KHL': {'id': 35, 'country': 'Russia', 'odds_key': None},
    'SHL': {'id': 47, 'country': 'Sweden', 'odds_key': 'icehockey_sweden_hockey_league'},
    'Liiga': {'id': 16, 'country': 'Finland', 'odds_key': 'icehockey_liiga'},
    'DEL': {'id': 19, 'country': 'Germany', 'odds_key': None},
}


class EuroLeagueLoader:
    """Загрузчик данных для европейских хоккейных лиг"""
    
    def __init__(self):
        self.cache_dir = CACHE_DIR
        self.league_data = {}
        
    def load_league_from_cache(self, league_name: str, n_seasons: int = 3) -> pd.DataFrame:
        """
        Загрузить данные лиги из кэша.
        
        Формат выхода совместим с PatternEngine:
        - date, home_team, away_team, home_goals, away_goals, home_win, overtime
        """
        if league_name not in EURO_LEAGUES:
            print(f"❌ Неизвестная лига: {league_name}")
            return pd.DataFrame()
        
        league_id = EURO_LEAGUES[league_name]['id']
        all_games = []
        
        cache_files = list(self.cache_dir.glob(f"games_{league_id}_*.json"))
        cache_files.sort(reverse=True)
        cache_files = cache_files[:n_seasons]
        
        for cache_file in cache_files:
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    games = json.load(f)
                    
                for game in games:
                    formatted_game = self._format_game(game, league_name)
                    if formatted_game:
                        all_games.append(formatted_game)
                        
                print(f"  📦 {cache_file.name}: {len(games)} матчей")
            except Exception as e:
                print(f"  ❌ Ошибка загрузки {cache_file}: {e}")
        
        if not all_games:
            return pd.DataFrame()
        
        df = pd.DataFrame(all_games)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        
        print(f"✅ {league_name}: загружено {len(df)} матчей")
        return df
    
    def _format_game(self, game: dict, league_name: str) -> Optional[dict]:
        """
        Преобразовать формат игры из кэша в формат PatternEngine.
        """
        try:
            home_score = game.get('home_score')
            away_score = game.get('away_score')
            
            if home_score is None or away_score is None:
                return None
            
            date_str = game.get('date', '')
            if isinstance(date_str, str):
                date = pd.to_datetime(date_str)
            else:
                date = date_str
            
            return {
                'date': date,
                'home_team': game.get('home_team', ''),
                'away_team': game.get('away_team', ''),
                'home_goals': int(home_score),
                'away_goals': int(away_score),
                'home_win': 1 if home_score > away_score else 0,
                'overtime': 0,
                'league': league_name,
                'season': game.get('season'),
                'game_id': game.get('id')
            }
        except Exception as e:
            return None
    
    def load_all_european_leagues(self, n_seasons: int = 3) -> Dict[str, pd.DataFrame]:
        """
        Загрузить все европейские лиги.
        """
        print("\n🏒 Загрузка европейских лиг...")
        print("=" * 50)
        
        for league_name in EURO_LEAGUES.keys():
            print(f"\n📥 {league_name} ({EURO_LEAGUES[league_name]['country']}):")
            df = self.load_league_from_cache(league_name, n_seasons)
            self.league_data[league_name] = df
        
        total_games = sum(len(df) for df in self.league_data.values())
        print(f"\n{'='*50}")
        print(f"📊 Всего загружено: {total_games} матчей")
        
        return self.league_data
    
    def get_league_teams(self, league_name: str) -> List[str]:
        """Получить список команд в лиге"""
        if league_name not in self.league_data:
            self.load_league_from_cache(league_name)
        
        df = self.league_data.get(league_name)
        if df is None or df.empty:
            return []
        
        teams = set(df['home_team'].unique()) | set(df['away_team'].unique())
        return sorted(list(teams))
    
    def get_team_recent_games(self, league_name: str, team: str, n_games: int = 10) -> pd.DataFrame:
        """Получить последние матчи команды"""
        if league_name not in self.league_data:
            self.load_league_from_cache(league_name)
        
        df = self.league_data.get(league_name)
        if df is None or df.empty:
            return pd.DataFrame()
        
        team_games = df[
            (df['home_team'] == team) | (df['away_team'] == team)
        ].sort_values('date', ascending=False).head(n_games)
        
        return team_games


euro_odds_cache = {}
euro_odds_cache_time = {}


def fetch_european_odds(league_key: str = None) -> dict:
    """
    Получить коэффициенты для европейских лиг из The Odds API.
    
    Поддерживаемые лиги:
    - icehockey_liiga (Финляндия)
    - icehockey_sweden_hockey_league (Швеция/SHL)
    """
    import requests
    from datetime import datetime
    
    global euro_odds_cache, euro_odds_cache_time
    
    ODDS_API_KEY = os.environ.get('ODDS_API_KEY', '').strip()
    
    if not ODDS_API_KEY:
        print("⚠️ ODDS_API_KEY не установлен")
        return {}
    
    leagues_to_fetch = []
    if league_key:
        leagues_to_fetch = [league_key]
    else:
        leagues_to_fetch = ['icehockey_liiga', 'icehockey_sweden_hockey_league']
    
    all_odds = {}
    
    for sport_key in leagues_to_fetch:
        cache_key = sport_key
        if cache_key in euro_odds_cache_time:
            if (datetime.now() - euro_odds_cache_time[cache_key]).seconds < 300:
                all_odds[cache_key] = euro_odds_cache.get(cache_key, {})
                continue
        
        try:
            url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
            params = {
                'apiKey': ODDS_API_KEY,
                'regions': 'eu',
                'markets': 'h2h',
                'oddsFormat': 'decimal'
            }
            
            response = requests.get(url, params=params, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                print(f"📊 {sport_key}: получено {len(data)} матчей с odds")
                
                odds_dict = {}
                for game in data:
                    home_team = game.get('home_team', '')
                    away_team = game.get('away_team', '')
                    game_key = f"{home_team}_{away_team}"
                    
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
                                    
                                    if name == home_team and price > best_home_odds:
                                        best_home_odds = price
                                        bookmaker_name = bookmaker.get('title')
                                    elif name == away_team and price > best_away_odds:
                                        best_away_odds = price
                    
                    if best_home_odds > 0 or best_away_odds > 0:
                        odds_dict[game_key] = {
                            'home_odds': best_home_odds,
                            'away_odds': best_away_odds,
                            'bookmaker': bookmaker_name,
                            'home_team': home_team,
                            'away_team': away_team,
                            'commence_time': game.get('commence_time')
                        }
                
                euro_odds_cache[cache_key] = odds_dict
                euro_odds_cache_time[cache_key] = datetime.now()
                all_odds[cache_key] = odds_dict
                
            elif response.status_code == 404:
                print(f"⚠️ {sport_key}: лига не найдена или нет матчей")
                all_odds[cache_key] = {}
            else:
                print(f"❌ {sport_key}: ошибка API {response.status_code}")
                all_odds[cache_key] = {}
                
        except Exception as e:
            print(f"❌ Ошибка загрузки odds для {sport_key}: {e}")
            all_odds[cache_key] = {}
    
    return all_odds


def get_league_odds_key(league_name: str) -> Optional[str]:
    """Получить ключ The Odds API для лиги"""
    return EURO_LEAGUES.get(league_name, {}).get('odds_key')


def match_odds_to_game(game_home: str, game_away: str, odds_dict: dict) -> Optional[dict]:
    """
    Сопоставить коэффициенты с матчем по названию команд.
    Использует нечеткое сопоставление.
    """
    if not odds_dict:
        return None
    
    game_home_lower = game_home.lower()
    game_away_lower = game_away.lower()
    
    for key, odds in odds_dict.items():
        odds_home = odds.get('home_team', '').lower()
        odds_away = odds.get('away_team', '').lower()
        
        if (game_home_lower in odds_home or odds_home in game_home_lower) and \
           (game_away_lower in odds_away or odds_away in game_away_lower):
            return odds
        
        home_parts = game_home_lower.split()
        away_parts = game_away_lower.split()
        
        for part in home_parts:
            if len(part) > 3 and part in odds_home:
                for apart in away_parts:
                    if len(apart) > 3 and apart in odds_away:
                        return odds
    
    return None
