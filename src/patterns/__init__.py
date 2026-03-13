"""
Unified pattern analysis package.

Re-exports the main classes so callers can write:

    from src.patterns import HockeyPatternAnalyzer, get_analyzer
"""
from src.patterns.base import (
    AlternationInfo,
    BasePatternAnalyzer,
    ComplexPatternInfo,
    CppPrediction,
    PatternResult,
    StreakInfo,
)
from src.patterns.hockey import HockeyPatternAnalyzer
from src.patterns.football import (
    BasketballPatternAnalyzer,
    FootballPatternAnalyzer,
    VolleyballPatternAnalyzer,
)
from src.patterns.universal import UniversalPatternAnalyzer
from src.patterns.analyzer import get_analyzer, register_analyzer

__all__ = [
    # Data classes
    "AlternationInfo",
    "ComplexPatternInfo",
    "CppPrediction",
    "PatternResult",
    "StreakInfo",
    # Base
    "BasePatternAnalyzer",
    # Sport plugins
    "HockeyPatternAnalyzer",
    "FootballPatternAnalyzer",
    "BasketballPatternAnalyzer",
    "VolleyballPatternAnalyzer",
    "UniversalPatternAnalyzer",
    # Factory
    "get_analyzer",
    "register_analyzer",
]
