"""
Dashboard and statistics routes.
"""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime

from flask import Blueprint, request

logger = logging.getLogger(__name__)

from src.routes.helpers import (
    extract_decision_traces,
    build_decision_trace_summary,
    get_prediction_sport_slug,
    get_prediction_target_odds,
)
from src.sports_config import SportType, get_sport_config

dashboard_bp = Blueprint('dashboard', __name__)


def _pkg():
    """Late-import the package so reads see monkeypatched values."""
    import src.routes as _rt
    return _rt


@dashboard_bp.route('/dashboard')
def dashboard_page() -> str:
    """AI dashboard with live monitoring status."""
    rt = _pkg()

    telegram_configured = bool(
        os.environ.get('TELEGRAM_BOT_TOKEN') and os.environ.get('TELEGRAM_CHAT_ID')
    )

    monitor_running = False
    if rt.odds_monitor:
        stats = rt.odds_monitor.get_stats()
        monitor_running = stats.get('is_running', False)

    total_predictions = 0
    today_predictions = 0
    pending_decisions = 0
    avg_confidence: float = 7.2

    if rt.Prediction and rt.db:
        try:
            total_predictions = rt.Prediction.query.count()

            today = datetime.now().date()
            today_predictions = rt.Prediction.query.filter(
                rt.db.func.date(rt.Prediction.created_at) == today
            ).count()

            pending_decisions = rt.Prediction.query.filter(
                rt.Prediction.user_decision.is_(None)
            ).count()

            all_preds = rt.Prediction.query.filter(rt.Prediction.confidence_1_10.isnot(None)).all()
            if all_preds:
                avg_confidence = sum(p.confidence_1_10 for p in all_preds) / len(all_preds)
        except Exception as e:
            logger.error(f"Error in dashboard_page: {e}", exc_info=True)

    return rt.render_template(
        'dashboard.html',
        total_predictions=total_predictions,
        today_predictions=today_predictions,
        pending_decisions=pending_decisions,
        avg_confidence=avg_confidence,
        telegram_configured=telegram_configured,
        monitor_running=monitor_running,
    )


