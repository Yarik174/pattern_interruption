"""
Loader factory -- returns the correct loader instance for a given league or sport.

Usage::

    from src.loaders.factory import get_loader

    loader = get_loader("NHL")          # -> NHLDataLoader
    loader = get_loader("KHL")          # -> MultiLeagueLoader
    loader = get_loader("flashlive")    # -> FlashLiveLoader
    loader = get_loader("apisports")    # -> APISportsOddsLoader
"""
from __future__ import annotations

from typing import Optional, Union

from src.loaders.base import BaseLoader
from src.loaders.nhl import NHLDataLoader
from src.loaders.flashlive import FlashLiveLoader, MultiSportFlashLiveLoader
from src.loaders.apisports import APISportsOddsLoader, MultiLeagueLoader
from src.loaders.euro import EuroLeagueLoader

# Leagues handled by each loader type
_NHL_LEAGUES = {"NHL"}
_EURO_LEAGUES = {"KHL", "SHL", "Liiga", "DEL", "Czech", "Swiss"}
_APISPORTS_LEAGUES = _NHL_LEAGUES | _EURO_LEAGUES  # superset via API-Sports

# Special aliases that select a loader by source rather than league
_SOURCE_ALIASES = {
    "flashlive": "flashlive",
    "flash": "flashlive",
    "apisports": "apisports",
    "api-sports": "apisports",
    "nhl": "nhl",
    "euro": "euro",
    "multi": "multi_league",
    "multi_league": "multi_league",
}


def get_loader(
    league_or_source: str = "NHL",
    *,
    purpose: str = "historical",
) -> BaseLoader:
    """Return the most appropriate loader for *league_or_source*.

    Args:
        league_or_source: A league code (``"NHL"``, ``"KHL"``, ...) or a
            source alias (``"flashlive"``, ``"apisports"``).
        purpose: ``"historical"`` (default) for past game data, or
            ``"live"`` for upcoming games and odds.

    Returns:
        A :class:`BaseLoader` subclass instance.

    Examples::

        get_loader("NHL")                          # NHLDataLoader
        get_loader("NHL", purpose="live")           # FlashLiveLoader
        get_loader("KHL")                           # MultiLeagueLoader
        get_loader("SHL", purpose="live")           # FlashLiveLoader
        get_loader("flashlive")                     # FlashLiveLoader
        get_loader("apisports")                     # APISportsOddsLoader
    """
    key = league_or_source.strip()
    key_lower = key.lower()

    # ---- Source-level aliases (only for non-league identifiers) ----
    is_league_code = key in _NHL_LEAGUES or key in _EURO_LEAGUES
    if not is_league_code:
        source = _SOURCE_ALIASES.get(key_lower)
        if source == "flashlive":
            return FlashLiveLoader()
        if source == "apisports":
            return APISportsOddsLoader()
        if source == "nhl":
            return NHLDataLoader()
        if source == "euro":
            return EuroLeagueLoader()
        if source == "multi_league":
            return MultiLeagueLoader()

    # ---- League-based selection ----
    if purpose == "live":
        # For live/upcoming data, FlashLive is the primary source
        return FlashLiveLoader()

    if key in _NHL_LEAGUES:
        return NHLDataLoader()

    if key in _EURO_LEAGUES:
        # For historical euro data, prefer cache-based EuroLeagueLoader
        return EuroLeagueLoader()

    # Fallback: multi-league loader covers all API-Sports leagues
    return MultiLeagueLoader()


def get_multi_sport_loader(
    api_key: Optional[str] = None,
) -> MultiSportFlashLiveLoader:
    """Convenience function to get the multi-sport FlashLive aggregator."""
    return MultiSportFlashLiveLoader(api_key=api_key)
