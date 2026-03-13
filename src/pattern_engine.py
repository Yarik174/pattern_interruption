"""
Backward-compatibility shim.

All logic has moved to ``src.patterns.hockey.HockeyPatternAnalyzer``.
This module re-exports ``PatternEngine`` so that existing imports like

    from src.pattern_engine import PatternEngine

continue to work without changes.
"""
from src.patterns.hockey import HockeyPatternAnalyzer as _HockeyPatternAnalyzer


class PatternEngine(_HockeyPatternAnalyzer):
    """Drop-in wrapper that preserves the original class name.

    ``PatternEngine(critical_thresholds=...)`` works exactly as before.
    Private helpers that tests or external code may call are also
    preserved.
    """

    # -- Backward-compatible private aliases ---------------------------
    # The original class used ``_find_streaks`` returning list[dict];
    # the new base class uses ``find_streaks`` returning list[StreakInfo].
    # We bridge the gap here.

    def _find_streaks(self, result_str):
        return [s.to_dict() for s in self.find_streaks(result_str)]

    def _find_alternations(self, result_str):
        return [a.to_dict() for a in self.find_alternations(result_str)]

    def _find_complex_patterns(self, result_str):
        return [c.to_dict() for c in self.find_complex_patterns(result_str)]

    def _get_alternation_length(self, result_str):
        return self.get_alternation_length(result_str)

    def _current_streak(self, results):
        return self.current_streak(list(results))

    def _check_alternation(self, results):
        return self.check_alternation_ratio(list(results))
