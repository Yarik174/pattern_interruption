"""
Decision engine -- orchestrates quality gate verdicts for a single match
and delegates sport-specific signal evaluation.

Extracted from AutoMonitor.evaluate_match and its helper methods.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from src.monitoring.quality_gate import QualityGate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class BetDecision:
    """Structured representation of the full evaluate_match output."""
    event_id: Optional[str] = None
    sport_type: str = ""
    league: Optional[str] = None
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    home_odds: Optional[float] = None
    away_odds: Optional[float] = None
    status: str = "rejected"
    reason: Optional[str] = None
    bet_on: Optional[str] = None
    target_odds: Optional[float] = None
    technical_verdict: dict = field(default_factory=lambda: {"status": "pending", "reason": None})
    odds_verdict: dict = field(default_factory=lambda: {"status": "pending", "reason": None})
    history_verdict: dict = field(default_factory=lambda: {"status": "pending", "reason": None})
    pattern_verdict: dict = field(default_factory=lambda: {"status": "pending", "reason": None})
    model_verdict: dict = field(default_factory=lambda: {"status": "pending", "reason": None})
    agreement_verdict: dict = field(default_factory=lambda: {"status": "pending", "reason": None})

    def to_dict(self) -> dict:
        """Serialise to the same dict shape the old code produced."""
        from dataclasses import asdict
        return asdict(self)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class DecisionEngine:
    """
    Stateful engine that caches history contexts across evaluations.

    Mirrors the decision pipeline that was inlined inside
    ``AutoMonitor.evaluate_match``.
    """

    def __init__(self) -> None:
        self._history_context: Dict[tuple[str, str], Dict[str, Any]] = {}
        self._gate = QualityGate()

    # -- public entry point -------------------------------------------------

    def evaluate_match(self, match: dict) -> dict:
        """Evaluate a single match dict and return a decision dict."""
        sport_type = self._resolve_sport_type(match)
        decision = self._build_decision_shell(match, sport_type)

        # Step 1: technical metadata
        technical_verdict = self._gate.evaluate_technical(match, sport_type)
        decision["technical_verdict"] = technical_verdict
        if technical_verdict["status"] != "pass":
            decision["reason"] = technical_verdict["reason"]
            return decision

        # Step 2: odds range
        odds_verdict = self._gate.evaluate_odds(match)
        decision["odds_verdict"] = odds_verdict
        if odds_verdict["status"] != "pass":
            decision["reason"] = odds_verdict["reason"]
            return decision

        decision["bet_on"] = odds_verdict.get("bet_on")
        decision["target_odds"] = odds_verdict.get("target_odds")

        # Step 3: historical coverage
        normalized_home = self._normalize_team_for_history(
            sport_type, match.get("league"), match.get("home_team")
        )
        normalized_away = self._normalize_team_for_history(
            sport_type, match.get("league"), match.get("away_team")
        )
        context = self._get_history_context(sport_type, match.get("league") or "")
        history_verdict = self._gate.evaluate_history(
            match, sport_type, context, normalized_home, normalized_away
        )
        decision["history_verdict"] = history_verdict
        if history_verdict["status"] != "pass":
            decision["reason"] = history_verdict["reason"]
            return decision

        # Step 4: pattern + model signals
        pattern_verdict, model_verdict = self._evaluate_pattern_and_model(
            match, sport_type, history_verdict
        )
        decision["pattern_verdict"] = pattern_verdict
        decision["model_verdict"] = model_verdict

        # Step 5: agreement
        agreement_verdict = self._gate.evaluate_agreement(
            decision["bet_on"], pattern_verdict, model_verdict
        )
        decision["agreement_verdict"] = agreement_verdict

        # Step 6: final status
        final_status, final_reason = self._gate.finalize_decision(
            pattern_verdict=pattern_verdict,
            model_verdict=model_verdict,
            agreement_verdict=agreement_verdict,
        )
        decision["status"] = final_status
        decision["reason"] = final_reason
        return decision

    # -- shell builder ------------------------------------------------------

    @staticmethod
    def _build_decision_shell(match: dict, sport_type: str) -> dict:
        return {
            "event_id": match.get("event_id"),
            "sport_type": sport_type,
            "league": match.get("league"),
            "home_team": match.get("home_team"),
            "away_team": match.get("away_team"),
            "home_odds": match.get("home_odds"),
            "away_odds": match.get("away_odds"),
            "status": "rejected",
            "reason": None,
            "bet_on": None,
            "target_odds": None,
            "technical_verdict": {"status": "pending", "reason": None},
            "odds_verdict": {"status": "pending", "reason": None},
            "history_verdict": {"status": "pending", "reason": None},
            "pattern_verdict": {"status": "pending", "reason": None},
            "model_verdict": {"status": "pending", "reason": None},
            "agreement_verdict": {"status": "pending", "reason": None},
        }

    # -- sport type resolution ----------------------------------------------

    @staticmethod
    def _resolve_sport_type(match: dict) -> str:
        sport_type = str(match.get("sport_type") or "").strip().lower()
        if sport_type:
            return sport_type
        try:
            from src.prediction_service import infer_sport_type_from_league, SPORT_SLUGS
            inferred = infer_sport_type_from_league(match.get("league"))
            return SPORT_SLUGS.get(inferred, "hockey")
        except Exception:
            return "hockey"

    # -- team name normalisation --------------------------------------------

    @staticmethod
    def _normalize_team_for_history(
        sport_type: str, league: Optional[str], team_name: Optional[str]
    ) -> Optional[str]:
        if not team_name:
            return team_name
        if sport_type == "hockey" and league == "NHL":
            normalized = team_name.strip().upper()
            try:
                from app import get_abbrev_from_full_name
                resolved = get_abbrev_from_full_name(team_name)
                if resolved:
                    return resolved
            except Exception:
                pass
            return normalized
        return team_name.strip()

    # -- history context (cached) -------------------------------------------

    def _get_history_context(self, sport_type: str, league: str) -> Dict[str, Any]:
        cache_key = (sport_type, league)
        if cache_key in self._history_context:
            return self._history_context[cache_key]

        from src.cache_catalog import load_history

        history = load_history(sport_type, league, prefer_odds=False)
        team_counts: Counter = Counter()
        pair_counts: Counter = Counter()
        for item in history:
            home_team = item.get("home_team")
            away_team = item.get("away_team")
            if home_team:
                team_counts[home_team] += 1
            if away_team:
                team_counts[away_team] += 1
            if home_team and away_team:
                pair_counts[tuple(sorted((home_team, away_team)))] += 1

        analyzer = None
        try:
            if sport_type == "football":
                from src.football_pattern_engine import FootballPatternEngine
                analyzer = FootballPatternEngine()
                analyzer.load_matches(history)
            elif sport_type == "basketball":
                from src.football_pattern_engine import BasketballPatternEngine
                analyzer = BasketballPatternEngine()
                analyzer.load_matches(history)
            elif sport_type == "volleyball":
                from src.football_pattern_engine import VolleyballPatternEngine
                analyzer = VolleyballPatternEngine()
                analyzer.load_matches(history)
        except Exception as e:
            logger.warning(f"Analyzer build error for {sport_type}/{league}: {e}")

        context: Dict[str, Any] = {
            "records": len(history),
            "team_counts": team_counts,
            "pair_counts": pair_counts,
            "analyzer": analyzer,
        }
        self._history_context[cache_key] = context
        return context

    # -- sport-specific signal evaluation -----------------------------------

    def _evaluate_pattern_and_model(
        self, match: dict, sport_type: str, history_verdict: dict
    ) -> tuple[dict, dict]:
        league = match.get("league")
        home_team = history_verdict.get("normalized_home_team") or match.get("home_team")
        away_team = history_verdict.get("normalized_away_team") or match.get("away_team")

        if sport_type == "hockey":
            return self._evaluate_hockey_signals(league, home_team, away_team)
        if sport_type == "basketball":
            return self._evaluate_basketball_signals(league, home_team, away_team)
        if sport_type == "volleyball":
            return self._evaluate_volleyball_signals(league, home_team, away_team)
        if sport_type == "football":
            return self._evaluate_football_signals(league, home_team, away_team)
        return (
            {"status": "fail", "reason": "unsupported_sport", "signal_side": None, "confidence": None},
            {"status": "unsupported", "reason": "unsupported_sport", "signal_side": None, "confidence": None},
        )

    # -- hockey -------------------------------------------------------------

    def _evaluate_hockey_signals(
        self, league: Optional[str], home_team: str, away_team: str
    ) -> tuple[dict, dict]:
        if league == "NHL":
            try:
                from app import analyze_game
                analysis = analyze_game(home_team, away_team)
            except Exception as e:
                logger.warning(f"NHL analysis unavailable: {e}")
                return (
                    {"status": "fail", "reason": "analysis_unavailable", "signal_side": None, "confidence": None},
                    {"status": "unavailable", "reason": "analysis_unavailable", "signal_side": None, "confidence": None},
                )

            if not analysis:
                return (
                    {"status": "fail", "reason": "analysis_unavailable", "signal_side": None, "confidence": None},
                    {"status": "unavailable", "reason": "analysis_unavailable", "signal_side": None, "confidence": None},
                )

            cpp = analysis.get("cpp_prediction", {})
            synergy = cpp.get("synergy", 0)
            pattern_side = cpp.get("team") if cpp.get("bet_recommendation") else None
            pattern_confidence = min(0.9, 0.55 + max(0, synergy - 2) * 0.05) if pattern_side else None
            pattern_verdict = {
                "status": "pass" if pattern_side else "fail",
                "reason": "pattern_signal_ready" if pattern_side else "no_pattern_signal",
                "signal_side": pattern_side,
                "confidence": pattern_confidence,
                "details": {
                    "synergy": synergy,
                    "patterns": cpp.get("patterns", []),
                    "strong_signal_max": analysis.get("strong_signal", {}).get("max", 0),
                },
            }

            prediction = analysis.get("prediction") or {}
            model_side = prediction.get("predicted_winner")
            if model_side == "home":
                model_confidence = (prediction.get("home_probability") or 0) / 100
            elif model_side == "away":
                model_confidence = (prediction.get("away_probability") or 0) / 100
            else:
                model_confidence = None

            threshold = 0.55
            if model_side and model_confidence is not None and model_confidence >= threshold:
                model_verdict = {
                    "status": "pass",
                    "reason": "model_signal_ready",
                    "signal_side": model_side,
                    "confidence": model_confidence,
                    "details": {
                        "break_probability": prediction.get("break_probability"),
                        "continue_probability": prediction.get("continue_probability"),
                    },
                }
            elif model_side and model_confidence is not None:
                model_verdict = {
                    "status": "fail",
                    "reason": "model_below_threshold",
                    "signal_side": model_side,
                    "confidence": model_confidence,
                }
            else:
                model_verdict = {
                    "status": "unavailable",
                    "reason": "model_unavailable",
                    "signal_side": None,
                    "confidence": None,
                }

            return pattern_verdict, model_verdict

        # Non-NHL hockey (euro leagues)
        try:
            from app import init_multi_league
            engine = init_multi_league()
            analysis = engine.analyze_match(league, home_team, away_team)
        except Exception as e:
            logger.warning(f"Euro hockey analysis unavailable: {e}")
            return (
                {"status": "fail", "reason": "analysis_unavailable", "signal_side": None, "confidence": None},
                {"status": "unsupported", "reason": "model_not_calibrated_for_league", "signal_side": None, "confidence": None},
            )

        cpp = analysis.get("cpp_prediction", {})
        pattern_side = analysis.get("bet_recommendation")
        synergy = cpp.get("synergy", 0)
        pattern_verdict = {
            "status": "pass" if pattern_side else "fail",
            "reason": "pattern_signal_ready" if pattern_side else "no_pattern_signal",
            "signal_side": pattern_side,
            "confidence": min(0.85, 0.55 + max(0, synergy - 2) * 0.05) if pattern_side else None,
            "details": {
                "synergy": synergy,
                "patterns": cpp.get("patterns", []),
                "max_score": analysis.get("max_score"),
            },
        }
        model_verdict = {
            "status": "unsupported",
            "reason": "model_not_calibrated_for_league",
            "signal_side": None,
            "confidence": None,
        }
        return pattern_verdict, model_verdict

    # -- basketball ---------------------------------------------------------

    def _evaluate_basketball_signals(
        self, league: Optional[str], home_team: str, away_team: str
    ) -> tuple[dict, dict]:
        context = self._get_history_context("basketball", league or "")
        analyzer = context.get("analyzer")
        if analyzer is None:
            return (
                {"status": "fail", "reason": "analysis_unavailable", "signal_side": None, "confidence": None},
                {"status": "unsupported", "reason": "model_not_implemented_for_sport", "signal_side": None, "confidence": None},
            )

        analysis = analyzer.analyze_match(home_team, away_team)
        return self._build_cpp_verdicts(analysis)

    # -- volleyball ---------------------------------------------------------

    def _evaluate_volleyball_signals(
        self, league: Optional[str], home_team: str, away_team: str
    ) -> tuple[dict, dict]:
        context = self._get_history_context("volleyball", league or "")
        analyzer = context.get("analyzer")
        if analyzer is None:
            return (
                {"status": "fail", "reason": "analysis_unavailable", "signal_side": None, "confidence": None},
                {"status": "unsupported", "reason": "model_not_implemented_for_sport", "signal_side": None, "confidence": None},
            )

        analysis = analyzer.analyze_match(home_team, away_team)
        return self._build_cpp_verdicts(analysis)

    # -- football -----------------------------------------------------------

    def _evaluate_football_signals(
        self, league: Optional[str], home_team: str, away_team: str
    ) -> tuple[dict, dict]:
        context = self._get_history_context("football", league or "")
        analyzer = context.get("analyzer")
        if analyzer is None:
            return (
                {"status": "fail", "reason": "analysis_unavailable", "signal_side": None, "confidence": None},
                {"status": "unsupported", "reason": "model_not_implemented_for_sport", "signal_side": None, "confidence": None},
            )

        analysis = analyzer.analyze_match(home_team, away_team)
        pattern_verdict = {
            "status": "fail",
            "reason": "market_mismatch",
            "signal_side": None,
            "confidence": analysis.get("best_confidence"),
            "details": {
                "best_bet": analysis.get("best_bet"),
                "bet_type": "half_totals",
                "patterns": analysis.get("patterns", []),
            },
        }
        model_verdict = {
            "status": "unsupported",
            "reason": "model_not_implemented_for_sport",
            "signal_side": None,
            "confidence": None,
        }
        return pattern_verdict, model_verdict

    # -- CPP-based verdict builder (basketball, volleyball) -------------------

    @staticmethod
    def _build_cpp_verdicts(analysis: dict) -> tuple[dict, dict]:
        """Build pattern + model verdicts from CPP analysis.

        Used by basketball and volleyball evaluators. Requires synergy >= 2
        for a signal — same logic as hockey CPP.
        """
        cpp = analysis.get("cpp_prediction", {})
        synergy = cpp.get("synergy", 0) if isinstance(cpp, dict) else getattr(cpp, "synergy", 0)
        signal_side = analysis.get("bet_on")
        confidence = analysis.get("confidence", 0)
        active_patterns = analysis.get("patterns", [])

        # Pattern verdict: pass only when CPP found synergy >= 2
        if signal_side and synergy >= 2:
            pattern_confidence = min(0.9, 0.55 + max(0, synergy - 2) * 0.05)
            pattern_verdict = {
                "status": "pass",
                "reason": "pattern_signal_ready",
                "signal_side": signal_side,
                "confidence": pattern_confidence,
                "details": {
                    "synergy": synergy,
                    "patterns": active_patterns,
                    "home_signal_score": analysis.get("home_signal_score", 0),
                    "away_signal_score": analysis.get("away_signal_score", 0),
                },
            }
        else:
            pattern_verdict = {
                "status": "fail",
                "reason": "no_pattern_signal" if synergy < 2 else "no_cpp_prediction",
                "signal_side": signal_side,
                "confidence": confidence,
                "details": {
                    "synergy": synergy,
                    "patterns": active_patterns,
                },
            }

        # Model verdict: use CPP probability as model signal
        # (no separate ML model for basketball/volleyball yet)
        if signal_side and synergy >= 2 and confidence > 0.5:
            model_verdict = {
                "status": "pass",
                "reason": "model_signal_ready",
                "signal_side": signal_side,
                "confidence": confidence,
                "details": {
                    "cpp_probability": confidence,
                    "synergy": synergy,
                    "pattern_count": len(active_patterns),
                },
            }
        elif signal_side:
            model_verdict = {
                "status": "fail",
                "reason": "insufficient_synergy",
                "signal_side": signal_side,
                "confidence": confidence,
                "details": {"synergy": synergy},
            }
        else:
            model_verdict = {
                "status": "unavailable",
                "reason": "no_cpp_prediction",
                "signal_side": None,
                "confidence": None,
            }

        return pattern_verdict, model_verdict

