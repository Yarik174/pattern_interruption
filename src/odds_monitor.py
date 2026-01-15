"""
Фоновый мониторинг коэффициентов и генерация прогнозов
С автозапуском и логированием в БД
"""
import threading
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Callable
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_global_monitor = None
_monitor_thread_started = False


class OddsMonitor:
    """Фоновый мониторинг коэффициентов
    
    ОПТИМИЗАЦИЯ для 100 запросов/день:
    - Интервал 2 часа вместо 5 минут
    - Кэширование в odds_loader
    - Не запускается автоматически
    """
    
    def __init__(self, 
                 odds_loader,
                 prediction_callback: Callable,
                 notification_callback: Optional[Callable] = None,
                 check_interval: int = 7200):  # 2 часа вместо 5 минут
        """
        Args:
            odds_loader: Загрузчик коэффициентов (APISportsOddsLoader)
            prediction_callback: Функция генерации прогноза (match_data) -> prediction
            notification_callback: Функция отправки уведомления (prediction) -> bool
            check_interval: Интервал проверки в секундах (default: 5 минут)
        """
        self.odds_loader = odds_loader
        self.prediction_callback = prediction_callback
        self.notification_callback = notification_callback
        self.check_interval = check_interval
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._processed_events = set()
        self._last_check = None
        self._stats = {
            'total_checks': 0,
            'matches_found': 0,
            'predictions_created': 0,
            'notifications_sent': 0,
            'errors': 0
        }
    
    def start(self):
        """Запустить мониторинг"""
        if self._running:
            logger.warning("Monitor already running")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info(f"Odds monitor started (interval: {self.check_interval}s)")
    
    def stop(self):
        """Остановить мониторинг"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Odds monitor stopped")
    
    def is_running(self) -> bool:
        """Статус мониторинга"""
        return self._running
    
    def get_stats(self) -> dict:
        """Получить статистику"""
        return {
            **self._stats,
            'is_running': self._running,
            'last_check': self._last_check.isoformat() if self._last_check else None,
            'processed_events': len(self._processed_events)
        }
    
    def check_now(self) -> dict:
        """Выполнить проверку сейчас"""
        return self._check_odds()
    
    def _monitor_loop(self):
        """Основной цикл мониторинга"""
        while self._running:
            try:
                self._check_odds()
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                self._stats['errors'] += 1
            
            time.sleep(self.check_interval)
    
    def _check_odds(self) -> dict:
        """Проверить коэффициенты и создать прогнозы"""
        self._last_check = datetime.utcnow()
        self._stats['total_checks'] += 1
        
        result = {
            'timestamp': self._last_check.isoformat(),
            'matches_found': 0,
            'new_predictions': 0,
            'notifications_sent': 0
        }
        
        try:
            matches = self.odds_loader.get_upcoming_games(days_ahead=2)
            result['matches_found'] = len(matches)
            self._stats['matches_found'] += len(matches)
            
            for match in matches:
                event_id = match.get('event_id')
                
                if event_id and event_id in self._processed_events:
                    continue
                
                try:
                    prediction = self.prediction_callback(match)
                    
                    if prediction:
                        result['new_predictions'] += 1
                        self._stats['predictions_created'] += 1
                        
                        if event_id:
                            self._processed_events.add(event_id)
                        
                        if self.notification_callback:
                            if self.notification_callback(prediction):
                                result['notifications_sent'] += 1
                                self._stats['notifications_sent'] += 1
                                
                except Exception as e:
                    logger.error(f"Error processing match {match.get('home_team')} vs {match.get('away_team')}: {e}")
            
            logger.info(f"Check complete: {result['matches_found']} matches, {result['new_predictions']} new predictions")
            
        except Exception as e:
            logger.error(f"Error checking odds: {e}")
            result['error'] = str(e)
            self._stats['errors'] += 1
        
        return result
    
    def clear_processed(self, older_than_hours: int = 48):
        """Очистить старые обработанные события"""
        old_count = len(self._processed_events)
        self._processed_events.clear()
        logger.info(f"Cleared {old_count} processed events")


class AutoMonitor:
    """
    Автоматический мониторинг с:
    - Проверкой матчей каждые 4 часа
    - Обновлением исторических данных раз в день
    - Логированием в БД
    """
    
    def __init__(self, check_interval: int = 14400):
        self.check_interval = check_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_check = None
        self._last_data_refresh = None
        self._stats = {
            'total_checks': 0,
            'matches_found': 0,
            'predictions_created': 0,
            'notifications_sent': 0,
            'data_refreshes': 0,
            'errors': 0
        }
    
    def start(self):
        """Запустить автомониторинг"""
        if self._running:
            logger.warning("AutoMonitor already running")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._main_loop, daemon=True)
        self._thread.start()
        logger.info(f"AutoMonitor started (interval: {self.check_interval}s = {self.check_interval // 3600}h)")
    
    def stop(self):
        """Остановить мониторинг"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("AutoMonitor stopped")
    
    def is_running(self) -> bool:
        return self._running
    
    def get_stats(self) -> dict:
        return {
            **self._stats,
            'is_running': self._running,
            'last_check': self._last_check.isoformat() if self._last_check else None,
            'last_data_refresh': self._last_data_refresh.isoformat() if self._last_data_refresh else None,
            'check_interval_hours': self.check_interval // 3600
        }
    
    def _main_loop(self):
        """Основной цикл"""
        time.sleep(10)
        
        while self._running:
            try:
                self._maybe_refresh_data()
                self._check_matches()
            except Exception as e:
                logger.error(f"AutoMonitor error: {e}")
                self._stats['errors'] += 1
                self._log_error(str(e))
            
            time.sleep(self.check_interval)
    
    def _maybe_refresh_data(self):
        """Обновить исторические данные если нужно"""
        try:
            from src.data_refresh import should_refresh, refresh_all_historical_data
            
            if should_refresh():
                logger.info("AutoMonitor: refreshing historical data...")
                result = refresh_all_historical_data()
                if not result.get('skipped'):
                    self._last_data_refresh = datetime.utcnow()
                    self._stats['data_refreshes'] += 1
        except ImportError as e:
            logger.warning(f"Data refresh module not available: {e}")
        except Exception as e:
            logger.error(f"Data refresh error: {e}")
    
    def _check_matches(self):
        """Проверить матчи и создать прогнозы"""
        from src.system_logger import log_monitoring
        
        self._last_check = datetime.utcnow()
        self._stats['total_checks'] += 1
        
        result = {
            'matches_found': 0,
            'predictions_created': 0,
            'notifications_sent': 0
        }
        
        try:
            from src.flashlive_loader import FlashLiveLoader
            
            loader = FlashLiveLoader()
            if not loader.is_configured():
                logger.warning("FlashLive not configured, skipping check")
                return result
            
            matches = loader.get_upcoming_games(days_ahead=2)
            result['matches_found'] = len(matches)
            self._stats['matches_found'] += len(matches)
            
            for match in matches:
                try:
                    prediction = self._process_match(match)
                    if prediction:
                        result['predictions_created'] += 1
                        self._stats['predictions_created'] += 1
                        
                        if self._send_notification(prediction):
                            result['notifications_sent'] += 1
                            self._stats['notifications_sent'] += 1
                except Exception as e:
                    logger.error(f"Error processing match: {e}")
            
            log_monitoring(
                result['matches_found'],
                result['predictions_created'],
                result['notifications_sent']
            )
            
            logger.info(f"AutoMonitor check: {result['matches_found']} matches, "
                       f"{result['predictions_created']} predictions")
            
        except Exception as e:
            logger.error(f"AutoMonitor check error: {e}")
            self._log_error(f"Check error: {e}")
        
        return result
    
    def _process_match(self, match: dict) -> Optional[dict]:
        """Обработать матч и создать прогноз если нужно"""
        home_odds = match.get('home_odds')
        away_odds = match.get('away_odds')
        
        min_odds, max_odds = 2.0, 3.5
        target_odds = None
        bet_on = None
        
        if home_odds and min_odds <= home_odds <= max_odds:
            target_odds = home_odds
            bet_on = 'home'
        elif away_odds and min_odds <= away_odds <= max_odds:
            target_odds = away_odds
            bet_on = 'away'
        
        if not target_odds:
            if not home_odds and not away_odds:
                bet_on = 'home'
                target_odds = 2.0
            else:
                return None
        
        try:
            from src.prediction_service import create_prediction_from_match
            return create_prediction_from_match(match, bet_on, target_odds)
        except ImportError:
            return None
        except Exception as e:
            logger.error(f"Prediction creation error: {e}")
            return None
    
    def _send_notification(self, prediction: dict) -> bool:
        """Отправить уведомление в Telegram"""
        try:
            from src.telegram_bot import send_prediction_notification
            return send_prediction_notification(prediction)
        except ImportError:
            return False
        except Exception as e:
            logger.error(f"Notification error: {e}")
            return False
    
    def _log_error(self, message: str):
        """Записать ошибку в лог"""
        try:
            from src.system_logger import log_error
            log_error(message, {'source': 'AutoMonitor'})
        except:
            pass
    
    def check_now(self) -> dict:
        """Выполнить проверку сейчас"""
        return self._check_matches()


def get_auto_monitor() -> AutoMonitor:
    """Получить глобальный экземпляр AutoMonitor"""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = AutoMonitor(check_interval=14400)
    return _global_monitor


def start_auto_monitoring():
    """Запустить автомониторинг (вызывается при старте сервера)"""
    global _monitor_thread_started
    if _monitor_thread_started:
        return
    
    monitor = get_auto_monitor()
    if not monitor.is_running():
        monitor.start()
        _monitor_thread_started = True
        logger.info("Auto monitoring started on server startup")


class MockOddsLoader:
    """Тестовый загрузчик для демо"""
    
    def is_configured(self):
        return True
    
    def get_upcoming_games(self, days_ahead=2):
        from src.apisports_odds_loader import get_demo_odds
        return get_demo_odds()
