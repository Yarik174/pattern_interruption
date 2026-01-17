"""
Database models for Hockey Pattern Prediction System
"""
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Prediction(db.Model):
    """Прогноз модели"""
    __tablename__ = 'predictions'
    
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    match_date = db.Column(db.DateTime, nullable=False)
    league = db.Column(db.String(50), nullable=False)
    home_team = db.Column(db.String(100), nullable=False)
    away_team = db.Column(db.String(100), nullable=False)
    prediction_type = db.Column(db.String(50), nullable=False)
    predicted_outcome = db.Column(db.String(50), nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    confidence_1_10 = db.Column(db.Integer, nullable=False)
    home_odds = db.Column(db.Float)
    away_odds = db.Column(db.Float)
    draw_odds = db.Column(db.Float)
    bookmaker = db.Column(db.String(100))
    patterns_data = db.Column(db.JSON)
    model_version = db.Column(db.String(50))
    actual_result = db.Column(db.String(50))
    result_updated_at = db.Column(db.DateTime)
    is_win = db.Column(db.Boolean)
    notified_telegram = db.Column(db.Boolean, default=False)
    flashlive_event_id = db.Column(db.String(50))
    
    # RL-агент рекомендация
    rl_recommendation = db.Column(db.String(10))  # 'BET' или 'SKIP'
    rl_confidence = db.Column(db.Float)
    rl_comment = db.Column(db.Text)
    
    user_decision = db.relationship('UserDecision', backref='prediction', uselist=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'match_date': self.match_date.isoformat() if self.match_date else None,
            'league': self.league,
            'home_team': self.home_team,
            'away_team': self.away_team,
            'prediction_type': self.prediction_type,
            'predicted_outcome': self.predicted_outcome,
            'confidence': self.confidence,
            'confidence_1_10': self.confidence_1_10,
            'home_odds': self.home_odds,
            'away_odds': self.away_odds,
            'draw_odds': self.draw_odds,
            'bookmaker': self.bookmaker,
            'patterns_data': self.patterns_data,
            'model_version': self.model_version,
            'actual_result': self.actual_result,
            'is_win': self.is_win,
            'user_decision': self.user_decision.to_dict() if self.user_decision else None
        }


class UserDecision(db.Model):
    """Решение пользователя по прогнозу"""
    __tablename__ = 'user_decisions'
    
    id = db.Column(db.Integer, primary_key=True)
    prediction_id = db.Column(db.Integer, db.ForeignKey('predictions.id'), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    decision = db.Column(db.String(20), nullable=False)
    comment = db.Column(db.Text)
    stake_amount = db.Column(db.Float)
    actual_profit = db.Column(db.Float)
    
    def to_dict(self):
        return {
            'id': self.id,
            'prediction_id': self.prediction_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'decision': self.decision,
            'comment': self.comment,
            'stake_amount': self.stake_amount,
            'actual_profit': self.actual_profit
        }


class ModelVersion(db.Model):
    """Версия модели и её метрики"""
    __tablename__ = 'model_versions'
    
    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.String(50), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    model_type = db.Column(db.String(50), nullable=False)
    accuracy = db.Column(db.Float)
    roi = db.Column(db.Float)
    total_predictions = db.Column(db.Integer, default=0)
    win_rate = db.Column(db.Float)
    training_data_size = db.Column(db.Integer)
    features_count = db.Column(db.Integer)
    parameters = db.Column(db.JSON)
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'version': self.version,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'model_type': self.model_type,
            'accuracy': self.accuracy,
            'roi': self.roi,
            'total_predictions': self.total_predictions,
            'win_rate': self.win_rate,
            'training_data_size': self.training_data_size,
            'features_count': self.features_count,
            'parameters': self.parameters,
            'notes': self.notes,
            'is_active': self.is_active
        }


class TelegramSettings(db.Model):
    """Настройки Telegram бота"""
    __tablename__ = 'telegram_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    min_confidence = db.Column(db.Integer, default=5)
    leagues_filter = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class OddsMonitorLog(db.Model):
    """Лог мониторинга коэффициентов"""
    __tablename__ = 'odds_monitor_log'
    
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    league = db.Column(db.String(50))
    matches_found = db.Column(db.Integer)
    predictions_created = db.Column(db.Integer)
    notifications_sent = db.Column(db.Integer)
    error_message = db.Column(db.Text)


class SystemLog(db.Model):
    """Универсальный лог системы"""
    __tablename__ = 'system_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    log_type = db.Column(db.String(50), nullable=False, index=True)
    level = db.Column(db.String(20), default='INFO')
    message = db.Column(db.Text, nullable=False)
    details = db.Column(db.JSON)
    
    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'log_type': self.log_type,
            'level': self.level,
            'message': self.message,
            'details': self.details
        }
