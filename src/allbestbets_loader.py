"""
AllBestBets API Loader
Получение valuebets и матчей через AllBestBets API
"""
import requests
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLBESTBETS_TOKEN = os.environ.get('ALLBESTBETS_API_TOKEN', '').strip()
ALLBESTBETS_FILTER_ID = os.environ.get('ALLBESTBETS_FILTER_ID', '').strip()

PREMATCH_URL = "https://rest-api-pr.allbestbets.com/api/v1/valuebets/bot_pro_search"
LIVE_URL = "https://rest-api-lv.allbestbets.com/api/v1/valuebets/bot_pro_search"

SPORT_IDS = {
    6: 'Hockey',
    4: 'Tennis',
    7: 'Football',
    1: 'Basketball'
}

HOCKEY_LEAGUES = {
    'NHL': ['NHL', 'USA. NHL', 'National Hockey League'],
    'KHL': ['KHL', 'Russia. KHL', 'Kontinental Hockey League'],
    'SHL': ['SHL', 'Sweden. SHL', 'Swedish Hockey League'],
    'Liiga': ['Liiga', 'Finland. Liiga', 'Finnish Liiga'],
    'DEL': ['DEL', 'Germany. DEL', 'Deutsche Eishockey Liga'],
}


class AllBestBetsLoader:
    """Загрузчик valuebets из AllBestBets API"""
    
    def __init__(self, token: Optional[str] = None, filter_id: Optional[str] = None):
        self.token = token or ALLBESTBETS_TOKEN
        self.filter_id = filter_id or ALLBESTBETS_FILTER_ID
        self._cache = {}
        self._cache_time = None
        self._cache_ttl = 300  # 5 минут
        
    def is_configured(self) -> bool:
        """Проверка настроен ли API"""
        return bool(self.token and self.filter_id)
    
    def get_upcoming_games(self, leagues: Optional[List[str]] = None, hours_ahead: int = 48) -> List[Dict]:
        """
        Получить предстоящие матчи с valuebets
        
        Args:
            leagues: Список лиг для фильтрации (NHL, KHL, SHL, Liiga, DEL)
            hours_ahead: Не используется (API возвращает все доступные)
            
        Returns:
            Список матчей
        """
        if not self.is_configured():
            logger.warning("AllBestBets API not configured")
            return []
        
        # Проверяем кэш
        cache_key = "valuebets_prematch"
        now = datetime.utcnow()
        
        if cache_key in self._cache:
            cache_data, cache_time = self._cache[cache_key]
            if (now - cache_time).total_seconds() < self._cache_ttl:
                logger.info(f"AllBestBets: используем кэш ({len(cache_data)} матчей)")
                return self._filter_by_leagues(cache_data, leagues)
        
        try:
            resp = requests.post(PREMATCH_URL, data={
                'access_token': self.token,
                'search_filter': self.filter_id
            }, timeout=30)
            
            if resp.status_code != 200:
                logger.error(f"AllBestBets error: {resp.status_code} - {resp.text[:200]}")
                return []
            
            data = resp.json()
            bets = data.get('bets', [])
            
            # Фильтруем только хоккей (sport_id=6)
            hockey_bets = [b for b in bets if b.get('sport_id') == 6]
            
            # Конвертируем в унифицированный формат
            matches = self._convert_to_matches(hockey_bets)
            
            # Кэшируем
            self._cache[cache_key] = (matches, now)
            logger.info(f"AllBestBets: найдено {len(matches)} хоккейных матчей")
            
            return self._filter_by_leagues(matches, leagues)
            
        except Exception as e:
            logger.error(f"AllBestBets request error: {e}")
            return []
    
    def _convert_to_matches(self, bets: List[Dict]) -> List[Dict]:
        """Конвертация valuebets в формат матчей"""
        seen_events = set()
        matches = []
        
        for bet in bets:
            event_id = bet.get('event_id') or bet.get('bookmaker_event_id')
            if not event_id or event_id in seen_events:
                continue
            
            seen_events.add(event_id)
            
            # Определяем лигу
            league_name = bet.get('league_name', '')
            league_code = self._detect_league(league_name)
            
            # Дата матча
            started_at = bet.get('started_at')
            match_date = None
            if started_at:
                try:
                    match_date = datetime.fromtimestamp(started_at)
                except:
                    pass
            
            matches.append({
                'event_id': f"abb_{event_id}",
                'game_id': event_id,
                'league': league_code,
                'league_name': league_name,
                'home_team': bet.get('home', ''),
                'away_team': bet.get('away', ''),
                'match_date': match_date,
                'status': 'Scheduled',
                'home_odds': bet.get('koef') if bet.get('home') else None,
                'away_odds': bet.get('koef') if bet.get('away') else None,
                'valuebet_coef': bet.get('koef'),
                'bookmaker_id': bet.get('bookmaker_id'),
                'source': 'allbestbets'
            })
        
        return matches
    
    def _detect_league(self, league_name: str) -> str:
        """Определить код лиги по названию"""
        league_upper = league_name.upper()
        
        for code, patterns in HOCKEY_LEAGUES.items():
            for pattern in patterns:
                if pattern.upper() in league_upper:
                    return code
        
        return 'OTHER'
    
    def _filter_by_leagues(self, matches: List[Dict], leagues: Optional[List[str]]) -> List[Dict]:
        """Фильтрация матчей по лигам"""
        if not leagues:
            return matches
        
        return [m for m in matches if m.get('league') in leagues]
    
    def get_valuebets(self, sport_id: int = 6) -> List[Dict]:
        """
        Получить все valuebets для спорта
        
        Args:
            sport_id: ID спорта (6 = хоккей)
            
        Returns:
            Список valuebets
        """
        if not self.is_configured():
            return []
        
        try:
            resp = requests.post(PREMATCH_URL, data={
                'access_token': self.token,
                'search_filter': self.filter_id
            }, timeout=30)
            
            if resp.status_code != 200:
                return []
            
            data = resp.json()
            bets = data.get('bets', [])
            
            return [b for b in bets if b.get('sport_id') == sport_id]
            
        except Exception as e:
            logger.error(f"AllBestBets valuebets error: {e}")
            return []


# Демо-данные для тестирования без API
def get_demo_matches() -> List[Dict]:
    """Демо матчи для тестирования"""
    now = datetime.utcnow()
    return [
        {
            'event_id': 'demo_1',
            'game_id': 1,
            'league': 'NHL',
            'league_name': 'USA. NHL',
            'home_team': 'Minnesota Wild',
            'away_team': 'Winnipeg Jets',
            'match_date': now + timedelta(hours=6),
            'status': 'Scheduled',
            'home_odds': 2.15,
            'away_odds': 1.85,
            'source': 'demo'
        },
        {
            'event_id': 'demo_2',
            'game_id': 2,
            'league': 'KHL',
            'league_name': 'Russia. KHL',
            'home_team': 'CSKA Moscow',
            'away_team': 'Avangard Omsk',
            'match_date': now + timedelta(hours=4),
            'status': 'Scheduled',
            'home_odds': 1.75,
            'away_odds': 2.25,
            'source': 'demo'
        },
        {
            'event_id': 'demo_3',
            'game_id': 3,
            'league': 'SHL',
            'league_name': 'Sweden. SHL',
            'home_team': 'Djurgården',
            'away_team': 'Växjö',
            'match_date': now + timedelta(hours=5),
            'status': 'Scheduled',
            'home_odds': 2.10,
            'away_odds': 1.90,
            'source': 'demo'
        }
    ]
