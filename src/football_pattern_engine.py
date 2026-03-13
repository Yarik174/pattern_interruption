"""
Backward-compatibility shim.

All logic has moved to ``src.patterns.football``.
This module re-exports the original class names so that existing imports like

    from src.football_pattern_engine import FootballPatternEngine

continue to work without changes.
"""
from src.patterns.football import (
    FootballPatternAnalyzer as FootballPatternEngine,
    BasketballPatternAnalyzer as BasketballPatternEngine,
    VolleyballPatternAnalyzer as VolleyballPatternEngine,
)

__all__ = [
    "FootballPatternEngine",
    "BasketballPatternEngine",
    "VolleyballPatternEngine",
]
