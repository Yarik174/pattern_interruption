"""
Unified configuration package for pattern_interruption.

Quick start::

    from src.config import settings, SportType, get_sport_config
    print(settings.patterns.critical_thresholds)
    print(get_sport_config(SportType.HOCKEY).name)

The package re-exports the most commonly used symbols so that callers
only need ``from src.config import ...``.

Backwards compatibility: all names previously available from the old
``src/config.py`` module (``CRITICAL_THRESHOLDS``, ``Config``,
``setup_logging``, etc.) are re-exported here.
"""
from __future__ import annotations

# -- Constants & enums -------------------------------------------------------
from src.config.constants import (
    SportType,
    SPORT_SLUG_MAP,
    SPORT_TYPE_TO_SLUG,
    ALL_SPORT_TYPES,
    GRID_SEARCH_PARAMS,
    RL_STATE_DIM,
    RL_ACTION_DIM,
    RL_DEFAULT_MODEL_PATH,
)

# -- Sports registry ---------------------------------------------------------
from src.config.sports import (
    LeagueConfig,
    SportConfig,
    SPORTS_REGISTRY,
    SPORTS_CONFIG,           # legacy dict compat
    get_sport_config,
    get_sport_by_id,
    get_leagues_for_sport,
    get_all_sports,
    get_all_league_names,
    resolve_league,
    infer_sport_type,
    resolve_sport_type,
    get_sport_slug,
)

# -- Settings ----------------------------------------------------------------
from src.config.settings import (
    Settings,
    DatabaseSettings,
    ApiKeySettings,
    PatternSettings,
    ModelSettings,
    TrainingSettings,
    DataSettings,
    OutputSettings,
    MonitoringSettings,
    LoggingSettings,
    get_settings,
)

# -- Legacy names (previously in src/config.py) ------------------------------
from src.config._legacy import (
    CRITICAL_THRESHOLDS,
    PATTERN_BREAK_RATES,
    BASE_HOME_WIN_RATE,
    DEFAULT_CONFIG,
    Config,
    setup_logging,
)

# Convenience alias so callers can do ``from src.config import settings``
settings = get_settings()

__all__ = [
    # Constants
    'SportType',
    'SPORT_SLUG_MAP',
    'SPORT_TYPE_TO_SLUG',
    'ALL_SPORT_TYPES',
    'GRID_SEARCH_PARAMS',
    'RL_STATE_DIM',
    'RL_ACTION_DIM',
    'RL_DEFAULT_MODEL_PATH',
    # Sports
    'LeagueConfig',
    'SportConfig',
    'SPORTS_REGISTRY',
    'SPORTS_CONFIG',
    'get_sport_config',
    'get_sport_by_id',
    'get_leagues_for_sport',
    'get_all_sports',
    'get_all_league_names',
    'resolve_league',
    'infer_sport_type',
    'resolve_sport_type',
    'get_sport_slug',
    # Settings
    'Settings',
    'DatabaseSettings',
    'ApiKeySettings',
    'PatternSettings',
    'ModelSettings',
    'TrainingSettings',
    'DataSettings',
    'OutputSettings',
    'MonitoringSettings',
    'LoggingSettings',
    'get_settings',
    'settings',
    # Legacy (from old src/config.py)
    'CRITICAL_THRESHOLDS',
    'PATTERN_BREAK_RATES',
    'BASE_HOME_WIN_RATE',
    'DEFAULT_CONFIG',
    'Config',
    'setup_logging',
]
