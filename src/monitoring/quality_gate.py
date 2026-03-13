"""
Quality gate for match evaluation.

Validates match metadata, odds ranges, historical coverage, and
signal agreement before a match can be promoted to candidate status.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class OddsSnapshot:
    """Immutable snapshot of a match's odds at evaluation time."""
    home_odds: Optional[float] = None
    away_odds: Optional[float] = None
    min_target: float = 2.0
    max_target: float = 3.5

    @property
    def home_in_range(self) -> bool:
        return self.home_odds is not None and self.min_target <= self.home_odds <= self.max_target

    @property
    def away_in_range(self) -> bool:
        return self.away_odds is not None and self.min_target <= self.away_odds <= self.max_target


@dataclass
class QualityReport:
    """Accumulated result of running a match through the quality gate."""
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


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------

class QualityGate:
    """Stateless quality gate: given a match dict, produce a verdict dict."""

    MIN_ODDS: float = 2.0
    MAX_ODDS: float = 3.5
    MIN_TEAM_HISTORY: dict[str, int] = {
        "hockey": 20,
        "football": 8,
        "basketball": 8,
        "volleyball": 8,
    }

    # -- technical checks ---------------------------------------------------

    @staticmethod
    def evaluate_technical(match: dict, sport_type: str) -> dict:
        """Validate that required metadata fields are present."""
        league = match.get("league")
        if not league:
            return {"status": "fail", "reason": "missing_league"}
        if not match.get("home_team") or not match.get("away_team"):
            return {"status": "fail", "reason": "missing_teams"}
        if not match.get("event_id"):
            return {"status": "fail", "reason": "missing_event_id"}
        if sport_type == "unknown":
            return {"status": "fail", "reason": "unknown_sport"}
        return {"status": "pass", "reason": "match_metadata_ready"}

    # -- odds checks --------------------------------------------------------

    @classmethod
    def evaluate_odds(cls, match: dict) -> dict:
        """Check whether home or away odds fall into the target range."""
        home_odds = match.get("home_odds")
        away_odds = match.get("away_odds")
        if not home_odds and not away_odds:
            return {"status": "fail", "reason": "missing_odds"}

        if home_odds and cls.MIN_ODDS <= home_odds <= cls.MAX_ODDS:
            return {
                "status": "pass",
                "reason": "odds_in_target_range",
                "bet_on": "home",
                "target_odds": home_odds,
            }
        if away_odds and cls.MIN_ODDS <= away_odds <= cls.MAX_ODDS:
            return {
                "status": "pass",
                "reason": "odds_in_target_range",
                "bet_on": "away",
                "target_odds": away_odds,
            }
        return {"status": "fail", "reason": "odds_out_of_range"}

    # -- history checks -----------------------------------------------------

    @classmethod
    def evaluate_history(
        cls,
        match: dict,
        sport_type: str,
        context: dict[str, Any],
        normalized_home: Optional[str],
        normalized_away: Optional[str],
    ) -> dict:
        """Check that enough historical data exists for both teams."""
        team_counts: Counter = context["team_counts"]
        pair_counts: Counter = context["pair_counts"]
        min_team_matches = cls.MIN_TEAM_HISTORY.get(sport_type, 8)
        h2h_key = tuple(sorted((normalized_home or "", normalized_away or "")))
        home_matches = team_counts.get(normalized_home, 0)
        away_matches = team_counts.get(normalized_away, 0)
        h2h_matches = pair_counts.get(h2h_key, 0)

        verdict: dict[str, Any] = {
            "status": "pass",
            "reason": "history_ready",
            "records_total": context["records"],
            "min_team_matches": min_team_matches,
            "home_matches": home_matches,
            "away_matches": away_matches,
            "h2h_matches": h2h_matches,
            "normalized_home_team": normalized_home,
            "normalized_away_team": normalized_away,
        }

        if context["records"] == 0:
            verdict["status"] = "fail"
            verdict["reason"] = "no_history"
        elif home_matches < min_team_matches or away_matches < min_team_matches:
            verdict["status"] = "fail"
            verdict["reason"] = "insufficient_team_history"

        return verdict

    # -- agreement check ----------------------------------------------------

    @staticmethod
    def evaluate_agreement(
        target_side: Optional[str],
        pattern_verdict: dict,
        model_verdict: dict,
    ) -> dict:
        """Check that pattern, model, and odds target agree on the side."""
        if not target_side:
            return {"status": "fail", "reason": "missing_target_side"}

        pattern_side = pattern_verdict.get("signal_side")
        model_side = model_verdict.get("signal_side")

        if pattern_verdict.get("status") == "pass" and pattern_side and pattern_side != target_side:
            return {"status": "fail", "reason": "pattern_odds_conflict"}
        if model_verdict.get("status") == "pass" and model_side and model_side != target_side:
            return {"status": "fail", "reason": "model_odds_conflict"}
        if (
            pattern_verdict.get("status") == "pass"
            and model_verdict.get("status") == "pass"
            and pattern_side != model_side
        ):
            return {"status": "fail", "reason": "pattern_model_conflict"}
        return {"status": "pass", "reason": "signals_aligned"}

    # -- final status -------------------------------------------------------

    @staticmethod
    def finalize_decision(
        *,
        pattern_verdict: dict,
        model_verdict: dict,
        agreement_verdict: dict,
    ) -> tuple[str, str]:
        """Return ``(status, reason)`` -- one of candidate / shadow_only / rejected."""
        pattern_pass = pattern_verdict.get("status") == "pass"
        model_pass = model_verdict.get("status") == "pass"
        model_status = model_verdict.get("status")
        pattern_reason = pattern_verdict.get("reason")
        model_reason = model_verdict.get("reason")

        if pattern_pass and model_pass and agreement_verdict.get("status") == "pass":
            return "candidate", "quality_gate_passed"

        if pattern_pass and model_status in {"unsupported", "unavailable"}:
            return "shadow_only", model_reason or "model_unavailable"
        if pattern_pass and model_status == "fail":
            return "shadow_only", model_reason or "model_rejected_signal"
        if pattern_reason == "market_mismatch":
            return "shadow_only", "market_mismatch"
        if model_pass and not pattern_pass:
            return "shadow_only", pattern_reason or "pattern_rejected_signal"
        if agreement_verdict.get("status") == "fail" and (pattern_pass or model_pass):
            return "shadow_only", agreement_verdict.get("reason") or "signal_conflict"
        return "rejected", pattern_reason or model_reason or agreement_verdict.get("reason") or "no_actionable_signal"
