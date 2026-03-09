"""
Система логирования в БД
"""
from datetime import datetime
from typing import Optional, Dict, Any
import logging
import sys

logger = logging.getLogger(__name__)

LOG_TYPES = {
    'DATA_UPDATE': 'data_update',
    'MONITORING': 'monitoring',
    'PREDICTION': 'prediction',
    'ERROR': 'error',
    'SYSTEM': 'system'
}


def _get_runtime_context():
    """Получить уже загруженные app/db без импортных side effects."""
    app_module = sys.modules.get('app')
    if app_module is None:
        return None, None

    app = getattr(app_module, 'app', None)
    db = getattr(app_module, 'db', None)
    if app is None or db is None:
        return None, None

    return app, db

LOG_LEVELS = {
    'DEBUG': 'DEBUG',
    'INFO': 'INFO',
    'WARNING': 'WARNING',
    'ERROR': 'ERROR',
    'CRITICAL': 'CRITICAL'
}


def log_to_db(log_type: str, message: str, level: str = 'INFO', details: Optional[Dict[str, Any]] = None):
    """
    Записать лог в базу данных
    
    Args:
        log_type: Тип лога (data_update, monitoring, prediction, error, system)
        message: Сообщение
        level: Уровень (INFO, WARNING, ERROR, CRITICAL)
        details: Дополнительные данные (JSON)
    """
    try:
        app, db = _get_runtime_context()
        if app is None or db is None:
            logger.info(f"[{log_type}] {message}")
            return

        from models import SystemLog
        
        with app.app_context():
            log_entry = SystemLog(
                timestamp=datetime.utcnow(),
                log_type=log_type,
                level=level,
                message=message,
                details=details
            )
            db.session.add(log_entry)
            db.session.commit()
            logger.info(f"[{log_type}] {message}")
    except Exception as e:
        logger.error(f"Failed to write log to DB: {e}")


def log_data_update(league: str, matches_count: int, success: bool, details: Optional[Dict] = None):
    """Лог обновления данных"""
    if success:
        message = f"Обновлены данные {league}: {matches_count} матчей"
        level = 'INFO'
    else:
        message = f"Ошибка обновления данных {league}"
        level = 'ERROR'
    
    log_to_db(
        log_type=LOG_TYPES['DATA_UPDATE'],
        message=message,
        level=level,
        details={'league': league, 'matches_count': matches_count, 'success': success, **(details or {})}
    )


def log_monitoring(matches_found: int, predictions_created: int, notifications_sent: int, details: Optional[Dict] = None):
    """Лог мониторинга"""
    message = f"Мониторинг: {matches_found} матчей, {predictions_created} прогнозов, {notifications_sent} уведомлений"
    log_to_db(
        log_type=LOG_TYPES['MONITORING'],
        message=message,
        level='INFO',
        details={'matches_found': matches_found, 'predictions_created': predictions_created, 
                 'notifications_sent': notifications_sent, **(details or {})}
    )


def log_prediction(home_team: str, away_team: str, prediction: str, confidence: float, details: Optional[Dict] = None):
    """Лог создания прогноза"""
    message = f"Прогноз: {home_team} vs {away_team} → {prediction} ({confidence:.1%})"
    log_to_db(
        log_type=LOG_TYPES['PREDICTION'],
        message=message,
        level='INFO',
        details={'home_team': home_team, 'away_team': away_team, 'prediction': prediction, 
                 'confidence': confidence, **(details or {})}
    )


def log_error(message: str, details: Optional[Dict] = None):
    """Лог ошибки"""
    log_to_db(
        log_type=LOG_TYPES['ERROR'],
        message=message,
        level='ERROR',
        details=details
    )


def log_system(message: str, level: str = 'INFO', details: Optional[Dict] = None):
    """Общий системный лог"""
    log_to_db(
        log_type=LOG_TYPES['SYSTEM'],
        message=message,
        level=level,
        details=details
    )


def get_recent_logs(limit: int = 50, log_type: Optional[str] = None, level: Optional[str] = None):
    """Получить последние логи из БД"""
    try:
        app, db = _get_runtime_context()
        if app is None or db is None:
            return []

        from models import SystemLog
        
        with app.app_context():
            query = SystemLog.query.order_by(SystemLog.timestamp.desc())
            
            if log_type:
                query = query.filter(SystemLog.log_type == log_type)
            if level:
                query = query.filter(SystemLog.level == level)
            
            logs = query.limit(limit).all()
            return [log.to_dict() for log in logs]
    except Exception as e:
        logger.error(f"Failed to get logs from DB: {e}")
        return []
