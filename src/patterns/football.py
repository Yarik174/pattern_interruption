"""
Football-specific pattern analyzer (half-totals / goals by half).

Also contains BasketballPatternAnalyzer and VolleyballPatternAnalyzer
which originally lived in ``football_pattern_engine.py``.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from src.patterns.base import BasePatternAnalyzer

logger = logging.getLogger(__name__)


class FootballPatternAnalyzer(BasePatternAnalyzer):
    """Analyse football patterns: first-half / second-half totals.

    Drop-in replacement for ``FootballPatternEngine``.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.team_stats: dict[str, dict[str, dict[str, list[int]]]] = defaultdict(
            lambda: {
                "home": {"fh_goals": [], "sh_goals": [], "total_goals": []},
                "away": {"fh_goals": [], "sh_goals": [], "total_goals": []},
            }
        )
        self.h2h_stats: dict[tuple[str, str], dict[str, list[int]]] = defaultdict(
            lambda: {"fh_goals": [], "sh_goals": [], "total_goals": []}
        )
        self.matches_loaded: int = 0

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_matches(self, matches: list[dict[str, Any]]) -> None:
        for match in matches:
            try:
                home = match.get("home_team", "")
                away = match.get("away_team", "")
                home_fh = match.get("home_score_fh", 0) or 0
                away_fh = match.get("away_score_fh", 0) or 0
                home_total = match.get("home_score", 0) or 0
                away_total = match.get("away_score", 0) or 0

                home_sh = home_total - home_fh
                away_sh = away_total - away_fh
                fh_total = home_fh + away_fh
                sh_total = home_sh + away_sh
                total = home_total + away_total

                self.team_stats[home]["home"]["fh_goals"].append(fh_total)
                self.team_stats[home]["home"]["sh_goals"].append(sh_total)
                self.team_stats[home]["home"]["total_goals"].append(total)

                self.team_stats[away]["away"]["fh_goals"].append(fh_total)
                self.team_stats[away]["away"]["sh_goals"].append(sh_total)
                self.team_stats[away]["away"]["total_goals"].append(total)

                h2h_key = tuple(sorted([home, away]))
                self.h2h_stats[h2h_key]["fh_goals"].append(fh_total)
                self.h2h_stats[h2h_key]["sh_goals"].append(sh_total)
                self.h2h_stats[h2h_key]["total_goals"].append(total)

                self.matches_loaded += 1
            except Exception as e:
                logger.warning("Error loading football match: %s", e)
                continue
        logger.info("FootballPatternAnalyzer: loaded %d matches", self.matches_loaded)

    # ------------------------------------------------------------------
    # Match analysis
    # ------------------------------------------------------------------

    def analyze_match(self, home_team: str, away_team: str, **kwargs: Any) -> dict[str, Any]:
        """Analyse upcoming football match for half-total patterns."""
        patterns: list[dict[str, Any]] = []
        recommendations: dict[str, float] = {}

        home_stats = self.team_stats.get(home_team, {}).get("home", {})
        away_stats = self.team_stats.get(away_team, {}).get("away", {})

        h2h_key = tuple(sorted([home_team, away_team]))
        h2h = self.h2h_stats.get(h2h_key, {})

        fh_analysis = self._analyze_half(home_stats, away_stats, h2h, "fh")
        sh_analysis = self._analyze_half(home_stats, away_stats, h2h, "sh")

        # First half recommendations
        if fh_analysis["avg"] is not None:
            if fh_analysis["over_0_5_pct"] >= 0.75:
                patterns.append({
                    "type": "FH_O0.5",
                    "description": f"First half goals in {fh_analysis['over_0_5_pct']*100:.0f}% of matches",
                    "confidence": fh_analysis["over_0_5_pct"],
                })
                recommendations["FH_O0.5"] = fh_analysis["over_0_5_pct"]
            elif fh_analysis["over_0_5_pct"] <= 0.35:
                patterns.append({
                    "type": "FH_U0.5",
                    "description": f"Scoreless first half in {(1-fh_analysis['over_0_5_pct'])*100:.0f}% of matches",
                    "confidence": 1 - fh_analysis["over_0_5_pct"],
                })
                recommendations["FH_U0.5"] = 1 - fh_analysis["over_0_5_pct"]

            if fh_analysis["over_1_5_pct"] >= 0.60:
                patterns.append({
                    "type": "FH_O1.5",
                    "description": f"2+ goals in first half in {fh_analysis['over_1_5_pct']*100:.0f}% of matches",
                    "confidence": fh_analysis["over_1_5_pct"],
                })
                recommendations["FH_O1.5"] = fh_analysis["over_1_5_pct"]
            elif fh_analysis["over_1_5_pct"] <= 0.25:
                patterns.append({
                    "type": "FH_U1.5",
                    "description": f"Under 2 goals in first half in {(1-fh_analysis['over_1_5_pct'])*100:.0f}% of matches",
                    "confidence": 1 - fh_analysis["over_1_5_pct"],
                })
                recommendations["FH_U1.5"] = 1 - fh_analysis["over_1_5_pct"]

        # Second half recommendations
        if sh_analysis["avg"] is not None:
            if sh_analysis["over_0_5_pct"] >= 0.80:
                patterns.append({
                    "type": "SH_O0.5",
                    "description": f"Second half goals in {sh_analysis['over_0_5_pct']*100:.0f}% of matches",
                    "confidence": sh_analysis["over_0_5_pct"],
                })
                recommendations["SH_O0.5"] = sh_analysis["over_0_5_pct"]
            elif sh_analysis["over_0_5_pct"] <= 0.30:
                patterns.append({
                    "type": "SH_U0.5",
                    "description": f"Scoreless second half in {(1-sh_analysis['over_0_5_pct'])*100:.0f}% of matches",
                    "confidence": 1 - sh_analysis["over_0_5_pct"],
                })
                recommendations["SH_U0.5"] = 1 - sh_analysis["over_0_5_pct"]

            if sh_analysis["over_1_5_pct"] >= 0.55:
                patterns.append({
                    "type": "SH_O1.5",
                    "description": f"2+ goals in second half in {sh_analysis['over_1_5_pct']*100:.0f}% of matches",
                    "confidence": sh_analysis["over_1_5_pct"],
                })
                recommendations["SH_O1.5"] = sh_analysis["over_1_5_pct"]

        # H2H specials
        if h2h.get("fh_goals"):
            h2h_fh_avg = sum(h2h["fh_goals"]) / len(h2h["fh_goals"])
            if h2h_fh_avg >= 1.5:
                patterns.append({
                    "type": "H2H_FH_HIGH",
                    "description": f"H2H average {h2h_fh_avg:.1f} first-half goals",
                    "confidence": min(0.9, h2h_fh_avg / 2),
                })

        best_bet = max(recommendations.items(), key=lambda x: x[1]) if recommendations else None

        return {
            "patterns": patterns,
            "recommendations": recommendations,
            "best_bet": best_bet[0] if best_bet else None,
            "best_confidence": best_bet[1] if best_bet else 0,
            "fh_analysis": fh_analysis,
            "sh_analysis": sh_analysis,
            "h2h_matches": len(h2h.get("fh_goals", [])),
        }

    # ------------------------------------------------------------------
    # Half analysis helper
    # ------------------------------------------------------------------

    def _analyze_half(
        self,
        home_stats: dict[str, Any],
        away_stats: dict[str, Any],
        h2h: dict[str, Any],
        half: str,
    ) -> dict[str, Any]:
        key = f"{half}_goals"
        all_goals: list[int] = []

        if home_stats.get(key):
            all_goals.extend(home_stats[key][-10:])
        if away_stats.get(key):
            all_goals.extend(away_stats[key][-10:])

        if not all_goals:
            return {"avg": None, "over_0_5_pct": 0.5, "over_1_5_pct": 0.3}

        avg = sum(all_goals) / len(all_goals)
        over_0_5 = sum(1 for g in all_goals if g > 0) / len(all_goals)
        over_1_5 = sum(1 for g in all_goals if g > 1) / len(all_goals)
        return {
            "avg": avg,
            "over_0_5_pct": over_0_5,
            "over_1_5_pct": over_1_5,
            "sample_size": len(all_goals),
        }

    # ------------------------------------------------------------------
    # Team stats accessor
    # ------------------------------------------------------------------

    def get_team_stats(self, team: str) -> dict[str, Any]:
        stats = self.team_stats.get(team, {})
        result: dict[str, Any] = {"home": {}, "away": {}}
        for location in ("home", "away"):
            loc_stats = stats.get(location, {})
            fh = loc_stats.get("fh_goals", [])
            sh = loc_stats.get("sh_goals", [])
            total = loc_stats.get("total_goals", [])
            if fh:
                result[location] = {
                    "matches": len(fh),
                    "avg_fh_goals": sum(fh) / len(fh),
                    "avg_sh_goals": sum(sh) / len(sh) if sh else 0,
                    "avg_total_goals": sum(total) / len(total) if total else 0,
                    "fh_over_0_5_pct": sum(1 for g in fh if g > 0) / len(fh),
                    "fh_over_1_5_pct": sum(1 for g in fh if g > 1) / len(fh),
                }
        return result


