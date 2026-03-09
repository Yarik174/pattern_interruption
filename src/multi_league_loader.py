"""
Multi-League Data Loader
Загрузчик данных для европейских хоккейных лиг через API-Sports
"""

import requests
import os
import json
from datetime import datetime, timedelta
from pathlib import Path

API_SPORTS_KEY = os.environ.get('API_SPORTS_KEY', '').strip()
ODDS_API_KEY = os.environ.get('ODDS_API_KEY', '').strip()
BASE_URL = "https://v1.hockey.api-sports.io"

LEAGUES = {
    'NHL': {'id': 57, 'country': 'USA', 'odds_key': 'icehockey_nhl'},
    'KHL': {'id': 35, 'country': 'Russia', 'odds_key': None},
    'SHL': {'id': 47, 'country': 'Sweden', 'odds_key': 'icehockey_sweden_hockey_league'},
    'Liiga': {'id': 16, 'country': 'Finland', 'odds_key': 'icehockey_liiga'},
    'DEL': {'id': 19, 'country': 'Germany', 'odds_key': None},
    'Czech': {'id': 10, 'country': 'Czech-Republic', 'odds_key': None},
    'Swiss': {'id': 52, 'country': 'Switzerland', 'odds_key': None},
}

CACHE_DIR = Path("data/cache/leagues")


