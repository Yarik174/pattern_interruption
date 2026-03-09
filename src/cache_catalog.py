"""
Канонический каталог локального кэша для мультиспорта.

Не мигрирует старые файлы, а строит единый manifest поверх существующих форматов.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from src.sports_config import SportType

logger = logging.getLogger(__name__)

CACHE_ROOT = Path("data/cache")
MANIFEST_FILE = CACHE_ROOT / "cache_manifest.json"

PRIMARY_HOCKEY_LEAGUES = {"NHL", "KHL", "SHL", "Liiga", "DEL"}
EURO_LEAGUE_IDS = {
    "KHL": 35,
    "SHL": 47,
    "Liiga": 16,
    "DEL": 19,
}
LEAGUE_ID_TO_NAME = {league_id: league for league, league_id in EURO_LEAGUE_IDS.items()}
SNAPSHOT_LEAGUE_ALIASES = {
    "football": {
        "LaLiga": "La Liga",
        "SerieA": "Serie A",
        "Ligue1": "Ligue 1",
    },
    "basketball": {
        "VTB": "VTB League",
    },
    "volleyball": {
        "SerieA": "Serie A Italy",
        "Superliga": "Superliga Russia",
        "CEV": "CEV Champions",
    },
}
SPORT_SLUGS = {
    SportType.HOCKEY: "hockey",
    SportType.FOOTBALL: "football",
    SportType.BASKETBALL: "basketball",
    SportType.VOLLEYBALL: "volleyball",
}


def _slugify(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")


def _ensure_path(path: Path | str) -> Path:
    return path if isinstance(path, Path) else Path(path)


def _json_relative(path: Path, cache_root: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _load_json(path: Path) -> Tuple[Any, Optional[str]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle), None
    except Exception as exc:
        return None, f"{path.name}: {exc}"


def _normalize_sport(sport: str | SportType) -> str:
    if isinstance(sport, SportType):
        return sport.name.lower()
    return str(sport).strip().lower()


def _normalize_date(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if parsed is None or pd.isna(parsed):
        return None
    if getattr(parsed, "tzinfo", None) is not None:
        try:
            parsed = parsed.tz_convert("UTC").tz_localize(None)
        except TypeError:
            parsed = parsed.tz_localize(None)
    return parsed.isoformat()


def _normalize_match_record(record: Dict[str, Any], sport: str, league: str) -> Optional[Dict[str, Any]]:
    if not isinstance(record, dict):
        return None

    game_id = record.get("game_id") or record.get("id") or record.get("match_id")
    home_team = record.get("home_team")
    away_team = record.get("away_team")
    if not home_team or not away_team:
        return None

    home_score = record.get("home_score")
    away_score = record.get("away_score")
    if home_score is None:
        home_score = record.get("home_goals")
    if away_score is None:
        away_score = record.get("away_goals")

    home_win = record.get("home_win")
    if home_win is None and home_score is not None and away_score is not None:
        try:
            home_win = int(home_score) > int(away_score)
        except Exception:
            home_win = None
    elif home_win is not None:
        home_win = bool(home_win)

    normalized = {
        "game_id": str(game_id) if game_id is not None else None,
        "date": _normalize_date(record.get("date")),
        "home_team": home_team,
        "away_team": away_team,
        "home_score": int(home_score) if home_score is not None else None,
        "away_score": int(away_score) if away_score is not None else None,
        "home_win": home_win,
        "home_odds": record.get("home_odds"),
        "draw_odds": record.get("draw_odds"),
        "away_odds": record.get("away_odds"),
        "bookmaker": record.get("bookmaker"),
        "season": record.get("season"),
        "sport": sport,
        "league": league,
    }
    if record.get("overtime") is not None:
        normalized["overtime"] = record.get("overtime")
    if record.get("home_score_ht") is not None or record.get("away_score_ht") is not None:
        normalized["home_score_ht"] = record.get("home_score_ht")
        normalized["away_score_ht"] = record.get("away_score_ht")
    if record.get("home_sets") is not None or record.get("away_sets") is not None:
        normalized["home_sets"] = record.get("home_sets")
        normalized["away_sets"] = record.get("away_sets")
    if record.get("set_scores") is not None:
        normalized["set_scores"] = record.get("set_scores")
    if record.get("periods") is not None:
        normalized["periods"] = record.get("periods")
    return normalized


def _record_key(record: Dict[str, Any]) -> Tuple[Any, Any, Any, Any]:
    return (
        record.get("game_id"),
        record.get("date"),
        record.get("home_team"),
        record.get("away_team"),
    )


def _finalize_dataset(
    *,
    cache_root: Path,
    sport: str,
    league: str,
    source: str,
    kind: str,
    format_name: str,
    files: Iterable[Path],
    seasons: Iterable[Any],
    for_training: bool,
    for_runtime: bool,
    metadata_expected_seasons: Optional[Iterable[Any]] = None,
    extra_issues: Optional[List[str]] = None,
) -> Dict[str, Any]:
    issues = list(extra_issues or [])
    files = list(files)
    normalized_records: List[Dict[str, Any]] = []
    corrupt_files = 0
    duplicate_count = 0

    for file_path in files:
        payload, error = _load_json(file_path)
        if error:
            corrupt_files += 1
            issues.append(f"corrupt file: {error}")
            continue
        if not isinstance(payload, list):
            corrupt_files += 1
            issues.append(f"unexpected payload in {file_path.name}: expected list")
            continue

        seen_keys = set()
        for row in payload:
            normalized = _normalize_match_record(row, sport=sport, league=league)
            if not normalized:
                continue
            key = _record_key(normalized)
            if key in seen_keys:
                duplicate_count += 1
                continue
            seen_keys.add(key)
            normalized_records.append(normalized)

    if duplicate_count:
        issues.append(f"duplicate records ignored: {duplicate_count}")

    expected = {str(item) for item in metadata_expected_seasons or [] if item is not None}
    actual = {str(item) for item in seasons if item is not None}
    missing_from_metadata = sorted(expected - actual)
    if missing_from_metadata:
        issues.append(f"metadata seasons without cached games: {', '.join(missing_from_metadata)}")

    unique_records: Dict[Tuple[Any, Any, Any, Any], Dict[str, Any]] = {}
    for row in normalized_records:
        unique_records.setdefault(_record_key(row), row)

    rows = list(unique_records.values())
    rows.sort(key=lambda item: (item.get("date") or "", item.get("game_id") or ""))
    date_values = [row["date"] for row in rows if row.get("date")]
    date_min = min(date_values) if date_values else None
    date_max = max(date_values) if date_values else None
    has_odds = any(
        row.get("home_odds") is not None or row.get("away_odds") is not None or row.get("draw_odds") is not None
        for row in rows
    )

    if rows:
        status = "partial" if issues else "ok"
    elif corrupt_files:
        status = "corrupt"
    else:
        status = "empty"

    return {
        "id": f"{sport}-{_slugify(league)}-{kind}",
        "sport": sport,
        "league": league,
        "source": source,
        "kind": kind,
        "format": format_name,
        "files": [_json_relative(path, cache_root) for path in sorted(files)],
        "seasons": sorted({str(item) for item in seasons if item is not None}),
        "records": len(rows),
        "date_min": date_min,
        "date_max": date_max,
        "has_odds": has_odds,
        "for_training": for_training,
        "for_runtime": for_runtime,
        "status": status,
        "issues": issues,
    }


def _build_nhl_dataset(cache_root: Path) -> Dict[str, Any]:
    files = sorted(cache_root.glob("season_*.json"))
    seasons = [path.stem.replace("season_", "") for path in files]
    return _finalize_dataset(
        cache_root=cache_root,
        sport="hockey",
        league="NHL",
        source="nhl_api",
        kind="seasonal_history",
        format_name="nhl_season_json",
        files=files,
        seasons=seasons,
        for_training=True,
        for_runtime=True,
    )


def _build_euro_hockey_datasets(cache_root: Path) -> List[Dict[str, Any]]:
    datasets = []
    leagues_root = cache_root / "leagues"
    for league, league_id in EURO_LEAGUE_IDS.items():
        files = sorted(leagues_root.glob(f"games_{league_id}_*.json"))
        seasons = [path.stem.split("_")[-1] for path in files]
        season_meta_file = leagues_root / f"seasons_{league_id}.json"
        expected_seasons: List[Any] = []
        issues: List[str] = []
        if season_meta_file.exists():
            payload, error = _load_json(season_meta_file)
            if error:
                issues.append(f"corrupt metadata: {error}")
            elif isinstance(payload, list):
                expected_seasons = payload
            else:
                issues.append(f"unexpected metadata payload in {season_meta_file.name}")

        datasets.append(
            _finalize_dataset(
                cache_root=cache_root,
                sport="hockey",
                league=league,
                source="api_sports_hockey",
                kind="seasonal_history",
                format_name="api_sports_games_json",
                files=files,
                seasons=seasons,
                for_training=True,
                for_runtime=True,
                metadata_expected_seasons=expected_seasons,
                extra_issues=issues,
            )
        )
    return datasets


def _canonical_snapshot_league(sport: str, raw_league: str) -> str:
    return SNAPSHOT_LEAGUE_ALIASES.get(sport, {}).get(raw_league, raw_league)


def _build_snapshot_datasets(cache_root: Path) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[str, str, str], List[Path]] = defaultdict(list)
    kind_meta: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    for sport in ("hockey", "football", "basketball", "volleyball"):
        sport_root = cache_root / sport
        if not sport_root.exists():
            continue
        for path in sorted(sport_root.glob("*.json")):
            if path.name == "cache_manifest.json":
                continue
            stem = path.stem
            if stem.endswith("_with_odds_matches"):
                raw_league = stem[: -len("_with_odds_matches")]
                kind = "snapshot_with_odds"
            elif stem.endswith("_matches"):
                raw_league = stem[: -len("_matches")]
                kind = "snapshot_history"
            else:
                continue

            is_test = raw_league.endswith("_test") or raw_league.endswith("-test")
            if is_test:
                raw_league = raw_league.rsplit("_test", 1)[0]
                kind = "auxiliary"

            if sport == "hockey" and kind != "auxiliary":
                kind = "auxiliary"

            league = _canonical_snapshot_league(sport, raw_league)
            group_key = (sport, league, kind)
            grouped[group_key].append(path)
            kind_meta[group_key] = {
                "source": "flashscore_scrape",
                "format": "flashscore_matches_json",
                "for_training": False,
                "for_runtime": sport != "hockey" and kind != "auxiliary",
            }

    datasets = []
    for (sport, league, kind), files in sorted(grouped.items()):
        datasets.append(
            _finalize_dataset(
                cache_root=cache_root,
                sport=sport,
                league=league,
                source=kind_meta[(sport, league, kind)]["source"],
                kind=kind,
                format_name=kind_meta[(sport, league, kind)]["format"],
                files=files,
                seasons=[],
                for_training=kind_meta[(sport, league, kind)]["for_training"],
                for_runtime=kind_meta[(sport, league, kind)]["for_runtime"],
                extra_issues=["test snapshot"] if kind == "auxiliary" and any("test" in file.name for file in files) else [],
            )
        )
    return datasets


def _build_auxiliary_datasets(cache_root: Path) -> List[Dict[str, Any]]:
    datasets = []
    period_path = cache_root / "period_data.json"
    if period_path.exists():
        payload, error = _load_json(period_path)
        issues = []
        if error:
            issues.append(f"corrupt auxiliary file: {error}")
            records = 0
            status = "corrupt"
        elif isinstance(payload, dict):
            records = len(payload)
            status = "ok"
        else:
            records = 0
            status = "empty"
            issues.append("unexpected payload in period_data.json")

        datasets.append(
            {
                "id": "hockey-nhl-aux-period-data",
                "sport": "hockey",
                "league": "NHL",
                "source": "nhl_api",
                "kind": "auxiliary",
                "format": "period_data_json",
                "files": [_json_relative(period_path, cache_root)],
                "seasons": [],
                "records": records,
                "date_min": None,
                "date_max": None,
                "has_odds": False,
                "for_training": False,
                "for_runtime": False,
                "status": status,
                "issues": issues or ["auxiliary period data only"],
            }
        )
    return datasets


def _dataset_sort_key(dataset: Dict[str, Any], prefer_odds: bool = False, use_for: str = "runtime") -> Tuple[int, int, int]:
    sport = dataset.get("sport")
    league = dataset.get("league")
    kind = dataset.get("kind")
    status_order = {"ok": 0, "partial": 1, "empty": 2, "corrupt": 3}

    if sport == "hockey" and league in PRIMARY_HOCKEY_LEAGUES:
        kind_order = {"seasonal_history": 0, "snapshot_with_odds": 1, "snapshot_history": 2, "auxiliary": 3}
    elif prefer_odds and use_for == "runtime":
        kind_order = {"snapshot_with_odds": 0, "snapshot_history": 1, "seasonal_history": 2, "auxiliary": 3}
    else:
        kind_order = {"seasonal_history": 0, "snapshot_with_odds": 1, "snapshot_history": 2, "auxiliary": 3}

    return (
        kind_order.get(kind, 9),
        status_order.get(dataset.get("status"), 9),
        -int(dataset.get("records", 0)),
    )


def _build_summary(datasets: List[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for dataset in datasets:
        grouped[(dataset["sport"], dataset["league"])].append(dataset)

    summary: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for (sport, league), items in sorted(grouped.items()):
        runtime_candidates = [
            item for item in items
            if item.get("for_runtime") and item.get("kind") != "auxiliary" and item.get("status") not in {"corrupt", "empty"}
        ]
        training_candidates = [
            item for item in items
            if item.get("for_training") and item.get("kind") != "auxiliary" and item.get("status") not in {"corrupt", "empty"}
        ]
        primary = None
        if runtime_candidates:
            primary = sorted(runtime_candidates, key=lambda row: _dataset_sort_key(row, prefer_odds=True))[0]
        elif training_candidates:
            primary = sorted(training_candidates, key=lambda row: _dataset_sort_key(row))[0]

        flattened_issues: List[str] = []
        issue_order = []
        if primary is not None:
            issue_order.append(primary)
        issue_order.extend(item for item in items if item is not primary)
        for item in issue_order:
            for issue in item.get("issues", []):
                if issue not in flattened_issues:
                    flattened_issues.append(issue)

        summary[sport][league] = {
            "sport": sport,
            "league": league,
            "full_cache_matches": int(primary["records"]) if primary else 0,
            "date_min": primary.get("date_min") if primary else None,
            "date_max": primary.get("date_max") if primary else None,
            "dataset_count": len(items),
            "has_training_history": bool(training_candidates),
            "has_runtime_history": bool(runtime_candidates),
            "issues": flattened_issues,
            "source": primary.get("source") if primary else None,
            "kind": primary.get("kind") if primary else None,
            "status": primary.get("status") if primary else "empty",
        }
    return {sport: dict(leagues) for sport, leagues in summary.items()}


def build_cache_manifest(cache_root: Path | str | None = None) -> Dict[str, Any]:
    cache_root = _ensure_path(cache_root or CACHE_ROOT)
    datasets = [
        _build_nhl_dataset(cache_root),
        *_build_euro_hockey_datasets(cache_root),
        *_build_snapshot_datasets(cache_root),
        *_build_auxiliary_datasets(cache_root),
    ]
    datasets.sort(key=lambda item: (item["sport"], item["league"], item["kind"], item["id"]))
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "datasets": datasets,
        "summary": _build_summary(datasets),
    }


def save_manifest(manifest: Dict[str, Any], manifest_path: Path | str | None = None):
    manifest_path = _ensure_path(manifest_path or MANIFEST_FILE)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)


def load_manifest(
    manifest_path: Path | str | None = None,
    cache_root: Path | str | None = None,
    rebuild: bool = False,
) -> Dict[str, Any]:
    manifest_path = _ensure_path(manifest_path or MANIFEST_FILE)
    cache_root = _ensure_path(cache_root or CACHE_ROOT)
    if not rebuild and manifest_path.exists():
        payload, error = _load_json(manifest_path)
        if error is None and isinstance(payload, dict) and "datasets" in payload and "summary" in payload:
            return payload
        logger.warning("Manifest read failed, rebuilding: %s", error or "invalid shape")
    return build_cache_manifest(cache_root=cache_root)


def get_cache_summary(
    manifest: Optional[Dict[str, Any]] = None,
    *,
    manifest_path: Path | str | None = None,
    cache_root: Path | str | None = None,
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    manifest = manifest or load_manifest(manifest_path=manifest_path, cache_root=cache_root)
    return manifest.get("summary", {})


def _resolve_summary_item(summary: Dict[str, Dict[str, Dict[str, Any]]], sport: str, league: str) -> Optional[Dict[str, Any]]:
    return summary.get(sport, {}).get(league)


def get_best_dataset(
    sport: str | SportType,
    league: str,
    *,
    prefer_odds: bool = False,
    use_for: str = "runtime",
    manifest: Optional[Dict[str, Any]] = None,
    manifest_path: Path | str | None = None,
    cache_root: Path | str | None = None,
) -> Optional[Dict[str, Any]]:
    sport_slug = _normalize_sport(sport)
    manifest = manifest or load_manifest(manifest_path=manifest_path, cache_root=cache_root)
    candidates = []
    for dataset in manifest.get("datasets", []):
        if dataset.get("sport") != sport_slug or dataset.get("league") != league:
            continue
        if dataset.get("kind") == "auxiliary":
            continue
        if dataset.get("status") in {"corrupt", "empty"}:
            continue
        if use_for == "training" and not dataset.get("for_training"):
            continue
        if use_for == "runtime" and not dataset.get("for_runtime"):
            continue
        candidates.append(dataset)

    if not candidates:
        return None
    return sorted(candidates, key=lambda row: _dataset_sort_key(row, prefer_odds=prefer_odds, use_for=use_for))[0]


def load_history(
    sport: str | SportType,
    league: str,
    *,
    prefer_odds: bool = False,
    manifest: Optional[Dict[str, Any]] = None,
    manifest_path: Path | str | None = None,
    cache_root: Path | str | None = None,
) -> List[Dict[str, Any]]:
    cache_root = _ensure_path(cache_root or CACHE_ROOT)
    manifest = manifest or load_manifest(manifest_path=manifest_path, cache_root=cache_root)
    dataset = get_best_dataset(
        sport,
        league,
        prefer_odds=prefer_odds,
        use_for="runtime",
        manifest=manifest,
        manifest_path=manifest_path,
        cache_root=cache_root,
    )
    if dataset is None:
        return []

    sport_slug = _normalize_sport(sport)
    rows: Dict[Tuple[Any, Any, Any, Any], Dict[str, Any]] = {}
    for rel_path in dataset.get("files", []):
        file_path = _ensure_path(rel_path)
        if not file_path.is_absolute():
            file_path = Path(rel_path)
        payload, error = _load_json(file_path)
        if error or not isinstance(payload, list):
            continue
        for record in payload:
            normalized = _normalize_match_record(record, sport=sport_slug, league=league)
            if normalized is None:
                continue
            rows.setdefault(_record_key(normalized), normalized)

    items = list(rows.values())
    items.sort(key=lambda row: (row.get("date") or "", row.get("game_id") or ""))
    return items


def filter_manifest(manifest: Dict[str, Any], *, sport: Optional[str] = None, league: Optional[str] = None) -> Dict[str, Any]:
    sport = _normalize_sport(sport) if sport else None
    datasets = [
        item for item in manifest.get("datasets", [])
        if (sport is None or item.get("sport") == sport) and (league is None or item.get("league") == league)
    ]
    return {
        "generated_at": manifest.get("generated_at"),
        "datasets": datasets,
        "summary": _build_summary(datasets),
    }


def verify_manifest(manifest: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    manifest = manifest or load_manifest()
    critical: List[str] = []
    warnings: List[str] = []
    now = datetime.utcnow()

    grouped: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for dataset in manifest.get("datasets", []):
        grouped[(dataset["sport"], dataset["league"], dataset["kind"])].append(dataset)

        is_primary = dataset.get("kind") != "auxiliary" and (dataset.get("for_runtime") or dataset.get("for_training"))
        if is_primary and dataset.get("status") in {"corrupt", "empty"}:
            critical.append(
                f"{dataset['sport']}/{dataset['league']} ({dataset['kind']}): {dataset['status']}"
            )

        if "test snapshot" in dataset.get("issues", []):
            warnings.append(f"test dataset present: {dataset['sport']}/{dataset['league']} -> {dataset['id']}")

        date_max = dataset.get("date_max")
        if date_max and is_primary:
            try:
                age_days = (now - datetime.fromisoformat(date_max)).days
            except ValueError:
                age_days = None
            if age_days is not None and age_days > 730:
                warnings.append(
                    f"stale dataset: {dataset['sport']}/{dataset['league']} ({dataset['kind']}) age={age_days}d"
                )

        if any("duplicate records ignored" in issue for issue in dataset.get("issues", [])):
            warnings.append(f"duplicate records: {dataset['sport']}/{dataset['league']} -> {dataset['id']}")

    for (sport, league, kind), items in grouped.items():
        if kind == "auxiliary":
            continue
        if len(items) > 1:
            warnings.append(f"multiple datasets for same slot: {sport}/{league}/{kind} -> {len(items)}")

    return {
        "ok": not critical,
        "critical": critical,
        "warnings": warnings,
    }
