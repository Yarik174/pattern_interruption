"""
FlashLive Sports API Loader (via RapidAPI)
Получение матчей и коэффициентов через FlashScore данные
"""
import requests
import os
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Callable
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Callback для отправки алертов (устанавливается извне)
_error_alert_callback: Optional[Callable[[str], None]] = None
_telegram_notifier_instance = None

def set_error_alert_callback(callback: Callable[[str], None]):
    """Установить callback для отправки алертов об ошибках"""
    global _error_alert_callback
    _error_alert_callback = callback

def set_telegram_notifier(notifier):
    """Установить TelegramNotifier для динамической отправки алертов"""
    global _telegram_notifier_instance
    _telegram_notifier_instance = notifier

def _send_error_alert(message: str):
    """Отправить алерт об ошибке через callback или TelegramNotifier"""
    global _error_alert_callback, _telegram_notifier_instance
    
    # Приоритет: callback, затем прямой вызов TelegramNotifier
    if _error_alert_callback:
        try:
            _error_alert_callback(message)
            return
        except Exception as e:
            logger.error(f"Failed to send error alert via callback: {e}")
    
    # Fallback: прямой вызов TelegramNotifier если он установлен и настроен
    if _telegram_notifier_instance:
        try:
            if _telegram_notifier_instance.is_configured():
                _telegram_notifier_instance.send_error_alert(message)
                return
        except Exception as e:
            logger.error(f"Failed to send error alert via notifier: {e}")
    
    # Если ничего не настроено - только логируем
    logger.warning(f"Error alert not sent (Telegram not configured): {message}")

RAPIDAPI_KEY = os.environ.get('RAPIDAPI_KEY', '').strip()
RAPIDAPI_HOST = 'flashlive-sports.p.rapidapi.com'
BASE_URL = f'https://{RAPIDAPI_HOST}'

from src.sports_config import SportType, SPORTS_CONFIG, get_sport_config, match_league, get_leagues_for_sport

HOCKEY_SPORT_ID = 4  # Hockey sport_id в FlashLive API (для обратной совместимости)

# Для обратной совместимости
SUPPORTED_LEAGUES = ['NHL', 'KHL', 'SHL', 'Liiga', 'DEL']

HOCKEY_LEAGUES = {
    'NHL': ['usa: nhl', 'usa. nhl', 'usa-nhl', 'national hockey league', 'nhl '],
    'KHL': ['russia: khl', 'russia. khl', 'russia-khl', 'kontinental hockey league', 'khl '],
    'SHL': ['sweden: shl', 'sweden. shl', 'sweden-shl', 'swedish hockey league', ' shl'],
    'Liiga': ['finland: liiga', 'finland. liiga', 'finland-liiga', 'finnish liiga', 'liiga'],
    'DEL': ['germany: del', 'germany. del', 'germany-del', 'deutsche eishockey liga', ' del'],
}


