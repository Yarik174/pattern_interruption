"""
NHL API data loader.

Loads historical game data from the official NHL API (api-web.nhle.com)
for training and analysis. Supports multi-season bulk loading with local
file-system caching.

Migrated from ``src/data_loader.py`` during the loader consolidation.
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from src.loaders.base import BaseLoader

logger = logging.getLogger(__name__)


class NHLDataLoader(BaseLoader):
    """Loader for historical NHL game data via the public NHL web API."""

    SOURCE_NAME = "nhl"
    DEFAULT_CACHE_DIR = "data/cache"

    def __init__(self, cache_dir: str = "data/cache") -> None:
        super().__init__(cache_dir=cache_dir)
        self.base_url: str = "https://api-web.nhle.com/v1"
        self.teams: Dict[str, Dict[str, str]] = {}
        self.games: List[Dict] = []

    # -- BaseLoader interface -----------------------------------------------

    def is_configured(self) -> bool:
        """NHL API is public and always available."""
        return True

    def get_upcoming_games(self, **kwargs: Any) -> List[Dict]:
        """NHL loader is historical-only; returns empty list."""
        return []

    def load_historical_data(
        self,
        seasons: Optional[List[str]] = None,
        use_cache: bool = True,
        **kwargs: Any,
    ) -> List[Dict]:
        """Load historical NHL game data, returning a list of game dicts.

        This delegates to :meth:`load_all_data` and converts the resulting
        DataFrame back to a list of dicts for interface conformance.
        """
        df = self.load_all_data(seasons=seasons, use_cache=use_cache)
        if df.empty:
            return []
        return df.to_dict("records")

    # -- Original public API (preserved) ------------------------------------

    def _get_cache_path_season(self, season: str) -> str:
        return os.path.join(str(self.cache_dir), f"season_{season}.json")

    def get_cached_seasons(self) -> List[str]:
        """Return season keys available in the local cache (chronological)."""
        seasons: List[str] = []
        if not os.path.exists(str(self.cache_dir)):
            return seasons
        for filename in os.listdir(str(self.cache_dir)):
            if not (filename.startswith("season_") and filename.endswith(".json")):
                continue
            season = filename.replace("season_", "").replace(".json", "")
            if season.isdigit():
                seasons.append(season)
        return sorted(set(seasons))

    def _load_from_cache(self, season: str) -> Optional[List[Dict]]:  # type: ignore[override]
        """Override BaseLoader._load_from_cache to use season-specific file layout."""
        cache_path = self._get_cache_path_season(season)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r") as fh:
                    data = json.load(fh)
                logger.info("Loaded from cache: season %s, %d games", season, len(data))
                return data
            except Exception as exc:
                logger.warning("Cache read error: %s", exc)
        return None

    def _save_to_cache(self, season: str, games: List[Dict]) -> None:  # type: ignore[override]
        """Override BaseLoader._save_to_cache to use season-specific file layout."""
        cache_path = self._get_cache_path_season(season)
        try:
            with open(cache_path, "w") as fh:
                json.dump(games, fh)
            logger.info("Saved to cache: season %s, %d games", season, len(games))
        except Exception as exc:
            logger.warning("Cache write error: %s", exc)

    def get_all_teams(self) -> Dict[str, Dict[str, str]]:
        """Fetch current NHL teams from the standings endpoint."""
        print("Loading NHL teams...")
        logger.info("Loading NHL teams")
        url = f"{self.base_url}/standings/now"
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()

            teams: Dict[str, Dict[str, str]] = {}
            for team_data in data.get("standings", []):
                team_abbr = team_data.get("teamAbbrev", {}).get("default", "")
                team_name = team_data.get("teamName", {}).get("default", "")
                if team_abbr and team_name:
                    teams[team_abbr] = {"name": team_name, "abbrev": team_abbr}

            self.teams = teams
            print(f"Loaded {len(teams)} teams")
            logger.info("Loaded %d teams", len(teams))
            return teams
        except Exception as exc:
            logger.warning("Error loading teams: %s", exc)
            print(f"Error loading teams: {exc}")
            return self._get_fallback_teams()

    def _get_fallback_teams(self) -> Dict[str, Dict[str, str]]:
        teams: Dict[str, Dict[str, str]] = {
            "ANA": {"name": "Anaheim Ducks", "abbrev": "ANA"},
            "ARI": {"name": "Arizona Coyotes", "abbrev": "ARI"},
            "BOS": {"name": "Boston Bruins", "abbrev": "BOS"},
            "BUF": {"name": "Buffalo Sabres", "abbrev": "BUF"},
            "CGY": {"name": "Calgary Flames", "abbrev": "CGY"},
            "CAR": {"name": "Carolina Hurricanes", "abbrev": "CAR"},
            "CHI": {"name": "Chicago Blackhawks", "abbrev": "CHI"},
            "COL": {"name": "Colorado Avalanche", "abbrev": "COL"},
            "CBJ": {"name": "Columbus Blue Jackets", "abbrev": "CBJ"},
            "DAL": {"name": "Dallas Stars", "abbrev": "DAL"},
            "DET": {"name": "Detroit Red Wings", "abbrev": "DET"},
            "EDM": {"name": "Edmonton Oilers", "abbrev": "EDM"},
            "FLA": {"name": "Florida Panthers", "abbrev": "FLA"},
            "LAK": {"name": "Los Angeles Kings", "abbrev": "LAK"},
            "MIN": {"name": "Minnesota Wild", "abbrev": "MIN"},
            "MTL": {"name": "Montreal Canadiens", "abbrev": "MTL"},
            "NSH": {"name": "Nashville Predators", "abbrev": "NSH"},
            "NJD": {"name": "New Jersey Devils", "abbrev": "NJD"},
            "NYI": {"name": "New York Islanders", "abbrev": "NYI"},
            "NYR": {"name": "New York Rangers", "abbrev": "NYR"},
            "OTT": {"name": "Ottawa Senators", "abbrev": "OTT"},
            "PHI": {"name": "Philadelphia Flyers", "abbrev": "PHI"},
            "PIT": {"name": "Pittsburgh Penguins", "abbrev": "PIT"},
            "SJS": {"name": "San Jose Sharks", "abbrev": "SJS"},
            "SEA": {"name": "Seattle Kraken", "abbrev": "SEA"},
            "STL": {"name": "St. Louis Blues", "abbrev": "STL"},
            "TBL": {"name": "Tampa Bay Lightning", "abbrev": "TBL"},
            "TOR": {"name": "Toronto Maple Leafs", "abbrev": "TOR"},
            "UTA": {"name": "Utah Hockey Club", "abbrev": "UTA"},
            "VAN": {"name": "Vancouver Canucks", "abbrev": "VAN"},
            "VGK": {"name": "Vegas Golden Knights", "abbrev": "VGK"},
            "WSH": {"name": "Washington Capitals", "abbrev": "WSH"},
            "WPG": {"name": "Winnipeg Jets", "abbrev": "WPG"},
        }
        self.teams = teams
        print(f"Using fallback list of {len(teams)} teams")
        return teams

    def load_team_schedule(self, team_abbr: str, season: str) -> List[Dict]:
        """Load all finished games for *team_abbr* in *season*."""
        url = f"{self.base_url}/club-schedule-season/{team_abbr}/{season}"
        games: List[Dict] = []
        try:
            response = requests.get(url, timeout=30)
            if response.status_code != 200:
                return games
            data = response.json()
            for game in data.get("games", []):
                if game.get("gameState") in ["OFF", "FINAL"]:
                    game_info = self._parse_game(game)
                    if game_info:
                        games.append(game_info)
            return games
        except Exception:
            return games

    def _parse_game(self, game: Dict) -> Optional[Dict]:
        try:
            home_team = game.get("homeTeam", {})
            away_team = game.get("awayTeam", {})
            home_abbr: str = home_team.get("abbrev", "")
            away_abbr: str = away_team.get("abbrev", "")
            home_score: int = home_team.get("score", 0)
            away_score: int = away_team.get("score", 0)

            if not home_abbr or not away_abbr:
                return None

            game_date: str = game.get("gameDate", "")
            game_id: int = game.get("id", 0)
            game_type: int = game.get("gameType", 2)

            return {
                "game_id": game_id,
                "date": game_date,
                "home_team": home_abbr,
                "away_team": away_abbr,
                "home_score": home_score,
                "away_score": away_score,
                "home_win": 1 if home_score > away_score else 0,
                "game_type": game_type,
                "overtime": 1
                if game.get("periodDescriptor", {}).get("periodType") in ("OT", "SO")
                else 0,
            }
        except Exception:
            return None

    def _load_season_from_api(self, season: str, use_cache: bool = True) -> List[Dict]:
        if use_cache:
            cached = self._load_from_cache(season)
            if cached:
                print(f"  Season {season[:4]}-{season[4:]} loaded from cache ({len(cached)} games)")
                return cached

        print(f"  Loading season {season[:4]}-{season[4:]} from API...")
        season_games: Dict[int, Dict] = {}
        teams_processed = 0

        for team_abbr in list(self.teams.keys()):
            games = self.load_team_schedule(team_abbr, season)
            for game in games:
                game_key = game["game_id"]
                if game_key not in season_games:
                    season_games[game_key] = game
            teams_processed += 1
            if teams_processed % 8 == 0:
                print(f"    Processed {teams_processed}/{len(self.teams)} teams, found {len(season_games)} games")
            time.sleep(0.1)

        games_list = list(season_games.values())
        if use_cache and len(games_list) > 0:
            self._save_to_cache(season, games_list)

        print(f"  Season {season}: loaded {len(games_list)} games")
        return games_list

    def load_all_data(
        self,
        seasons: Optional[List[str]] = None,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """Load data for multiple seasons, returning a ``pandas.DataFrame``."""
        if seasons is None:
            seasons = self.get_default_seasons(n_seasons=10)

        print("NHL Pattern Prediction System")
        print("=" * 50)

        self.get_all_teams()

        print(f"\nLoading data for {len(seasons)} seasons...")
        logger.info("Loading %d seasons: %s", len(seasons), seasons)

        all_games: List[Dict] = []
        stats: Dict[str, int] = {
            "seasons_loaded": 0,
            "from_cache": 0,
            "from_api": 0,
            "total_games": 0,
        }

        for i, season in enumerate(seasons):
            print(f"\n[{i + 1}/{len(seasons)}] Season {season[:4]}-{season[4:]}")

            cached = self._load_from_cache(season) if use_cache else None
            if cached:
                games_list = cached
                print(f"  Loaded from cache: {len(games_list)} games")
                stats["from_cache"] += 1
            else:
                games_list = self._load_season_from_api(season, use_cache=use_cache)
                stats["from_api"] += 1

            all_games.extend(games_list)
            stats["seasons_loaded"] += 1
            stats["total_games"] = len(all_games)

        self.games = all_games

        df = pd.DataFrame(all_games)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            df = df.drop_duplicates(subset=["game_id"]).reset_index(drop=True)

        print(f"\n{'=' * 50}")
        print(f"Total loaded:")
        print(f"   Seasons: {stats['seasons_loaded']}")
        print(f"   From cache: {stats['from_cache']}")
        print(f"   From API: {stats['from_api']}")
        print(f"   Total games: {len(df)}")

        logger.info("Loaded %d games from %d seasons", len(df), stats["seasons_loaded"])
        return df

    @staticmethod
    def get_default_seasons(n_seasons: int = 10) -> List[str]:
        """Generate season identifiers for the last *n_seasons* NHL seasons."""
        import sys
        # Look up datetime from the legacy wrapper first so that tests
        # patching ``src.data_loader.datetime`` still work.
        wrapper = sys.modules.get("src.data_loader")
        _dt = getattr(wrapper, "datetime", None) if wrapper else None
        if _dt is None:
            _dt = datetime
        current_year = _dt.now().year
        current_month = _dt.now().month

        if current_month >= 10:
            end_year = current_year + 1
        else:
            end_year = current_year

        seasons: List[str] = []
        for i in range(n_seasons):
            start = end_year - 1 - i
            end = end_year - i
            seasons.append(f"{start}{end}")

        seasons.reverse()
        return seasons

    def get_cache_info(self) -> Dict[str, Any]:
        """Return cache info in the legacy format expected by callers."""
        info: Dict[str, Any] = {"seasons": [], "total_games": 0, "total_size_mb": 0.0}
        if not os.path.exists(str(self.cache_dir)):
            return info

        for filename in os.listdir(str(self.cache_dir)):
            if filename.startswith("season_") and filename.endswith(".json"):
                filepath = os.path.join(str(self.cache_dir), filename)
                season = filename.replace("season_", "").replace(".json", "")
                size_mb = os.path.getsize(filepath) / (1024 * 1024)
                try:
                    with open(filepath, "r") as fh:
                        data = json.load(fh)
                    games_count = len(data)
                except Exception:
                    games_count = 0
                info["seasons"].append({
                    "season": season,
                    "games": games_count,
                    "size_mb": round(size_mb, 2),
                })
                info["total_games"] += games_count
                info["total_size_mb"] += size_mb

        info["total_size_mb"] = round(info["total_size_mb"], 2)
        return info

    def generate_sample_data(self, n_games: int = 2000) -> pd.DataFrame:
        """Generate synthetic test data."""
        print("Generating sample data...")

        if not self.teams:
            self._get_fallback_teams()

        team_list = list(self.teams.keys())
        games: List[Dict] = []
        start_date = datetime(2020, 10, 1)

        for i in range(n_games):
            home_team = random.choice(team_list)
            away_team = random.choice([t for t in team_list if t != home_team])

            home_score = random.randint(0, 6)
            away_score = random.randint(0, 6)
            if home_score == away_score:
                if random.random() > 0.5:
                    home_score += 1
                else:
                    away_score += 1

            game_date = start_date + pd.Timedelta(days=i // 5)

            games.append({
                "game_id": 2020000000 + i,
                "date": game_date,
                "home_team": home_team,
                "away_team": away_team,
                "home_score": home_score,
                "away_score": away_score,
                "home_win": 1 if home_score > away_score else 0,
                "game_type": 2,
                "overtime": random.choice([0, 0, 0, 1]),
            })

        df = pd.DataFrame(games)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        print(f"Generated {len(df)} sample games")
        self.games = games
        return df


# Backward compatibility alias
DataLoader = NHLDataLoader
