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
                           base_delay: float = 1.0, allow_not_found: bool = False) -> Optional[requests.Response]:
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
                
                if resp.status_code == 404 and allow_not_found:
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

    @staticmethod
    def _clean_participant_name(name: Optional[str]) -> str:
        """Нормализовать имена участников из разных форматов ответа API."""
        if not name:
            return ""
        return str(name).lstrip("*").strip()

    @classmethod
    def _extract_team_names(cls, payload: Dict) -> tuple[str, str]:
        """Достать home/away команды из плоской или вложенной структуры API."""
        home_team = cls._clean_participant_name(
            payload.get('HOME_NAME')
            or payload.get('HOME_PARTICIPANT')
            or payload.get('HOME_PARTICIPANT_NAME_ONE')
            or payload.get('PARTICIPANT_NAME_1')
            or payload.get('SHORTNAME_HOME')
        )
        away_team = cls._clean_participant_name(
            payload.get('AWAY_NAME')
            or payload.get('AWAY_PARTICIPANT')
            or payload.get('AWAY_PARTICIPANT_NAME_ONE')
            or payload.get('PARTICIPANT_NAME_2')
            or payload.get('SHORTNAME_AWAY')
        )
        return home_team, away_team

    @staticmethod
    def _to_float(value) -> Optional[float]:
        """Безопасно преобразовать odds-значение в float."""
        if isinstance(value, dict):
            value = value.get('VALUE')
        if value in (None, ''):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value) -> Optional[int]:
        """Безопасно преобразовать score-значение в int."""
        if value in (None, ''):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _parse_match_date(self, start_time) -> Optional[datetime]:
        """Преобразовать unix timestamp в datetime."""
        if not start_time:
            return None
        try:
            return datetime.fromtimestamp(start_time)
        except Exception:
            return None

    def _extract_inline_event_odds(self, odds_data: Dict) -> tuple[Optional[float], Optional[float], Optional[float]]:
        """Извлечь inline odds из списка событий, если API их вернул."""
        if not isinstance(odds_data, dict):
            return None, None, None

        if any(key in odds_data for key in ('1', '2', 'X')):
            return (
                self._to_float(odds_data.get('1')),
                self._to_float(odds_data.get('2')),
                self._to_float(odds_data.get('X')),
            )

        return (
            self._to_float(odds_data.get('ODD_CELL_SECOND')),
            self._to_float(odds_data.get('ODD_CELL_THIRD')),
            None,
        )

    def _get_preferred_betting_types(self) -> List[str]:
        """Вернуть приоритет рынков для текущего вида спорта."""
        if self.sport_type in {SportType.HOCKEY, SportType.FOOTBALL}:
            return ['*1X2', '1X2', '*Home/Away', 'Home/Away']
        return ['*Home/Away', 'Home/Away', '*1X2', '1X2']

    @staticmethod
    def _get_preferred_periods(periods: List[Dict]) -> List[Dict]:
        """Вернуть наиболее релевантные периоды, предпочитая полный матч."""
        preferred_markers = ('full time', 'ft including ot', 'match')
        preferred = [
            period for period in periods
            if any(marker in str(period.get('ODDS_STAGE', '')).lower() for marker in preferred_markers)
        ]
        return preferred or periods

    def _extract_market_odds(self, market: Dict, betting_type: str) -> Optional[Dict]:
        """Нормализовать odds из одного market-блока."""
        if not isinstance(market, dict):
            return None

        if betting_type in ('*Home/Away', 'Home/Away'):
            home = self._to_float(market.get('ODD_CELL_SECOND'))
            away = self._to_float(market.get('ODD_CELL_THIRD'))
            draw = None
        else:
            home = self._to_float(market.get('ODD_CELL_FIRST'))
            draw = self._to_float(market.get('ODD_CELL_SECOND'))
            away = self._to_float(market.get('ODD_CELL_THIRD'))

        if home is None or away is None:
            return None

        return {
            'home_odds': home,
            'draw_odds': draw,
            'away_odds': away,
            'bookmaker': market.get('BOOKMAKER_NAME', 'Unknown')
        }

    @staticmethod
    def _extract_h2h_groups(data: Dict) -> List[Dict]:
        """Собрать H2H группы из старого и нового формата ответа Flash API."""
        groups = []
        data_root = data.get('DATA', [])

        if not isinstance(data_root, list):
            return groups

        for entry in data_root:
            if not isinstance(entry, dict):
                continue
            if entry.get('GROUP_LABEL'):
                groups.append(entry)
            for group in entry.get('GROUPS', []) or []:
                if isinstance(group, dict):
                    groups.append(group)

        return groups

    def _build_score_string(self, item: Dict) -> str:
        """Построить человекочитаемый счёт из полей H2H/результата."""
        current_result = item.get('CURRENT_RESULT')
        if current_result:
            return str(current_result)

        home_score = self._to_int(item.get('HOME_SCORE_FULL'))
        away_score = self._to_int(item.get('AWAY_SCORE_FULL'))
        if home_score is not None and away_score is not None:
            return f"{home_score}:{away_score}"

        return ""

    def _resolve_h2h_result(self, item: Dict, is_home_team: bool) -> str:
        """Определить исход матча для конкретной команды."""
        h_result = str(item.get('H_RESULT', '')).upper()
        if h_result in ('WIN', '1'):
            return 'WIN' if is_home_team else 'LOSS'
        if h_result in ('LOSS', '2'):
            return 'LOSS' if is_home_team else 'WIN'
        if h_result == 'DRAW':
            return 'DRAW'

        home_score = self._to_int(item.get('HOME_SCORE_FULL'))
        away_score = self._to_int(item.get('AWAY_SCORE_FULL'))
        if home_score is None or away_score is None:
            return 'DRAW'

        if home_score == away_score:
            return 'DRAW'
        if is_home_team:
            return 'WIN' if home_score > away_score else 'LOSS'
        return 'WIN' if away_score > home_score else 'LOSS'
    
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
                home_team, away_team = self._extract_team_names(event)
                
                # Время матча
                match_date = self._parse_match_date(event.get('START_TIME'))
                
                # Коэффициенты (если есть)
                home_odds, away_odds, draw_odds = self._extract_inline_event_odds(event.get('ODDS', {}))
                
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
            },
            allow_not_found=True
        )
        
        if not resp:
            return None

        if getattr(resp, 'status_code', 200) == 404:
            return None
        
        try:
            data = resp.json().get('DATA', [])
            betting_types = [bt for bt in data if isinstance(bt, dict)]

            ordered_types = []
            preferred_types = self._get_preferred_betting_types()
            for preferred_type in preferred_types:
                ordered_types.extend(
                    betting_type for betting_type in betting_types
                    if betting_type.get('BETTING_TYPE') == preferred_type
                )
            ordered_types.extend(
                betting_type for betting_type in betting_types
                if betting_type not in ordered_types
            )

            for betting_type in ordered_types:
                periods = self._get_preferred_periods(betting_type.get('PERIODS', []))
                market_type = betting_type.get('BETTING_TYPE', '')

                for period in periods:
                    for group in period.get('GROUPS', []):
                        for market in group.get('MARKETS', []):
                            parsed = self._extract_market_odds(market, market_type)
                            if parsed:
                                return parsed

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
            
            groups = self._extract_h2h_groups(data)
            seen_labels = set()

            for group in groups:
                group_label = group.get('GROUP_LABEL', '') or ''
                if 'Last matches:' not in group_label or group_label in seen_labels:
                    continue
                seen_labels.add(group_label)

                items = group.get('ITEMS', [])
                team_name = self._clean_participant_name(group_label.replace('Last matches:', '').strip())
                
                matches = []
                for item in items[:5]:
                    dt = self._parse_match_date(item.get('START_TIME'))
                    date_str = dt.strftime('%d.%m') if dt else ''
                    home_team, away_team = self._extract_team_names(item)

                    is_home = team_name.lower() in home_team.lower()
                    if not home_team and not away_team:
                        continue

                    matches.append({
                        'date': date_str,
                        'opponent': away_team if is_home else home_team,
                        'score': self._build_score_string(item),
                        'result': self._resolve_h2h_result(item, is_home)
                    })

                if matches:
                    if not result['home_team_matches']:
                        result['home_team_matches'] = matches
                    elif not result['away_team_matches']:
                        result['away_team_matches'] = matches
                    if result['home_team_matches'] and result['away_team_matches']:
                        break
            
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
            if isinstance(event_data, dict) and isinstance(event_data.get('EVENT'), dict):
                event_data = event_data.get('EVENT', {})
            
            stage_type = event_data.get('STAGE_TYPE', '')
            home_team, away_team = self._extract_team_names(event_data)
            
            result = {
                'status': stage_type,
                'home_team': home_team,
                'away_team': away_team,
                'home_score': None,
                'away_score': None,
                'winner': None
            }
            
            if stage_type == 'FINISHED':
                home_score = self._to_int(
                    event_data.get('HOME_SCORE_CURRENT', event_data.get('HOME_SCORE_FULL'))
                )
                away_score = self._to_int(
                    event_data.get('AWAY_SCORE_CURRENT', event_data.get('AWAY_SCORE_FULL'))
                )
                
                if home_score is not None and away_score is not None:
                    result['home_score'] = home_score
                    result['away_score'] = away_score
                    if home_score > away_score:
                        result['winner'] = 'home'
                    elif away_score > home_score:
                        result['winner'] = 'away'
                    else:
                        result['winner'] = 'draw'
            
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
        
        target_leagues = leagues if leagues is not None else self.supported_leagues
        filtered = self._filter_by_leagues(matches, target_leagues)
        
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


