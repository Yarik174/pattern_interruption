import json

from src.cache_catalog import (
    archive_test_snapshots,
    build_cache_manifest,
    find_test_snapshots,
    get_best_dataset,
    load_history,
    verify_manifest,
)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _match(
    date,
    home,
    away,
    home_score,
    away_score,
    *,
    game_id=None,
    season=None,
    home_odds=None,
    away_odds=None,
    draw_odds=None,
):
    return {
        "game_id": game_id or f"{home}-{away}-{date}",
        "date": date,
        "home_team": home,
        "away_team": away,
        "home_score": home_score,
        "away_score": away_score,
        "home_win": int(home_score > away_score),
        "season": season,
        "home_odds": home_odds,
        "away_odds": away_odds,
        "draw_odds": draw_odds,
    }


def _build_primary_hockey_cache(cache_root):
    _write_json(
        cache_root / "season_20242025.json",
        [_match("2024-10-01", "ANA", "BOS", 3, 2, game_id="nhl-1", season="20242025")],
    )
    _write_json(
        cache_root / "leagues" / "games_35_2024.json",
        [_match("2024-09-01", "SKA", "CSKA", 2, 1, game_id="khl-1", season=2024)],
    )
    _write_json(cache_root / "leagues" / "seasons_35.json", [2025, 2024])
    _write_json(
        cache_root / "leagues" / "games_47_2024.json",
        [_match("2024-09-02", "Frolunda", "Lulea", 4, 1, game_id="shl-1", season=2024)],
    )
    _write_json(cache_root / "leagues" / "seasons_47.json", [2024])
    _write_json(
        cache_root / "leagues" / "games_16_2024.json",
        [_match("2024-09-03", "Tappara", "Ilves", 3, 0, game_id="liiga-1", season=2024)],
    )
    _write_json(cache_root / "leagues" / "seasons_16.json", [2024])
    _write_json(
        cache_root / "leagues" / "games_19_2024.json",
        [_match("2024-09-04", "Berlin", "Koln", 5, 3, game_id="del-1", season=2024)],
    )
    _write_json(cache_root / "leagues" / "seasons_19.json", [2024])


def test_build_cache_manifest_classifies_datasets_and_summaries(tmp_path):
    cache_root = tmp_path / "data" / "cache"
    _build_primary_hockey_cache(cache_root)
    _write_json(
        cache_root / "football" / "EPL_matches.json",
        [_match("2025-01-01", "Arsenal", "Chelsea", 2, 1, game_id="epl-raw")],
    )
    _write_json(
        cache_root / "football" / "EPL_with_odds_matches.json",
        [
            _match("2025-01-02", "Arsenal", "Chelsea", 2, 0, game_id="epl-odds-1", home_odds=2.1, away_odds=3.2),
            _match("2025-01-03", "Liverpool", "Everton", 1, 1, game_id="epl-odds-2", home_odds=1.8, away_odds=4.1, draw_odds=3.4),
        ],
    )
    _write_json(
        cache_root / "hockey" / "KHL_matches.json",
        [_match("2025-01-04", "SKA", "CSKA", 2, 1, game_id="khl-snapshot")],
    )
    _write_json(
        cache_root / "hockey" / "KHL_test_matches.json",
        [_match("2025-01-05", "SKA", "CSKA", 2, 0, game_id="khl-test")],
    )
    _write_json(cache_root / "period_data.json", {"nhl-1": {"periods": [{"home": 1, "away": 0}]}})

    manifest = build_cache_manifest(cache_root=cache_root)

    assert manifest["summary"]["hockey"]["NHL"]["issues"] == []
    assert manifest["summary"]["hockey"]["NHL"]["full_cache_matches"] == 1
    assert manifest["summary"]["hockey"]["KHL"]["full_cache_matches"] == 1
    assert manifest["summary"]["hockey"]["KHL"]["status"] == "partial"
    assert "metadata seasons without cached games: 2025" in manifest["summary"]["hockey"]["KHL"]["issues"]

    assert manifest["summary"]["football"]["EPL"]["full_cache_matches"] == 2
    assert manifest["summary"]["football"]["EPL"]["has_runtime_history"] is True
    assert manifest["summary"]["football"]["EPL"]["has_training_history"] is False

    khl_auxiliary = [
        item for item in manifest["datasets"]
        if item["sport"] == "hockey" and item["league"] == "KHL" and item["kind"] == "auxiliary"
    ]
    assert khl_auxiliary
    assert all(item["for_runtime"] is False for item in khl_auxiliary)

    period_dataset = next(item for item in manifest["datasets"] if item["format"] == "period_data_json")
    assert period_dataset["kind"] == "auxiliary"
    assert period_dataset["records"] == 1

    assert get_best_dataset("hockey", "KHL", prefer_odds=True, manifest=manifest)["kind"] == "seasonal_history"
    assert get_best_dataset("football", "EPL", prefer_odds=True, manifest=manifest)["kind"] == "snapshot_with_odds"


def test_load_history_prefers_odds_snapshot_and_normalizes_records(tmp_path):
    cache_root = tmp_path / "data" / "cache"
    _build_primary_hockey_cache(cache_root)
    _write_json(
        cache_root / "football" / "EPL_matches.json",
        [_match("2025-01-03", "Liverpool", "Everton", 2, 1, game_id="raw-1")],
    )
    _write_json(
        cache_root / "football" / "EPL_with_odds_matches.json",
        [
            _match("2025-01-02", "Arsenal", "Chelsea", 2, 0, game_id="odds-1", home_odds=2.15, away_odds=3.2),
            _match("2025-01-04", "Liverpool", "Everton", 1, 1, game_id="odds-2", home_odds=1.9, away_odds=4.0, draw_odds=3.5),
        ],
    )

    manifest = build_cache_manifest(cache_root=cache_root)
    history = load_history("football", "EPL", prefer_odds=True, manifest=manifest, cache_root=cache_root)

    assert [row["game_id"] for row in history] == ["odds-1", "odds-2"]
    assert history[0]["sport"] == "football"
    assert history[0]["league"] == "EPL"
    assert history[0]["home_odds"] == 2.15
    assert history[1]["draw_odds"] == 3.5


