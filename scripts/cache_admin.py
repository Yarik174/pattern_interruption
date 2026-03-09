#!/usr/bin/env python3
"""
Операционный CLI для кэша и refresh-state.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cache_catalog import (
    archive_test_snapshots,
    build_cache_manifest,
    filter_manifest,
    load_manifest,
    save_manifest,
    verify_manifest,
)
from src.data_refresh import (
    backfill_hockey_history,
    build_refresh_state_from_manifest,
    EURO_HOCKEY_LEAGUES,
    refresh_all_historical_data,
    refresh_multi_league_data,
    refresh_nhl_data,
    rebuild_refresh_state_from_cache,
    save_refresh_state,
)


def _print_json(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _flatten_summary(summary):
    rows = []
    for sport in sorted(summary):
        for league in sorted(summary[sport]):
            rows.append(summary[sport][league])
    return rows


def _format_audit_report(manifest) -> str:
    lines = []
    lines.append("CACHE AUDIT")
    lines.append("=" * 72)
    lines.append(f"Generated at: {manifest.get('generated_at', '-')}")
    lines.append("")
    lines.append("Summary")
    lines.append("-" * 72)
    for item in _flatten_summary(manifest.get("summary", {})):
        flags = []
        if item.get("has_training_history"):
            flags.append("training")
        if item.get("has_runtime_history"):
            flags.append("runtime")
        lines.append(
            f"{item['sport']:<12} {item['league']:<18} "
            f"{item.get('full_cache_matches', 0):>6} matches  "
            f"{item.get('kind') or '-':<18} {','.join(flags) or '-'}"
        )
        lines.append(
            f"  date: {item.get('date_min') or '-'} -> {item.get('date_max') or '-'}; "
            f"datasets={item.get('dataset_count', 0)}; status={item.get('status') or '-'}"
        )
        if item.get("coverage_policy"):
            policy = item["coverage_policy"]
            seasons = ",".join(str(season) for season in policy.get("accepted_seasons", [])) or "-"
            lines.append(f"  policy: {policy.get('mode', 'accepted_local_baseline')} seasons={seasons}")
            if policy.get("note"):
                lines.append(f"  note: {policy['note']}")
        if item.get("issues"):
            lines.append(f"  issues: {'; '.join(item['issues'])}")

    lines.append("")
    lines.append("Datasets")
    lines.append("-" * 72)
    for dataset in manifest.get("datasets", []):
        lines.append(
            f"{dataset['id']} | {dataset['sport']}/{dataset['league']} | "
            f"{dataset['kind']} | {dataset['records']} rec | status={dataset['status']}"
        )
        lines.append(f"  files: {', '.join(dataset.get('files', [])) or '-'}")
        if dataset.get("coverage_policy"):
            policy = dataset["coverage_policy"]
            seasons = ",".join(str(season) for season in policy.get("accepted_seasons", [])) or "-"
            lines.append(f"  policy: {policy.get('mode', 'accepted_local_baseline')} seasons={seasons}")
        if dataset.get("issues"):
            lines.append(f"  issues: {'; '.join(dataset['issues'])}")

    return "\n".join(lines)


def cmd_audit(args) -> int:
    manifest = build_cache_manifest()
    filtered = filter_manifest(manifest, sport=args.sport, league=args.league)
    if args.json:
        _print_json(filtered)
    else:
        print(_format_audit_report(filtered))
    return 0


def cmd_rebuild_manifest(args) -> int:
    manifest = build_cache_manifest()
    save_manifest(manifest)
    summary_count = sum(len(leagues) for leagues in manifest.get("summary", {}).values())
    print(f"Manifest rebuilt: {summary_count} league summaries, {len(manifest.get('datasets', []))} datasets")
    return 0


def cmd_rebuild_refresh_state(args) -> int:
    result = rebuild_refresh_state_from_cache()
    _print_json(result)
    return 0


def cmd_verify(args) -> int:
    manifest = load_manifest()
    result = verify_manifest(manifest)
    print("VERIFY")
    print("=" * 72)
    if result["critical"]:
        print("Critical:")
        for line in result["critical"]:
            print(f"- {line}")
    else:
        print("Critical: none")

    if result["warnings"]:
        print("Warnings:")
        for line in result["warnings"]:
            print(f"- {line}")
    else:
        print("Warnings: none")
    return 0 if result["ok"] else 1


def cmd_archive_test_snapshots(args) -> int:
    result = archive_test_snapshots(dry_run=args.dry_run)
    if not args.dry_run:
        manifest = build_cache_manifest()
        save_manifest(manifest)
        state = build_refresh_state_from_manifest(
            manifest,
            timestamp=result["timestamp"],
            source="cache_cleanup",
        )
        save_refresh_state(state)
        result["manifest_generated_at"] = manifest.get("generated_at")

    if args.json:
        _print_json(result)
    else:
        print(f"Test snapshots found: {result['files_found']}")
        for item in result["items"]:
            print(f"- {item['status']}: {item['source']} -> {item['destination']}")
    return 0 if result["failed"] == 0 else 1


def cmd_backfill_hockey(args) -> int:
    result = backfill_hockey_history(
        leagues=[args.league] if args.league != "all" else list(EURO_HOCKEY_LEAGUES),
        from_season=args.from_season,
        to_season=args.to_season,
        include_current=args.include_current,
        refresh_existing_current=args.refresh_existing_current,
        dry_run=args.dry_run,
    )
    _print_json(result)
    return 0


def _sync_single_league(league: str) -> dict:
    if league == "NHL":
        return refresh_nhl_data()
    return refresh_multi_league_data(league)


def cmd_sync_hockey(args) -> int:
    if args.league == "all":
        result = refresh_all_historical_data(force=args.force)
        _print_json(result)
        return 0

    refreshed = _sync_single_league(args.league)
    manifest = build_cache_manifest()
    save_manifest(manifest)
    state = build_refresh_state_from_manifest(
        manifest,
        refreshed_results={args.league: refreshed},
        source="refresh",
    )
    save_refresh_state(state)

    payload = {
        "timestamp": state["last_refresh"],
        "league": args.league,
        "refresh_result": refreshed,
        "state_result": state["last_results"][args.league],
    }
    _print_json(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cache admin for multi-sport history")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="Scan cache and print report without writing files")
    audit.add_argument("--json", action="store_true", help="Print JSON instead of human-readable report")
    audit.add_argument("--sport", choices=["hockey", "football", "basketball", "volleyball"], help="Filter by sport")
    audit.add_argument("--league", help="Filter by league")
    audit.set_defaults(func=cmd_audit)

    rebuild_manifest = subparsers.add_parser("rebuild-manifest", help="Rebuild data/cache/cache_manifest.json")
    rebuild_manifest.set_defaults(func=cmd_rebuild_manifest)

    rebuild_state = subparsers.add_parser("rebuild-refresh-state", help="Rebuild data/cache/refresh_state.json from manifest")
    rebuild_state.set_defaults(func=cmd_rebuild_refresh_state)

    verify = subparsers.add_parser("verify", help="Verify primary datasets and print issues")
    verify.set_defaults(func=cmd_verify)

    archive = subparsers.add_parser("archive-test-snapshots", help="Move *_test_matches.json outside the live cache")
    archive.add_argument("--dry-run", action="store_true", help="Show what would be archived without moving files")
    archive.add_argument("--json", action="store_true", help="Print JSON result")
    archive.set_defaults(func=cmd_archive_test_snapshots)

    sync = subparsers.add_parser("sync-hockey", help="Run manual refresh for NHL/KHL/SHL/Liiga/DEL")
    sync.add_argument(
        "--league",
        choices=["all", "NHL", "KHL", "SHL", "Liiga", "DEL"],
        default="all",
        help="Refresh specific league or all hockey leagues",
    )
    sync.add_argument("--force", action="store_true", help="Ignore 20-hour refresh interval for all-league sync")
    sync.set_defaults(func=cmd_sync_hockey)

    backfill = subparsers.add_parser("backfill-hockey", help="Deep backfill for KHL/SHL/Liiga/DEL seasons")
    backfill.add_argument(
        "--league",
        choices=["all", "KHL", "SHL", "Liiga", "DEL"],
        default="all",
        help="Backfill one league or all European hockey leagues",
    )
    backfill.add_argument("--from-season", type=int, help="Inclusive lower season bound, e.g. 2008")
    backfill.add_argument("--to-season", type=int, help="Inclusive upper season bound, e.g. 2025")
    backfill.add_argument("--dry-run", action="store_true", help="Plan backfill without downloading data")
    backfill.add_argument(
        "--refresh-existing-current",
        action="store_true",
        help="Refresh the current rolling season even if its cache file already exists",
    )
    backfill.add_argument(
        "--exclude-current",
        dest="include_current",
        action="store_false",
        help="Exclude the current rolling season from the plan",
    )
    backfill.set_defaults(include_current=True, func=cmd_backfill_hockey)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
