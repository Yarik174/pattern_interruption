"""
Routes package for the multi-sport betting prediction system.

This package splits the monolithic routes.py into focused modules while
keeping full backward compatibility with the existing ``routes_bp`` blueprint
name so that ``url_for('routes.predictions_page')`` and every other reference
in app.py and templates continues to work unchanged.

Architecture
------------
* ``helpers``     - shared state (db, models, monitor, etc.) and utility functions
* ``dashboard``   - dashboard, statistics, logs, explainability, watchlist page
* ``predictions`` - prediction list, detail, decide
* ``sports``      - sport-specific prediction views
* ``settings``    - telegram / config pages
* ``api``         - JSON API endpoints

Usage in app.py (unchanged from before)::

    from src.routes import routes_bp, init_routes, set_monitor, set_telegram, set_odds_loader
    app.register_blueprint(routes_bp)
"""
from __future__ import annotations

from flask import Blueprint, render_template  # noqa: F401
from typing import Any

from src.routes import helpers as _helpers
from src.routes.dashboard import dashboard_bp
from src.routes.predictions import predictions_bp
from src.routes.sports import sports_bp
from src.routes.settings import settings_bp
from src.routes.api import api_bp
from src.sports_config import SportType  # noqa: F401  (tests read routes_module.SportType)

# ── Mutable state exposed at package level for test monkeypatching ───────────
#
# Tests do ``monkeypatch.setattr(routes_module, "odds_monitor", fake_monitor)``
# which calls ``setattr(src.routes, "odds_monitor", fake_monitor)``.
# Python's ``setattr`` on a module puts the value directly into ``__dict__``,
# so we must also *read* from this module's ``__dict__`` in route functions.
# The ``_get()`` helper in each route module does this via
# ``import src.routes as _pkg; _pkg.odds_monitor``.
#
# We initialise these to None; ``init_routes`` / ``set_*`` populate them.

db: Any = None
Prediction: Any = None
UserDecision: Any = None
UserWatchlist: Any = None
ModelVersion: Any = None
TelegramSettings: Any = None
odds_monitor: Any = None
telegram_notifier: Any = None
odds_loader: Any = None


# ── Master blueprint that preserves the 'routes' name ────────────────────────

routes_bp = Blueprint('routes', __name__)


def _attach_views() -> None:
    """Copy all view functions from sub-blueprints onto ``routes_bp``."""
    for bp in (dashboard_bp, predictions_bp, sports_bp, settings_bp, api_bp):
        for deferred in bp.deferred_functions:
            deferred(routes_bp)


_attach_views()


# ── Public API (backward-compatible) ─────────────────────────────────────────

def _sync_to_helpers() -> None:
    """Push package-level state down to helpers (route functions may import either)."""
    _helpers.db = db
    _helpers.Prediction = Prediction
    _helpers.UserDecision = UserDecision
    _helpers.UserWatchlist = UserWatchlist
    _helpers.ModelVersion = ModelVersion
    _helpers.TelegramSettings = TelegramSettings
    _helpers.odds_monitor = odds_monitor
    _helpers.telegram_notifier = telegram_notifier
    _helpers.odds_loader = odds_loader


def init_routes(database: Any, models: dict[str, Any]) -> None:
    """Initialise shared state for all route modules."""
    global db, Prediction, UserDecision, UserWatchlist, ModelVersion, TelegramSettings
    db = database
    Prediction = models['Prediction']
    UserDecision = models['UserDecision']
    UserWatchlist = models.get('UserWatchlist')
    ModelVersion = models['ModelVersion']
    TelegramSettings = models.get('TelegramSettings')
    _helpers.init_routes(database, models)


def set_monitor(monitor: Any) -> None:
    global odds_monitor
    odds_monitor = monitor
    _helpers.set_monitor(monitor)


def set_telegram(notifier: Any) -> None:
    global telegram_notifier
    telegram_notifier = notifier
    _helpers.set_telegram(notifier)


def set_odds_loader(loader: Any) -> None:
    global odds_loader
    odds_loader = loader
    _helpers.set_odds_loader(loader)
