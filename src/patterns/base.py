"""
Base pattern analyzer: abstract class and shared data structures.

All sport-specific engines inherit from BasePatternAnalyzer, which
provides the core streak / alternation / CPP detection logic that was
previously duplicated across pattern_engine.py,
multi_league_predictor.py and football_pattern_engine.py.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from src.config import CRITICAL_THRESHOLDS, PATTERN_BREAK_RATES, BASE_HOME_WIN_RATE

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StreakInfo:
    """A single streak (consecutive identical outcomes)."""
    pattern: str
    length: int
    position: int
    next_result: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "length": self.length,
            "position": self.position,
            "next_result": self.next_result,
        }


@dataclass
class AlternationInfo:
    """A single alternation sequence (W-L-W-L ...)."""
    pattern: str
    length: int
    position: int
    next_result: str | None = None
    broke: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "length": self.length,
            "position": self.position,
            "next_result": self.next_result,
            "broke": self.broke,
        }


@dataclass
class ComplexPatternInfo:
    """A repeating block pattern (e.g. WL repeated 3+ times)."""
    pattern: str
    length: int
    repetitions: int
    position: int
    unit: str
    next_result: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "length": self.length,
            "repetitions": self.repetitions,
            "position": self.position,
            "unit": self.unit,
            "next_result": self.next_result,
        }


@dataclass
class PatternResult:
    """Container returned by :pymethod:`analyze_match` implementations."""
    team: str | None = None
    teams: tuple[str, str] | None = None
    pattern_type: str = ""
    pattern: str = ""
    length: int = 0
    critical: bool = False
    position: int = 0
    next_result: str | None = None
    confidence: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": self.pattern_type,
            "pattern": self.pattern,
            "length": self.length,
            "critical": self.critical,
            "position": self.position,
            "next_result": self.next_result,
            "confidence": self.confidence,
        }
        if self.team is not None:
            d["team"] = self.team
        if self.teams is not None:
            d["teams"] = self.teams
        d.update(self.extra)
        return d


@dataclass
class CppPrediction:
    """Result of CPP (Critical Pattern Prediction) analysis."""
    team: str | None = None
    synergy: int = 0
    patterns: list[dict[str, Any]] = field(default_factory=list)
    home_synergy: int = 0
    away_synergy: int = 0
    home_patterns: list[dict[str, Any]] = field(default_factory=list)
    away_patterns: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "team": self.team,
            "synergy": self.synergy,
            "patterns": self.patterns,
            "home_synergy": self.home_synergy,
            "away_synergy": self.away_synergy,
            "home_patterns": self.home_patterns,
            "away_patterns": self.away_patterns,
        }


# ---------------------------------------------------------------------------
# Default pattern weights (used in CPP probability estimation)
# ---------------------------------------------------------------------------

DEFAULT_PATTERN_WEIGHTS: dict[str, float] = {
    "overall_alternation": 1.3,
    "home_alternation": 1.2,
    "overall_streak": 1.0,
    "home_streak": 0.9,
    "h2h_streak": 0.9,
    "away_streak": 0.5,
    "h2h_alternation": 0.8,
    "away_alternation": 0.6,
}


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class BasePatternAnalyzer(ABC):
    """Core pattern-detection logic shared by every sport engine.

    Sub-classes only need to implement :pymethod:`analyze_match` (and
    optionally :pymethod:`load_matches`) to specialise for a sport.
    """

    def __init__(
        self,
        thresholds: dict[str, int] | None = None,
        break_rates: dict[str, float] | None = None,
        base_home_win_rate: float | None = None,
        pattern_weights: dict[str, float] | None = None,
    ) -> None:
        self.thresholds: dict[str, int] = dict(thresholds or CRITICAL_THRESHOLDS)
        self.break_rates: dict[str, float] = dict(break_rates or PATTERN_BREAK_RATES)
        self.base_home_win_rate: float = (
            base_home_win_rate if base_home_win_rate is not None else BASE_HOME_WIN_RATE
        )
        self.pattern_weights: dict[str, float] = dict(
            pattern_weights or DEFAULT_PATTERN_WEIGHTS
        )

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def analyze_match(
        self, home_team: str, away_team: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Return analysis dict for an upcoming match."""
        ...

    # ------------------------------------------------------------------
    # Streak detection
    # ------------------------------------------------------------------

    def find_streaks(self, result_str: str, min_length: int = 3) -> list[StreakInfo]:
        """Find all runs of identical characters >= *min_length*.

        Reproduces the logic from ``PatternEngine._find_streaks`` and
        ``MultiLeaguePatternEngine._calc_streak`` but returns structured
        :class:`StreakInfo` objects.
        """
        streaks: list[StreakInfo] = []
        i = 0
        while i < len(result_str):
            char = result_str[i]
            streak_len = 1
            while (
                i + streak_len < len(result_str)
                and result_str[i + streak_len] == char
            ):
                streak_len += 1

            if streak_len >= min_length:
                next_result = (
                    result_str[i + streak_len]
                    if i + streak_len < len(result_str)
                    else None
                )
                streaks.append(
                    StreakInfo(
                        pattern=char * streak_len,
                        length=streak_len,
                        position=i,
                        next_result=next_result,
                    )
                )
            i += streak_len
        return streaks

    def current_streak(self, results: list[int] | list[str]) -> int:
        """Return the current streak at the tail of *results*.

        For numeric lists (0/1), a positive value means wins, negative
        means losses.  For string lists (``'W'``/``'L'``), positive
        means the last element was ``'W'``.
        """
        if not results:
            return 0

        last = results[-1]
        streak = 1
        for i in range(len(results) - 2, -1, -1):
            if results[i] == last:
                streak += 1
            else:
                break

        if isinstance(last, str):
            return streak if last == "W" else -streak
        return streak if last == 1 else -streak

    # ------------------------------------------------------------------
    # Alternation detection
    # ------------------------------------------------------------------

    def find_alternations(
        self, result_str: str, min_length: int = 4
    ) -> list[AlternationInfo]:
        """Detect W-L-W-L style alternating runs >= *min_length*.

        Reproduces ``PatternEngine._find_alternations``.
        """
        alternations: list[AlternationInfo] = []
        for i in range(len(result_str) - (min_length - 1)):
            if result_str[i] == result_str[i + 1]:
                continue  # not alternating at this position
            alt_len = 2
            is_alternating = True
            while i + alt_len < len(result_str) and is_alternating:
                expected = (
                    result_str[i] if alt_len % 2 == 0 else result_str[i + 1]
                )
                if result_str[i + alt_len] == expected:
                    alt_len += 1
                else:
                    is_alternating = False

            if alt_len >= min_length:
                next_result = (
                    result_str[i + alt_len]
                    if i + alt_len < len(result_str)
                    else None
                )
                alternations.append(
                    AlternationInfo(
                        pattern=result_str[i : i + alt_len],
                        length=alt_len,
                        position=i,
                        next_result=next_result,
                        broke=(
                            next_result is not None
                            and next_result == result_str[i + alt_len - 1]
                        ),
                    )
                )
        return alternations

    def get_alternation_length(self, result_str: str) -> int:
        """Return the length of the trailing alternation (0 if < 4).

        Reproduces ``PatternEngine._get_alternation_length``.
        """
        if len(result_str) < 4:
            return 0
        alt_len = 1
        for i in range(len(result_str) - 2, -1, -1):
            if result_str[i] != result_str[i + 1]:
                alt_len += 1
            else:
                break
        return alt_len if alt_len >= 4 else 0

    def check_alternation(self, results: list[str] | list[int]) -> int:
        """Return trailing alternation count (from the end, breaking on repeat).

        Reproduces ``MultiLeaguePatternEngine._check_alternation``.
        """
        if len(results) < 4:
            return 0
        alt_count = 0
        for i in range(len(results) - 1, 0, -1):
            if results[i] != results[i - 1]:
                alt_count += 1
            else:
                break
        return alt_count

    def check_alternation_ratio(self, results: list[int]) -> int:
        """Return the length if alternation ratio >= 0.8, else 0.

        Reproduces ``PatternEngine._check_alternation`` (the ratio-based
        variant used in the original hockey engine).
        """
        if len(results) < 4:
            return 0
        alt_count = sum(
            1 for i in range(1, len(results)) if results[i] != results[i - 1]
        )
        alt_ratio = alt_count / (len(results) - 1)
        return len(results) if alt_ratio >= 0.8 else 0

    # ------------------------------------------------------------------
    # Complex / repeating-unit patterns
    # ------------------------------------------------------------------

    def find_complex_patterns(
        self, result_str: str, unit_lengths: tuple[int, ...] = (2, 3), min_reps: int = 3
    ) -> list[ComplexPatternInfo]:
        """Find repeating block patterns (e.g. ``WL`` x 3).

        Reproduces ``PatternEngine._find_complex_patterns``.
        """
        patterns: list[ComplexPatternInfo] = []
        for unit_len in unit_lengths:
            if len(result_str) < unit_len * min_reps:
                continue
            for start in range(len(result_str) - unit_len * 2):
                unit = result_str[start : start + unit_len]
                repetitions = 1
                pos = start + unit_len
                while (
                    pos + unit_len <= len(result_str)
                    and result_str[pos : pos + unit_len] == unit
                ):
                    repetitions += 1
                    pos += unit_len

                total_games = unit_len * repetitions
                if repetitions >= min_reps:
                    pattern_end = start + total_games
                    next_result = (
                        result_str[pattern_end]
                        if pattern_end < len(result_str)
                        else None
                    )
                    patterns.append(
                        ComplexPatternInfo(
                            pattern=unit,
                            length=total_games,
                            repetitions=repetitions,
                            position=start,
                            unit=unit,
                            next_result=next_result,
                        )
                    )
        return patterns

    # ------------------------------------------------------------------
    # CPP (Critical Pattern Prediction)
    # ------------------------------------------------------------------

    def get_cpp_prediction(
        self,
        home_pattern: dict[str, Any],
        away_pattern: dict[str, Any],
    ) -> CppPrediction:
        """Analyse CPP for a match given team pattern dicts.

        CPP logic:
        - Streak at critical length -> interruption -> OPPOSITE result
        - Alternation at critical length -> interruption -> REPEAT last

        Reproduces ``MultiLeaguePatternEngine.get_cpp_prediction``.
        """
        home_predictions: list[dict[str, Any]] = []
        away_predictions: list[dict[str, Any]] = []

        # --- Home team patterns ---
        overall_streak = home_pattern.get("overall_streak", 0)
        if home_pattern.get("overall_critical"):
            if overall_streak > 0:
                away_predictions.append({
                    "type": "overall_streak",
                    "length": abs(overall_streak),
                    "value": overall_streak,
                    "reason": f"Interruption of home win streak ({overall_streak})",
                })
            elif overall_streak < 0:
                home_predictions.append({
                    "type": "overall_streak",
                    "length": abs(overall_streak),
                    "value": overall_streak,
                    "reason": f"Interruption of home loss streak ({overall_streak})",
                })

        home_streak = home_pattern.get("home_streak", 0)
        if home_pattern.get("home_critical"):
            if home_streak > 0:
                away_predictions.append({
                    "type": "home_streak",
                    "length": abs(home_streak),
                    "value": home_streak,
                    "reason": f"Interruption of home-ice win streak ({home_streak})",
                })
            elif home_streak < 0:
                home_predictions.append({
                    "type": "home_streak",
                    "length": abs(home_streak),
                    "value": home_streak,
                    "reason": f"Interruption of home-ice loss streak ({home_streak})",
                })

        if home_pattern.get("alt_critical"):
            last_result = "W" if overall_streak > 0 else "L"
            alt_len = home_pattern.get("overall_alt", 0)
            if last_result == "W":
                home_predictions.append({
                    "type": "overall_alternation",
                    "length": alt_len,
                    "value": alt_len,
                    "reason": "Interruption of home alternation (last W, repeat)",
                })
            else:
                away_predictions.append({
                    "type": "overall_alternation",
                    "length": alt_len,
                    "value": alt_len,
                    "reason": "Interruption of home alternation (last L, repeat)",
                })

        # --- Away team patterns ---
        away_overall_streak = away_pattern.get("overall_streak", 0)
        if away_pattern.get("overall_critical"):
            if away_overall_streak > 0:
                home_predictions.append({
                    "type": "overall_streak",
                    "length": abs(away_overall_streak),
                    "value": away_overall_streak,
                    "reason": f"Interruption of away win streak ({away_overall_streak})",
                })
            elif away_overall_streak < 0:
                away_predictions.append({
                    "type": "overall_streak",
                    "length": abs(away_overall_streak),
                    "value": away_overall_streak,
                    "reason": f"Interruption of away loss streak ({away_overall_streak})",
                })

        away_away_streak = away_pattern.get("away_streak", 0)
        if away_pattern.get("away_critical"):
            if away_away_streak > 0:
                home_predictions.append({
                    "type": "away_streak",
                    "length": abs(away_away_streak),
                    "value": away_away_streak,
                    "reason": f"Interruption of road win streak ({away_away_streak})",
                })
            elif away_away_streak < 0:
                away_predictions.append({
                    "type": "away_streak",
                    "length": abs(away_away_streak),
                    "value": away_away_streak,
                    "reason": f"Interruption of road loss streak ({away_away_streak})",
                })

        if away_pattern.get("alt_critical"):
            last_result = "W" if away_overall_streak > 0 else "L"
            alt_len = away_pattern.get("overall_alt", 0)
            if last_result == "W":
                away_predictions.append({
                    "type": "away_alternation",
                    "length": alt_len,
                    "value": alt_len,
                    "reason": "Interruption of away alternation (last W, repeat)",
                })
            else:
                home_predictions.append({
                    "type": "away_alternation",
                    "length": alt_len,
                    "value": alt_len,
                    "reason": "Interruption of away alternation (last L, repeat)",
                })

        home_synergy = len(home_predictions)
        away_synergy = len(away_predictions)

        if home_synergy > away_synergy:
            predicted_team = "home"
            synergy = home_synergy
            patterns = home_predictions
        elif away_synergy > home_synergy:
            predicted_team = "away"
            synergy = away_synergy
            patterns = away_predictions
        elif home_synergy > 0:
            predicted_team = "home" if home_synergy >= away_synergy else "away"
            synergy = max(home_synergy, away_synergy)
            patterns = (
                home_predictions if home_synergy >= away_synergy else away_predictions
            )
        else:
            predicted_team = None
            synergy = 0
            patterns = []

        return CppPrediction(
            team=predicted_team,
            synergy=synergy,
            patterns=patterns,
            home_synergy=home_synergy,
            away_synergy=away_synergy,
            home_patterns=home_predictions,
            away_patterns=away_predictions,
        )

    # ------------------------------------------------------------------
    # Signal strength scoring
    # ------------------------------------------------------------------

    def calc_strong_signal(self, team_pattern: dict[str, Any]) -> int:
        """Compute an integer *signal score* for a team pattern dict.

        Reproduces ``MultiLeaguePatternEngine.calc_strong_signal``.
        """
        score = 0
        if team_pattern.get("overall_critical"):
            score += 1
        if team_pattern.get("home_critical"):
            score += 1
        if team_pattern.get("away_critical"):
            score += 1
        if team_pattern.get("alt_critical"):
            score += 1

        synergy = sum([
            team_pattern.get("overall_critical", False),
            team_pattern.get("home_critical", False),
            team_pattern.get("away_critical", False),
        ])
        if synergy >= 2:
            score += 1

        streak = abs(team_pattern.get("overall_streak", 0))
        if streak >= 8:
            score += 2
        elif streak >= 6:
            score += 1

        return score

    # ------------------------------------------------------------------
    # CPP probability estimation
    # ------------------------------------------------------------------

    def estimate_cpp_probability(
        self, patterns: list[dict[str, Any]], synergy: int
    ) -> float:
        """Weighted break probability from real pattern weights.

        Reproduces ``MultiLeaguePatternEngine._estimate_cpp_probability``.
        """
        if synergy < 2 or not patterns:
            return 0.5

        total_weight = 0.0
        weighted_prob = 0.0

        for p in patterns:
            pattern_type = p.get("type", "overall_streak")
            length = p.get("length", 5)

            base_rate = self.break_rates.get(pattern_type, 0.5)
            threshold = self.thresholds.get(pattern_type, 5)
            excess = max(0, length - threshold)
            adjusted_rate = min(base_rate + excess * 0.015, 0.75)

            weight = self.pattern_weights.get(pattern_type, 1.0)
            weighted_prob += adjusted_rate * weight
            total_weight += weight

        if total_weight > 0:
            raw_prob = weighted_prob / total_weight
            return 0.6 * raw_prob + 0.4 * (1 - self.base_home_win_rate)
        return 0.5

    # ------------------------------------------------------------------
    # Synergy helpers
    # ------------------------------------------------------------------

    def get_synergy_details(
        self,
        home_pattern: dict[str, Any],
        away_pattern: dict[str, Any],
    ) -> dict[str, Any]:
        """Synergy details for both teams.

        Reproduces ``MultiLeaguePatternEngine.get_synergy_details``.
        """
        cpp = self.get_cpp_prediction(home_pattern, away_pattern)

        active_patterns: list[dict[str, Any]] = []
        for p in cpp.home_patterns:
            active_patterns.append({
                "pattern": p["type"],
                "value": p["value"],
                "direction": "home",
                "reason": p["reason"],
            })
        for p in cpp.away_patterns:
            active_patterns.append({
                "pattern": p["type"],
                "value": p["value"],
                "direction": "away",
                "reason": p["reason"],
            })

        bet_recommendation = None
        if cpp.synergy >= 2:
            bet_recommendation = cpp.team

        return {
            "active_patterns": active_patterns,
            "home_synergy": cpp.home_synergy,
            "away_synergy": cpp.away_synergy,
            "bet_recommendation": bet_recommendation,
            "total_critical": len(active_patterns),
        }
