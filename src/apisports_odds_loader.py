"""
DEPRECATED -- this module now re-exports from ``src.loaders.apisports``.

All classes, constants and functions are preserved for backwards compatibility.
New code should import directly from ``src.loaders`` or ``src.loaders.apisports``.
"""
# Re-export everything from the new location
from src.loaders.apisports import (  # noqa: F401
    APISportsOddsLoader,
    get_demo_odds,
    LEAGUES,
    API_SPORTS_KEY,
    BASE_URL,
)

# Keep module-level references so that monkeypatch / tests that do
# ``monkeypatch.setattr("src.apisports_odds_loader.requests.get", ...)`` still work.
import requests  # noqa: F401

import src.loaders.apisports as _apisports_module  # noqa: F401

__all__ = [
    "APISportsOddsLoader",
    "get_demo_odds",
    "LEAGUES",
    "API_SPORTS_KEY",
    "BASE_URL",
]


def __getattr__(name: str):
    """Proxy attribute lookups to ``src.loaders.apisports`` for backwards compat."""
    import src.loaders.apisports as _mod
    try:
        return getattr(_mod, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __setattr__(name: str, value) -> None:  # type: ignore[override]
    """Forward attribute patches (e.g. monkeypatch) to the canonical module."""
    import sys
    import src.loaders.apisports as _mod
    sys.modules[__name__].__dict__[name] = value
    if hasattr(_mod, name):
        setattr(_mod, name, value)
