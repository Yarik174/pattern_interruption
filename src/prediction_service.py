"""
Сервис создания прогнозов для AutoMonitor
"""
import logging
from contextlib import nullcontext
from datetime import datetime
from typing import Optional, Dict

from flask import has_app_context
from src.sports_config import SportType, get_leagues_for_sport

logger = logging.getLogger(__name__)


TARGET_SPORT_TYPES = (
    SportType.HOCKEY,
    SportType.FOOTBALL,
    SportType.BASKETBALL,
    SportType.VOLLEYBALL,
)

TARGET_LEAGUES = {
    league
    for sport_type in TARGET_SPORT_TYPES
    for league in get_leagues_for_sport(sport_type)
}

SPORT_SLUGS = {
    SportType.HOCKEY: 'hockey',
    SportType.FOOTBALL: 'football',
    SportType.BASKETBALL: 'basketball',
    SportType.VOLLEYBALL: 'volleyball',
}


def infer_sport_type_from_league(league: str) -> SportType:
    """Определить вид спорта по коду лиги."""
    if league:
        for sport_type in TARGET_SPORT_TYPES:
            if league in get_leagues_for_sport(sport_type):
                return sport_type
    return SportType.HOCKEY


def create_prediction_from_match(
    match: dict,
    bet_on: str,
    target_odds: float,
    decision: Optional[dict] = None,
    flask_app=None
) -> Optional[dict]:
    """
    Создать прогноз в БД на основе матча
    
    Args:
        match: Данные матча от FlashLive
        bet_on: 'home' или 'away'
        target_odds: Коэффициент на ставку
        
    Returns:
        Словарь с данными прогноза или None
    """
    try:
        from models import Prediction, db
        
        league = match.get('league', 'Unknown')
        if not is_target_league(league):
            logger.debug(f"Skipping non-target league: {league}")
            return None
        
        home_team = match.get('home_team', 'Unknown')
        away_team = match.get('away_team', 'Unknown')
        event_id = match.get('event_id')

        app_obj = flask_app
        if app_obj is None and has_app_context():
            from flask import current_app
            app_obj = current_app._get_current_object()
        if app_obj is None:
            from app import app as default_app
            app_obj = default_app

        context = nullcontext() if has_app_context() else app_obj.app_context()

        with context:
            existing = Prediction.query.filter(
                Prediction.home_team == home_team,
                Prediction.away_team == away_team,
                Prediction.match_date >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            ).first()
            
            if existing:
                logger.debug(f"Prediction already exists: {home_team} vs {away_team}")
                return None
            
            predicted_team = home_team if bet_on == 'home' else away_team
            decision = decision or {}
            model_verdict = decision.get('model_verdict', {})
            confidence = model_verdict.get('confidence')
            if confidence is None:
                confidence = calculate_confidence(target_odds)
            sport_type = infer_sport_type_from_league(league)
            sport_slug = SPORT_SLUGS.get(sport_type, 'hockey')
            
            flashlive_event_id = event_id.replace('flash_', '') if isinstance(event_id, str) else event_id
            
            # Получаем рекомендацию RL-агента
            rl_rec = None
            rl_action = None
            rl_conf = None
            rl_comment = None
            try:
                from src.rl_agent import get_rl_recommendation
                rl_rec = get_rl_recommendation(
                    model_confidence=confidence,
                    predicted_probability=1.0 / target_odds if target_odds > 0 else 0.5,
                    odds=target_odds
                )
                rl_action = rl_rec.get('action')
                rl_conf = rl_rec.get('confidence')
                rl_comment = rl_rec.get('comment')
            except Exception as e:
                logger.warning(f"RL recommendation not available: {e}")
            
            prediction = Prediction(
                created_at=datetime.utcnow(),
                match_date=parse_match_date(match),
                sport_type=sport_slug,
                bet_type=match.get('bet_type') or 'winner',
                league=match.get('league', 'Unknown'),
                home_team=home_team,
                away_team=away_team,
                prediction_type='Money Line',
                predicted_outcome=predicted_team,
                confidence=confidence,
                confidence_1_10=int(confidence * 10),
                home_odds=match.get('home_odds'),
                away_odds=match.get('away_odds'),
                draw_odds=match.get('draw_odds'),
                bookmaker=match.get('bookmaker') or 'FlashLive',
                patterns_data={
                    'event_id': event_id,
                    'bet_on': bet_on,
                    'target_odds': target_odds,
                    'source': 'AutoMonitorQualityGate',
                    'odds_filter': '[2.0-3.5]',
                    'sport_type': sport_slug,
                    'decision_status': decision.get('status'),
                    'decision_reason': decision.get('reason'),
                    'pattern_verdict': decision.get('pattern_verdict'),
                    'model_verdict': model_verdict,
                    'history_verdict': decision.get('history_verdict'),
                    'odds_verdict': decision.get('odds_verdict'),
                    'agreement_verdict': decision.get('agreement_verdict'),
                },
                model_version='AutoMonitor_v2',
                flashlive_event_id=flashlive_event_id,
                rl_recommendation=rl_action,
                rl_confidence=rl_conf,
                rl_comment=rl_comment
            )
            
            db.session.add(prediction)
            db.session.commit()
            
            logger.info(f"Created prediction: {home_team} vs {away_team} -> {predicted_team}")
            
            return {
                'id': prediction.id,
                'home_team': home_team,
                'away_team': away_team,
                'predicted_outcome': predicted_team,
                'confidence': confidence,
                'odds': target_odds,
                'league': prediction.league,
                'sport_type': prediction.sport_type,
                'match_date': prediction.match_date.isoformat() if prediction.match_date else None
            }
            
    except Exception as e:
        logger.error(f"Error creating prediction: {e}")
        return None


