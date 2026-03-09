from src.cache_catalog import build_cache_manifest, get_best_dataset, verify_manifest


def test_real_cache_manifest_contains_primary_hockey_and_snapshot_sports():
    manifest = build_cache_manifest()
    summary = manifest["summary"]

    assert summary["hockey"]["NHL"]["full_cache_matches"] > 0
    assert summary["hockey"]["KHL"]["full_cache_matches"] > 0
    assert summary["football"]["EPL"]["full_cache_matches"] > 0
    assert summary["basketball"]["NBA"]["full_cache_matches"] > 0
    assert summary["volleyball"]["PlusLiga"]["full_cache_matches"] > 0

    assert get_best_dataset("hockey", "NHL", manifest=manifest)["kind"] == "seasonal_history"
    assert get_best_dataset("football", "EPL", prefer_odds=True, manifest=manifest)["kind"] == "snapshot_with_odds"


def test_real_cache_manifest_no_longer_contains_test_snapshot_warnings():
    manifest = build_cache_manifest()
    verification = verify_manifest(manifest)

    assert all("test dataset present" not in warning for warning in verification["warnings"])
    assert all("partial dataset: hockey/" not in warning for warning in verification["warnings"])
    assert manifest["summary"]["hockey"]["KHL"]["coverage_policy"]["accepted_seasons"] == [2022, 2023, 2024]
    assert manifest["summary"]["football"]["EPL"]["coverage_policy"]["accepted_dataset_kind"] == "snapshot_with_odds"
    assert manifest["summary"]["basketball"]["NBA"]["coverage_policy"]["accepted_dataset_kind"] == "snapshot_with_odds"
    assert manifest["summary"]["volleyball"]["PlusLiga"]["coverage_policy"]["accepted_dataset_kind"] == "snapshot_history"
