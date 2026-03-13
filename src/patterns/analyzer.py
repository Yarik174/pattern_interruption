"""
Unified pattern analyzer: picks the right sport plugin automatically.
"""
from __future__ import annotations

import logging
from typing import Any

from src.patterns.base import BasePatternAnalyzer
from src.patterns.hockey import HockeyPatternAnalyzer
from src.patterns.football import (
    FootballPatternAnalyzer,
    BasketballPatternAnalyzer,
    VolleyballPatternAnalyzer,
)
from src.patterns.universal import UniversalPatternAnalyzer

logger = logging.getLogger(__name__)


# Sport type string -> analyzer class mapping
_SPORT_ANALYZERS: dict[str, type[BasePatternAnalyzer]] = {
    "hockey": HockeyPatternAnalyzer,
    "football": FootballPatternAnalyzer,
    "basketball": BasketballPatternAnalyzer,
    "volleyball": VolleyballPatternAnalyzer,
}


def get_analyzer(
    sport_type: str,
    **kwargs: Any,
) -> BasePatternAnalyzer:
    """Return the appropriate analyzer instance for *sport_type*.

    Parameters
    ----------
    sport_type:
        One of ``'hockey'``, ``'football'``, ``'basketball'``,
        ``'volleyball'``, or ``'universal'``.
    **kwargs:
        Forwarded to the analyzer constructor.

    Returns
    -------
    BasePatternAnalyzer
        An instance ready for ``analyze_match`` / ``load_matches`` calls.
    """
    sport_key = sport_type.lower().strip()

    if sport_key == "universal":
        return UniversalPatternAnalyzer(**kwargs)

    cls = _SPORT_ANALYZERS.get(sport_key)
    if cls is None:
        logger.warning(
            "Unknown sport_type '%s', falling back to UniversalPatternAnalyzer",
            sport_type,
        )
        return UniversalPatternAnalyzer(**kwargs)

    return cls(**kwargs)


def register_analyzer(
    sport_type: str,
    analyzer_class: type[BasePatternAnalyzer],
) -> None:
    """Register a custom analyzer for a sport type.

    Useful when downstream code introduces a new sport without
    modifying this module.
    """
    _SPORT_ANALYZERS[sport_type.lower().strip()] = analyzer_class
