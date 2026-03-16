"""
Sport-specific view routes.
"""
from __future__ import annotations

import logging

from flask import Blueprint, redirect, url_for

logger = logging.getLogger(__name__)

from src.routes.helpers import get_prediction_target_odds
from src.sports_config import SportType, get_leagues_for_sport, get_sport_config

sports_bp = Blueprint('sports', __name__)


def _pkg():
    """Late-import the package so reads see monkeypatched values."""
    import src.routes as _rt
    return _rt


@sports_bp.route('/sports/<sport>')
def sports_predictions_page(sport: str) -> str:
    """Predictions filtered by sport."""
    rt = _pkg()

    sport_map = {
        'hockey': SportType.HOCKEY,
        'football': SportType.FOOTBALL,
        'basketball': SportType.BASKETBALL,
        'volleyball': SportType.VOLLEYBALL,
    }
    sport_type = sport_map.get(str(sport).lower())
    if not sport_type:
        return redirect(url_for('routes.predictions_page'))

    leagues = get_leagues_for_sport(sport_type)
    predictions: list = []
    stats: dict = {'total': 0, 'pending': 0, 'win_rate': 0, 'roi': 0}

    if rt.Prediction and rt.db:
        try:
            query = rt.Prediction.query.filter(
                rt.Prediction.league.in_(leagues)
            ).order_by(rt.Prediction.match_date.desc())
            predictions = query.limit(100).all()

            total = rt.Prediction.query.filter(rt.Prediction.league.in_(leagues)).count()
            completed = rt.Prediction.query.filter(
                rt.Prediction.league.in_(leagues)
            ).filter(rt.Prediction.is_win.isnot(None)).all()
            pending = total - len(completed)
            wins = sum(1 for p in completed if p.is_win)
            losses = len(completed) - wins
            win_rate = (wins / len(completed) * 100) if completed else 0

            profit = sum(
                get_prediction_target_odds(p) - 1 for p in completed if p.is_win
            ) - losses
            roi = (profit / len(completed) * 100) if completed else 0

            stats = {
                'total': total,
                'pending': pending,
                'win_rate': round(win_rate, 1),
                'roi': round(roi, 1),
            }
        except Exception as e:
            logger.error(f"Error in sports_predictions_page (sport={sport}): {e}", exc_info=True)

    sport_config = get_sport_config(sport_type)
    return rt.render_template(
        'sports/sport_predictions.html',
        sport=sport,
        sport_config=sport_config,
        leagues=leagues,
        predictions=predictions,
        stats=stats,
    )
