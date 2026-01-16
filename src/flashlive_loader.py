"""
FlashLive Sports API Loader (via RapidAPI)
Получение матчей и коэффициентов через FlashScore данные
"""
import requests
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RAPIDAPI_KEY = os.environ.get('RAPIDAPI_KEY', '').strip()
RAPIDAPI_HOST = 'flashlive-sports.p.rapidapi.com'
BASE_URL = f'https://{RAPIDAPI_HOST}'

HOCKEY_SPORT_ID = 4  # Hockey sport_id в FlashLive API

# Только 5 основных лиг
SUPPORTED_LEAGUES = ['NHL', 'KHL', 'SHL', 'Liiga', 'DEL']

HOCKEY_LEAGUES = {
    'NHL': ['usa: nhl', 'usa. nhl', 'usa-nhl', 'national hockey league', 'nhl '],
    'KHL': ['russia: khl', 'russia. khl', 'russia-khl', 'kontinental hockey league', 'khl '],
    'SHL': ['sweden: shl', 'sweden. shl', 'sweden-shl', 'swedish hockey league', ' shl'],
    'Liiga': ['finland: liiga', 'finland. liiga', 'finland-liiga', 'finnish liiga', 'liiga'],
    'DEL': ['germany: del', 'germany. del', 'germany-del', 'deutsche eishockey liga', ' del'],
}


