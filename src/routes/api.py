"""
JSON API endpoints.
"""
from __future__ import annotations

import logging
from datetime import datetime

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

from src.routes.helpers import (
    build_decision_trace_summary,
    extract_decision_traces,
    get_odds_loader_for_sport,
    get_prediction_by_id,
)
from src.sports_config import SportType

api_bp = Blueprint('api', __name__)


def _pkg():
    """Late-import the package so reads see monkeypatched values."""
    import src.routes as _rt
    return _rt


# ── Telegram ─────────────────────────────────────────────────────────────────

@api_bp.route('/api/telegram/test', methods=['POST'])
def api_telegram_test():
    """Test Telegram connection."""
    data = request.get_json() or {}
    bot_token = data.get('bot_token')

    if not bot_token:
        return jsonify({'ok': False, 'error': 'Token required'})

    try:
        import requests as req
        response = req.get(
            f"https://api.telegram.org/bot{bot_token}/getMe",
            timeout=10,
        )

        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                bot_info = result.get('result', {})
                return jsonify({
                    'ok': True,
                    'bot_username': bot_info.get('username'),
                    'bot_name': bot_info.get('first_name'),
                })

        return jsonify({'ok': False, 'error': 'Invalid token'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


# ── Monitor ──────────────────────────────────────────────────────────────────

@api_bp.route('/api/monitor/start', methods=['POST'])
def api_monitor_start():
    """Start odds monitoring."""
    rt = _pkg()
    if rt.odds_monitor:
        rt.odds_monitor.start()
        return jsonify({'ok': True, 'message': 'Мониторинг запущен'})
    return jsonify({'ok': False, 'error': 'Monitor not configured'})


@api_bp.route('/api/monitor/stop', methods=['POST'])
def api_monitor_stop():
    """Stop odds monitoring."""
    rt = _pkg()
    if rt.odds_monitor:
        rt.odds_monitor.stop()
        return jsonify({'ok': True, 'message': 'Мониторинг остановлен'})
    return jsonify({'ok': False, 'error': 'Monitor not configured'})


@api_bp.route('/api/monitor/check', methods=['POST'])
def api_monitor_check():
    """Check odds now."""
    rt = _pkg()
    if rt.odds_monitor:
        result = rt.odds_monitor.check_now()
        return jsonify(result)
    return jsonify({'ok': False, 'error': 'Monitor not configured'})


@api_bp.route('/api/monitor/stats')
def api_monitor_stats():
    """Monitoring statistics."""
    rt = _pkg()

    stats: dict = {'is_running': False}
    if rt.odds_monitor:
        stats = rt.odds_monitor.get_stats()

    loader = get_odds_loader_for_sport(SportType.HOCKEY)
    if loader:
        if hasattr(loader, 'get_upcoming_games'):
            try:
                matches = loader.get_upcoming_games(days_ahead=1)
                stats['matches_available'] = len(matches)
            except Exception as e:
                logger.error(f"Error in api_monitor_stats (get_upcoming_games): {e}", exc_info=True)
                stats['matches_available'] = 0
        else:
            stats['matches_available'] = 0

    if rt.Prediction and rt.db:
        try:
            today = datetime.utcnow().date()
            today_start = datetime.combine(today, datetime.min.time())
            today_predictions = rt.Prediction.query.filter(
                rt.Prediction.created_at >= today_start
            ).count()
            stats['bets_suggested'] = today_predictions
        except Exception as e:
            logger.error(f"Error in api_monitor_stats (bets_suggested): {e}", exc_info=True)
            stats['bets_suggested'] = 0
    else:
        stats['bets_suggested'] = 0

    return jsonify(stats)


# ── Predictions API ──────────────────────────────────────────────────────────

@api_bp.route('/api/predictions')
def api_predictions():
    """List predictions."""
    rt = _pkg()
    predictions: list = []

    if rt.Prediction and rt.db:
        try:
            limit = request.args.get('limit', 50, type=int)
            league = request.args.get('league')

            query = rt.Prediction.query.order_by(rt.Prediction.match_date.desc())
            if league:
                query = query.filter(rt.Prediction.league == league)

            predictions = [p.to_dict() for p in query.limit(limit).all()]
        except Exception as e:
            logger.error(f"Error in api_predictions: {e}", exc_info=True)

    return jsonify({'predictions': predictions})


@api_bp.route('/api/predictions/<int:prediction_id>')
def api_prediction_detail(prediction_id: int):
    """Prediction detail."""
    rt = _pkg()

    if rt.Prediction and rt.db:
        try:
            prediction = get_prediction_by_id(prediction_id)
            if prediction is None:
                return jsonify({'error': 'Not found'}), 404
            return jsonify(prediction.to_dict())
        except Exception as e:
            logger.error(f"Error in api_prediction_detail (id={prediction_id}): {e}", exc_info=True)
            return jsonify({'error': str(e)}), 404

    return jsonify({'error': 'Not found'}), 404


# ── Logs API ─────────────────────────────────────────────────────────────────

@api_bp.route('/api/logs')
def api_logs():
    """Get system logs."""
    from models import SystemLog

    log_type = request.args.get('type', '')
    level = request.args.get('level', '')
    limit = request.args.get('limit', 50, type=int)

    query = SystemLog.query.order_by(SystemLog.timestamp.desc())
    if log_type:
        query = query.filter(SystemLog.log_type == log_type)
    if level:
        query = query.filter(SystemLog.level == level)

    logs = [log.to_dict() for log in query.limit(limit).all()]
    return jsonify({'logs': logs})


# ── Explainability API ───────────────────────────────────────────────────────

@api_bp.route('/api/explainability/decisions')
def api_explainability_decisions():
    """Recent decision traces with filters."""
    status = request.args.get('status', '')
    reason = request.args.get('reason', '')
    sport = request.args.get('sport', '')
    league = request.args.get('league', '')
    limit = request.args.get('limit', 50, type=int)

    items = extract_decision_traces(
        limit=limit,
        status=status,
        reason=reason,
        sport=sport,
        league=league,
    )

    payload: list = []
    for item in items:
        serialized = dict(item)
        serialized['timestamp'] = item['timestamp'].isoformat() if item['timestamp'] else None
        payload.append(serialized)

    return jsonify({'items': payload, 'summary': build_decision_trace_summary(items)})


# ── Auto-monitor API ─────────────────────────────────────────────────────────

@api_bp.route('/api/auto-monitor/stats')
def api_auto_monitor_stats():
    """Auto-monitor statistics."""
    from src.odds_monitor import get_auto_monitor
    from src.data_refresh import get_last_refresh_info

    monitor = get_auto_monitor()
    stats = monitor.get_stats() if monitor else {'is_running': False}

    refresh_info = get_last_refresh_info()
    if refresh_info:
        stats['last_data_refresh_info'] = refresh_info

    return jsonify(stats)


@api_bp.route('/api/auto-monitor/check', methods=['POST'])
def api_auto_monitor_check():
    """Trigger auto-monitor check now."""
    from src.odds_monitor import get_auto_monitor

    monitor = get_auto_monitor()
    if monitor:
        result = monitor.check_now()
        return jsonify({'ok': True, 'result': result})
    return jsonify({'ok': False, 'error': 'AutoMonitor not available'})


# ── Watchlist API ────────────────────────────────────────────────────────────

@api_bp.route('/api/watchlist/<int:prediction_id>', methods=['POST'])
def api_watchlist_add(prediction_id: int):
    """Add a match to watchlist."""
    rt = _pkg()

    if not rt.UserWatchlist or not rt.db:
        return jsonify({'error': 'Unavailable'}), 503
    try:
        existing = rt.UserWatchlist.query.filter_by(prediction_id=prediction_id).first()
        if existing:
            return jsonify({'status': 'already_added'})
        entry = rt.UserWatchlist(prediction_id=prediction_id)
        rt.db.session.add(entry)
        rt.db.session.commit()
        return jsonify({'status': 'added'})
    except Exception as e:
        rt.db.session.rollback()
        logger.error(f"Error in api_watchlist_add (id={prediction_id}): {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/api/watchlist/<int:prediction_id>', methods=['DELETE'])
def api_watchlist_remove(prediction_id: int):
    """Remove a match from watchlist."""
    rt = _pkg()

    if not rt.UserWatchlist or not rt.db:
        return jsonify({'error': 'Unavailable'}), 503
    try:
        entry = rt.UserWatchlist.query.filter_by(prediction_id=prediction_id).first()
        if entry:
            rt.db.session.delete(entry)
            rt.db.session.commit()
        return jsonify({'status': 'removed'})
    except Exception as e:
        rt.db.session.rollback()
        logger.error(f"Error in api_watchlist_remove (id={prediction_id}): {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/api/watchlist/<int:prediction_id>/note', methods=['PATCH'])
def api_watchlist_note(prediction_id: int):
    """Update watchlist note."""
    rt = _pkg()

    if not rt.UserWatchlist or not rt.db:
        return jsonify({'error': 'Unavailable'}), 503
    try:
        entry = rt.UserWatchlist.query.filter_by(prediction_id=prediction_id).first()
        if not entry:
            return jsonify({'error': 'Not found'}), 404
        data = request.get_json() or {}
        entry.note = data.get('note', '')
        rt.db.session.commit()
        return jsonify({'status': 'ok'})
    except Exception as e:
        rt.db.session.rollback()
        logger.error(f"Error in api_watchlist_note (id={prediction_id}): {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
