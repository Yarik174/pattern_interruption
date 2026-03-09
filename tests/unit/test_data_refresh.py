from datetime import datetime, timedelta

from src import cache_catalog
from src import data_refresh


def test_refresh_state_round_trip(tmp_path, monkeypatch):
    state_file = tmp_path / "refresh_state.json"
    monkeypatch.setattr(data_refresh, "REFRESH_STATE_FILE", str(state_file))

    payload = {"last_refresh": "2026-01-10T00:00:00", "last_results": {"NHL": {"success": True}}}
    data_refresh.save_refresh_state(payload)

    assert data_refresh.get_refresh_state() == payload


def test_should_refresh_handles_missing_fresh_stale_and_invalid_state(monkeypatch):
    monkeypatch.setattr(data_refresh, "get_refresh_state", lambda: {})
    assert data_refresh.should_refresh() is True

    monkeypatch.setattr(
        data_refresh,
        "get_refresh_state",
        lambda: {"last_refresh": (datetime.utcnow() - timedelta(hours=1)).isoformat()},
    )
    assert data_refresh.should_refresh() is False

    monkeypatch.setattr(
        data_refresh,
        "get_refresh_state",
        lambda: {"last_refresh": (datetime.utcnow() - timedelta(hours=25)).isoformat()},
    )
    assert data_refresh.should_refresh() is True

    monkeypatch.setattr(data_refresh, "get_refresh_state", lambda: {"last_refresh": "bad-date"})
    assert data_refresh.should_refresh() is True


def test_refresh_all_historical_data_skips_recent_refresh(monkeypatch):
    monkeypatch.setattr(
        data_refresh,
        "get_refresh_state",
        lambda: {"last_refresh": (datetime.utcnow() - timedelta(hours=2)).isoformat()},
    )

    result = data_refresh.refresh_all_historical_data()

    assert result["skipped"] is True


def test_refresh_all_historical_data_aggregates_results_and_saves_state(monkeypatch):
    saved_states = []
    saved_manifests = []
    monkeypatch.setattr(data_refresh, "get_refresh_state", lambda: {})
    monkeypatch.setattr(data_refresh, "save_refresh_state", lambda state: saved_states.append(state))
    monkeypatch.setattr(data_refresh, "refresh_nhl_data", lambda: {"league": "NHL", "success": True, "matches": 10})
    monkeypatch.setattr(
        data_refresh,
        "refresh_multi_league_data",
        lambda league: {"league": league, "success": league != "DEL", "matches": 3, "error": None},
    )

    from src import system_logger

    monkeypatch.setattr(system_logger, "log_system", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        cache_catalog,
        "build_cache_manifest",
        lambda: {
            "generated_at": "2026-03-09T10:00:00",
            "summary": {
                "hockey": {
                    "NHL": {"full_cache_matches": 812, "date_min": "2024-01-01T00:00:00", "date_max": "2026-03-01T00:00:00", "source": "nhl_api", "kind": "seasonal_history", "status": "ok", "issues": []},
                    "KHL": {"full_cache_matches": 873, "date_min": "2022-01-01T00:00:00", "date_max": "2024-12-31T00:00:00", "source": "api_sports_hockey", "kind": "seasonal_history", "status": "ok", "issues": []},
                    "SHL": {"full_cache_matches": 415, "date_min": "2022-01-01T00:00:00", "date_max": "2024-12-31T00:00:00", "source": "api_sports_hockey", "kind": "seasonal_history", "status": "ok", "issues": []},
                    "Liiga": {"full_cache_matches": 545, "date_min": "2022-01-01T00:00:00", "date_max": "2024-12-31T00:00:00", "source": "api_sports_hockey", "kind": "seasonal_history", "status": "ok", "issues": []},
                    "DEL": {"full_cache_matches": 406, "date_min": "2022-01-01T00:00:00", "date_max": "2024-12-31T00:00:00", "source": "api_sports_hockey", "kind": "seasonal_history", "status": "ok", "issues": []},
                }
            },
            "datasets": [],
        },
    )
    monkeypatch.setattr(cache_catalog, "save_manifest", lambda manifest: saved_manifests.append(manifest))

    result = data_refresh.refresh_all_historical_data(force=True)

    assert result["leagues"]["NHL"]["matches"] == 10
    assert result["leagues"]["DEL"]["success"] is False
    assert saved_manifests
    assert saved_states
    assert saved_states[0]["last_results"]["KHL"]["matches"] == 873
    assert saved_states[0]["last_results"]["KHL"]["refreshed_matches"] == 3
    assert saved_states[0]["last_results"]["DEL"]["success"] is False