class FlashLiveLoader:
    """Загрузчик матчей через FlashLive Sports API (RapidAPI)"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or RAPIDAPI_KEY
        self._cache = {}
        self._cache_time = None
        self._cache_ttl = 300  # 5 минут
        self._sport_id = None  # Будет получен динамически
        
    def is_configured(self) -> bool:
        """Проверка настроен ли API"""
        return bool(self.api_key)
    
    def _get_headers(self) -> Dict:
        """Заголовки для RapidAPI"""
        return {
            'x-rapidapi-key': self.api_key,
            'x-rapidapi-host': RAPIDAPI_HOST
        }
    
    def _get_hockey_sport_id(self) -> int:
        """Получить sport_id для хоккея"""
        if self._sport_id:
            return self._sport_id
        
        try:
            resp = requests.get(
                f'{BASE_URL}/v1/sports/list',
                headers=self._get_headers(),
                params={'locale': 'en_INT'},
                timeout=30
            )
            
            if resp.status_code == 200:
                data = resp.json()
                sports = data.get('DATA', [])
                for sport in sports:
                    name = sport.get('NAME', '').lower()
                    if 'hockey' in name or 'ice hockey' in name:
                        self._sport_id = sport.get('ID')
                        logger.info(f"FlashLive: Hockey sport_id = {self._sport_id}")
                        return self._sport_id
            
            # Fallback
            self._sport_id = HOCKEY_SPORT_ID
            return self._sport_id
            
        except Exception as e:
            logger.error(f"FlashLive get_sports error: {e}")
            return HOCKEY_SPORT_ID
    
    def get_upcoming_games(self, leagues: Optional[List[str]] = None, days_ahead: int = 2) -> List[Dict]:
        """
        Получить предстоящие матчи (только 5 основных лиг: NHL, KHL, SHL, Liiga, DEL)
        
        Args:
            leagues: Список лиг для фильтрации (по умолчанию все 5)
            days_ahead: Сколько дней вперёд
            
        Returns:
            Список матчей
        """
        if not self.is_configured():
            logger.warning("FlashLive API not configured (RAPIDAPI_KEY missing)")
            return []
        
        # По умолчанию только 5 основных лиг
        if leagues is None:
            leagues = SUPPORTED_LEAGUES
        
        # Проверяем кэш
        cache_key = f"events_{days_ahead}"
        now = datetime.utcnow()
        
        if cache_key in self._cache:
            cache_data, cache_time = self._cache[cache_key]
            if (now - cache_time).total_seconds() < self._cache_ttl:
                filtered = self._filter_by_leagues(cache_data, leagues)
                logger.info(f"FlashLive: из кэша {len(filtered)} матчей (5 лиг)")
                return filtered
        
        all_matches = []
        sport_id = self._get_hockey_sport_id()
        
        # Получаем матчи на несколько дней
        for day_offset in range(days_ahead + 1):
            try:
                matches = self._fetch_events_for_day(sport_id, day_offset)
                all_matches.extend(matches)
            except Exception as e:
                logger.error(f"FlashLive day {day_offset} error: {e}")
        
        # Убираем дубликаты
        seen_ids = set()
        unique_matches = []
        for m in all_matches:
            if m['event_id'] not in seen_ids:
                seen_ids.add(m['event_id'])
                unique_matches.append(m)
        
        # Кэшируем все матчи
        self._cache[cache_key] = (unique_matches, now)
        
        # Фильтруем только 5 основных лиг
        filtered = self._filter_by_leagues(unique_matches, leagues)
        logger.info(f"FlashLive: {len(filtered)} матчей в 5 лигах (всего {len(unique_matches)})")
        
        return filtered
    
    def _fetch_events_for_day(self, sport_id: int, day_offset: int) -> List[Dict]:
        """Получить матчи на конкретный день"""
        try:
            resp = requests.get(
                f'{BASE_URL}/v1/events/list',
                headers=self._get_headers(),
                params={
                    'sport_id': sport_id,
                    'indent_days': day_offset,  # FlashLive uses indent_days, not day
                    'locale': 'en_INT',
                    'timezone': 0  # UTC offset as integer
                },
                timeout=30
            )
            
            if resp.status_code == 429:
                logger.warning("FlashLive: Rate limit exceeded")
                return []
            
            if resp.status_code != 200:
                logger.error(f"FlashLive error: {resp.status_code}")
                return []
            
            data = resp.json()
            return self._parse_events(data)
            
        except Exception as e:
            logger.error(f"FlashLive request error: {e}")
            return []
    
    def _parse_events(self, data: Dict) -> List[Dict]:
        """Парсинг ответа API в унифицированный формат"""
        matches = []
        events_data = data.get('DATA', [])
        
        for tournament in events_data:
            tournament_name = tournament.get('NAME', '')
            league_code = self._detect_league(tournament_name)
            
            events = tournament.get('EVENTS', [])
            for event in events:
                # Пропускаем завершённые матчи
                stage_type = event.get('STAGE_TYPE')
                if stage_type == 'FINISHED':
                    continue
                
                event_id = event.get('EVENT_ID', '')
                home_team = event.get('HOME_NAME', '')
                away_team = event.get('AWAY_NAME', '')
                
                # Время матча
                start_time = event.get('START_TIME')
                match_date = None
                if start_time:
                    try:
                        match_date = datetime.fromtimestamp(start_time)
                    except:
                        pass
                
                # Коэффициенты (если есть)
                home_odds = None
                away_odds = None
                draw_odds = None
                
                odds_data = event.get('ODDS', {})
                if odds_data:
                    home_odds = odds_data.get('1')
                    away_odds = odds_data.get('2')
                    draw_odds = odds_data.get('X')
                
                matches.append({
                    'event_id': f"flash_{event_id}",
                    'game_id': event_id,
                    'league': league_code,
                    'league_name': tournament_name,
                    'home_team': home_team,
                    'away_team': away_team,
                    'match_date': match_date,
                    'status': stage_type or 'Scheduled',
                    'home_odds': home_odds,
                    'away_odds': away_odds,
                    'draw_odds': draw_odds,
                    'source': 'flashlive'
                })
        
        return matches
    
    def _detect_league(self, tournament_name: str) -> str:
        """Определить код лиги по названию турнира"""
        name_lower = tournament_name.lower()
        
        for code, patterns in HOCKEY_LEAGUES.items():
            for pattern in patterns:
                if pattern in name_lower:
                    return code
        
        return 'OTHER'
    
    def _filter_by_leagues(self, matches: List[Dict], leagues: Optional[List[str]]) -> List[Dict]:
        """Фильтрация матчей по лигам"""
        if not leagues:
            return matches
        
        return [m for m in matches if m.get('league') in leagues]
    
    def get_event_odds(self, event_id: str) -> Optional[Dict]:
        """Получить коэффициенты для конкретного матча
        
        Returns:
            Dict с ключами home_odds, draw_odds, away_odds, bookmaker
            или None если коэффициенты недоступны
        """
        if not self.is_configured():
            return None
        
        raw_id = event_id.replace('flash_', '')
        
        try:
            resp = requests.get(
                f'{BASE_URL}/v1/events/odds',
                headers=self._get_headers(),
                params={
                    'event_id': raw_id,
                    'locale': 'en_INT'
                },
                timeout=30
            )
            
            if resp.status_code != 200:
                return None
            
            data = resp.json()
            
            for betting_type in data.get('DATA', []):
                if betting_type.get('BETTING_TYPE') != '*1X2':
                    continue
                
                for period in betting_type.get('PERIODS', []):
                    if 'Full Time' not in period.get('ODDS_STAGE', ''):
                        continue
                    
                    for group in period.get('GROUPS', []):
                        markets = group.get('MARKETS', [])
                        if not markets:
                            continue
                        
                        market = markets[0]
                        home = market.get('ODD_CELL_FIRST', {}).get('VALUE')
                        draw = market.get('ODD_CELL_SECOND', {}).get('VALUE')
                        away = market.get('ODD_CELL_THIRD', {}).get('VALUE')
                        bookmaker = market.get('BOOKMAKER_NAME', 'Unknown')
                        
                        if home and away:
                            return {
                                'home_odds': float(home),
                                'draw_odds': float(draw) if draw else None,
                                'away_odds': float(away),
                                'bookmaker': bookmaker
                            }
            
            return None
            
        except Exception as e:
            logger.error(f"FlashLive odds error: {e}")
            return None
    
    def get_matches_with_odds(self, days_ahead: int = 2, leagues: Optional[List[str]] = None) -> List[Dict]:
        """Получить матчи с коэффициентами
        
        Сначала получает список матчей, затем загружает коэффициенты
        для каждого матча из целевых лиг.
        """
        matches = self.get_upcoming_games(days_ahead=days_ahead, leagues=leagues)
        
        target_leagues = leagues or SUPPORTED_LEAGUES
        filtered = [m for m in matches if m.get('league') in target_leagues]
        
        logger.info(f"Загрузка коэффициентов для {len(filtered)} матчей...")
        
        matches_with_odds = []
        for match in filtered:
            event_id = match.get('event_id', '')
            odds = self.get_event_odds(event_id)
            
            if odds:
                match['home_odds'] = odds['home_odds']
                match['away_odds'] = odds['away_odds']
                match['draw_odds'] = odds.get('draw_odds')
                match['bookmaker'] = odds.get('bookmaker')
                matches_with_odds.append(match)
        
        logger.info(f"Получено {len(matches_with_odds)} матчей с коэффициентами")
        return matches_with_odds


def get_demo_matches() -> List[Dict]:
    """Демо матчи для тестирования"""
    now = datetime.utcnow()
    return [
        {
            'event_id': 'demo_1',
            'game_id': 1,
            'league': 'NHL',
            'league_name': 'USA: NHL',
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
            'league': 'NHL',
            'league_name': 'USA: NHL',
            'home_team': 'Edmonton Oilers',
            'away_team': 'Calgary Flames',
            'match_date': now + timedelta(hours=8),
            'status': 'Scheduled',
            'home_odds': 1.75,
            'away_odds': 2.25,
            'source': 'demo'
        },
        {
            'event_id': 'demo_3',
            'game_id': 3,
            'league': 'KHL',
            'league_name': 'Russia: KHL',
            'home_team': 'CSKA Moscow',
            'away_team': 'Avangard Omsk',
            'match_date': now + timedelta(hours=4),
            'status': 'Scheduled',
            'home_odds': 1.65,
            'away_odds': 2.40,
            'source': 'demo'
        }
    ]
