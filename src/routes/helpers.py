"""
Shared helpers and state for all route modules.

All route blueprints import from here to access the database session,
ORM models, and utility functions.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Optional

from flask import render_template  # noqa: F401  (re-exported for monkeypatching)
from src.sports_config import SportType, get_leagues_for_sport, get_sport_config


# ── Module-level state (set once at init time) ──────────────────────────────

db: Any = None
Prediction: Any = None
UserDecision: Any = None
UserWatchlist: Any = None
ModelVersion: Any = None
TelegramSettings: Any = None

odds_monitor: Any = None
telegram_notifier: Any = None
odds_loader: Any = None


# ── Setters ──────────────────────────────────────────────────────────────────

def init_routes(database: Any, models: dict[str, Any]) -> None:
    """Initialise shared state for all route modules."""
    global db, Prediction, UserDecision, UserWatchlist, ModelVersion, TelegramSettings
    db = database
    Prediction = models['Prediction']
    UserDecision = models['UserDecision']
    UserWatchlist = models.get('UserWatchlist')
    ModelVersion = models['ModelVersion']
    TelegramSettings = models.get('TelegramSettings')


def set_monitor(monitor: Any) -> None:
    global odds_monitor
    odds_monitor = monitor


def set_telegram(notifier: Any) -> None:
    global telegram_notifier
    telegram_notifier = notifier


def set_odds_loader(loader: Any) -> None:
    global odds_loader
    odds_loader = loader


# ── Utility functions ────────────────────────────────────────────────────────

def resolve_sport_type_from_league(league: Optional[str]) -> SportType:
    """Determine sport type from league code."""
    if not league:
        return SportType.HOCKEY
    for sport_type in (SportType.HOCKEY, SportType.FOOTBALL, SportType.BASKETBALL, SportType.VOLLEYBALL):
        if league in get_leagues_for_sport(sport_type):
            return sport_type
    return SportType.HOCKEY


def get_odds_loader_for_sport(sport: Any) -> Any:
    """Return the loader appropriate for *sport*.

    Supports both old single-loader and new callable manager.
    Reads from the package module so test monkeypatches are visible.
    """
    import src.routes as _rt
    _loader = _rt.odds_loader
    if callable(_loader):
        return _loader(sport)
    return _loader


def get_prediction_by_id(prediction_id: int) -> Any:
    """Fetch prediction by id without legacy Query.get API.

    Reads from the package module so test monkeypatches are visible.
    """
    import src.routes as _rt
    if not _rt.Prediction or not _rt.db:
        return None
    return _rt.db.session.get(_rt.Prediction, prediction_id)


def get_prediction_target_odds(prediction: Any) -> float:
    """Extract the target odds from a prediction's pattern data."""
    patterns = prediction.patterns_data or {}
    if isinstance(patterns, str):
        try:
            patterns = json.loads(patterns)
        except Exception:
            patterns = {}

    target_odds = patterns.get('target_odds')
    if isinstance(target_odds, (int, float)) and target_odds > 0:
        return float(target_odds)

    bet_on = patterns.get('bet_on') or patterns.get('target')
    if bet_on == 'home' and prediction.home_odds:
        return prediction.home_odds
    if bet_on == 'away' and prediction.away_odds:
        return prediction.away_odds

    if prediction.predicted_outcome == prediction.home_team and prediction.home_odds:
        return prediction.home_odds
    if prediction.predicted_outcome == prediction.away_team and prediction.away_odds:
        return prediction.away_odds

    return prediction.home_odds or prediction.away_odds or 2.0


def get_prediction_sport_slug(prediction: Any) -> str:
    """Get lowercase sport slug from a prediction."""
    sport_slug = getattr(prediction, 'sport_type', None)
    if sport_slug:
        return str(sport_slug).lower()
    return resolve_sport_type_from_league(
        getattr(prediction, 'league', None)
    ).name.lower()


def extract_decision_traces(
    limit: int = 100,
    status: str = '',
    reason: str = '',
    sport: str = '',
    league: str = '',
) -> list[dict[str, Any]]:
    """Collect explainability decision traces from monitoring logs."""
    from models import SystemLog

    query = (
        SystemLog.query
        .filter(SystemLog.log_type == 'monitoring')
        .order_by(SystemLog.timestamp.desc())
        .limit(max(limit * 5, 200))
    )

    items: list[dict[str, Any]] = []
    for log in query.all():
        details = log.details or {}
        decision = details.get('decision')
        if not isinstance(decision, dict):
            continue

        item: dict[str, Any] = {
            'log_id': log.id,
            'timestamp': log.timestamp,
            'message': log.message,
            'status': decision.get('status') or 'unknown',
            'reason': decision.get('reason') or 'unknown',
            'sport_type': decision.get('sport_type') or 'unknown',
            'league': decision.get('league') or '-',
            'home_team': decision.get('home_team') or '-',
            'away_team': decision.get('away_team') or '-',
            'bet_on': decision.get('bet_on'),
            'target_odds': decision.get('target_odds'),
            'home_odds': decision.get('home_odds'),
            'away_odds': decision.get('away_odds'),
            'technical_verdict': decision.get('technical_verdict') or {},
            'odds_verdict': decision.get('odds_verdict') or {},
            'history_verdict': decision.get('history_verdict') or {},
            'pattern_verdict': decision.get('pattern_verdict') or {},
            'model_verdict': decision.get('model_verdict') or {},
            'agreement_verdict': decision.get('agreement_verdict') or {},
        }

        if status and item['status'] != status:
            continue
        if reason and item['reason'] != reason:
            continue
        if sport and item['sport_type'] != sport:
            continue
        if league and item['league'] != league:
            continue

        items.append(item)
        if len(items) >= limit:
            break

    return items


def build_decision_trace_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Build aggregate summary over explainability decision traces."""
    status_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    sport_counts: Counter[str] = Counter()
    league_counts: Counter[str] = Counter()
    pattern_counts: Counter[str] = Counter()
    model_counts: Counter[str] = Counter()

    for item in items:
        status_counts[item['status']] += 1
        reason_counts[item['reason']] += 1
        sport_counts[item['sport_type']] += 1
        league_counts[item['league']] += 1
        pattern_counts[item['pattern_verdict'].get('reason') or 'unknown'] += 1
        model_counts[item['model_verdict'].get('reason') or 'unknown'] += 1

    return {
        'total': len(items),
        'status_counts': dict(status_counts),
        'reason_counts': reason_counts.most_common(8),
        'sport_counts': dict(sport_counts),
        'league_counts': league_counts.most_common(8),
        'pattern_reason_counts': pattern_counts.most_common(8),
        'model_reason_counts': model_counts.most_common(8),
    }
