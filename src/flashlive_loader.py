"""
DEPRECATED -- this module now re-exports from ``src.loaders.flashlive``.

All classes, constants and functions are preserved for backwards compatibility.
New code should import directly from ``src.loaders`` or ``src.loaders.flashlive``.
"""
# Re-export everything from the new location
from src.loaders.flashlive import (  # noqa: F401
    FlashLiveLoader,
    MultiSportFlashLiveLoader,
    get_demo_matches,
    set_error_alert_callback,
    set_telegram_notifier,
    _send_error_alert,
    _error_alert_callback,
    _telegram_notifier_instance,
    RAPIDAPI_KEY,
    RAPIDAPI_HOST,
    BASE_URL,
    HOCKEY_SPORT_ID,
    SUPPORTED_LEAGUES,
    HOCKEY_LEAGUES,
)

from src.sports_config import SportType  # noqa: F401

# Keep module-level references so that monkeypatch / tests that do
# ``monkeypatch.setattr("src.flashlive_loader.requests.get", ...)`` still work.
import requests  # noqa: F401
import time  # noqa: F401

import src.loaders.flashlive as _flashlive_module  # noqa: F401

__all__ = [
    "FlashLiveLoader",
    "MultiSportFlashLiveLoader",
    "get_demo_matches",
    "set_error_alert_callback",
    "set_telegram_notifier",
    "_send_error_alert",
    "_error_alert_callback",
    "_telegram_notifier_instance",
    "RAPIDAPI_KEY",
    "RAPIDAPI_HOST",
    "BASE_URL",
    "HOCKEY_SPORT_ID",
    "SUPPORTED_LEAGUES",
    "HOCKEY_LEAGUES",
    "SportType",
]


def __getattr__(name: str):
    """Proxy attribute lookups to ``src.loaders.flashlive`` for backwards compat."""
    import src.loaders.flashlive as _mod
    try:
        return getattr(_mod, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __setattr__(name: str, value) -> None:  # type: ignore[override]
    """Forward attribute patches (e.g. monkeypatch) to the canonical module."""
    import sys
    import src.loaders.flashlive as _mod
    sys.modules[__name__].__dict__[name] = value
    if hasattr(_mod, name):
        setattr(_mod, name, value)
