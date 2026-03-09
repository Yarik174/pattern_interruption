import importlib.util
import json
import sys
from pathlib import Path

from src import cache_catalog, data_refresh


ROOT = Path(__file__).resolve().parents[2]


def _load_cache_admin_module():
    module_path = ROOT / "scripts" / "cache_admin.py"
    spec = importlib.util.spec_from_file_location("cache_admin_script", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _match(date, home, away, home_score, away_score, *, game_id):
    return {
        "game_id": game_id,
        "date": date,
        "home_team": home,
        "away_team": away,
        "home_score": home_score,
        "away_score": away_score,
        "home_win": int(home_score > away_score),
    }


def _seed_primary_hockey(cache_root):
    _write_json(cache_root / "season_20242025.json", [_match("2024-10-01", "ANA", "BOS", 3, 2, game_id="nhl-1")])
    _write_json(cache_root / "leagues" / "games_35_2024.json", [_match("2024-09-01", "SKA", "CSKA", 2, 1, game_id="khl-1")])
    _write_json(cache_root / "leagues" / "seasons_35.json", [2024])
    _write_json(cache_root / "leagues" / "games_47_2024.json", [_match("2024-09-02", "Frolunda", "Lulea", 4, 1, game_id="shl-1")])
    _write_json(cache_root / "leagues" / "seasons_47.json", [2024])
    _write_json(cache_root / "leagues" / "games_16_2024.json", [_match("2024-09-03", "Tappara", "Ilves", 3, 0, game_id="liiga-1")])
    _write_json(cache_root / "leagues" / "seasons_16.json", [2024])
    _write_json(cache_root / "leagues" / "games_19_2024.json", [_match("2024-09-04", "Berlin", "Koln", 5, 3, game_id="del-1")])
    _write_json(cache_root / "leagues" / "seasons_19.json", [2024])


def test_audit_prints_report_and_does_not_write_manifest(tmp_path, monkeypatch, capsys):
    cache_root = tmp_path / "data" / "cache"
    _seed_primary_hockey(cache_root)
    module = _load_cache_admin_module()

    monkeypatch.setattr(cache_catalog, "CACHE_ROOT", cache_root)
    monkeypatch.setattr(cache_catalog, "MANIFEST_FILE", cache_root / "cache_manifest.json")
    monkeypatch.setattr(data_refresh, "REFRESH_STATE_FILE", str(cache_root / "refresh_state.json"))

    rc = module.main(["audit", "--json"])
    output = capsys.readouterr().out

    assert rc == 0
    assert '"generated_at"' in output
    assert not (cache_root / "cache_manifest.json").exists()


def test_rebuild_manifest_and_refresh_state_create_files(tmp_path, monkeypatch):
    cache_root = tmp_path / "data" / "cache"
    _seed_primary_hockey(cache_root)
    module = _load_cache_admin_module()

    monkeypatch.setattr(cache_catalog, "CACHE_ROOT", cache_root)
    monkeypatch.setattr(cache_catalog, "MANIFEST_FILE", cache_root / "cache_manifest.json")
    monkeypatch.setattr(data_refresh, "REFRESH_STATE_FILE", str(cache_root / "refresh_state.json"))

    assert module.main(["rebuild-manifest"]) == 0
    assert (cache_root / "cache_manifest.json").exists()

    assert module.main(["rebuild-refresh-state"]) == 0
    refresh_state = json.loads((cache_root / "refresh_state.json").read_text(encoding="utf-8"))
    assert refresh_state["last_results"]["NHL"]["matches"] == 1
    assert refresh_state["last_results"]["KHL"]["matches"] == 1
    assert refresh_state["source"] == "cache_rebuild"


def test_verify_returns_nonzero_for_corrupt_primary_dataset(tmp_path, monkeypatch):
    cache_root = tmp_path / "data" / "cache"
    _seed_primary_hockey(cache_root)
    broken = cache_root / "basketball" / "NBA_matches.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("{broken", encoding="utf-8")
    module = _load_cache_admin_module()

    monkeypatch.setattr(cache_catalog, "CACHE_ROOT", cache_root)
    monkeypatch.setattr(cache_catalog, "MANIFEST_FILE", cache_root / "cache_manifest.json")
    monkeypatch.setattr(data_refresh, "REFRESH_STATE_FILE", str(cache_root / "refresh_state.json"))

    assert module.main(["verify"]) == 1


def test_archive_test_snapshots_dry_run_reports_files(tmp_path, monkeypatch, capsys):
    cache_root = tmp_path / "data" / "cache"
    archive_root = tmp_path / "data" / "cache_archive" / "test_snapshots"
    _seed_primary_hockey(cache_root)
    _write_json(cache_root / "hockey" / "KHL_test_matches.json", [_match("2025-01-01", "SKA", "CSKA", 2, 1, game_id="test-khl")])
    module = _load_cache_admin_module()

    monkeypatch.setattr(cache_catalog, "CACHE_ROOT", cache_root)
    monkeypatch.setattr(cache_catalog, "MANIFEST_FILE", cache_root / "cache_manifest.json")
    monkeypatch.setattr(cache_catalog, "TEST_ARCHIVE_ROOT", archive_root)
    monkeypatch.setattr(data_refresh, "REFRESH_STATE_FILE", str(cache_root / "refresh_state.json"))

    rc = module.main(["archive-test-snapshots", "--dry-run", "--json"])
    output = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert output["files_found"] == 1
    assert output["items"][0]["status"] == "planned"
    assert (cache_root / "hockey" / "KHL_test_matches.json").exists()
    assert not (archive_root / "hockey" / "KHL_test_matches.json").exists()


def test_backfill_hockey_dry_run_returns_planned_range(tmp_path, monkeypatch, capsys):
    cache_root = tmp_path / "data" / "cache"
    _seed_primary_hockey(cache_root)
    module = _load_cache_admin_module()

    class _Loader:
        def get_available_seasons(self, league_id):
            return [2025, 2024, 2023, 2008]

        def _get_cached_game_seasons(self, league_id):
            return [2024]

    monkeypatch.setitem(sys.modules, "src.multi_league_loader", type("Mod", (), {"MultiLeagueLoader": _Loader}))
    monkeypatch.setattr(cache_catalog, "CACHE_ROOT", cache_root)
    monkeypatch.setattr(cache_catalog, "MANIFEST_FILE", cache_root / "cache_manifest.json")
    monkeypatch.setattr(data_refresh, "REFRESH_STATE_FILE", str(cache_root / "refresh_state.json"))

    rc = module.main(["backfill-hockey", "--league", "KHL", "--dry-run", "--from-season", "2008", "--to-season", "2025"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["mode"] == "dry-run"
    assert payload["planned_seasons"]["KHL"] == [2008, 2023, 2024, 2025]
