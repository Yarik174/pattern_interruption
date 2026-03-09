import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd

from src import data_refresh


def test_refresh_nhl_data_success_with_dataframe(monkeypatch):
    logged_updates = []

    class _Loader:
        def get_all_teams(self):
            return {"ANA": {}, "BOS": {}}

        def load_all_data(self, seasons=None, use_cache=False):
            return pd.DataFrame([{"game_id": 1}, {"game_id": 2}, {"game_id": 3}])

    monkeypatch.setitem(sys.modules, "src.data_loader", SimpleNamespace(NHLDataLoader=_Loader))
    monkeypatch.setitem(
        sys.modules,
        "src.system_logger",
        SimpleNamespace(log_data_update=lambda league, matches, success, details: logged_updates.append((league, matches, success, details))),
    )

    result = data_refresh.refresh_nhl_data()

    assert result == {"league": "NHL", "success": True, "matches": 3, "error": None}
    assert logged_updates == [("NHL", 3, True, {"season": "20252026"})]


def test_refresh_nhl_data_logs_error_on_failure(monkeypatch):
    logged_updates = []

    class _BrokenLoader:
        def get_all_teams(self):
            raise RuntimeError("nhl api unavailable")

    monkeypatch.setitem(sys.modules, "src.data_loader", SimpleNamespace(NHLDataLoader=_BrokenLoader))
    monkeypatch.setitem(
        sys.modules,
        "src.system_logger",
        SimpleNamespace(log_data_update=lambda league, matches, success, details: logged_updates.append((league, matches, success, details))),
    )

    result = data_refresh.refresh_nhl_data()

    assert result["success"] is False
    assert result["matches"] == 0
    assert "nhl api unavailable" in result["error"]
    assert logged_updates == [("NHL", 0, False, {"error": "nhl api unavailable"})]


def test_refresh_multi_league_data_handles_success_invalid_config_and_import_error(monkeypatch):
    logged_updates = []

    class _Loader:
        def load_league_data(self, league_name, n_seasons=1):
            return [{"id": 1}, {"id": 2}]

    monkeypatch.setitem(sys.modules, "src.multi_league_loader", SimpleNamespace(MultiLeagueLoader=_Loader))
    monkeypatch.setitem(
        sys.modules,
        "src.system_logger",
        SimpleNamespace(log_data_update=lambda league, matches, success, details: logged_updates.append((league, matches, success, details))),
    )

    success = data_refresh.refresh_multi_league_data("KHL")
    invalid = data_refresh.refresh_multi_league_data("UNKNOWN")

    assert success == {"league": "KHL", "success": True, "matches": 2, "error": None}
    assert invalid == {"league": "UNKNOWN", "success": False, "error": "Invalid config"}
    assert logged_updates == [("KHL", 2, True, {"n_seasons": 1})]


def test_refresh_multi_league_data_import_error_and_runtime_error(monkeypatch):
    logged_updates = []
    import builtins

    real_import = builtins.__import__
    monkeypatch.delitem(sys.modules, "src.multi_league_loader", raising=False)

    def _import_with_error(name, *args, **kwargs):
        if name == "src.multi_league_loader":
            raise ImportError("missing loader")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import_with_error)
    monkeypatch.setitem(
        sys.modules,
        "src.system_logger",
        SimpleNamespace(log_data_update=lambda league, matches, success, details: logged_updates.append((league, matches, success, details))),
    )

    import_error_result = data_refresh.refresh_multi_league_data("SHL")

    assert import_error_result == {
        "league": "SHL",
        "success": False,
        "matches": 0,
        "error": "MultiLeagueLoader not available",
    }
    assert logged_updates == []

    class _BrokenLoader:
        def load_league_data(self, league_name, n_seasons=1):
            raise RuntimeError("league api down")

    monkeypatch.setattr(builtins, "__import__", real_import)
    monkeypatch.setitem(sys.modules, "src.multi_league_loader", SimpleNamespace(MultiLeagueLoader=_BrokenLoader))

    runtime_error_result = data_refresh.refresh_multi_league_data("Liiga")

    assert runtime_error_result["success"] is False
    assert runtime_error_result["matches"] == 0
    assert runtime_error_result["error"] == "league api down"
    assert logged_updates == [("Liiga", 0, False, {"error": "league api down"})]


def test_get_last_refresh_info_includes_recency_and_handles_invalid_timestamp(monkeypatch):
    fresh_ts = (datetime.utcnow() - timedelta(hours=3)).isoformat()
    monkeypatch.setattr(
        data_refresh,
        "get_refresh_state",
        lambda: {"last_refresh": fresh_ts, "last_results": {"NHL": {"success": True}}},
    )

    info = data_refresh.get_last_refresh_info()

    assert info["last_refresh"] == fresh_ts
    assert info["results"]["NHL"]["success"] is True
    assert 2.5 <= info["hours_since"] <= 3.5
    assert info["needs_refresh"] is False

    monkeypatch.setattr(
        data_refresh,
        "get_refresh_state",
        lambda: {"last_refresh": "bad-date", "last_results": {}},
    )

    invalid_info = data_refresh.get_last_refresh_info()

    assert invalid_info["hours_since"] is None
    assert invalid_info["needs_refresh"] is True
    assert invalid_info["invalid_timestamp"] is True


def test_rebuild_refresh_state_from_cache_uses_local_cached_counts(monkeypatch):
    saved_states = []
    logged = []
    manifest = {
        "generated_at": "2026-03-09T10:00:00",
        "summary": {
            "hockey": {
                "NHL": {"full_cache_matches": 2, "date_min": None, "date_max": None, "source": "nhl_api", "kind": "seasonal_history", "status": "ok", "issues": []},
                "KHL": {"full_cache_matches": 3, "date_min": None, "date_max": None, "source": "api_sports_hockey", "kind": "seasonal_history", "status": "ok", "issues": []},
                "SHL": {"full_cache_matches": 4, "date_min": None, "date_max": None, "source": "api_sports_hockey", "kind": "seasonal_history", "status": "ok", "issues": []},
                "Liiga": {"full_cache_matches": 5, "date_min": None, "date_max": None, "source": "api_sports_hockey", "kind": "seasonal_history", "status": "ok", "issues": []},
                "DEL": {"full_cache_matches": 6, "date_min": None, "date_max": None, "source": "api_sports_hockey", "kind": "seasonal_history", "status": "ok", "issues": []},
            }
        },
    }

    monkeypatch.setitem(
        sys.modules,
        "src.cache_catalog",
        SimpleNamespace(
            load_manifest=lambda: manifest,
            get_cache_summary=lambda manifest=None, **kwargs: (manifest or {}).get("summary", {}),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.system_logger",
        SimpleNamespace(log_system=lambda message, level, details=None: logged.append((message, level, details))),
    )
    monkeypatch.setattr(data_refresh, "save_refresh_state", lambda state: saved_states.append(state))

    result = data_refresh.rebuild_refresh_state_from_cache()

    assert result["source"] == "cache_rebuild"
    assert result["leagues"]["NHL"]["matches"] == 2
    assert result["leagues"]["DEL"]["matches"] == 6
    assert saved_states[0]["last_results"]["SHL"]["matches"] == 4
    assert saved_states[0]["source"] == "cache_rebuild"
    assert logged[0][1] == "INFO"
    assert saved_states[0]["last_results"]["NHL"]["refreshed_matches"] == 0