def test_refresh_all_historical_data_handles_invalid_last_refresh(monkeypatch):
    monkeypatch.setattr(data_refresh, "get_refresh_state", lambda: {"last_refresh": "not-an-iso-date"})
    monkeypatch.setattr(data_refresh, "save_refresh_state", lambda state: None)
    monkeypatch.setattr(data_refresh, "refresh_nhl_data", lambda: {"league": "NHL", "success": True, "matches": 1})
    monkeypatch.setattr(
        data_refresh,
        "refresh_multi_league_data",
        lambda league: {"league": league, "success": True, "matches": 1, "error": None},
    )

    from src import system_logger

    monkeypatch.setattr(system_logger, "log_system", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        cache_catalog,
        "build_cache_manifest",
        lambda: {
            "generated_at": "2026-03-09T10:00:00",
            "summary": {
                "hockey": {
                    league: {
                        "full_cache_matches": 1,
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
        },
    )
    monkeypatch.setattr(cache_catalog, "save_manifest", lambda manifest: None)

    result = data_refresh.refresh_all_historical_data(force=False)

    assert result["leagues"]["NHL"]["success"] is True


def test_build_refresh_state_from_manifest_uses_full_and_refreshed_counts():
    manifest = {
        "generated_at": "2026-03-09T10:00:00",
        "summary": {
            "hockey": {
                "NHL": {"full_cache_matches": 812, "date_min": "2024-01-01T00:00:00", "date_max": "2026-03-01T00:00:00", "source": "nhl_api", "kind": "seasonal_history", "status": "ok", "issues": []},
                "KHL": {"full_cache_matches": 873, "date_min": "2022-01-01T00:00:00", "date_max": "2024-12-31T00:00:00", "source": "api_sports_hockey", "kind": "seasonal_history", "status": "partial", "issues": ["metadata seasons without cached games: 2025"]},
                "SHL": {"full_cache_matches": 415, "date_min": None, "date_max": None, "source": "api_sports_hockey", "kind": "seasonal_history", "status": "ok", "issues": []},
                "Liiga": {"full_cache_matches": 545, "date_min": None, "date_max": None, "source": "api_sports_hockey", "kind": "seasonal_history", "status": "ok", "issues": []},
                "DEL": {"full_cache_matches": 406, "date_min": None, "date_max": None, "source": "api_sports_hockey", "kind": "seasonal_history", "status": "ok", "issues": []},
            }
        },
    }

    state = data_refresh.build_refresh_state_from_manifest(
        manifest,
        refreshed_results={
            "NHL": {"league": "NHL", "success": True, "matches": 12, "error": None},
            "KHL": {"league": "KHL", "success": False, "matches": 0, "error": "api down"},
        },
        timestamp="2026-03-09T11:00:00",
        source="refresh",
    )

    assert state["last_results"]["NHL"]["matches"] == 812
    assert state["last_results"]["NHL"]["refreshed_matches"] == 12
    assert state["last_results"]["KHL"]["matches"] == 873
    assert state["last_results"]["KHL"]["refreshed_matches"] == 0
    assert state["last_results"]["KHL"]["error"] == "api down"
    assert state["last_results"]["KHL"]["issues_count"] == 1