def test_manifest_marks_corrupt_primary_dataset_and_verify_fails(tmp_path):
    cache_root = tmp_path / "data" / "cache"
    _build_primary_hockey_cache(cache_root)
    corrupt_file = cache_root / "basketball" / "NBA_matches.json"
    corrupt_file.parent.mkdir(parents=True, exist_ok=True)
    corrupt_file.write_text("{bad json", encoding="utf-8")

    manifest = build_cache_manifest(cache_root=cache_root)
    nba_dataset = next(
        item for item in manifest["datasets"]
        if item["sport"] == "basketball" and item["league"] == "NBA" and item["kind"] == "snapshot_history"
    )

    assert nba_dataset["status"] == "corrupt"

    verification = verify_manifest(manifest)
    assert verification["ok"] is False
    assert any("basketball/NBA" in issue for issue in verification["critical"])


def test_archive_test_snapshots_moves_files_out_of_live_cache(tmp_path):
    cache_root = tmp_path / "data" / "cache"
    archive_root = tmp_path / "data" / "cache_archive" / "test_snapshots"
    _build_primary_hockey_cache(cache_root)
    _write_json(
        cache_root / "hockey" / "KHL_test_matches.json",
        [_match("2025-01-05", "SKA", "CSKA", 2, 0, game_id="khl-test")],
    )
    _write_json(
        cache_root / "basketball" / "VTB_test_matches.json",
        [_match("2025-01-06", "CSKA", "Zenit", 88, 80, game_id="vtb-test")],
    )

    snapshots = find_test_snapshots(cache_root=cache_root)
    assert [item["filename"] for item in snapshots] == ["VTB_test_matches.json", "KHL_test_matches.json"]

    dry_run = archive_test_snapshots(cache_root=cache_root, archive_root=archive_root, dry_run=True)
    assert dry_run["files_found"] == 2
    assert (cache_root / "hockey" / "KHL_test_matches.json").exists()

    moved = archive_test_snapshots(cache_root=cache_root, archive_root=archive_root, dry_run=False)
    assert moved["archived"] == 2
    assert not (cache_root / "hockey" / "KHL_test_matches.json").exists()
    assert (archive_root / "hockey" / "KHL_test_matches.json").exists()
    assert (archive_root / "basketball" / "VTB_test_matches.json").exists()

    manifest = build_cache_manifest(cache_root=cache_root)
    assert all("test snapshot" not in dataset.get("issues", []) for dataset in manifest["datasets"])


def test_build_cache_manifest_honors_local_coverage_policy(tmp_path):
    cache_root = tmp_path / "data" / "cache"
    _build_primary_hockey_cache(cache_root)
    _write_json(
        cache_root / "cache_policy.json",
        {
            "seasonal_history": {
                "hockey": {
                    "KHL": {
                        "mode": "accepted_local_baseline",
                        "accepted_seasons": [2024],
                        "note": "local baseline",
                    }
                }
            }
        },
    )

    manifest = build_cache_manifest(cache_root=cache_root)
    khl_summary = manifest["summary"]["hockey"]["KHL"]
    khl_dataset = next(
        item for item in manifest["datasets"]
        if item["sport"] == "hockey" and item["league"] == "KHL" and item["kind"] == "seasonal_history"
    )

    assert khl_summary["status"] == "ok"
    assert khl_summary["issues"] == []
    assert khl_summary["coverage_policy"]["accepted_seasons"] == [2024]
    assert khl_dataset["coverage_policy"]["mode"] == "accepted_local_baseline"


def test_build_cache_manifest_attaches_snapshot_policy_to_runtime_dataset(tmp_path):
    cache_root = tmp_path / "data" / "cache"
    _build_primary_hockey_cache(cache_root)
    _write_json(
        cache_root / "football" / "EPL_matches.json",
        [_match("2025-01-01", "Arsenal", "Chelsea", 2, 1, game_id="epl-raw")],
    )
    _write_json(
        cache_root / "football" / "EPL_with_odds_matches.json",
        [_match("2025-01-02", "Arsenal", "Chelsea", 2, 0, game_id="epl-odds", home_odds=2.1, away_odds=3.2)],
    )
    _write_json(
        cache_root / "cache_policy.json",
        {
            "snapshot_with_odds": {
                "football": {
                    "EPL": {
                        "mode": "accepted_runtime_snapshot",
                        "accepted_dataset_kind": "snapshot_with_odds",
                        "note": "runtime baseline",
                    }
                }
            }
        },
    )

    manifest = build_cache_manifest(cache_root=cache_root)
    epl_summary = manifest["summary"]["football"]["EPL"]
    epl_dataset = next(
        item for item in manifest["datasets"]
        if item["sport"] == "football" and item["league"] == "EPL" and item["kind"] == "snapshot_with_odds"
    )

    assert epl_summary["coverage_policy"]["accepted_dataset_kind"] == "snapshot_with_odds"
    assert epl_dataset["coverage_policy"]["mode"] == "accepted_runtime_snapshot"
