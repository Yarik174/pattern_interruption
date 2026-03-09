from src.cache_catalog import build_cache_manifest, get_best_dataset


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
