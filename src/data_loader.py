import requests
import pandas as pd
from datetime import datetime
import time
import json
import os
import logging

logger = logging.getLogger(__name__)

class NHLDataLoader:
    def __init__(self, cache_dir='data/cache'):
        self.base_url = "https://api-web.nhle.com/v1"
        self.teams = {}
        self.games = []
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        
    def _get_cache_path(self, season):
        return os.path.join(self.cache_dir, f"season_{season}.json")

    def get_cached_seasons(self):
        """Получить все доступные сезоны из локального кэша в хронологическом порядке."""
        seasons = []
        if not os.path.exists(self.cache_dir):
            return seasons

        for filename in os.listdir(self.cache_dir):
            if not (filename.startswith('season_') and filename.endswith('.json')):
                continue
            season = filename.replace('season_', '').replace('.json', '')
            if season.isdigit():
                seasons.append(season)

        return sorted(set(seasons))
    
    def _load_from_cache(self, season):
        cache_path = self._get_cache_path(season)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r') as f:
                    data = json.load(f)
                logger.info(f"Загружено из кэша: сезон {season}, {len(data)} матчей")
                return data
            except Exception as e:
                logger.warning(f"Ошибка чтения кэша: {e}")
        return None
    
    def _save_to_cache(self, season, games):
        cache_path = self._get_cache_path(season)
        try:
            with open(cache_path, 'w') as f:
                json.dump(games, f)
            logger.info(f"Сохранено в кэш: сезон {season}, {len(games)} матчей")
        except Exception as e:
            logger.warning(f"Ошибка записи кэша: {e}")
        
    def get_all_teams(self):
        print("📥 Загрузка списка команд NHL...")
        logger.info("Загрузка списка команд NHL")
        url = f"{self.base_url}/standings/now"
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            teams = {}
            for team_data in data.get('standings', []):
                team_abbr = team_data.get('teamAbbrev', {}).get('default', '')
                team_name = team_data.get('teamName', {}).get('default', '')
                if team_abbr and team_name:
                    teams[team_abbr] = {
                        'name': team_name,
                        'abbrev': team_abbr
                    }
            
            self.teams = teams
            print(f"✅ Загружено {len(teams)} команд")
            logger.info(f"Загружено {len(teams)} команд")
            return teams
        except Exception as e:
            logger.warning(f"Ошибка загрузки команд: {e}")
            print(f"⚠️ Ошибка загрузки команд: {e}")
            return self._get_fallback_teams()
    
    def _get_fallback_teams(self):
        teams = {
            'ANA': {'name': 'Anaheim Ducks', 'abbrev': 'ANA'},
            'ARI': {'name': 'Arizona Coyotes', 'abbrev': 'ARI'},
            'BOS': {'name': 'Boston Bruins', 'abbrev': 'BOS'},
            'BUF': {'name': 'Buffalo Sabres', 'abbrev': 'BUF'},
            'CGY': {'name': 'Calgary Flames', 'abbrev': 'CGY'},
            'CAR': {'name': 'Carolina Hurricanes', 'abbrev': 'CAR'},
            'CHI': {'name': 'Chicago Blackhawks', 'abbrev': 'CHI'},
            'COL': {'name': 'Colorado Avalanche', 'abbrev': 'COL'},
            'CBJ': {'name': 'Columbus Blue Jackets', 'abbrev': 'CBJ'},
            'DAL': {'name': 'Dallas Stars', 'abbrev': 'DAL'},
            'DET': {'name': 'Detroit Red Wings', 'abbrev': 'DET'},
            'EDM': {'name': 'Edmonton Oilers', 'abbrev': 'EDM'},
            'FLA': {'name': 'Florida Panthers', 'abbrev': 'FLA'},
            'LAK': {'name': 'Los Angeles Kings', 'abbrev': 'LAK'},
            'MIN': {'name': 'Minnesota Wild', 'abbrev': 'MIN'},
            'MTL': {'name': 'Montreal Canadiens', 'abbrev': 'MTL'},
            'NSH': {'name': 'Nashville Predators', 'abbrev': 'NSH'},
            'NJD': {'name': 'New Jersey Devils', 'abbrev': 'NJD'},
            'NYI': {'name': 'New York Islanders', 'abbrev': 'NYI'},
            'NYR': {'name': 'New York Rangers', 'abbrev': 'NYR'},
            'OTT': {'name': 'Ottawa Senators', 'abbrev': 'OTT'},
            'PHI': {'name': 'Philadelphia Flyers', 'abbrev': 'PHI'},
            'PIT': {'name': 'Pittsburgh Penguins', 'abbrev': 'PIT'},
            'SJS': {'name': 'San Jose Sharks', 'abbrev': 'SJS'},
            'SEA': {'name': 'Seattle Kraken', 'abbrev': 'SEA'},
            'STL': {'name': 'St. Louis Blues', 'abbrev': 'STL'},
            'TBL': {'name': 'Tampa Bay Lightning', 'abbrev': 'TBL'},
            'TOR': {'name': 'Toronto Maple Leafs', 'abbrev': 'TOR'},
            'UTA': {'name': 'Utah Hockey Club', 'abbrev': 'UTA'},
            'VAN': {'name': 'Vancouver Canucks', 'abbrev': 'VAN'},
            'VGK': {'name': 'Vegas Golden Knights', 'abbrev': 'VGK'},
            'WSH': {'name': 'Washington Capitals', 'abbrev': 'WSH'},
            'WPG': {'name': 'Winnipeg Jets', 'abbrev': 'WPG'}
        }
        self.teams = teams
        print(f"✅ Используем резервный список из {len(teams)} команд")
        return teams
    
    def load_team_schedule(self, team_abbr, season):
        url = f"{self.base_url}/club-schedule-season/{team_abbr}/{season}"
        games = []
        
        try:
            response = requests.get(url, timeout=30)
            if response.status_code != 200:
                return games
            data = response.json()
            
            for game in data.get('games', []):
                if game.get('gameState') in ['OFF', 'FINAL']:
                    game_info = self._parse_game(game)
                    if game_info:
                        games.append(game_info)
            
            return games
        except Exception as e:
            return games
    
    def _parse_game(self, game):
        try:
            home_team = game.get('homeTeam', {})
            away_team = game.get('awayTeam', {})
            
            home_abbr = home_team.get('abbrev', '')
            away_abbr = away_team.get('abbrev', '')
            home_score = home_team.get('score', 0)
            away_score = away_team.get('score', 0)
            
            if not home_abbr or not away_abbr:
                return None
            
            game_date = game.get('gameDate', '')
            game_id = game.get('id', 0)
            game_type = game.get('gameType', 2)
            
            return {
                'game_id': game_id,
                'date': game_date,
                'home_team': home_abbr,
                'away_team': away_abbr,
                'home_score': home_score,
                'away_score': away_score,
                'home_win': 1 if home_score > away_score else 0,
                'game_type': game_type,
                'overtime': 1 if game.get('periodDescriptor', {}).get('periodType') in ['OT', 'SO'] else 0
            }
        except Exception:
            return None
    
    def _load_season_from_api(self, season, use_cache=True):
        if use_cache:
            cached = self._load_from_cache(season)
            if cached:
                print(f"  📦 Сезон {season[:4]}-{season[4:]} загружен из кэша ({len(cached)} матчей)")
                return cached
        
        print(f"  🌐 Загрузка сезона {season[:4]}-{season[4:]} из API...")
        season_games = {}
        teams_processed = 0
        
        for team_abbr in list(self.teams.keys()):
            games = self.load_team_schedule(team_abbr, season)
            for game in games:
                game_key = game['game_id']
                if game_key not in season_games:
                    season_games[game_key] = game
            teams_processed += 1
            
            if teams_processed % 8 == 0:
                print(f"    Обработано {teams_processed}/{len(self.teams)} команд, найдено {len(season_games)} матчей")
            
            time.sleep(0.1)
        
        games_list = list(season_games.values())
        
        if use_cache and len(games_list) > 0:
            self._save_to_cache(season, games_list)
        
        print(f"  ✅ Сезон {season}: загружено {len(games_list)} матчей")
        return games_list
    
    def load_all_data(self, seasons=None, use_cache=True):
        if seasons is None:
            seasons = self.get_default_seasons(n_seasons=10)
        
        print("🏒 NHL Pattern Prediction System")
        print("=" * 50)
        
        self.get_all_teams()
        
        print(f"\n📊 Загрузка данных за {len(seasons)} сезонов...")
        logger.info(f"Загрузка {len(seasons)} сезонов: {seasons}")
        
        all_games = []
        stats = {
            'seasons_loaded': 0,
            'from_cache': 0,
            'from_api': 0,
            'total_games': 0
        }
        
        for i, season in enumerate(seasons):
            print(f"\n[{i+1}/{len(seasons)}] Сезон {season[:4]}-{season[4:]}")
            
            cached = self._load_from_cache(season) if use_cache else None
            
            if cached:
                games_list = cached
                print(f"  📦 Загружено из кэша: {len(games_list)} матчей")
                stats['from_cache'] += 1
            else:
                games_list = self._load_season_from_api(season, use_cache=use_cache)
                stats['from_api'] += 1
            
            all_games.extend(games_list)
            stats['seasons_loaded'] += 1
            stats['total_games'] = len(all_games)
        
        self.games = all_games
        
        df = pd.DataFrame(all_games)
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
            df = df.drop_duplicates(subset=['game_id']).reset_index(drop=True)
        
        print(f"\n{'='*50}")
        print(f"📊 Итого загружено:")
        print(f"   • Сезонов: {stats['seasons_loaded']}")
        print(f"   • Из кэша: {stats['from_cache']}")
        print(f"   • Из API: {stats['from_api']}")
        print(f"   • Всего матчей: {len(df)}")
        
        logger.info(f"Загружено {len(df)} матчей из {stats['seasons_loaded']} сезонов")
        
        return df
    
    @staticmethod
    def get_default_seasons(n_seasons=10):
        current_year = datetime.now().year
        current_month = datetime.now().month
        
        if current_month >= 10:
            end_year = current_year + 1
        else:
            end_year = current_year
        
        seasons = []
        for i in range(n_seasons):
            start = end_year - 1 - i
            end = end_year - i
            seasons.append(f"{start}{end}")
        
        seasons.reverse()
        return seasons
    
    def clear_cache(self):
        import shutil
        if os.path.exists(self.cache_dir):
            shutil.rmtree(self.cache_dir)
            os.makedirs(self.cache_dir)
            print("🗑️ Кэш очищен")
            logger.info("Кэш очищен")
    
    def get_cache_info(self):
        info = {'seasons': [], 'total_games': 0, 'total_size_mb': 0}
        
        if not os.path.exists(self.cache_dir):
            return info
        
        for filename in os.listdir(self.cache_dir):
            if filename.startswith('season_') and filename.endswith('.json'):
                filepath = os.path.join(self.cache_dir, filename)
                season = filename.replace('season_', '').replace('.json', '')
                size_mb = os.path.getsize(filepath) / (1024 * 1024)
                
                try:
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                    games_count = len(data)
                except:
                    games_count = 0
                
                info['seasons'].append({
                    'season': season,
                    'games': games_count,
                    'size_mb': round(size_mb, 2)
                })
                info['total_games'] += games_count
                info['total_size_mb'] += size_mb
        
        info['total_size_mb'] = round(info['total_size_mb'], 2)
        return info
    
    def generate_sample_data(self, n_games=2000):
        print("🎲 Генерация тестовых данных...")
        
        import random
        
        if not self.teams:
            self._get_fallback_teams()
        
        team_list = list(self.teams.keys())
        games = []
        
        start_date = datetime(2020, 10, 1)
        
        for i in range(n_games):
            home_team = random.choice(team_list)
            away_team = random.choice([t for t in team_list if t != home_team])
            
            home_score = random.randint(0, 6)
            away_score = random.randint(0, 6)
            if home_score == away_score:
                if random.random() > 0.5:
                    home_score += 1
                else:
                    away_score += 1
            
            game_date = start_date + pd.Timedelta(days=i // 5)
            
            games.append({
                'game_id': 2020000000 + i,
                'date': game_date,
                'home_team': home_team,
                'away_team': away_team,
                'home_score': home_score,
                'away_score': away_score,
                'home_win': 1 if home_score > away_score else 0,
                'game_type': 2,
                'overtime': random.choice([0, 0, 0, 1])
            })
        
        df = pd.DataFrame(games)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        
        print(f"✅ Сгенерировано {len(df)} тестовых матчей")
        self.games = games
        return df

# Backward compatibility alias
DataLoader = NHLDataLoader
