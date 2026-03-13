"""
Shared data structures for all loaders.

Provides typed dataclasses that replace the ad-hoc dicts previously
scattered across data_loader, multi_league_loader, flashlive_loader,
apisports_odds_loader, and euro_league_loader.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class MatchData:
    """Unified representation of a single match / game."""

    event_id: str = ""
    game_id: int | str = 0
    date: Optional[datetime] = None
    match_date: Optional[datetime] = None  # alias used by live-data loaders
    home_team: str = ""
    away_team: str = ""
    home_team_id: Optional[int] = None
    away_team_id: Optional[int] = None
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    home_win: Optional[int | bool] = None
    league: str = ""
    league_name: str = ""
    season: Optional[int | str] = None
    game_type: Optional[int] = None
    overtime: int = 0
    status: str = "Scheduled"
    source: str = ""
    sport: str = ""
    sport_type: str = ""
    venue: str = ""
    is_live: bool = False
    current_period: Optional[int] = None

    # Inline odds that may come with the event listing
    home_odds: Optional[float] = None
    away_odds: Optional[float] = None
    draw_odds: Optional[float] = None
    bookmaker: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to a plain dict (backwards-compatible with old loader output)."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class OddsData:
    """Odds information for a match from a single bookmaker."""

    home_odds: Optional[float] = None
    away_odds: Optional[float] = None
    draw_odds: Optional[float] = None
    bookmaker: str = "Unknown"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TeamStats:
    """Basic team statistics."""

    name: str = ""
    abbrev: str = ""
    team_id: Optional[int] = None
    league: str = ""
    country: str = ""
    recent_results: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BookmakerOdds:
    """Detailed odds from a specific bookmaker, used by APISports loader."""

    bookmaker: str = ""
    market: str = ""
    home_odds: Optional[float] = None
    away_odds: Optional[float] = None
    draw_odds: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AggregatedOdds:
    """Best odds aggregated across multiple bookmakers."""

    best_home_odds: Optional[float] = None
    best_away_odds: Optional[float] = None
    best_draw_odds: Optional[float] = None
    bookmakers: list[BookmakerOdds] = field(default_factory=list)

    def to_dict(self) -> dict:
        result = {
            "best_home_odds": self.best_home_odds,
            "best_away_odds": self.best_away_odds,
            "best_draw_odds": self.best_draw_odds,
            "bookmakers": [b.to_dict() for b in self.bookmakers],
        }
        return result