@dashboard_bp.route('/statistics')
def statistics_page() -> str:
    """Extended statistics with model accuracy analytics."""
    rt = _pkg()

    model_stats: dict = {'total': 0, 'wins': 0, 'losses': 0, 'pending': 0, 'win_rate': 0, 'roi': 0}
    rl_stats: dict = {'total': 0, 'wins': 0, 'losses': 0, 'win_rate': 0, 'roi': 0, 'bet_count': 0, 'skip_count': 0}
    manual_stats: dict = {'total': 0, 'wins': 0, 'win_rate': 0, 'roi': 0}
    sport_stats: dict = {}
    league_stats: dict = {}
    monthly_stats: list = []
    confidence_stats: dict = {}
    pattern_stats: dict = {}
    chart_data: dict = {'labels': [], 'win_rates': [], 'totals': []}

    if rt.Prediction and rt.UserDecision and rt.db:
        try:
            # TODO: Replace with SQL-level aggregation (COUNT, AVG, GROUP BY) to avoid loading entire table
            # Current query loads all N predictions into memory on every dashboard request
            all_predictions = rt.Prediction.query.all()
            completed = [p for p in all_predictions if p.is_win is not None]
            pending = [p for p in all_predictions if p.is_win is None]

            model_stats['total'] = len(completed)
            model_stats['wins'] = sum(1 for p in completed if p.is_win)
            model_stats['losses'] = sum(1 for p in completed if not p.is_win)
            model_stats['pending'] = len(pending)
            model_stats['win_rate'] = (model_stats['wins'] / model_stats['total'] * 100) if model_stats['total'] else 0

            profit = sum(get_prediction_target_odds(p) - 1 for p in completed if p.is_win) - model_stats['losses']
            if model_stats['total'] > 0:
                model_stats['roi'] = (profit / model_stats['total']) * 100

            accepted = rt.Prediction.query.join(rt.UserDecision).filter(
                rt.UserDecision.decision == 'accepted',
                rt.Prediction.is_win.isnot(None)
            ).all()
            manual_stats['total'] = len(accepted)
            manual_stats['wins'] = sum(1 for p in accepted if p.is_win)
            manual_stats['losses'] = len(accepted) - manual_stats['wins']
            manual_stats['win_rate'] = (manual_stats['wins'] / manual_stats['total'] * 100) if manual_stats['total'] else 0

            manual_profit = sum(get_prediction_target_odds(p) - 1 for p in accepted if p.is_win) - manual_stats['losses']
            if manual_stats['total'] > 0:
                manual_stats['roi'] = (manual_profit / manual_stats['total']) * 100

            # RL agent stats
            all_rl_bet = [p for p in all_predictions if p.rl_recommendation == 'BET']
            all_rl_skip = [p for p in all_predictions if p.rl_recommendation == 'SKIP']

            rl_bet_completed = [p for p in completed if p.rl_recommendation == 'BET']
            rl_skip_completed = [p for p in completed if p.rl_recommendation == 'SKIP']

            rl_stats['bet_count'] = len(all_rl_bet)
            rl_stats['skip_count'] = len(all_rl_skip)
            rl_stats['total'] = len(rl_bet_completed)
            rl_stats['wins'] = sum(1 for p in rl_bet_completed if p.is_win)
            rl_stats['losses'] = rl_stats['total'] - rl_stats['wins']
            rl_stats['win_rate'] = (rl_stats['wins'] / rl_stats['total'] * 100) if rl_stats['total'] else 0

            skip_would_lose = sum(1 for p in rl_skip_completed if not p.is_win)
            rl_stats['skip_saved'] = skip_would_lose

            rl_profit = sum(get_prediction_target_odds(p) - 1 for p in rl_bet_completed if p.is_win) - rl_stats['losses']
            if rl_stats['total'] > 0:
                rl_stats['roi'] = (rl_profit / rl_stats['total']) * 100

            # Per-sport stats
            sport_order = ['hockey', 'football', 'basketball', 'volleyball']
            for sport_slug in sport_order:
                sport_preds = [p for p in completed if get_prediction_sport_slug(p) == sport_slug]
                if sport_preds:
                    wins = sum(1 for p in sport_preds if p.is_win)
                    losses = len(sport_preds) - wins
                    sport_profit = sum(get_prediction_target_odds(p) - 1 for p in sport_preds if p.is_win) - losses
                    sport_type = {
                        'hockey': SportType.HOCKEY,
                        'football': SportType.FOOTBALL,
                        'basketball': SportType.BASKETBALL,
                        'volleyball': SportType.VOLLEYBALL,
                    }[sport_slug]
                    sport_config = get_sport_config(sport_type)
                    sport_stats[sport_slug] = {
                        'slug': sport_slug,
                        'name': sport_config.get('name', sport_slug.title()),
                        'name_ru': sport_config.get('name_ru', sport_slug.title()),
                        'icon': sport_config.get('icon', ''),
                        'total': len(sport_preds),
                        'wins': wins,
                        'losses': losses,
                        'win_rate': wins / len(sport_preds) * 100,
                        'roi': (sport_profit / len(sport_preds)) * 100 if sport_preds else 0,
                    }

            # Per-league stats
            for league in sorted({p.league for p in completed if p.league}):
                league_preds = [p for p in completed if p.league == league]
                if league_preds:
                    wins = sum(1 for p in league_preds if p.is_win)
                    losses = len(league_preds) - wins
                    league_profit = sum(get_prediction_target_odds(p) - 1 for p in league_preds if p.is_win) - losses
                    roi = (league_profit / len(league_preds)) * 100 if league_preds else 0
                    sport_slug = get_prediction_sport_slug(league_preds[0])
                    sport_type = {
                        'hockey': SportType.HOCKEY,
                        'football': SportType.FOOTBALL,
                        'basketball': SportType.BASKETBALL,
                        'volleyball': SportType.VOLLEYBALL,
                    }.get(sport_slug, SportType.HOCKEY)
                    sport_config = get_sport_config(sport_type)
                    league_stats[league] = {
                        'total': len(league_preds),
                        'wins': wins,
                        'losses': losses,
                        'win_rate': wins / len(league_preds) * 100,
                        'roi': roi,
                        'sport_slug': sport_slug,
                        'sport_name': sport_config.get('name_ru', sport_slug.title()),
                        'sport_icon': sport_config.get('icon', ''),
                    }

            # Per-confidence stats
            for conf_level in range(1, 11):
                conf_preds = [p for p in completed if p.confidence_1_10 == conf_level]
                if conf_preds:
                    wins = sum(1 for p in conf_preds if p.is_win)
                    confidence_stats[conf_level] = {
                        'total': len(conf_preds),
                        'wins': wins,
                        'win_rate': wins / len(conf_preds) * 100,
                    }

            # Per-pattern stats
            pattern_counts: dict = defaultdict(lambda: {'total': 0, 'wins': 0})
            for pred in completed:
                if pred.patterns_data:
                    patterns = pred.patterns_data
                    if isinstance(patterns, str):
                        try:
                            patterns = json.loads(patterns)
                        except Exception:
                            patterns = {}
                    pattern_type = patterns.get('pattern_type', 'unknown')
                    if pattern_type and pattern_type != 'unknown':
                        pattern_counts[pattern_type]['total'] += 1
                        if pred.is_win:
                            pattern_counts[pattern_type]['wins'] += 1

            for pattern_type, counts in pattern_counts.items():
                if counts['total'] >= 3:
                    pattern_stats[pattern_type] = {
                        'total': counts['total'],
                        'wins': counts['wins'],
                        'win_rate': counts['wins'] / counts['total'] * 100,
                    }

            pattern_stats = dict(sorted(
                pattern_stats.items(),
                key=lambda x: x[1]['win_rate'],
                reverse=True,
            ))

            # Monthly stats
            monthly_data: dict = defaultdict(lambda: {'total': 0, 'wins': 0, 'accepted': 0})
            for pred in completed:
                if pred.match_date:
                    month_key = pred.match_date.strftime('%Y-%m')
                    monthly_data[month_key]['total'] += 1
                    if pred.is_win:
                        monthly_data[month_key]['wins'] += 1

            for pred in accepted:
                if pred.match_date:
                    month_key = pred.match_date.strftime('%Y-%m')
                    monthly_data[month_key]['accepted'] += 1

            sorted_months = sorted(monthly_data.keys())
            prev_win_rate = None
            for month in sorted_months:
                data = monthly_data[month]
                win_rate = data['wins'] / data['total'] * 100 if data['total'] else 0
                trend = 0
                if prev_win_rate is not None:
                    trend = 1 if win_rate > prev_win_rate else (-1 if win_rate < prev_win_rate else 0)
                prev_win_rate = win_rate

                month_preds = [p for p in completed if p.match_date and p.match_date.strftime('%Y-%m') == month]
                month_wins = [p for p in month_preds if p.is_win]
                month_losses = len(month_preds) - len(month_wins)
                month_profit = sum(get_prediction_target_odds(p) - 1 for p in month_wins) - month_losses
                roi = (month_profit / len(month_preds)) * 100 if month_preds else 0

                monthly_stats.append({
                    'month': month,
                    'total': data['total'],
                    'wins': data['wins'],
                    'win_rate': win_rate,
                    'roi': roi,
                    'accepted': data['accepted'],
                    'trend': trend,
                })

            # Chart data
            chart_data['labels'] = sorted_months[-12:]
            chart_data['cumulative_roi'] = []
            cumulative_profit = 0.0
            cumulative_total = 0

            for month in chart_data['labels']:
                data = monthly_data[month]
                win_rate = data['wins'] / data['total'] * 100 if data['total'] else 0
                chart_data['win_rates'].append(round(win_rate, 1))
                chart_data['totals'].append(data['total'])

                month_preds = [p for p in completed if p.match_date and p.match_date.strftime('%Y-%m') == month]
                month_wins = [p for p in month_preds if p.is_win]
                month_losses = len(month_preds) - len(month_wins)
                month_profit = sum(get_prediction_target_odds(p) - 1 for p in month_wins) - month_losses

                cumulative_profit += month_profit
                cumulative_total += len(month_preds)

                cum_roi = (cumulative_profit / cumulative_total) * 100 if cumulative_total > 0 else 0
                chart_data['cumulative_roi'].append(round(cum_roi, 1))

        except Exception as e:
            logger.error(f"Error in statistics_page: {e}", exc_info=True)

    return rt.render_template(
        'statistics.html',
        model_stats=model_stats,
        rl_stats=rl_stats,
        manual_stats=manual_stats,
        sport_stats=sport_stats,
        league_stats=league_stats,
        league_order=list(league_stats.keys()),
        monthly_stats=monthly_stats,
        confidence_stats=confidence_stats,
        pattern_stats=pattern_stats,
        chart_data=chart_data,
    )