class MultiLeagueLoader:
    """Загрузчик данных для нескольких хоккейных лиг"""
    
    def __init__(self):
        self.api_key = API_SPORTS_KEY
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _get_cached_game_seasons(self, league_id):
        """Получить сезоны, для которых уже есть кэш матчей."""
        seasons = []
        for path in CACHE_DIR.glob(f"games_{league_id}_*.json"):
            try:
                season = int(path.stem.split("_")[-1])
                seasons.append(season)
            except (ValueError, IndexError):
                continue
        return sorted(set(seasons), reverse=True)
        
    def _make_request(self, endpoint, params=None):
        """Выполнить запрос к API"""
        if not self.api_key:
            print("⚠️ API_SPORTS_KEY не установлен")
            return None
            
        headers = {'x-apisports-key': self.api_key}
        url = f"{BASE_URL}/{endpoint}"
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"❌ Ошибка API: {response.status_code}")
                return None
        except Exception as e:
            print(f"❌ Ошибка запроса: {e}")
            return None
    
    def get_available_seasons(self, league_id):
        """Получить доступные сезоны для лиги"""
        cache_file = CACHE_DIR / f"seasons_{league_id}.json"
        
        if cache_file.exists():
            with open(cache_file, 'r') as f:
                return json.load(f)

        cached_seasons = self._get_cached_game_seasons(league_id)
        if cached_seasons:
            return cached_seasons
        
        data = self._make_request('leagues', {'id': league_id})
        if data and data.get('response'):
            seasons = data['response'][0].get('seasons', [])
            season_list = [s['season'] for s in seasons]
            
            with open(cache_file, 'w') as f:
                json.dump(season_list, f)
            
            return season_list
        return []
    
    def get_teams(self, league_id, season):
        """Получить команды лиги"""
        cache_file = CACHE_DIR / f"teams_{league_id}_{season}.json"
        
        if cache_file.exists():
            with open(cache_file, 'r') as f:
                return json.load(f)
        
        data = self._make_request('teams', {'league': league_id, 'season': season})
        if data and data.get('response'):
            teams = data['response']
            
            with open(cache_file, 'w') as f:
                json.dump(teams, f)
            
            return teams
        return []
    
    def get_games(self, league_id, season):
        """Получить все матчи сезона"""
        cache_file = CACHE_DIR / f"games_{league_id}_{season}.json"
        
        if cache_file.exists():
            with open(cache_file, 'r') as f:
                cached = json.load(f)
                print(f"  📦 Загружено из кэша: {len(cached)} матчей")
                return cached

        if not self.api_key:
            return []
        
        data = self._make_request('games', {'league': league_id, 'season': season})
        if data and data.get('response'):
            games = []
            for game in data['response']:
                if game.get('status', {}).get('short') in ['FT', 'AOT', 'AP']:
                    home_team = game.get('teams', {}).get('home', {})
                    away_team = game.get('teams', {}).get('away', {})
                    scores = game.get('scores', {})
                    
                    home_score = scores.get('home')
                    away_score = scores.get('away')
                    
                    if home_score is not None and away_score is not None:
                        games.append({
                            'id': game.get('id'),
                            'date': game.get('date'),
                            'home_team': home_team.get('name'),
                            'home_team_id': home_team.get('id'),
                            'away_team': away_team.get('name'),
                            'away_team_id': away_team.get('id'),
                            'home_score': home_score,
                            'away_score': away_score,
                            'home_win': home_score > away_score,
                            'league_id': league_id,
                            'season': season
                        })
            
            with open(cache_file, 'w') as f:
                json.dump(games, f)
            
            print(f"  ✅ Загружено: {len(games)} матчей")
            return games
        return []
    
    def load_league_data(self, league_name, n_seasons=5):
        """Загрузить данные для лиги"""
        if league_name not in LEAGUES:
            print(f"❌ Неизвестная лига: {league_name}")
            return []
        
        league_info = LEAGUES[league_name]
        league_id = league_info['id']
        
        print(f"\n🏒 Загрузка {league_name} ({league_info['country']})")
        print("=" * 50)
        
        seasons = self.get_available_seasons(league_id)
        if not seasons:
            print(f"❌ Не удалось получить сезоны для {league_name}")
            return []
        
        cached_seasons = self._get_cached_game_seasons(league_id)
        seasons = sorted(set(seasons) | set(cached_seasons), reverse=True)
        print(f"📅 Кандидаты сезонов: {seasons}")
        
        all_games = []
        requested_seasons = n_seasons if n_seasons and n_seasons > 0 else None
        loaded_seasons = 0
        for season in seasons:
            if requested_seasons is not None and loaded_seasons >= requested_seasons:
                break

            target_label = requested_seasons if requested_seasons is not None else "all"
            print(f"[{loaded_seasons + 1}/{target_label}] Сезон {season}")
            games = self.get_games(league_id, season)
            if not games:
                continue
            all_games.extend(games)
            loaded_seasons += 1
        
        print(f"\n📊 Итого: {len(all_games)} матчей")
        return all_games
    
    def load_multiple_leagues(self, league_names, n_seasons=5):
        """Загрузить данные для нескольких лиг"""
        all_data = {}
        
        for league_name in league_names:
            games = self.load_league_data(league_name, n_seasons)
            all_data[league_name] = games
        
        total = sum(len(g) for g in all_data.values())
        print(f"\n{'='*50}")
        print(f"📊 Всего загружено: {total} матчей из {len(league_names)} лиг")
        
        return all_data
    
    def get_upcoming_games(self, league_name):
        """Получить предстоящие матчи лиги"""
        if league_name not in LEAGUES:
            return []
        
        league_id = LEAGUES[league_name]['id']
        today = datetime.now().strftime("%Y-%m-%d")
        
        data = self._make_request('games', {
            'league': league_id,
            'date': today
        })
        
        if data and data.get('response'):
            games = []
            for game in data['response']:
                status = game.get('status', {}).get('short', '')
                if status in ['NS', 'TBD']:
                    home_team = game.get('teams', {}).get('home', {})
                    away_team = game.get('teams', {}).get('away', {})
                    
                    games.append({
                        'id': game.get('id'),
                        'date': game.get('date'),
                        'time': game.get('time'),
                        'home_team': home_team.get('name'),
                        'home_team_id': home_team.get('id'),
                        'away_team': away_team.get('name'),
                        'away_team_id': away_team.get('id'),
                        'league': league_name,
                        'league_id': league_id
                    })
            return games
        return []
    
    def get_all_upcoming(self, league_names=None):
        """Получить предстоящие матчи для всех лиг"""
        if league_names is None:
            league_names = list(LEAGUES.keys())
        
        all_upcoming = []
        for league_name in league_names:
            games = self.get_upcoming_games(league_name)
            all_upcoming.extend(games)
            print(f"📅 {league_name}: {len(games)} предстоящих матчей")
        
        return all_upcoming
    
    def fetch_odds(self, league_name):
        """Получить коэффициенты для лиги через The Odds API"""
        if league_name not in LEAGUES:
            return {}
        
        odds_key = LEAGUES[league_name].get('odds_key')
        if not odds_key:
            return {}
        
        if not ODDS_API_KEY:
            print(f"⚠️ ODDS_API_KEY не установлен")
            return {}
        
        try:
            url = f"https://api.the-odds-api.com/v4/sports/{odds_key}/odds"
            params = {
                'apiKey': ODDS_API_KEY,
                'regions': 'us,eu',
                'markets': 'h2h',
                'oddsFormat': 'decimal'
            }
            
            response = requests.get(url, params=params, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                print(f"📊 {league_name}: загружено {len(data)} матчей с коэффициентами")
                
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
                                for outcome in market.get('outcomes', []):
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
                
                return odds_dict
            else:
                print(f"❌ Ошибка API коэффициентов: {response.status_code}")
                return {}
        except Exception as e:
            print(f"❌ Ошибка загрузки коэффициентов: {e}")
            return {}
    
    def fetch_all_odds(self, league_names=None):
        """Получить коэффициенты для всех лиг"""
        if league_names is None:
            league_names = [l for l, info in LEAGUES.items() if info.get('odds_key')]
        
        all_odds = {}
        for league_name in league_names:
            odds = self.fetch_odds(league_name)
            if odds:
                all_odds[league_name] = odds
        
        return all_odds


def test_loader():
    """Тест загрузчика"""
    loader = MultiLeagueLoader()
    
    print("\n" + "="*60)
    print("ТЕСТ ЗАГРУЗЧИКА ЕВРОПЕЙСКИХ ЛИГ")
    print("="*60)
    
    for league_name in ['KHL', 'SHL', 'Liiga']:
        games = loader.load_league_data(league_name, n_seasons=1)
        if games:
            print(f"\n✅ {league_name}: {len(games)} матчей")
            print(f"   Пример: {games[0]['away_team']} @ {games[0]['home_team']}")
    
    print("\n📅 Предстоящие матчи:")
    upcoming = loader.get_all_upcoming(['KHL', 'SHL', 'Liiga'])
    for game in upcoming[:5]:
        print(f"  {game['league']}: {game['away_team']} @ {game['home_team']}")


if __name__ == '__main__':
    test_loader()
