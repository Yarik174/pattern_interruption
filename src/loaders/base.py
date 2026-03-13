"""
Abstract base loader that captures the common interface shared by all sport/league loaders.

Every concrete loader inherits from ``BaseLoader`` and implements:
- ``is_configured()``          -- whether API keys / cache are available
- ``get_upcoming_games()``     -- scheduled matches (future)
- ``load_historical_data()``   -- past results for training / analysis
"""
from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.loaders.models import MatchData, OddsData

logger = logging.getLogger(__name__)


class BaseLoader(ABC):
    """Abstract interface that every data loader must implement."""

    # Subclasses should override these class-level defaults
    SOURCE_NAME: str = "base"
    DEFAULT_CACHE_DIR: str = "data/cache"

    def __init__(self, cache_dir: str | Path | None = None) -> None:
        self.cache_dir = Path(cache_dir or self.DEFAULT_CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True when all required credentials / data sources are available."""
        ...

    @abstractmethod
    def get_upcoming_games(self, **kwargs: Any) -> List[Dict]:
        """Return upcoming (future) matches as a list of dicts.

        Each dict must at minimum contain:
        ``event_id``, ``home_team``, ``away_team``, ``match_date``, ``league``.
        """
        ...

    @abstractmethod
    def load_historical_data(self, **kwargs: Any) -> List[Dict]:
        """Return historical match results as a list of dicts.

        Each dict must at minimum contain:
        ``game_id``, ``date``, ``home_team``, ``away_team``,
        ``home_score``, ``away_score``, ``home_win``.
        """
        ...

    # ------------------------------------------------------------------
    # Shared cache helpers
    # ------------------------------------------------------------------

    def _get_cache_path(self, key: str) -> Path:
        """Build a cache file path from an arbitrary string key."""
        safe_key = key.replace("/", "_").replace("\\", "_")
        return self.cache_dir / f"{safe_key}.json"

    def _load_from_cache(self, key: str) -> Optional[Any]:
        """Load JSON data from a cache file, or return ``None`` on miss."""
        cache_path = self._get_cache_path(key)
        if not cache_path.exists():
            return None
        try:
            with open(cache_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            logger.info("Cache hit: %s (%s entries)", key, len(data) if isinstance(data, list) else "?")
            return data
        except Exception as exc:
            logger.warning("Cache read error for %s: %s", key, exc)
            return None

    def _save_to_cache(self, key: str, data: Any) -> None:
        """Persist JSON-serialisable *data* under *key*."""
        cache_path = self._get_cache_path(key)
        try:
            with open(cache_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            size = len(data) if isinstance(data, list) else "?"
            logger.info("Cache write: %s (%s entries)", key, size)
        except Exception as exc:
            logger.warning("Cache write error for %s: %s", key, exc)

    def get_cache_info(self) -> Dict[str, Any]:
        """Return summary information about the local cache directory."""
        info: Dict[str, Any] = {"files": [], "total_size_mb": 0.0}
        if not self.cache_dir.exists():
            return info

        for filepath in self.cache_dir.iterdir():
            if filepath.suffix == ".json":
                size_mb = filepath.stat().st_size / (1024 * 1024)
                info["files"].append({
                    "name": filepath.name,
                    "size_mb": round(size_mb, 2),
                })
                info["total_size_mb"] += size_mb

        info["total_size_mb"] = round(info["total_size_mb"], 2)
        return info

    def clear_cache(self) -> None:
        """Delete all cached files."""
        import shutil
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Cache cleared: %s", self.cache_dir)
