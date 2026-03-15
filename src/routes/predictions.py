"""
Prediction CRUD routes: list, detail, decide.
"""
from __future__ import annotations

from flask import Blueprint, redirect, request, url_for

from src.routes.helpers import (
    get_odds_loader_for_sport,
    get_prediction_by_id,
    get_prediction_target_odds,
    resolve_sport_type_from_league,
)

predictions_bp = Blueprint('predictions', __name__)


def _pkg():
    """Late-import the package so reads see monkeypatched values."""
    import src.routes as _rt
    return _rt


@predictions_bp.route('/predictions')
def predictions_page() -> str:
    """Prediction list page."""
    rt = _pkg()

    predictions: list = []
    stats: dict = {'total': 0, 'pending': 0, 'win_rate': 0, 'roi': 0}

    if rt.Prediction and rt.db:
        try:
            predictions = rt.Prediction.query.order_by(rt.Prediction.match_date.desc()).limit(100).all()

            total = rt.Prediction.query.count()

            completed = rt.Prediction.query.filter(rt.Prediction.is_win != None).all()  # noqa: E711
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
            print(f"Error loading predictions: {e}")

    return rt.render_template('predictions.html', predictions=predictions, stats=stats)


@predictions_bp.route('/prediction/<int:prediction_id>')
def prediction_detail(prediction_id: int) -> str:
    """Detailed prediction page."""
    rt = _pkg()

    prediction = None
    home_history: list = []
    away_history: list = []
    h2h_history: list = []
    h2h_data = None

    if rt.Prediction and rt.db:
        try:
            prediction = get_prediction_by_id(prediction_id)
            if prediction is None:
                return "Прогноз не найден", 404  # type: ignore[return-value]

            event_id = prediction.flashlive_event_id
            if not event_id and prediction.patterns_data:
                event_id = prediction.patterns_data.get('event_id', '')
                if event_id:
                    event_id = event_id.replace('flash_', '')

            loader = get_odds_loader_for_sport(
                getattr(prediction, 'sport_type', None)
                or resolve_sport_type_from_league(prediction.league)
            )

            if event_id and loader:
                try:
                    h2h_data = loader.get_h2h_data(event_id)
                    if h2h_data:
                        home_history = h2h_data.get('home_team_matches', [])
                        away_history = h2h_data.get('away_team_matches', [])
                except Exception as e:
                    print(f"Error loading H2H data: {e}")

        except Exception as e:
            print(f"Error loading prediction: {e}")
            return "Прогноз не найден", 404  # type: ignore[return-value]

    # RL agent recommendation
    rl_recommendation = None
    if prediction:
        try:
            from src.prediction_service import get_rl_recommendation_for_prediction
            prediction_data = {
                'confidence': prediction.confidence or 0.5,
                'home_odds': prediction.home_odds,
                'away_odds': prediction.away_odds,
                'patterns_data': prediction.patterns_data or {},
            }
            rl_recommendation = get_rl_recommendation_for_prediction(prediction_data)
        except Exception as e:
            print(f"Error getting RL recommendation: {e}")

    return rt.render_template(
        'prediction_detail.html',
        prediction=prediction,
        home_history=home_history,
        away_history=away_history,
        h2h_history=h2h_history,
        h2h_data=h2h_data,
        rl_recommendation=rl_recommendation,
    )


@predictions_bp.route('/prediction/<int:prediction_id>/decide', methods=['POST'])
def prediction_decide(prediction_id: int):
    """Save a user decision on a prediction."""
    rt = _pkg()

    if not rt.Prediction or not rt.db or not rt.UserDecision:
        return redirect(url_for('routes.predictions_page'))

    try:
        prediction = get_prediction_by_id(prediction_id)
        if prediction is None:
            return redirect(url_for('routes.predictions_page'))

        decision = request.form.get('decision')
        comment = request.form.get('comment', '')

        if decision and decision in ['accepted', 'rejected']:
            user_decision = rt.UserDecision(
                prediction_id=prediction_id,
                decision=decision,
                comment=comment,
            )
            rt.db.session.add(user_decision)
            rt.db.session.commit()
    except Exception as e:
        print(f"Error saving decision: {e}")
        rt.db.session.rollback()

    return redirect(url_for('routes.prediction_detail', prediction_id=prediction_id))
