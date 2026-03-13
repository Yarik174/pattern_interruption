"""
Truly constant values that are NOT configurable at runtime.

These are mathematical/domain constants, enum definitions, and
canonical lookup tables. Nothing here should depend on environment
variables or user configuration.
"""
from __future__ import annotations

from enum import Enum
from typing import Final


# ---------------------------------------------------------------------------
# Sport type enum (canonical source - replaces src/sports_config.SportType)
# ---------------------------------------------------------------------------
class SportType(Enum):
    """Sport identifiers matching the FlashLive / API-Sports IDs."""
    FOOTBALL = 1
    TENNIS = 2
    BASKETBALL = 3
    HOCKEY = 4
    VOLLEYBALL = 12


# ---------------------------------------------------------------------------
# Slug <-> SportType mapping (canonical, ONE place)
# ---------------------------------------------------------------------------
SPORT_SLUG_MAP: Final[dict[str, SportType]] = {
    'hockey': SportType.HOCKEY,
    'nhl': SportType.HOCKEY,
    'football': SportType.FOOTBALL,
    'soccer': SportType.FOOTBALL,
    'basketball': SportType.BASKETBALL,
    'volleyball': SportType.VOLLEYBALL,
    'tennis': SportType.TENNIS,
}

SPORT_TYPE_TO_SLUG: Final[dict[SportType, str]] = {
    SportType.HOCKEY: 'hockey',
    SportType.FOOTBALL: 'football',
    SportType.BASKETBALL: 'basketball',
    SportType.VOLLEYBALL: 'volleyball',
    SportType.TENNIS: 'tennis',
}

# Ordered list for iteration (UI display order, monitoring order)
ALL_SPORT_TYPES: Final[tuple[SportType, ...]] = (
    SportType.HOCKEY,
    SportType.FOOTBALL,
    SportType.BASKETBALL,
    SportType.VOLLEYBALL,
)


# ---------------------------------------------------------------------------
# Grid search parameter space (ML model tuning - constant by design)
# ---------------------------------------------------------------------------
GRID_SEARCH_PARAMS: Final[dict[str, list]] = {
    'n_estimators': [50, 100, 200],
    'max_depth': [5, 10, 15, None],
    'min_samples_split': [2, 5, 10],
    'min_samples_leaf': [1, 2, 4],
    'max_features': ['sqrt', 'log2'],
    'class_weight': ['balanced', 'balanced_subsample'],
}


# ---------------------------------------------------------------------------
# RL Agent constants
# ---------------------------------------------------------------------------
RL_STATE_DIM: Final[int] = 8
RL_ACTION_DIM: Final[int] = 2   # SKIP=0, BET=1
RL_DEFAULT_MODEL_PATH: Final[str] = 'models/rl_agent.pth'
