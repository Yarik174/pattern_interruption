"""
Odds fetching and loading facade.

Consolidates the live-loader acquisition (FlashLive) and historical
odds loading (OddsLoader + odds_scraper) into a single entry point.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class OddsFetcher:
    """
    Unified facade for obtaining odds data.

    * ``get_live_loader()`` -- returns the multi-sport FlashLive loader
      used by the monitor loop for upcoming matches.
    * ``get_match_result()`` -- proxies to the live loader for result
      checking.
    * ``load_historical()`` -- thin wrapper around the legacy
      ``OddsLoader`` / ``odds_scraper`` for backtesting.
    """

    def __init__(self) -> None:
        self._live_loader: Any = None

    # -- live loader --------------------------------------------------------

    def get_live_loader(self) -> Any:
        """Return (and cache) the multi-sport FlashLive loader."""
        if self._live_loader is None:
            from src.flashlive_loader import MultiSportFlashLiveLoader
            self._live_loader = MultiSportFlashLiveLoader()
        return self._live_loader

    def get_matches_with_odds(self, days_ahead: int = 2) -> list[dict]:
        """Fetch upcoming matches with odds from the live loader."""
        loader = self.get_live_loader()
        if not loader.is_configured():
            logger.warning("Live loader not configured")
            return []
        return loader.get_matches_with_odds(days_ahead=days_ahead)

    def get_match_result(
        self,
        event_id: str,
        sport: Optional[str] = None,
        league: Optional[str] = None,
    ) -> Optional[dict]:
        """Look up a finished match result by event id."""
        loader = self.get_live_loader()
        if not loader.is_configured():
            return None
        return loader.get_match_result(event_id, sport=sport, league=league)

    def is_configured(self) -> bool:
        """Check whether the live loader has its API keys set."""
        return self.get_live_loader().is_configured()

    # -- historical loading -------------------------------------------------

    @staticmethod
    def load_historical_odds(odds_dir: str = "data/odds") -> Any:
        """Load historical odds via the legacy OddsLoader."""
        from src.odds_loader import OddsLoader
        loader = OddsLoader(odds_dir=odds_dir)
        return loader.load_all_odds()

    @staticmethod
    def scrape_historical_odds(n_seasons: int = 8) -> Any:
        """Scrape historical odds via the legacy scraper."""
        from src.odds_scraper import load_all_historical_odds
        return load_all_historical_odds(n_seasons=n_seasons)
