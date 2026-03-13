"""
Shared domain types for the multi-sport betting prediction system.

These dataclasses and enums provide a single source of truth for data structures
used across modules: routes, prediction services, pattern engines, loaders, etc.

Note: SportType enum is re-exported from sports_config for convenience,
but the canonical definition lives in src/sports_config.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


# ── Re-export SportType from canonical location ──────────────────────────────
from src.sports_config import SportType  # noqa: F401


# ── Enums ────────────────────────────────────────────────────────────────────

class BetType(str, Enum):
    """Supported bet types."""
    WINNER = "winner"
    HALF_TOTALS = "half_totals"
    MONEYLINE = "moneyline"
    SPREAD = "spread"
    TOTAL = "total"
    OVER_UNDER = "over_under"

    def __str__(self) -> str:
        return self.value


class DecisionStatus(str, Enum):
    """Gate decision status for a match."""
    CANDIDATE = "candidate"
    SHADOW_ONLY = "shadow_only"
    REJECTED = "rejected"
    ACCEPTED = "accepted"

    def __str__(self) -> str:
        return self.value


class RLAction(str, Enum):
    """RL agent recommendation."""
    BET = "BET"
    SKIP = "SKIP"

    def __str__(self) -> str:
        return self.value


# ── Core dataclasses ─────────────────────────────────────────────────────────

@dataclass
class MatchData:
    """Represents a single match with basic info and optional scores.

    For the canonical ORM model see ``models.Prediction``.  This dataclass is
    intended for in-memory processing and data transfer between services.
    """
    match_id: str
    home_team: str
    away_team: str
    league: str
    sport_type: str = "hockey"
    date: Optional[datetime] = None
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    home_score_ht: Optional[int] = None
    away_score_ht: Optional[int] = None
    match_url: Optional[str] = None
    event_id: Optional[str] = None


@dataclass
class OddsData:
    """Odds for a match at a point in time."""
    home_odds: Optional[float] = None
    away_odds: Optional[float] = None
    draw_odds: Optional[float] = None
    bookmaker: Optional[str] = None
    timestamp: Optional[datetime] = None
    target_odds: Optional[float] = None
    bet_on: Optional[str] = None  # "home" | "away" | "draw"


@dataclass
class StreakInfo:
    """Information about a detected streak pattern."""
    streak_type: str  # "home_streak" | "away_streak" | "h2h_streak"
    pattern: str  # e.g. "WWWW" or "LLLL"
    length: int
    critical: bool = False
    position: int = 0
    next_result: Optional[str] = None


@dataclass
class PatternResult:
    """Result of a pattern analysis for one match."""
    pattern_type: str  # e.g. "streak", "underdog", "correction"
    confidence: float  # 0.0 - 1.0
    bet_on: Optional[str] = None  # "home" | "away"
    target_odds: Optional[float] = None
    streaks: list[StreakInfo] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""


@dataclass
class PredictionResult:
    """Output of the prediction pipeline for a single match."""
    match: MatchData
    odds: OddsData
    pattern: Optional[PatternResult] = None
    predicted_outcome: Optional[str] = None
    confidence: float = 0.0
    confidence_1_10: int = 5
    model_version: Optional[str] = None
    rl_recommendation: Optional[str] = None  # "BET" | "SKIP"
    rl_confidence: Optional[float] = None


@dataclass
class VerdictDetail:
    """Single gate verdict (technical, odds, history, pattern, model, agreement)."""
    status: str = "unknown"  # "pass" | "fail" | "unsupported" | "pending"
    reason: Optional[str] = None


@dataclass
class Decision:
    """Betting decision with full explainability trace."""
    status: DecisionStatus = DecisionStatus.REJECTED
    reason: str = "unknown"
    sport_type: str = "unknown"
    league: str = "-"
    home_team: str = "-"
    away_team: str = "-"
    bet_on: Optional[str] = None
    target_odds: Optional[float] = None
    home_odds: Optional[float] = None
    away_odds: Optional[float] = None
    technical_verdict: VerdictDetail = field(default_factory=VerdictDetail)
    odds_verdict: VerdictDetail = field(default_factory=VerdictDetail)
    history_verdict: VerdictDetail = field(default_factory=VerdictDetail)
    pattern_verdict: VerdictDetail = field(default_factory=VerdictDetail)
    model_verdict: VerdictDetail = field(default_factory=VerdictDetail)
    agreement_verdict: VerdictDetail = field(default_factory=VerdictDetail)


@dataclass
class PredictionStats:
    """Aggregate prediction statistics used in dashboard / statistics views."""
    total: int = 0
    wins: int = 0
    losses: int = 0
    pending: int = 0
    win_rate: float = 0.0
    roi: float = 0.0
