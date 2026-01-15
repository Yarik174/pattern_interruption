"""
API-Sports Odds Loader
Получение коэффициентов для хоккейных матчей через API-Sports
"""
import requests
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_SPORTS_KEY = os.environ.get('API_SPORTS_KEY', '').strip()
BASE_URL = "https://v1.hockey.api-sports.io"

LEAGUES = {
    'NHL': {'id': 57, 'name': 'NHL', 'country': 'USA'},
    'KHL': {'id': 35, 'name': 'KHL', 'country': 'Russia'},
    'SHL': {'id': 47, 'name': 'SHL', 'country': 'Sweden'},
    'Liiga': {'id': 16, 'name': 'Liiga', 'country': 'Finland'},
    'DEL': {'id': 19, 'name': 'DEL', 'country': 'Germany'},
    'Czech': {'id': 10, 'name': 'Extraliga', 'country': 'Czech Republic'},
    'Swiss': {'id': 52, 'name': 'NL', 'country': 'Switzerland'},
}


class APISportsOddsLoader:
    """Загрузчик коэффициентов из API-Sports
    
    ВАЖНО: Бесплатный план = 100 запросов/день!
    Оптимизации:
    - Кэширование на 2 часа
    - Один запрос на лигу (только сегодня)
    - Счётчик запросов для контроля
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or API_SPORTS_KEY
        self._games_cache = {}
        self._odds_cache = {}
        self._cache_time = None
        self._cache_ttl = 7200  # 2 часа кэш (было 300 сек)
        self._daily_requests = 0
        self._daily_limit = 95  # Оставляем 5 запросов на ручные проверки
        self._last_reset_date = None
        
    def is_configured(self) -> bool:
        """Проверка настроен ли API"""
        return bool(self.api_key)
    
    def _check_daily_limit(self):
        """Проверить и сбросить дневной счётчик"""
        today = datetime.utcnow().date()
        if self._last_reset_date != today:
            self._daily_requests = 0
            self._last_reset_date = today
            logger.info("API-Sports: дневной счётчик сброшен")
    
    def get_requests_remaining(self) -> int:
        """Сколько запросов осталось на сегодня"""
        self._check_daily_limit()
        return max(0, self._daily_limit - self._daily_requests)
    
    def _make_request(self, endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
        """Выполнить запрос к API с проверкой лимитов"""
        if not self.api_key:
            logger.warning("API_SPORTS_KEY не установлен")
            return None
        
        # Проверка дневного лимита
        self._check_daily_limit()
        if self._daily_requests >= self._daily_limit:
            logger.warning(f"API-Sports: дневной лимит исчерпан ({self._daily_limit} запросов)")
            return None
            
        headers = {'x-apisports-key': self.api_key.strip()}
        url = f"{BASE_URL}/{endpoint}"
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            self._daily_requests += 1
            
            if response.status_code == 200:
                data = response.json()
                remaining = response.headers.get('x-ratelimit-requests-remaining', 'N/A')
                logger.info(f"API-Sports: {endpoint} - осталось API: {remaining}, локальный лимит: {self._daily_limit - self._daily_requests}")
                return data
            else:
                logger.error(f"API-Sports error: {response.status_code} - {response.text[:200]}")
                return None
        except Exception as e:
            logger.error(f"API-Sports request error: {e}")
            return None
    
    def get_upcoming_games(self, leagues: Optional[List[str]] = None, hours_ahead: int = 24) -> List[Dict]:
        """
        Получить предстоящие матчи (с кэшированием 2 часа)
        
        ОПТИМИЗАЦИЯ: При 100 запросах/день и 5 лигах:
        - Проверка раз в 2 часа = 12 проверок × 5 лиг = 60 запросов
        - Остаётся 40 запросов на odds и ручные проверки
        
        Args:
            leagues: Список лиг (по умолчанию NHL только - экономия)
            hours_ahead: Сколько часов вперёд смотреть (24 = только сегодня)
            
        Returns:
            Список матчей (из кэша или API)
        """
        # По умолчанию только NHL для экономии запросов
        if leagues is None:
            leagues = ['NHL']  # Было ['NHL', 'KHL', 'SHL', 'Liiga', 'DEL']
        
        # Проверяем кэш
        cache_key = f"games_{'-'.join(sorted(leagues))}"
        now = datetime.utcnow()
        
        if cache_key in self._games_cache:
            cache_data, cache_time = self._games_cache[cache_key]
            if (now - cache_time).total_seconds() < self._cache_ttl:
                logger.info(f"API-Sports: используем кэш ({len(cache_data)} матчей, возраст {int((now - cache_time).total_seconds())}с)")
                return cache_data
        
        date_from = now.strftime('%Y-%m-%d')
        
        all_games = []
        
        for league_code in leagues:
            if league_code not in LEAGUES:
                continue
            
            # Проверка лимита перед запросом
            if self.get_requests_remaining() <= 0:
                logger.warning("API-Sports: лимит исчерпан, используем частичные данные")
                break
                
            league_info = LEAGUES[league_code]
            league_id = league_info['id']
            
            # ОДИН запрос на лигу (только сегодня)
            # ВАЖНО: API требует указать season для текущего сезона
            data = self._make_request('games', {
                'league': league_id,
                'season': 2025,
                'date': date_from,
                'timezone': 'UTC'
            })
            
            if data and 'response' in data:
                games_count = len(data['response'])
                statuses = {}
                for game in data['response']:
                    status = game.get('status', {}).get('short', '')
                    statuses[status] = statuses.get(status, 0) + 1
                    # Расширенный фильтр: NS (Not Started), TBD, SUSP, POST (Postponed), CANC, PST
                    # Также включаем пустой статус и любые "scheduled" варианты
                    if status in ['NS', 'TBD', 'SUSP', 'POST', 'PST', 'CANC', ''] or status is None:
                        game_info = self._parse_game(game, league_code)
                        if game_info:
                            all_games.append(game_info)
                logger.info(f"API-Sports {league_code}: {games_count} матчей, статусы: {statuses}")
        
        all_games.sort(key=lambda x: x.get('match_date') or datetime.max)
        
        # Сохраняем в кэш
        self._games_cache[cache_key] = (all_games, now)
        logger.info(f"API-Sports: найдено {len(all_games)} матчей, кэшировано на {self._cache_ttl}с")
        
        return all_games
    
    def _parse_game(self, game: dict, league_code: str) -> Optional[Dict]:
        """Парсинг данных матча"""
        try:
            game_id = game.get('id')
            date_str = game.get('date')
            
            home_team = game.get('teams', {}).get('home', {})
            away_team = game.get('teams', {}).get('away', {})
            
            match_date = None
            if date_str:
                try:
                    match_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    match_date = match_date.replace(tzinfo=None)
                except:
                    pass
            
            return {
                'event_id': f"apisports_{game_id}",
                'game_id': game_id,
                'league': league_code,
                'home_team': home_team.get('name', ''),
                'home_team_id': home_team.get('id'),
                'away_team': away_team.get('name', ''),
                'away_team_id': away_team.get('id'),
                'match_date': match_date,
                'status': game.get('status', {}).get('long', 'Scheduled'),
                'venue': game.get('venue', {}).get('name', ''),
            }
        except Exception as e:
            logger.error(f"Error parsing game: {e}")
            return None
    
    def get_odds_for_game(self, game_id: int) -> Optional[Dict]:
        """
        Получить коэффициенты для матча
        
        Args:
            game_id: ID матча в API-Sports
            
        Returns:
            Словарь с коэффициентами
        """
        data = self._make_request('odds', {'game': game_id})
        
        if not data or 'response' not in data:
            return None
        
        odds_list = data['response']
        if not odds_list:
            return None
        
        return self._parse_odds(odds_list[0])
    
    def _parse_odds(self, odds_data: dict) -> Dict:
        """Парсинг данных о коэффициентах"""
        result = {
            'bookmakers': [],
            'best_home_odds': None,
            'best_away_odds': None,
            'best_draw_odds': None,
        }
        
        bookmakers = odds_data.get('bookmakers', [])
        
        for bm in bookmakers:
            bm_name = bm.get('name', '')
            bm_bets = bm.get('bets', [])
            
            for bet in bm_bets:
                bet_name = bet.get('name', '')
                if bet_name in ['Match Winner', 'Home/Away', '1X2']:
                    values = bet.get('values', [])
                    odds_info = {
                        'bookmaker': bm_name,
                        'market': bet_name,
                        'home_odds': None,
                        'away_odds': None,
                        'draw_odds': None,
                    }
                    
                    for v in values:
                        value = v.get('value', '')
                        odd = self._parse_odd(v.get('odd'))
                        
                        if value in ['Home', '1', 'home']:
                            odds_info['home_odds'] = odd
                            if odd and (result['best_home_odds'] is None or odd > result['best_home_odds']):
                                result['best_home_odds'] = odd
                        elif value in ['Away', '2', 'away']:
                            odds_info['away_odds'] = odd
                            if odd and (result['best_away_odds'] is None or odd > result['best_away_odds']):
                                result['best_away_odds'] = odd
                        elif value in ['Draw', 'X', 'draw']:
                            odds_info['draw_odds'] = odd
                            if odd and (result['best_draw_odds'] is None or odd > result['best_draw_odds']):
                                result['best_draw_odds'] = odd
                    
                    result['bookmakers'].append(odds_info)
        
        return result
    
    def _parse_odd(self, odd) -> Optional[float]:
        """Парсинг коэффициента"""
        if odd is None:
            return None
        try:
            return float(odd)
        except (ValueError, TypeError):
            return None
    
    def get_upcoming_matches(self, hours_ahead: int = 48) -> List[Dict]:
        """
        Получить предстоящие матчи с коэффициентами
        Совместимый интерфейс с OddsMonitor
        
        Args:
            hours_ahead: Сколько часов вперёд смотреть
            
        Returns:
            Список матчей с коэффициентами
        """
        games = self.get_upcoming_games(hours_ahead=hours_ahead)
        
        matches_with_odds = []
        
        for game in games[:20]:
            game_id = game.get('game_id')
            if not game_id:
                continue
            
            odds = self.get_odds_for_game(game_id)
            
            match = {
                'event_id': game.get('event_id'),
                'game_id': game_id,
                'league': game.get('league'),
                'home_team': game.get('home_team'),
                'away_team': game.get('away_team'),
                'match_date': game.get('match_date'),
                'market': 'moneyline',
                'bookmaker': 'API-Sports',
                'home_odds': None,
                'away_odds': None,
                'draw_odds': None,
                'value_percent': 0,
            }
            
            if odds:
                match['home_odds'] = odds.get('best_home_odds')
                match['away_odds'] = odds.get('best_away_odds')
                match['draw_odds'] = odds.get('best_draw_odds')
                match['bookmakers'] = odds.get('bookmakers', [])
            
            matches_with_odds.append(match)
        
        logger.info(f"API-Sports: {len(matches_with_odds)} матчей с коэффициентами")
        return matches_with_odds
    
    def get_live_games(self) -> List[Dict]:
        """Получить текущие live матчи"""
        data = self._make_request('games', {'live': 'all'})
        
        if not data or 'response' not in data:
            return []
        
        games = []
        for game in data['response']:
            league_id = game.get('league', {}).get('id')
            league_code = None
            for code, info in LEAGUES.items():
                if info['id'] == league_id:
                    league_code = code
                    break
            
            if league_code:
                game_info = self._parse_game(game, league_code)
                if game_info:
                    game_info['is_live'] = True
                    game_info['current_period'] = game.get('periods', {}).get('current')
                    game_info['home_score'] = game.get('scores', {}).get('home')
                    game_info['away_score'] = game.get('scores', {}).get('away')
                    games.append(game_info)
        
        return games


def get_demo_odds():
    """Демо-данные для тестирования без API ключа"""
    now = datetime.utcnow()
    
    return [
        {
            'event_id': 'demo_1',
            'league': 'NHL',
            'home_team': 'Boston Bruins',
            'away_team': 'Toronto Maple Leafs',
            'match_date': now + timedelta(hours=2),
            'market': 'moneyline',
            'bookmaker': 'Demo',
            'home_odds': 1.85,
            'away_odds': 2.10,
            'draw_odds': None,
            'value_percent': 0
        },
        {
            'event_id': 'demo_2',
            'league': 'KHL',
            'home_team': 'CSKA Moscow',
            'away_team': 'SKA St. Petersburg',
            'match_date': now + timedelta(hours=5),
            'market': 'moneyline',
            'bookmaker': 'Demo',
            'home_odds': 2.20,
            'away_odds': 1.75,
            'draw_odds': 3.80,
            'value_percent': 0
        },
        {
            'event_id': 'demo_3',
            'league': 'SHL',
            'home_team': 'Frolunda HC',
            'away_team': 'Lulea HF',
            'match_date': now + timedelta(hours=8),
            'market': 'moneyline',
            'bookmaker': 'Demo',
            'home_odds': 1.95,
            'away_odds': 1.95,
            'draw_odds': 3.60,
            'value_percent': 0
        }
    ]