def calculate_confidence(odds: float) -> float:
    """
    Рассчитать уверенность на основе коэффициента
    
    Фильтр [2.0-3.5] — это зона "небольшого аутсайдера":
    - 2.0 = 50% implied probability -> 0.7 confidence
    - 2.5 = 40% implied probability -> 0.6 confidence
    - 3.0 = 33% implied probability -> 0.5 confidence
    - 3.5 = 29% implied probability -> 0.4 confidence
    """
    if not odds or odds < 1.0:
        return 0.5
    
    implied_prob = 1.0 / odds
    
    if 2.0 <= odds <= 2.5:
        confidence = 0.65 + (2.5 - odds) * 0.1
    elif 2.5 < odds <= 3.0:
        confidence = 0.55 + (3.0 - odds) * 0.2
    elif 3.0 < odds <= 3.5:
        confidence = 0.45 + (3.5 - odds) * 0.2
    else:
        confidence = implied_prob
    
    return min(max(confidence, 0.3), 0.8)


def parse_match_date(match: dict) -> datetime:
    """Парсинг даты матча"""
    date_val = match.get('match_date') or match.get('date') or match.get('start_time')
    
    if not date_val:
        return datetime.utcnow()
    
    if isinstance(date_val, datetime):
        return date_val
    
    try:
        if 'T' in str(date_val):
            return datetime.fromisoformat(str(date_val).replace('Z', '+00:00').replace('+00:00', ''))
        else:
            return datetime.strptime(str(date_val)[:10], '%Y-%m-%d')
    except:
        return datetime.utcnow()

def is_target_league(league: str) -> bool:
    """Проверка что лига входит в список целевых"""
    if not league:
        return False
    return league.upper() in {l.upper() for l in TARGET_LEAGUES}


def get_rl_recommendation_for_prediction(prediction_data: dict) -> dict:
    """
    Получить рекомендацию RL-агента для прогноза.
    
    Args:
        prediction_data: Данные прогноза с confidence, odds и т.д.
        
    Returns:
        Рекомендация RL-агента: BET/SKIP с уверенностью
    """
    try:
        from src.rl_agent import get_rl_recommendation
        
        # Извлекаем данные из прогноза
        confidence = prediction_data.get('confidence', 0.5)
        patterns = prediction_data.get('patterns_data', {})
        bet_on = patterns.get('bet_on', 'home')
        
        # Получаем коэффициент
        if bet_on == 'home':
            odds = prediction_data.get('home_odds') or patterns.get('target_odds', 2.0)
        else:
            odds = prediction_data.get('away_odds') or patterns.get('target_odds', 2.0)
        
        # Серии команд (если есть в паттернах)
        home_series = patterns.get('home_series', 0)
        away_series = patterns.get('away_series', 0)
        h2h_advantage = patterns.get('h2h_advantage', 0)
        
        # Получаем статистику банкролла (упрощённо)
        bankroll_ratio = 1.0  # TODO: отслеживать реальный банкролл
        recent_winrate = 0.5  # TODO: рассчитывать из последних прогнозов
        
        recommendation = get_rl_recommendation(
            model_confidence=confidence,
            predicted_probability=1.0 / odds if odds > 0 else 0.5,
            odds=odds,
            home_series=home_series,
            away_series=away_series,
            h2h_advantage=h2h_advantage,
            bankroll_ratio=bankroll_ratio,
            recent_winrate=recent_winrate
        )
        
        return recommendation
        
    except Exception as e:
        logger.error(f"Error getting RL recommendation: {e}")
        return {
            'action': 'UNKNOWN',
            'confidence': 0,
            'recommendation': 'RL-агент не доступен'
        }
