"""
Universal pattern analyzer: generic patterns that work for any sport.

Includes the multi-league pattern engine logic (team pattern
aggregation, match analysis, EV calculation) that was previously in
``multi_league_predictor.py``.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import pandas as pd

from src.patterns.base import BasePatternAnalyzer, CppPrediction

logger = logging.getLogger(__name__)


class UniversalPatternAnalyzer(BasePatternAnalyzer):
    """Sport-agnostic pattern engine for multi-league analysis.

    Drop-in replacement for ``MultiLeaguePatternEngine`` from
    ``multi_league_predictor.py``.  All public methods preserve the
    original signatures and return values.
    """

    def __init__(
        self,
        critical_length: int = 5,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.critical_length: int = critical_length
        self.league_data: dict[str, Any] = {}
        self.team_patterns: dict[str, dict[str, dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_leagues(
        self,
        league_names: list[str],
        n_seasons: int = 5,
        loader: Any = None,
    ) -> dict[str, Any]:
        """Load league data and analyze patterns.

        When *loader* is ``None`` a ``MultiLeagueLoader`` is created
        internally (keeps backward compatibility).
        """
        if loader is None:
            from src.multi_league_loader import MultiLeagueLoader
            loader = MultiLeagueLoader()

        print("\n\U0001f4e5 Loading league data...")
        self.league_data = loader.load_multiple_leagues(league_names, n_seasons)

        for league, games in self.league_data.items():
            if games:
                df = pd.DataFrame(games)
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date")
                self.league_data[league] = df.to_dict("records")

        for league in league_names:
            if league in self.league_data and self.league_data[league]:
                self.analyze_team_patterns(league)
                team_count = len(self.team_patterns.get(league, {}))
                print(f"\u2705 {league}: patterns analyzed ({team_count} teams)")

        return self.league_data

    # ------------------------------------------------------------------
    # Team pattern analysis
    # ------------------------------------------------------------------

    def analyze_team_patterns(self, league_name: str) -> dict[str, dict[str, Any]]:
        if league_name not in self.league_data:
            return {}
        games = self.league_data[league_name]
        if not games:
            return {}

        team_history: dict[str, list[tuple[str, Any]]] = defaultdict(list)
        home_history: dict[str, list[str]] = defaultdict(list)
        away_history: dict[str, list[str]] = defaultdict(list)
        h2h_history: dict[tuple[str, str], list[tuple[str, Any]]] = defaultdict(list)

        for game in games:
            home = game["home_team"]
            away = game["away_team"]
            home_win = game["home_win"]

            team_history[home].append(("W" if home_win else "L", game["date"]))
            team_history[away].append(("L" if home_win else "W", game["date"]))

            home_history[home].append("W" if home_win else "L")
            away_history[away].append("W" if not home_win else "L")

            h2h_key = tuple(sorted([home, away]))
            h2h_history[h2h_key].append((home, home_win))

        patterns: dict[str, dict[str, Any]] = {}
        for team, results in team_history.items():
            results_only = [r[0] for r in results]
            overall_streak = self.current_streak(results_only)
            home_streak = self.current_streak(home_history.get(team, []))
            away_streak = self.current_streak(away_history.get(team, []))

            overall_alt = self.check_alternation(results_only)
            home_alt = self.check_alternation(home_history.get(team, []))

            patterns[team] = {
                "overall_streak": overall_streak,
                "home_streak": home_streak,
                "away_streak": away_streak,
                "overall_alt": overall_alt,
                "home_alt": home_alt,
                "games_played": len(results),
                "overall_critical": abs(overall_streak) >= self.critical_length,
                "home_critical": abs(home_streak) >= self.critical_length,
                "away_critical": abs(away_streak) >= self.critical_length,
                "alt_critical": overall_alt >= self.critical_length,
            }

        self.team_patterns[league_name] = patterns
        return patterns

    # ------------------------------------------------------------------
    # Match analysis (abstract interface)
    # ------------------------------------------------------------------

    def analyze_match(
        self, home_team: str, away_team: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Analyse a single match using precomputed team patterns.

        Accepts ``league_name`` via *kwargs*.
        """
        league_name: str = kwargs.get("league_name", "")

        if league_name and league_name not in self.team_patterns:
            self.analyze_team_patterns(league_name)

        patterns = self.team_patterns.get(league_name, {})
        home_pattern = patterns.get(home_team, {})
        away_pattern = patterns.get(away_team, {})

        home_score = self.calc_strong_signal(home_pattern)
        away_score = self.calc_strong_signal(away_pattern)

        cpp_prediction = self.get_cpp_prediction(home_pattern, away_pattern)
        synergy_details = self.get_synergy_details(home_pattern, away_pattern)

        return {
            "league": league_name,
            "home_team": home_team,
            "away_team": away_team,
            "home_pattern": home_pattern,
            "away_pattern": away_pattern,
            "home_score": home_score,
            "away_score": away_score,
            "max_score": max(home_score, away_score),
            "recommendation": self._get_recommendation(
                home_pattern, away_pattern, home_score, away_score
            ),
            "cpp_prediction": {
                "team": cpp_prediction.team,
                "synergy": cpp_prediction.synergy,
                "patterns": cpp_prediction.patterns,
                "home_synergy": cpp_prediction.home_synergy,
                "away_synergy": cpp_prediction.away_synergy,
            },
            "bet_recommendation": synergy_details["bet_recommendation"],
        }

    # ------------------------------------------------------------------
    # Recommendation text
    # ------------------------------------------------------------------

    def _get_recommendation(
        self,
        home_pattern: dict[str, Any],
        away_pattern: dict[str, Any],
        home_score: int,
        away_score: int,
    ) -> str:
        if home_score >= 4 or away_score >= 4:
            if home_score >= away_score:
                streak = home_pattern.get("overall_streak", 0)
                if streak > 0:
                    return "Bet on away (interrupt home win streak)"
                elif streak < 0:
                    return "Bet on home (interrupt loss streak)"
            else:
                streak = away_pattern.get("overall_streak", 0)
                if streak > 0:
                    return "Bet on home (interrupt away win streak)"
                elif streak < 0:
                    return "Bet on away (interrupt loss streak)"

        if home_score >= 3 or away_score >= 3:
            return "Medium signal - possible interruption"

        return "No strong signal"

    # ------------------------------------------------------------------
    # EV calculation helpers (used by multi_league_predictor)
    # ------------------------------------------------------------------

    def calc_ev(
        self, analysis: dict[str, Any], odds_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Calculate expected value based on CPP prediction.

        Reproduces ``MultiLeaguePatternEngine._calc_ev``.
        """
        cpp_prediction = analysis.get("cpp_prediction", {})
        league = analysis.get("league", "NHL")

        ev_result: dict[str, Any] = {
            "bet_on": None,
            "odds": 0,
            "probability": 0,
            "ev": 0,
            "ev_percent": 0,
            "synergy": 0,
            "patterns": [],
            "calibrated": league == "NHL",
            "note": "Requires synergy >= 2 patterns",
        }

        synergy = cpp_prediction.get("synergy", 0)
        bet_team = cpp_prediction.get("team")
        patterns = cpp_prediction.get("patterns", [])

        if synergy < 2 or bet_team is None:
            ev_result["note"] = f"Synergy {synergy} < 2, no recommendation"
            return ev_result

        odds = odds_data.get(
            "home_odds" if bet_team == "home" else "away_odds", 0
        )
        if odds <= 0:
            ev_result["note"] = "Odds unavailable"
            return ev_result

        probability = self.estimate_cpp_probability(patterns, synergy)
        ev = (probability * (odds - 1)) - (1 - probability)
        ev_percent = ev * 100

        return {
            "bet_on": bet_team,
            "odds": odds,
            "probability": round(probability * 100, 1),
            "ev": round(ev, 4),
            "ev_percent": round(ev_percent, 1),
            "synergy": synergy,
            "patterns": [p["reason"] for p in patterns],
            "calibrated": league == "NHL",
            "note": f"Synergy {synergy} patterns -> {bet_team}",
        }

    def estimate_break_prob(self, score: int, league: str = "NHL") -> float:
        """Score-based break probability estimate.

        Reproduces ``MultiLeaguePatternEngine._estimate_break_prob``.
        """
        prob_map = {3: 0.41, 4: 0.50, 5: 0.60, 6: 0.70}
        return prob_map.get(min(score, 6), 0.35)

    # ------------------------------------------------------------------
    # Summary printer
    # ------------------------------------------------------------------

    def print_summary(self, league_name: str) -> dict[str, dict[str, Any]]:
        if league_name not in self.team_patterns:
            self.analyze_team_patterns(league_name)

        patterns = self.team_patterns[league_name]
        print(f"\n\U0001f4ca Summary for {league_name}")
        print("=" * 60)

        critical_teams = [
            (t, p)
            for t, p in patterns.items()
            if p.get("overall_critical") or p.get("alt_critical")
        ]

        if critical_teams:
            print(f"\n\U0001f525 Teams with critical patterns ({len(critical_teams)}):")
            for team, pat in sorted(
                critical_teams,
                key=lambda x: abs(x[1].get("overall_streak", 0)),
                reverse=True,
            )[:10]:
                streak = pat["overall_streak"]
                streak_str = f"+{streak}" if streak > 0 else str(streak)
                print(f"  {team}: streak {streak_str}, alt={pat.get('overall_alt', 0)}")
        else:
            print("  No critical patterns")

        return patterns
