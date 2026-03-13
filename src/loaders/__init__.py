"""
Unified loader package for the pattern_interruption betting prediction system.

This package consolidates five previously separate loader modules into a
clean architecture with a shared base class, typed data models, and a
factory function for easy instantiation.

Submodules
----------
base       -- Abstract ``BaseLoader`` interface
models     -- Shared dataclasses (MatchData, OddsData, TeamStats, ...)
flashlive  -- FlashLive Sports API (RapidAPI) -- primary real-time source
nhl        -- NHL public API -- historical game data
apisports  -- API-Sports hockey API -- odds and multi-league data
euro       -- European leagues (cache-based historical data)
factory    -- ``get_loader()`` factory function

Quick start::

    from src.loaders import get_loader, NHLDataLoader, FlashLiveLoader

    loader = get_loader("NHL")
    data = loader.load_historical_data(seasons=["20242025"])
"""

# Base
from src.loaders.base import BaseLoader

# Data models
from src.loaders.models import MatchData, OddsData, TeamStats

# Concrete loaders
from src.loaders.nhl import NHLDataLoader, DataLoader
from src.loaders.flashlive import (
    FlashLiveLoader,
    MultiSportFlashLiveLoader,
    get_demo_matches,
    set_error_alert_callback,
    set_telegram_notifier,
    HOCKEY_SPORT_ID,
    SUPPORTED_LEAGUES,
    HOCKEY_LEAGUES,
)
from src.loaders.apisports import (
    APISportsOddsLoader,
    MultiLeagueLoader,
    get_demo_odds,
    LEAGUES,
)
from src.loaders.euro import (
    EuroLeagueLoader,
    EURO_LEAGUES,
    fetch_european_odds,
    get_league_odds_key,
    match_odds_to_game,
)

# Factory
from src.loaders.factory import get_loader, get_multi_sport_loader

__all__ = [
    # Base
    "BaseLoader",
    # Models
    "MatchData",
    "OddsData",
    "TeamStats",
    # Loaders
    "NHLDataLoader",
    "DataLoader",
    "FlashLiveLoader",
    "MultiSportFlashLiveLoader",
    "APISportsOddsLoader",
    "MultiLeagueLoader",
    "EuroLeagueLoader",
    # Helpers
    "get_demo_matches",
    "get_demo_odds",
    "set_error_alert_callback",
    "set_telegram_notifier",
    "fetch_european_odds",
    "get_league_odds_key",
    "match_odds_to_game",
    # Constants
    "HOCKEY_SPORT_ID",
    "SUPPORTED_LEAGUES",
    "HOCKEY_LEAGUES",
    "LEAGUES",
    "EURO_LEAGUES",
    # Factory
    "get_loader",
    "get_multi_sport_loader",
]