# ======================================================================
# Basketball
# ======================================================================

class BasketballPatternAnalyzer(BasePatternAnalyzer):
    """Analyse basketball win/loss patterns with streak detection.

    Drop-in replacement for ``BasketballPatternEngine``.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.team_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "home": {"wins": 0, "losses": 0, "points_for": [], "points_against": []},
            "away": {"wins": 0, "losses": 0, "points_for": [], "points_against": []},
        })
        self.recent_form: dict[str, list[str]] = defaultdict(list)
        self.h2h: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        self.matches_loaded: int = 0

    def load_matches(self, matches: list[dict[str, Any]]) -> None:
        for match in matches:
            try:
                home = match.get("home_team", "")
                away = match.get("away_team", "")
                home_score = match.get("home_score", 0) or 0
                away_score = match.get("away_score", 0) or 0

                if home_score > away_score:
                    self.team_stats[home]["home"]["wins"] += 1
                    self.team_stats[away]["away"]["losses"] += 1
                    self.recent_form[home].append("W")
                    self.recent_form[away].append("L")
                else:
                    self.team_stats[home]["home"]["losses"] += 1
                    self.team_stats[away]["away"]["wins"] += 1
                    self.recent_form[home].append("L")
                    self.recent_form[away].append("W")

                self.team_stats[home]["home"]["points_for"].append(home_score)
                self.team_stats[home]["home"]["points_against"].append(away_score)
                self.team_stats[away]["away"]["points_for"].append(away_score)
                self.team_stats[away]["away"]["points_against"].append(home_score)

                h2h_key = tuple(sorted([home, away]))
                self.h2h[h2h_key].append({
                    "home": home,
                    "away": away,
                    "home_score": home_score,
                    "away_score": away_score,
                    "winner": home if home_score > away_score else away,
                })
                self.matches_loaded += 1
            except Exception as e:
                logger.warning("Error loading basketball match: %s", e)
                continue
        logger.info("BasketballPatternAnalyzer: loaded %d matches", self.matches_loaded)

    def _build_team_pattern(self, team: str) -> dict[str, Any]:
        """Build a pattern dict from recent_form for CPP prediction.

        Returns dict with keys expected by get_cpp_prediction:
        overall_streak, overall_critical, home_streak, home_critical,
        away_streak, away_critical, alt_critical, overall_alt.
        """
        form = self.recent_form.get(team, [])
        result_str = "".join(form[-20:])  # last 20 games

        overall_streak = self.current_streak(form[-20:])
        overall_alt = self.get_alternation_length(result_str)

        streak_threshold = self.thresholds.get("overall_streak", 5)
        home_threshold = self.thresholds.get("home_streak", 4)
        away_threshold = self.thresholds.get("away_streak", 3)
        alt_threshold = self.thresholds.get("alternation", 6)

        return {
            "overall_streak": overall_streak,
            "overall_critical": abs(overall_streak) >= streak_threshold,
            "home_streak": overall_streak,  # approximation from overall
            "home_critical": abs(overall_streak) >= home_threshold,
            "away_streak": overall_streak,
            "away_critical": abs(overall_streak) >= away_threshold,
            "alt_critical": overall_alt >= alt_threshold,
            "overall_alt": overall_alt,
        }

    def analyze_match(self, home_team: str, away_team: str, **kwargs: Any) -> dict[str, Any]:
        """Pattern interruption analysis for basketball.

        Uses streak/alternation/synergy detection from BasePatternAnalyzer
        and CPP prediction: bet AGAINST the pattern when synergy >= 2.
        """
        home_pattern = self._build_team_pattern(home_team)
        away_pattern = self._build_team_pattern(away_team)

        cpp = self.get_cpp_prediction(home_pattern, away_pattern)
        cpp_prob = self.estimate_cpp_probability(cpp.patterns, cpp.synergy)

        home_score = self.calc_strong_signal(home_pattern)
        away_score = self.calc_strong_signal(away_pattern)

        # Build human-readable pattern descriptions
        patterns: list[dict[str, Any]] = []
        for p in cpp.patterns:
            patterns.append({
                "type": p["type"],
                "description": p["reason"],
                "length": p.get("length", 0),
                "confidence": cpp_prob,
            })

        # CPP decision: bet recommendation only when synergy >= 2
        bet_on = cpp.team  # "home", "away", or None
        confidence = cpp_prob if bet_on else 0.0

        # Winrate stats for context (not for decision-making)
        home_home = self.team_stats.get(home_team, {}).get("home", {})
        away_away = self.team_stats.get(away_team, {}).get("away", {})
        total_hh = home_home.get("wins", 0) + home_home.get("losses", 0)
        total_aa = away_away.get("wins", 0) + away_away.get("losses", 0)
        home_win_pct = home_home["wins"] / total_hh if total_hh > 0 else 0.5
        away_win_pct = away_away["wins"] / total_aa if total_aa > 0 else 0.5

        h2h_key = tuple(sorted([home_team, away_team]))
        h2h_matches = self.h2h.get(h2h_key, [])

        return {
            "patterns": patterns,
            "bet_on": bet_on,
            "predicted_team": (home_team if bet_on == "home" else away_team) if bet_on else None,
            "confidence": confidence,
            "home_win_pct": home_win_pct,
            "away_win_pct": away_win_pct,
            "home_streak": home_pattern["overall_streak"],
            "away_streak": away_pattern["overall_streak"],
            "h2h_matches": len(h2h_matches),
            "cpp_prediction": cpp.to_dict(),
            "synergy": cpp.synergy,
            "home_pattern": home_pattern,
            "away_pattern": away_pattern,
            "home_signal_score": home_score,
            "away_signal_score": away_score,
        }


# ======================================================================
# Volleyball
# ======================================================================

class VolleyballPatternAnalyzer(BasePatternAnalyzer):
    """Analyse volleyball win/loss patterns (sets, tiebreaks).

    Drop-in replacement for ``VolleyballPatternEngine``.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.team_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "home": {"wins": 0, "losses": 0, "sets_won": 0, "sets_lost": 0},
            "away": {"wins": 0, "losses": 0, "sets_won": 0, "sets_lost": 0},
        })
        self.tiebreak_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"wins": 0, "total": 0}
        )
        self.recent_form: dict[str, list[str]] = defaultdict(list)
        self.matches_loaded: int = 0

    def load_matches(self, matches: list[dict[str, Any]]) -> None:
        for match in matches:
            try:
                home = match.get("home_team", "")
                away = match.get("away_team", "")
                home_sets = match.get("home_sets", 0) or 0
                away_sets = match.get("away_sets", 0) or 0
                is_tiebreak = (home_sets + away_sets) == 5

                if home_sets > away_sets:
                    self.team_stats[home]["home"]["wins"] += 1
                    self.team_stats[away]["away"]["losses"] += 1
                    self.recent_form[home].append("W")
                    self.recent_form[away].append("L")
                    if is_tiebreak:
                        self.tiebreak_stats[home]["wins"] += 1
                else:
                    self.team_stats[home]["home"]["losses"] += 1
                    self.team_stats[away]["away"]["wins"] += 1
                    self.recent_form[home].append("L")
                    self.recent_form[away].append("W")
                    if is_tiebreak:
                        self.tiebreak_stats[away]["wins"] += 1

                if is_tiebreak:
                    self.tiebreak_stats[home]["total"] += 1
                    self.tiebreak_stats[away]["total"] += 1

                self.team_stats[home]["home"]["sets_won"] += home_sets
                self.team_stats[home]["home"]["sets_lost"] += away_sets
                self.team_stats[away]["away"]["sets_won"] += away_sets
                self.team_stats[away]["away"]["sets_lost"] += home_sets

                self.matches_loaded += 1
            except Exception as e:
                logger.warning("Error loading volleyball match: %s", e)
                continue
        logger.info("VolleyballPatternAnalyzer: loaded %d matches", self.matches_loaded)

    def _build_team_pattern(self, team: str) -> dict[str, Any]:
        """Build pattern dict from recent_form for CPP prediction."""
        form = self.recent_form.get(team, [])
        result_str = "".join(form[-20:])

        overall_streak = self.current_streak(form[-20:])
        overall_alt = self.get_alternation_length(result_str)

        streak_threshold = self.thresholds.get("overall_streak", 5)
        home_threshold = self.thresholds.get("home_streak", 4)
        away_threshold = self.thresholds.get("away_streak", 3)
        alt_threshold = self.thresholds.get("alternation", 6)

        return {
            "overall_streak": overall_streak,
            "overall_critical": abs(overall_streak) >= streak_threshold,
            "home_streak": overall_streak,
            "home_critical": abs(overall_streak) >= home_threshold,
            "away_streak": overall_streak,
            "away_critical": abs(overall_streak) >= away_threshold,
            "alt_critical": overall_alt >= alt_threshold,
            "overall_alt": overall_alt,
        }

    def analyze_match(self, home_team: str, away_team: str, **kwargs: Any) -> dict[str, Any]:
        """Pattern interruption analysis for volleyball.

        Uses streak/alternation/synergy detection from BasePatternAnalyzer
        and CPP prediction: bet AGAINST the pattern when synergy >= 2.
        """
        home_pattern = self._build_team_pattern(home_team)
        away_pattern = self._build_team_pattern(away_team)

        cpp = self.get_cpp_prediction(home_pattern, away_pattern)
        cpp_prob = self.estimate_cpp_probability(cpp.patterns, cpp.synergy)

        home_score = self.calc_strong_signal(home_pattern)
        away_score = self.calc_strong_signal(away_pattern)

        patterns: list[dict[str, Any]] = []
        for p in cpp.patterns:
            patterns.append({
                "type": p["type"],
                "description": p["reason"],
                "length": p.get("length", 0),
                "confidence": cpp_prob,
            })

        bet_on = cpp.team
        confidence = cpp_prob if bet_on else 0.0

        # Winrate stats for context only
        home_stats = self.team_stats.get(home_team, {}).get("home", {})
        away_stats = self.team_stats.get(away_team, {}).get("away", {})
        total_home = home_stats.get("wins", 0) + home_stats.get("losses", 0)
        total_away = away_stats.get("wins", 0) + away_stats.get("losses", 0)
        home_win_pct = home_stats["wins"] / total_home if total_home > 0 else 0.5
        away_win_pct = away_stats["wins"] / total_away if total_away > 0 else 0.5

        return {
            "patterns": patterns,
            "bet_on": bet_on,
            "predicted_team": (home_team if bet_on == "home" else away_team) if bet_on else None,
            "confidence": confidence,
            "home_win_pct": home_win_pct,
            "away_win_pct": away_win_pct,
            "home_streak": home_pattern["overall_streak"],
            "away_streak": away_pattern["overall_streak"],
            "cpp_prediction": cpp.to_dict(),
            "synergy": cpp.synergy,
            "home_pattern": home_pattern,
            "away_pattern": away_pattern,
            "home_signal_score": home_score,
            "away_signal_score": away_score,
        }
