import json
import sys
from types import SimpleNamespace

from src import data_refresh


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _match(game_id, date, home, away, home_score, away_score, season):
    return {
        "id": game_id,
        "date": date,
        "home_team": home,
        "away_team": away,
        "home_score": home_score,
        "away_score": away_score,
        "home_win": int(home_score > away_score),
        "season": season,
    }


def test_plan_hockey_backfill_builds_full_2008_2025_range(monkeypatch):
    seasons = list(range(2008, 2026))

    class _Loader:
        def get_available_seasons(self, league_id):
            return list(reversed(seasons))

        def _get_cached_game_seasons(self, league_id):
            return [2024, 2023]

    monkeypatch.setitem(sys.modules, "src.multi_league_loader", SimpleNamespace(MultiLeagueLoader=_Loader))

    result = data_refresh.plan_hockey_backfill(
        leagues=["KHL"],
        from_season=2008,
        to_season=2025,
        include_current=True,
    )

    assert result["planned_seasons"]["KHL"] == seasons
    assert result["leagues"]["KHL"]["current_season"] == 2025
    assert result["leagues"]["KHL"]["cached_seasons"] == [2023, 2024]


def test_backfill_hockey_history_skips_existing_and_refreshes_current(monkeypatch, tmp_path):
    cache_root = tmp_path / "data" / "cache"
    leagues_root = cache_root / "leagues"
    saved_manifests = []
    saved_states = []
    built_states = []

    _write_json(
        leagues_root / "games_35_2023.json",
        [_match("khl-2023-1", "2023-09-01", "SKA", "CSKA", 2, 1, 2023)],
    )
    _write_json(
        leagues_root / "games_35_2025.json",
        [
            _match("khl-2025-1", "2025-09-01", "SKA", "CSKA", 3, 1, 2025),
            _match("khl-2025-2", "2025-09-03", "Ak Bars", "Avangard", 2, 1, 2025),
        ],
    )

    class _Loader:
        def __init__(self):
            self.api_key = "present"

        def get_available_seasons(self, league_id):
            return [2025, 2024, 2023]

        def _get_cached_game_seasons(self, league_id):
            seasons = []
            for path in leagues_root.glob(f"games_{league_id}_*.json"):
                seasons.append(int(path.stem.split("_")[-1]))
            return sorted(seasons, reverse=True)

        def get_games_cache_path(self, league_id, season):
            return leagues_root / f"games_{league_id}_{season}.json"

        def get_games(self, league_id, season, force_refresh=False):
            payload = {
                2024: [
                    _match("khl-2024-1", "2024-09-01", "SKA", "CSKA", 2, 1, 2024),
                    _match("khl-2024-2", "2024-09-02", "Dynamo", "Spartak", 4, 3, 2024),
                ],
                2025: [
                    _match("khl-2025-1", "2025-09-01", "SKA", "CSKA", 3, 1, 2025),
                    _match("khl-2025-2", "2025-09-03", "Ak Bars", "Avangard", 2, 1, 2025),
                    _match("khl-2025-3", "2025-09-05", "Lokomotiv", "Torpedo", 1, 0, 2025),
                ],
            }[season]
            _write_json(self.get_games_cache_path(league_id, season), payload)
            return payload

    manifest = {
        "generated_at": "2026-03-09T12:00:00",
        "summary": {
            "hockey": {
                league: {
                    "full_cache_matches": 0,
                    "date_min": None,
                    "date_max": None,
                    "source": "api_sports_hockey",
                    "kind": "seasonal_history",
                    "status": "ok",
                    "issues": [],
                }
                for league in ["NHL", "KHL", "SHL", "Liiga", "DEL"]
            }
        },
        "datasets": [],
    }

    monkeypatch.setitem(sys.modules, "src.multi_league_loader", SimpleNamespace(MultiLeagueLoader=_Loader))
    monkeypatch.setitem(
        sys.modules,
        "src.cache_catalog",
        SimpleNamespace(
            build_cache_manifest=lambda: manifest,
            save_manifest=lambda payload: saved_manifests.append(payload),
        ),
    )
    monkeypatch.setattr(
        data_refresh,
        "build_refresh_state_from_manifest",
        lambda manifest, refreshed_results=None, timestamp=None, source=None: built_states.append(
            {
                "manifest": manifest,
                "refreshed_results": refreshed_results,
                "timestamp": timestamp,
                "source": source,
            }
        )
        or {"last_refresh": timestamp, "last_results": refreshed_results or {}, "source": source},
    )
    monkeypatch.setattr(data_refresh, "save_refresh_state", lambda state: saved_states.append(state))

    result = data_refresh.backfill_hockey_history(
        leagues=["KHL"],
        from_season=2023,
        to_season=2025,
        include_current=True,
        refresh_existing_current=True,
        dry_run=False,
    )

    assert result["mode"] == "execute"
    assert result["planned_seasons"]["KHL"] == [2023, 2024, 2025]
    assert result["skipped_seasons"]["KHL"] == [2023]
    assert result["downloaded_seasons"]["KHL"] == [{"season": 2024, "matches": 2}]
    assert result["updated_seasons"]["KHL"] == [{"season": 2025, "matches": 3, "delta": 1}]
    assert result["failed_seasons"]["KHL"] == []
    assert result["manifest_generated_at"] == "2026-03-09T12:00:00"
    assert saved_manifests == [manifest]
    assert saved_states[0]["source"] == "backfill"
    assert built_states[0]["refreshed_results"]["KHL"]["matches"] == 3


def test_backfill_hockey_history_fails_fast_without_api_key(monkeypatch):
    class _Loader:
        def __init__(self):
            self.api_key = ""

        def get_available_seasons(self, league_id):
            return [2025, 2024]

        def _get_cached_game_seasons(self, league_id):
            return []

    monkeypatch.setitem(sys.modules, "src.multi_league_loader", SimpleNamespace(MultiLeagueLoader=_Loader))
    monkeypatch.setitem(
        sys.modules,
        "src.cache_catalog",
        SimpleNamespace(
            build_cache_manifest=lambda: {"generated_at": "ignored", "summary": {}, "datasets": []},
            save_manifest=lambda payload: None,
        ),
    )

    result = data_refresh.backfill_hockey_history(
        leagues=["KHL"],
        from_season=2024,
        to_season=2025,
        include_current=True,
        refresh_existing_current=False,
        dry_run=False,
    )

    assert result["mode"] == "execute"
    assert result["error"] == "API_SPORTS_KEY not set"
    assert result["failed_seasons"]["KHL"] == [{"season": None, "error": "API_SPORTS_KEY not set"}]
    assert result["manifest_generated_at"] is None
