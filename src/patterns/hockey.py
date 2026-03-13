"""
Hockey-specific pattern analyzer.

Preserves the full public API of the original ``PatternEngine`` so that
callers like ``feature_builder.py``, ``app.py`` and ``main.py`` keep
working without any changes.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd

from src.patterns.base import (
    BasePatternAnalyzer,
    PatternResult,
)

logger = logging.getLogger(__name__)


class HockeyPatternAnalyzer(BasePatternAnalyzer):
    """Hockey-specific pattern engine.

    Drop-in replacement for the original ``PatternEngine``.  Every
    public method that existed on ``PatternEngine`` is present here
    with identical signatures and return shapes.
    """

    def __init__(
        self,
        critical_thresholds: dict[str, int] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(thresholds=critical_thresholds, **kwargs)
        self.patterns: dict[str, list[Any]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Main analysis entry-point
    # ------------------------------------------------------------------

    def analyze_all_patterns(self, games_df: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
        """Analyse home/away/h2h/alternation patterns over a DataFrame.

        Returns the same ``dict[str, list[dict]]`` that the original
        ``PatternEngine.analyze_all_patterns`` returned.
        """
        print("\n\U0001f50d Анализ паттернов...")
        print("=" * 50)

        home_patterns = self._analyze_home_patterns(games_df)
        away_patterns = self._analyze_away_patterns(games_df)
        h2h_patterns = self._analyze_head_to_head_patterns(games_df)
        alternation_patterns = self._analyze_alternation_patterns(games_df)

        all_patterns: dict[str, list[dict[str, Any]]] = {
            "home": home_patterns,
            "away": away_patterns,
            "head_to_head": h2h_patterns,
            "alternation": alternation_patterns,
        }

        self._print_pattern_stats(all_patterns)
        return all_patterns

    # ------------------------------------------------------------------
    # Per-category analysis (kept private)
    # ------------------------------------------------------------------

    def _analyze_home_patterns(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        print("\n  \U0001f4cd Анализ домашних паттернов...")
        patterns: list[dict[str, Any]] = []
        for team in df["home_team"].unique():
            home_games = df[df["home_team"] == team].sort_values("date")
            if len(home_games) < 3:
                continue
            results = home_games["home_win"].values
            result_str = "".join("W" if r == 1 else "L" for r in results)

            for s in self.find_streaks(result_str):
                patterns.append({
                    "team": team,
                    "type": "home_streak",
                    "pattern": s.pattern,
                    "length": s.length,
                    "critical": s.length >= self.thresholds["home_streak"],
                    "position": s.position,
                    "next_result": s.next_result,
                })

            for a in self.find_alternations(result_str):
                patterns.append({
                    "team": team,
                    "type": "home_alternation",
                    "pattern": a.pattern,
                    "length": a.length,
                    "critical": a.length >= self.thresholds["home_alternation"],
                    "position": a.position,
                    "next_result": a.next_result,
                })
        return patterns

    def _analyze_away_patterns(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        print("  \U0001f697 Анализ гостевых паттернов...")
        patterns: list[dict[str, Any]] = []
        for team in df["away_team"].unique():
            away_games = df[df["away_team"] == team].sort_values("date")
            if len(away_games) < 3:
                continue
            results = [1 if row["home_win"] == 0 else 0 for _, row in away_games.iterrows()]
            result_str = "".join("W" if r == 1 else "L" for r in results)

            for s in self.find_streaks(result_str):
                patterns.append({
                    "team": team,
                    "type": "away_streak",
                    "pattern": s.pattern,
                    "length": s.length,
                    "critical": s.length >= self.thresholds["away_streak"],
                    "position": s.position,
                    "next_result": s.next_result,
                })

            for a in self.find_alternations(result_str):
                patterns.append({
                    "team": team,
                    "type": "away_alternation",
                    "pattern": a.pattern,
                    "length": a.length,
                    "critical": a.length >= self.thresholds["away_alternation"],
                    "position": a.position,
                    "next_result": a.next_result,
                })
        return patterns

    def _analyze_head_to_head_patterns(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        print("  \U0001f91d Анализ личных встреч...")
        patterns: list[dict[str, Any]] = []
        matchups = df.groupby(["home_team", "away_team"]).size().reset_index()

        for _, row in matchups.iterrows():
            team1 = row["home_team"]
            team2 = row["away_team"]
            h2h_games = df[
                ((df["home_team"] == team1) & (df["away_team"] == team2))
                | ((df["home_team"] == team2) & (df["away_team"] == team1))
            ].sort_values("date")

            if len(h2h_games) < 3:
                continue

            results: list[str] = []
            for _, game in h2h_games.iterrows():
                if game["home_team"] == team1:
                    results.append("W" if game["home_win"] == 1 else "L")
                else:
                    results.append("L" if game["home_win"] == 1 else "W")
            result_str = "".join(results)

            for s in self.find_streaks(result_str):
                patterns.append({
                    "teams": (team1, team2),
                    "type": "h2h_streak",
                    "pattern": s.pattern,
                    "length": s.length,
                    "critical": s.length >= self.thresholds["h2h_streak"],
                    "position": s.position,
                    "next_result": s.next_result,
                })

            for a in self.find_alternations(result_str):
                patterns.append({
                    "teams": (team1, team2),
                    "type": "h2h_alternation",
                    "pattern": a.pattern,
                    "length": a.length,
                    "critical": a.length >= self.thresholds["h2h_alternation"],
                    "position": a.position,
                    "next_result": a.next_result,
                })
        return patterns

    def _analyze_alternation_patterns(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        print("  \U0001f504 Анализ чередований...")
        patterns: list[dict[str, Any]] = []
        teams = pd.concat([df["home_team"], df["away_team"]]).unique()

        for team in teams:
            team_games = df[
                (df["home_team"] == team) | (df["away_team"] == team)
            ].sort_values("date")
            if len(team_games) < 4:
                continue

            results: list[str] = []
            for _, game in team_games.iterrows():
                if game["home_team"] == team:
                    results.append("W" if game["home_win"] == 1 else "L")
                else:
                    results.append("L" if game["home_win"] == 1 else "W")
            result_str = "".join(results)

            for cp in self.find_complex_patterns(result_str):
                patterns.append({
                    "team": team,
                    "type": "complex_alternation",
                    "pattern": cp.pattern,
                    "length": cp.length,
                    "critical": cp.length >= self.thresholds["alternation"],
                    "position": cp.position,
                    "next_result": cp.next_result,
                })
        return patterns

    # ------------------------------------------------------------------
    # Print helpers
    # ------------------------------------------------------------------

    def _print_pattern_stats(self, all_patterns: dict[str, list[dict[str, Any]]]) -> None:
        print("\n\U0001f4ca Статистика паттернов:")
        print("-" * 40)
        total = 0
        critical_total = 0
        for pattern_type, pats in all_patterns.items():
            critical = sum(1 for p in pats if p.get("critical", False))
            print(f"  {pattern_type}: {len(pats)} (критических: {critical})")
            total += len(pats)
            critical_total += critical
        print("-" * 40)
        print(f"  ВСЕГО: {total} паттернов")
        print(f"  Критических: {critical_total}")

    # ------------------------------------------------------------------
    # Feature extraction (used by FeatureBuilder)
    # ------------------------------------------------------------------

    def get_pattern_features(
        self,
        team: str,
        opponent: str,
        games_df: pd.DataFrame,
        game_date: Any,
    ) -> dict[str, Any]:
        """Extract numeric pattern features for one (team, opponent, date).

        Returns the exact same dict keys that the original
        ``PatternEngine.get_pattern_features`` returned.
        """
        features: dict[str, Any] = {}

        # -- Home games ------------------------------------------------
        home_games = games_df[
            (games_df["home_team"] == team) & (games_df["date"] < game_date)
        ].sort_values("date").tail(15)

        if len(home_games) > 0:
            home_results = home_games["home_win"].values
            features["home_win_streak"] = self.current_streak(list(home_results))
            features["home_last_5_wins"] = (
                int(sum(home_results[-5:])) if len(home_results) >= 5 else int(sum(home_results))
            )
            home_str = "".join("W" if r == 1 else "L" for r in home_results)
            features["home_alternation_len"] = self.get_alternation_length(home_str)
            features["home_last_result"] = int(home_results[-1])
            features["home_expected_alt"] = (
                1 - int(home_results[-1]) if features["home_alternation_len"] >= 4 else -1
            )
        else:
            features["home_win_streak"] = 0
            features["home_last_5_wins"] = 0
            features["home_alternation_len"] = 0
            features["home_last_result"] = -1
            features["home_expected_alt"] = -1

        # -- Away games ------------------------------------------------
        away_games = games_df[
            (games_df["away_team"] == team) & (games_df["date"] < game_date)
        ].sort_values("date").tail(15)

        if len(away_games) > 0:
            away_results = [1 if r == 0 else 0 for r in away_games["home_win"].values]
            features["away_win_streak"] = self.current_streak(away_results)
            features["away_last_5_wins"] = (
                int(sum(away_results[-5:])) if len(away_results) >= 5 else int(sum(away_results))
            )
            away_str = "".join("W" if r == 1 else "L" for r in away_results)
            features["away_alternation_len"] = self.get_alternation_length(away_str)
            features["away_last_result"] = int(away_results[-1])
            features["away_expected_alt"] = (
                1 - int(away_results[-1]) if features["away_alternation_len"] >= 4 else -1
            )
        else:
            features["away_win_streak"] = 0
            features["away_last_5_wins"] = 0
            features["away_alternation_len"] = 0
            features["away_last_result"] = -1
            features["away_expected_alt"] = -1

        # -- Head-to-head ---------------------------------------------
        h2h_games = games_df[
            (
                ((games_df["home_team"] == team) & (games_df["away_team"] == opponent))
                | ((games_df["home_team"] == opponent) & (games_df["away_team"] == team))
            )
            & (games_df["date"] < game_date)
        ].sort_values("date").tail(15)

        if len(h2h_games) > 0:
            h2h_results: list[int] = []
            for _, game in h2h_games.iterrows():
                if game["home_team"] == team:
                    h2h_results.append(int(game["home_win"]))
                else:
                    h2h_results.append(int(1 - game["home_win"]))

            features["h2h_win_streak"] = self.current_streak(h2h_results)
            features["h2h_last_5_wins"] = (
                int(sum(h2h_results[-5:])) if len(h2h_results) >= 5 else int(sum(h2h_results))
            )
            features["h2h_games_count"] = len(h2h_results)
            h2h_str = "".join("W" if r == 1 else "L" for r in h2h_results)
            features["h2h_alternation_len"] = self.get_alternation_length(h2h_str)
            features["h2h_last_result"] = int(h2h_results[-1])
            features["h2h_expected_alt"] = (
                1 - int(h2h_results[-1]) if features["h2h_alternation_len"] >= 4 else -1
            )
        else:
            features["h2h_win_streak"] = 0
            features["h2h_last_5_wins"] = 0
            features["h2h_games_count"] = 0
            features["h2h_alternation_len"] = 0
            features["h2h_last_result"] = -1
            features["h2h_expected_alt"] = -1

        # -- Overall ---------------------------------------------------
        all_games = games_df[
            ((games_df["home_team"] == team) | (games_df["away_team"] == team))
            & (games_df["date"] < game_date)
        ].sort_values("date").tail(20)

        if len(all_games) > 0:
            overall_results: list[int] = []
            for _, game in all_games.iterrows():
                if game["home_team"] == team:
                    overall_results.append(int(game["home_win"]))
                else:
                    overall_results.append(int(1 - game["home_win"]))

            features["overall_win_streak"] = self.current_streak(overall_results)
            overall_str = "".join("W" if r == 1 else "L" for r in overall_results)
            features["overall_alternation_len"] = self.get_alternation_length(overall_str)
            features["overall_last_10_wins"] = (
                int(sum(overall_results[-10:])) if len(overall_results) >= 10 else int(sum(overall_results))
            )
            features["overall_last_result"] = int(overall_results[-1])
            features["overall_expected_alt"] = (
                1 - int(overall_results[-1]) if features["overall_alternation_len"] >= 4 else -1
            )
        else:
            features["overall_win_streak"] = 0
            features["overall_alternation_len"] = 0
            features["overall_last_10_wins"] = 0
            features["overall_last_result"] = -1
            features["overall_expected_alt"] = -1

        # -- Critical flags --------------------------------------------
        features["home_streak_critical"] = (
            1 if abs(features["home_win_streak"]) >= self.thresholds["home_streak"] else 0
        )
        features["away_streak_critical"] = (
            1 if abs(features["away_win_streak"]) >= self.thresholds["away_streak"] else 0
        )
        features["h2h_streak_critical"] = (
            1 if abs(features["h2h_win_streak"]) >= self.thresholds["h2h"] else 0
        )
        features["overall_streak_critical"] = (
            1 if abs(features["overall_win_streak"]) >= self.thresholds["overall_streak"] else 0
        )
        features["home_alt_critical"] = (
            1 if features["home_alternation_len"] >= self.thresholds["home_alternation"] else 0
        )
        features["away_alt_critical"] = (
            1 if features["away_alternation_len"] >= self.thresholds["away_alternation"] else 0
        )
        features["h2h_alt_critical"] = (
            1 if features["h2h_alternation_len"] >= self.thresholds["h2h_alternation"] else 0
        )
        features["overall_alt_critical"] = (
            1 if features["overall_alternation_len"] >= self.thresholds["overall_alternation"] else 0
        )

        features["total_critical_patterns"] = (
            features["home_streak_critical"]
            + features["away_streak_critical"]
            + features["h2h_streak_critical"]
            + features["overall_streak_critical"]
            + features["home_alt_critical"]
            + features["away_alt_critical"]
            + features["h2h_alt_critical"]
            + features["overall_alt_critical"]
        )

        features["max_streak_len"] = max(
            abs(features["home_win_streak"]),
            abs(features["away_win_streak"]),
            abs(features["h2h_win_streak"]),
            abs(features["overall_win_streak"]),
        )
        features["max_alternation_len"] = max(
            features["home_alternation_len"],
            features["away_alternation_len"],
            features["h2h_alternation_len"],
            features["overall_alternation_len"],
        )

        # -- H2H home/away specific ------------------------------------
        h2h_home_games = games_df[
            (games_df["home_team"] == team)
            & (games_df["away_team"] == opponent)
            & (games_df["date"] < game_date)
        ].sort_values("date").tail(10)

        if len(h2h_home_games) >= 2:
            h2h_home_results = h2h_home_games["home_win"].values
            features["h2h_home_win_streak"] = self.current_streak(list(h2h_home_results))
        else:
            features["h2h_home_win_streak"] = 0

        h2h_away_games = games_df[
            (games_df["home_team"] == opponent)
            & (games_df["away_team"] == team)
            & (games_df["date"] < game_date)
        ].sort_values("date").tail(10)

        if len(h2h_away_games) >= 2:
            h2h_away_results = [1 - r for r in h2h_away_games["home_win"].values]
            features["h2h_away_win_streak"] = self.current_streak(h2h_away_results)
        else:
            features["h2h_away_win_streak"] = 0

        features["h2h_home_streak_critical"] = (
            1
            if abs(features["h2h_home_win_streak"]) >= self.thresholds.get("h2h_home_streak", 3)
            else 0
        )
        features["h2h_away_streak_critical"] = (
            1
            if abs(features["h2h_away_win_streak"]) >= self.thresholds.get("h2h_away_streak", 2)
            else 0
        )

        # -- League-wide home trend ------------------------------------
        league_last_20 = games_df[games_df["date"] < game_date].sort_values("date").tail(20)
        if len(league_last_20) > 0:
            features["league_home_wins_last_20"] = int(league_last_20["home_win"].sum())
            features["league_home_rate"] = float(league_last_20["home_win"].mean())
            league_recent = (
                games_df[games_df["date"] < game_date]
                .sort_values("date")
                .tail(10)["home_win"]
                .values
            )
            features["league_home_streak"] = self.current_streak(list(league_recent))
        else:
            features["league_home_wins_last_20"] = 10
            features["league_home_rate"] = 0.5
            features["league_home_streak"] = 0

        features["league_home_streak_critical"] = (
            1
            if abs(features["league_home_streak"]) >= self.thresholds.get("league_home_streak", 5)
            else 0
        )

        return features

    # ------------------------------------------------------------------
    # analyze_match (abstract interface)
    # ------------------------------------------------------------------

    def analyze_match(
        self, home_team: str, away_team: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Analyze a single hockey match.

        Accepts ``games_df`` and ``game_date`` via *kwargs* for the
        feature-extraction path, or ``home_pattern`` / ``away_pattern``
        dicts for the CPP prediction path.
        """
        games_df = kwargs.get("games_df")
        game_date = kwargs.get("game_date")

        if games_df is not None and game_date is not None:
            features = self.get_pattern_features(home_team, away_team, games_df, game_date)
            return {"features": features}

        home_pattern: dict[str, Any] = kwargs.get("home_pattern", {})
        away_pattern: dict[str, Any] = kwargs.get("away_pattern", {})

        home_score = self.calc_strong_signal(home_pattern)
        away_score = self.calc_strong_signal(away_pattern)
        cpp_prediction = self.get_cpp_prediction(home_pattern, away_pattern)
        synergy_details = self.get_synergy_details(home_pattern, away_pattern)

        return {
            "home_team": home_team,
            "away_team": away_team,
            "home_pattern": home_pattern,
            "away_pattern": away_pattern,
            "home_score": home_score,
            "away_score": away_score,
            "max_score": max(home_score, away_score),
            "cpp_prediction": cpp_prediction.to_dict(),
            "bet_recommendation": synergy_details["bet_recommendation"],
        }
