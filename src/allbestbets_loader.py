"""
AllBestBets API Integration
Получение коэффициентов для хоккейных матчей
"""
import requests
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AllBestBetsLoader:
    """Загрузчик коэффициентов из AllBestBets API"""
    
    BASE_URL_PREMATCH = "https://rest-api-pr.allbestbets.com"
    BASE_URL_LIVE = "https://rest-api-lv.allbestbets.com"
    
    HOCKEY_LEAGUES = {
        'NHL': {'sport': 'hockey', 'country': 'USA', 'league': 'NHL'},
        'KHL': {'sport': 'hockey', 'country': 'Russia', 'league': 'KHL'},
        'SHL': {'sport': 'hockey', 'country': 'Sweden', 'league': 'SHL'},
        'Liiga': {'sport': 'hockey', 'country': 'Finland', 'league': 'Liiga'},
        'DEL': {'sport': 'hockey', 'country': 'Germany', 'league': 'DEL'}
    }
    
    def __init__(self, api_token: Optional[str] = None):
        self.api_token = api_token or os.environ.get('ALLBESTBETS_API_TOKEN')
        self.filter_id = os.environ.get('ALLBESTBETS_FILTER_ID')
        
    def is_configured(self) -> bool:
        """Проверка настроен ли API"""
        return bool(self.api_token and self.filter_id)
    
    def get_hockey_odds(self, league: str = None) -> List[Dict]:
        """
        Получить коэффициенты для хоккейных матчей
        
        Args:
            league: Конкретная лига (NHL, KHL, SHL, Liiga, DEL) или None для всех
            
        Returns:
            Список матчей с коэффициентами
        """
        if not self.is_configured():
            logger.warning("AllBestBets API не настроен. Установите ALLBESTBETS_API_TOKEN и ALLBESTBETS_FILTER_ID")
            return []
        
        try:
            headers = {
                'Authorization': f'Bearer {self.api_token}',
                'Content-Type': 'application/json'
            }
            
            params = {
                'filter_id': self.filter_id,
                'sport': 'hockey'
            }
            
            if league and league in self.HOCKEY_LEAGUES:
                league_info = self.HOCKEY_LEAGUES[league]
                params['country'] = league_info['country']
                params['league'] = league_info['league']
            
            response = requests.get(
                f"{self.BASE_URL_PREMATCH}/api/v1/valuebets",
                headers=headers,
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return self._parse_odds_response(data, league)
            else:
                logger.error(f"AllBestBets API error: {response.status_code} - {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"Error fetching odds from AllBestBets: {e}")
            return []
    
    def _parse_odds_response(self, data: Dict, league_filter: str = None) -> List[Dict]:
        """Парсинг ответа API"""
        matches = []
        
        events = data.get('data', []) if isinstance(data, dict) else data
        
        for event in events:
            try:
                match_info = {
                    'event_id': event.get('event_id'),
                    'league': self._detect_league(event),
                    'home_team': event.get('home', event.get('team1', '')),
                    'away_team': event.get('away', event.get('team2', '')),
                    'match_date': self._parse_date(event.get('starts', event.get('start_time'))),
                    'market': event.get('market', 'moneyline'),
                    'bookmaker': event.get('bookmaker', event.get('bk_name', '')),
                    'home_odds': self._parse_odds(event.get('home_odds', event.get('cf1'))),
                    'away_odds': self._parse_odds(event.get('away_odds', event.get('cf2'))),
                    'draw_odds': self._parse_odds(event.get('draw_odds', event.get('cfx'))),
                    'value_percent': event.get('value', event.get('percent', 0)),
                    'raw_data': event
                }
                
                if league_filter and match_info['league'] != league_filter:
                    continue
                    
                if match_info['home_team'] and match_info['away_team']:
                    matches.append(match_info)
                    
            except Exception as e:
                logger.warning(f"Error parsing event: {e}")
                continue
        
        return matches
    
    def _detect_league(self, event: Dict) -> str:
        """Определить лигу по данным события"""
        league_name = event.get('league', event.get('competition', '')).upper()
        country = event.get('country', '').upper()
        
        if 'NHL' in league_name or country == 'USA':
            return 'NHL'
        elif 'KHL' in league_name or country == 'RUSSIA':
            return 'KHL'
        elif 'SHL' in league_name or country == 'SWEDEN':
            return 'SHL'
        elif 'LIIGA' in league_name or country == 'FINLAND':
            return 'Liiga'
        elif 'DEL' in league_name or country == 'GERMANY':
            return 'DEL'
        else:
            return league_name or 'Unknown'
    
    def _parse_date(self, date_str) -> Optional[datetime]:
        """Парсинг даты"""
        if not date_str:
            return None
            
        if isinstance(date_str, datetime):
            return date_str
            
        try:
            if isinstance(date_str, (int, float)):
                return datetime.fromtimestamp(date_str)
            
            for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
        except Exception:
            pass
            
        return None
    
    def _parse_odds(self, odds) -> Optional[float]:
        """Парсинг коэффициента"""
        if odds is None:
            return None
        try:
            return float(odds)
        except (ValueError, TypeError):
            return None
    
    def get_upcoming_matches(self, hours_ahead: int = 48) -> List[Dict]:
        """
        Получить предстоящие матчи на ближайшие N часов
        
        Args:
            hours_ahead: Сколько часов вперед смотреть
            
        Returns:
            Список предстоящих матчей с коэффициентами
        """
        all_matches = self.get_hockey_odds()
        
        now = datetime.utcnow()
        cutoff = now + timedelta(hours=hours_ahead)
        
        upcoming = []
        for match in all_matches:
            match_date = match.get('match_date')
            if match_date and now <= match_date <= cutoff:
                upcoming.append(match)
        
        upcoming.sort(key=lambda x: x.get('match_date') or datetime.max)
        
        return upcoming


def get_demo_odds():
    """
    Демо-данные для тестирования без API токена
    """
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
