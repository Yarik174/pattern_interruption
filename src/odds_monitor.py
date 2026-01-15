"""
Фоновый мониторинг коэффициентов и генерация прогнозов
"""
import threading
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Callable
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
            matches = self.odds_loader.get_upcoming_games(leagues=['NHL', 'KHL', 'SHL', 'Liiga', 'DEL'], hours_ahead=48)
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


class MockOddsLoader:
    """Тестовый загрузчик для демо"""
    
    def is_configured(self):
        return True
    
    def get_upcoming_games(self, leagues=None, hours_ahead=48):
        from src.apisports_odds_loader import get_demo_odds
        return get_demo_odds()