class MultiSportFlashLiveLoader:
    """Агрегатор FlashLive loader-ов по нескольким видам спорта."""

    def __init__(self, api_key: Optional[str] = None, sport_types: Optional[List[SportType]] = None):
        self.api_key = api_key or RAPIDAPI_KEY
        self.sport_types = sport_types or [
            SportType.HOCKEY,
            SportType.FOOTBALL,
            SportType.BASKETBALL,
            SportType.VOLLEYBALL,
        ]
        self._loaders: Dict[SportType, FlashLiveLoader] = {}

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _get_loader(self, sport_type: SportType) -> FlashLiveLoader:
        loader = self._loaders.get(sport_type)
        if loader is None:
            loader = FlashLiveLoader(api_key=self.api_key, sport_type=sport_type)
            self._loaders[sport_type] = loader
        return loader

    def _iter_sport_types(self, sports=None) -> List[SportType]:
        if sports is None:
            return list(self.sport_types)

        resolved = []
        for sport in sports:
            if isinstance(sport, SportType) and sport in self.sport_types:
                resolved.append(sport)
            elif isinstance(sport, str):
                name = sport.strip().lower()
                for sport_type in self.sport_types:
                    if sport_type.name.lower() == name:
                        resolved.append(sport_type)
                        break
        return resolved or list(self.sport_types)

    @staticmethod
    def _with_sport_metadata(match: Dict, sport_type: SportType) -> Dict:
        enriched = dict(match)
        enriched['sport'] = sport_type.name.lower()
        enriched['sport_type'] = sport_type.name.lower()
        return enriched

    @staticmethod
    def _deduplicate_matches(matches: List[Dict]) -> List[Dict]:
        seen = set()
        unique = []
        for match in matches:
            key = (match.get('sport_type'), match.get('event_id'))
            if key in seen:
                continue
            seen.add(key)
            unique.append(match)
        return unique

    def _get_leagues_for_sport(self, sport_type: SportType, leagues=None):
        supported = get_leagues_for_sport(sport_type)
        if leagues is None:
            return supported
        selected = [league for league in leagues if league in supported]
        return selected or []

    def get_upcoming_games(self, days_ahead: int = 2, sports=None, leagues=None) -> List[Dict]:
        matches = []
        for sport_type in self._iter_sport_types(sports):
            loader = self._get_loader(sport_type)
            sport_leagues = self._get_leagues_for_sport(sport_type, leagues)
            if leagues is not None and not sport_leagues:
                continue
            sport_matches = loader.get_upcoming_games(days_ahead=days_ahead, leagues=sport_leagues)
            matches.extend(self._with_sport_metadata(match, sport_type) for match in sport_matches)
        return self._deduplicate_matches(matches)

    def get_matches_with_odds(self, days_ahead: int = 2, sports=None, leagues=None) -> List[Dict]:
        matches = []
        for sport_type in self._iter_sport_types(sports):
            loader = self._get_loader(sport_type)
            sport_leagues = self._get_leagues_for_sport(sport_type, leagues)
            if leagues is not None and not sport_leagues:
                continue
            sport_matches = loader.get_matches_with_odds(days_ahead=days_ahead, leagues=sport_leagues)
            matches.extend(self._with_sport_metadata(match, sport_type) for match in sport_matches)
        return self._deduplicate_matches(matches)

    def _resolve_sport_type(self, sport=None, league: Optional[str] = None) -> Optional[SportType]:
        if isinstance(sport, SportType):
            return sport
        if isinstance(sport, str):
            for sport_type in self.sport_types:
                if sport_type.name.lower() == sport.strip().lower():
                    return sport_type
        if league:
            for sport_type in self.sport_types:
                if league in get_leagues_for_sport(sport_type):
                    return sport_type
        return None

    def get_h2h_data(self, event_id: str, sport=None, league: Optional[str] = None) -> Optional[Dict]:
        resolved_sport = self._resolve_sport_type(sport=sport, league=league)
        candidate_sports = [resolved_sport] if resolved_sport else list(self.sport_types)
        for sport_type in candidate_sports:
            if sport_type is None:
                continue
            result = self._get_loader(sport_type).get_h2h_data(event_id)
            if result:
                return result
        return None

    def get_match_result(self, event_id: str, sport=None, league: Optional[str] = None) -> Optional[Dict]:
        resolved_sport = self._resolve_sport_type(sport=sport, league=league)
        candidate_sports = [resolved_sport] if resolved_sport else list(self.sport_types)
        for sport_type in candidate_sports:
            if sport_type is None:
                continue
            result = self._get_loader(sport_type).get_match_result(event_id)
            if result:
                return result
        return None


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
