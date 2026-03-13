"""
DEPRECATED -- this module now re-exports from ``src.loaders.euro``.

All classes, constants and functions are preserved for backwards compatibility.
New code should import directly from ``src.loaders`` or ``src.loaders.euro``.
"""
# Re-export everything from the new location
from src.loaders.euro import (  # noqa: F401
    EuroLeagueLoader,
    EURO_LEAGUES,
    CACHE_DIR,
    fetch_european_odds,
    get_league_odds_key,
    match_odds_to_game,
    euro_odds_cache,
    euro_odds_cache_time,
)

import src.loaders.euro as _euro_module  # noqa: F401

__all__ = [
    "EuroLeagueLoader",
    "EURO_LEAGUES",
    "CACHE_DIR",
    "fetch_european_odds",
    "get_league_odds_key",
    "match_odds_to_game",
    "euro_odds_cache",
    "euro_odds_cache_time",
]


def __getattr__(name: str):
    """Proxy attribute lookups to ``src.loaders.euro`` for backwards compat."""
    import src.loaders.euro as _mod
    try:
        return getattr(_mod, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __setattr__(name: str, value) -> None:  # type: ignore[override]
    """Forward attribute patches (e.g. monkeypatch) to the canonical module."""
    import sys
    import src.loaders.euro as _mod
    sys.modules[__name__].__dict__[name] = value
    if hasattr(_mod, name):
        setattr(_mod, name, value)