@dashboard_bp.route('/logs')
def logs_page() -> str:
    """System logs page."""
    rt = _pkg()
    from models import SystemLog
    from src.odds_monitor import get_auto_monitor
    from src.data_refresh import get_last_refresh_info

    log_type = request.args.get('type', '')
    level = request.args.get('level', '')
    limit = request.args.get('limit', 50, type=int)

    query = SystemLog.query.order_by(SystemLog.timestamp.desc())

    if log_type:
        query = query.filter(SystemLog.log_type == log_type)
    if level:
        query = query.filter(SystemLog.level == level)

    logs = query.limit(limit).all()

    monitor = get_auto_monitor()
    monitor_stats = monitor.get_stats() if monitor else {}

    refresh_info = get_last_refresh_info() or {}

    log_types = ['data_update', 'monitoring', 'prediction', 'error', 'system']
    levels = ['INFO', 'WARNING', 'ERROR', 'CRITICAL']

    return rt.render_template(
        'logs.html',
        logs=logs,
        log_types=log_types,
        levels=levels,
        selected_type=log_type,
        selected_level=level,
        limit=limit,
        monitor_stats=monitor_stats,
        refresh_info=refresh_info,
    )


@dashboard_bp.route('/explainability')
def explainability_page() -> str:
    """Explainability page: how the gate decides on matches."""
    rt = _pkg()

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
    summary = build_decision_trace_summary(items)

    return rt.render_template(
        'explainability.html',
        items=items,
        summary=summary,
        selected_status=status,
        selected_reason=reason,
        selected_sport=sport,
        selected_league=league,
        limit=limit,
        statuses=['candidate', 'shadow_only', 'rejected'],
        sports=['hockey', 'football', 'basketball', 'volleyball'],
        reasons=[reason_name for reason_name, _ in summary['reason_counts']],
        leagues=[league_name for league_name, _ in summary['league_counts']],
    )


@dashboard_bp.route('/watchlist')
def watchlist_page() -> str:
    """User watchlist page."""
    rt = _pkg()

    entries: list = []
    if rt.UserWatchlist and rt.db:
        try:
            entries = rt.UserWatchlist.query.order_by(rt.UserWatchlist.created_at.desc()).all()
        except Exception as e:
            logger.error(f"Error in watchlist_page: {e}", exc_info=True)
    return rt.render_template('watchlist.html', entries=entries)