class FlashLiveLoader:
    """Загрузчик матчей через FlashLive Sports API (RapidAPI) - мульти-спорт версия"""
    
    def __init__(self, api_key: Optional[str] = None, sport_type: SportType = SportType.HOCKEY):
        self.api_key = api_key or RAPIDAPI_KEY
        self.sport_type = sport_type
        self.sport_config = get_sport_config(sport_type)
        self._cache = {}
        self._cache_time = {}
        self._cache_ttl = 3600  # 60 минут (экономия API запросов)
        self._sport_id = sport_type.value
        self._h2h_cache = {}
        self._h2h_cache_time = {}
        self._h2h_cache_ttl = 86400  # 24 часа для H2H данных
    
    @property
    def supported_leagues(self) -> List[str]:
        """Получить список поддерживаемых лиг для текущего вида спорта"""
        return get_leagues_for_sport(self.sport_type)
    
    def get_sport_name(self) -> str:
        """Получить название вида спорта"""
        return self.sport_config.get('name', 'Unknown')
    
    def get_sport_icon(self) -> str:
        """Получить иконку вида спорта"""
        return self.sport_config.get('icon', '🎯')
        
    def is_configured(self) -> bool:
        """Проверка настроен ли API"""
        return bool(self.api_key)
    
    def _request_with_retry(self, url: str, params: Dict, max_retries: int = 3, 
                           base_delay: float = 1.0) -> Optional[requests.Response]:
        """
        Выполнить HTTP запрос с exponential backoff при ошибках
        
        Args:
            url: URL для запроса
            params: Параметры запроса
            max_retries: Максимальное число попыток
            base_delay: Базовая задержка в секундах
            
        Returns:
            Response объект или None при неудаче
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                resp = requests.get(
                    url,
                    headers=self._get_headers(),
                    params=params,
                    timeout=30
                )
                
                # Успешный ответ
                if resp.status_code == 200:
                    return resp
                
                # Rate limit - ждём и повторяем
                if resp.status_code == 429:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Rate limit (429), retry {attempt+1}/{max_retries} in {delay}s")
                    time.sleep(delay)
                    continue
                
                # Серверные ошибки - повторяем
                if resp.status_code >= 500:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Server error {resp.status_code}, retry {attempt+1}/{max_retries} in {delay}s")
                    time.sleep(delay)
                    continue
                
                # Клиентские ошибки (4xx кроме 429) - не повторяем
                logger.error(f"API error {resp.status_code}: {resp.text[:200]}")
                return None
                
            except requests.exceptions.Timeout:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Timeout, retry {attempt+1}/{max_retries} in {delay}s")
                last_error = "Timeout"
                time.sleep(delay)
                
            except requests.exceptions.ConnectionError as e:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Connection error, retry {attempt+1}/{max_retries} in {delay}s")
                last_error = str(e)
                time.sleep(delay)
                
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                last_error = str(e)
                break
        
        # Все попытки исчерпаны - отправляем алерт
        error_msg = f"FlashLive API failed after {max_retries} retries: {last_error}"
        logger.error(error_msg)
        _send_error_alert(f"⚠️ API ERROR\n\n{error_msg}")
        return None
    
    def _get_headers(self) -> Dict:
        """Заголовки для RapidAPI"""
        return {
            'x-rapidapi-key': self.api_key,
            'x-rapidapi-host': RAPIDAPI_HOST
        }
    
    def _get_sport_id(self) -> int:
        """Получить sport_id для текущего вида спорта"""
        return self._sport_id
    
    def get_upcoming_games(self, leagues: Optional[List[str]] = None, days_ahead: int = 2) -> List[Dict]:
        """
        Получить предстоящие матчи для текущего вида спорта
        
        Args:
            leagues: Список лиг для фильтрации (по умолчанию все из конфигурации)
            days_ahead: Сколько дней вперёд
            
        Returns:
            Список матчей
        """
        if not self.is_configured():
            logger.warning("FlashLive API not configured (RAPIDAPI_KEY missing)")
            return []
        
        # По умолчанию все лиги для данного вида спорта
        if leagues is None:
            leagues = self.supported_leagues
        
        # Проверяем кэш
        cache_key = f"events_{self._sport_id}_{days_ahead}"
        now = datetime.utcnow()
        
        if cache_key in self._cache:
            cache_data, cache_time = self._cache[cache_key]
            if (now - cache_time).total_seconds() < self._cache_ttl:
                filtered = self._filter_by_leagues(cache_data, leagues)
                logger.info(f"FlashLive {self.get_sport_icon()}: из кэша {len(filtered)} матчей")
                return filtered
        
        all_matches = []
        sport_id = self._get_sport_id()
        
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
        
        # Фильтруем по лигам
        filtered = self._filter_by_leagues(unique_matches, leagues)
        logger.info(f"FlashLive {self.get_sport_icon()}: {len(filtered)} матчей (всего {len(unique_matches)})")
        
        return filtered
    
    def _fetch_events_for_day(self, sport_id: int, day_offset: int) -> List[Dict]:
        """Получить матчи на конкретный день (с retry логикой)"""
        resp = self._request_with_retry(
            f'{BASE_URL}/v1/events/list',
            params={
                'sport_id': sport_id,
                'indent_days': day_offset,
                'locale': 'en_INT',
                'timezone': 0
            }
        )
        
        if not resp:
            return []
        
        try:
            data = resp.json()
            return self._parse_events(data)
        except Exception as e:
            logger.error(f"FlashLive parse error: {e}")
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
        """Определить код лиги по названию турнира (мульти-спорт)"""
        return match_league(tournament_name, self.sport_type)
    
    def _filter_by_leagues(self, matches: List[Dict], leagues: Optional[List[str]]) -> List[Dict]:
        """Фильтрация матчей по лигам"""
        if not leagues:
            return matches
        
        return [m for m in matches if m.get('league') in leagues]
    
    def get_event_odds(self, event_id: str) -> Optional[Dict]:
        """Получить коэффициенты для конкретного матча (с retry логикой)
        
        Returns:
            Dict с ключами home_odds, draw_odds, away_odds, bookmaker
            или None если коэффициенты недоступны
        """
        if not self.is_configured():
            return None
        
        raw_id = event_id.replace('flash_', '')
        
        resp = self._request_with_retry(
            f'{BASE_URL}/v1/events/odds',
            params={
                'event_id': raw_id,
                'locale': 'en_INT'
            }
        )
        
        if not resp:
            return None
        
        try:
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
            logger.error(f"FlashLive odds parse error: {e}")
            return None
    
    def get_h2h_data(self, event_id: str) -> Optional[Dict]:
        """
        Получить данные H2H (последние матчи команд) для события (с retry логикой)
        С кэшированием на 24 часа для экономии API запросов
        
        Args:
            event_id: ID события (может содержать префикс 'flash_')
            
        Returns:
            Dict с ключами home_team_matches и away_team_matches,
            каждый содержит список последних 5 матчей
        """
        if not self.is_configured():
            return None
        
        raw_id = event_id.replace('flash_', '')
        
        now = datetime.now()
        if raw_id in self._h2h_cache:
            cache_time = self._h2h_cache_time.get(raw_id)
            if cache_time and (now - cache_time).total_seconds() < self._h2h_cache_ttl:
                logger.info(f"H2H cache hit for {raw_id}")
                return self._h2h_cache[raw_id]
        
        resp = self._request_with_retry(
            f'{BASE_URL}/v1/events/h2h',
            params={
                'event_id': raw_id,
                'locale': 'en_GB'
            }
        )
        
        if not resp:
            return None
        
        try:
            data = resp.json()
            
            result = {
                'home_team_matches': [],
                'away_team_matches': []
            }
            
            groups = data.get('DATA', [])
            
            for group in groups:
                group_label = group.get('GROUP_LABEL', '')
                items = group.get('ITEMS', [])
                
                matches = []
                for item in items[:5]:
                    start_time = item.get('START_TIME')
                    date_str = ''
                    if start_time:
                        try:
                            dt = datetime.fromtimestamp(start_time)
                            date_str = dt.strftime('%d.%m')
                        except:
                            pass
                    
                    home_team = item.get('HOME_PARTICIPANT', '')
                    away_team = item.get('AWAY_PARTICIPANT', '')
                    current_result = item.get('CURRENT_RESULT', '')
                    h_result = item.get('H_RESULT', '')
                    
                    if 'Last matches' in group_label:
                        team_name = group_label.replace('Last matches:', '').strip()
                        
                        if team_name.lower() in home_team.lower():
                            opponent = away_team
                            is_home = True
                        else:
                            opponent = home_team
                            is_home = False
                        
                        if h_result in ('WIN', '1'):
                            result_str = 'WIN'
                        elif h_result in ('LOSS', '2'):
                            result_str = 'LOSS'
                        else:
                            result_str = 'DRAW'
                        
                        matches.append({
                            'date': date_str,
                            'opponent': opponent,
                            'score': current_result,
                            'result': result_str
                        })
                
                if 'Last matches' in group_label:
                    if not result['home_team_matches']:
                        result['home_team_matches'] = matches
                    else:
                        result['away_team_matches'] = matches
            
            self._h2h_cache[raw_id] = result
            self._h2h_cache_time[raw_id] = now
            
            return result
            
        except Exception as e:
            logger.error(f"FlashLive H2H error: {e}")
            return None

    def get_match_result(self, event_id: str) -> Optional[Dict]:
        """
        Получить результат матча по event_id (с retry логикой)
        
        Args:
            event_id: ID события (может содержать префикс 'flash_')
            
        Returns:
            Dict с ключами:
                - status: 'FINISHED', 'NOT_STARTED', 'LIVE', etc.
                - home_score: int (если матч завершён)
                - away_score: int (если матч завершён)
                - winner: 'home', 'away', или 'draw'
            или None если ошибка
        """
        if not self.is_configured():
            return None
        
        raw_id = event_id.replace('flash_', '')
        
        resp = self._request_with_retry(
            f'{BASE_URL}/v1/events/data',
            params={
                'event_id': raw_id,
                'locale': 'en_INT'
            }
        )
        
        if not resp:
            return None
        
        try:
            data = resp.json()
            event_data = data.get('DATA', {})
            
            stage_type = event_data.get('STAGE_TYPE', '')
            
            result = {
                'status': stage_type,
                'home_team': event_data.get('HOME_NAME', ''),
                'away_team': event_data.get('AWAY_NAME', ''),
                'home_score': None,
                'away_score': None,
                'winner': None
            }
            
            if stage_type == 'FINISHED':
                home_score_str = event_data.get('HOME_SCORE_CURRENT', '')
                away_score_str = event_data.get('AWAY_SCORE_CURRENT', '')
                
                try:
                    result['home_score'] = int(home_score_str) if home_score_str else 0
                    result['away_score'] = int(away_score_str) if away_score_str else 0
                    
                    if result['home_score'] > result['away_score']:
                        result['winner'] = 'home'
                    elif result['away_score'] > result['home_score']:
                        result['winner'] = 'away'
                    else:
                        result['winner'] = 'draw'
                except (ValueError, TypeError):
                    pass
            
            return result
            
        except Exception as e:
            logger.error(f"FlashLive match result error: {e}")
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
