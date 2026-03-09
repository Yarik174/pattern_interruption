"""
Операционный runtime-слой: doctor, безопасный bootstrap и форматирование статуса.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from src.cache_catalog import MANIFEST_FILE, get_cache_summary, load_manifest, verify_manifest
from src.data_refresh import REFRESH_STATE_FILE, get_last_refresh_info


def _env_check(name: str, *, required: bool) -> Dict[str, Any]:
    value = os.environ.get(name, "")
    return {
        "name": name,
        "required": required,
        "ok": bool(str(value).strip()),
    }


def _path_check(path: str | Path) -> Dict[str, Any]:
    path_obj = Path(path)
    return {
        "path": path_obj.as_posix(),
        "ok": path_obj.exists(),
    }


def build_doctor_report() -> Dict[str, Any]:
    """Собрать сводный отчёт по готовности runtime-контура."""
    manifest = load_manifest()
    verification = verify_manifest(manifest)
    cache_summary = get_cache_summary(manifest=manifest)
    refresh_info = get_last_refresh_info() or {}

    env_checks = {
        "session_secret": _env_check("SESSION_SECRET", required=True),
        "database_url": _env_check("DATABASE_URL", required=True),
        "rapidapi_key": _env_check("RAPIDAPI_KEY", required=True),
        "telegram_bot_token": _env_check("TELEGRAM_BOT_TOKEN", required=False),
        "telegram_chat_id": _env_check("TELEGRAM_CHAT_ID", required=False),
    }

    file_checks = {
        "cache_manifest": _path_check(MANIFEST_FILE),
        "refresh_state": _path_check(REFRESH_STATE_FILE),
    }

    sports = {
        sport: {
            "league_count": len(leagues),
            "matches": sum(item.get("full_cache_matches", 0) for item in leagues.values()),
        }
        for sport, leagues in cache_summary.items()
    }

    required_ok = all(item["ok"] for item in env_checks.values() if item["required"])
    cache_ok = verification["ok"] and not verification["warnings"]
    files_ok = all(item["ok"] for item in file_checks.values())
    telegram_ok = env_checks["telegram_bot_token"]["ok"] and env_checks["telegram_chat_id"]["ok"]

    readiness = {
        "web_ready": required_ok,
        "cache_ready": cache_ok and files_ok,
        "monitor_ready": required_ok and cache_ok and files_ok and env_checks["rapidapi_key"]["ok"],
        "telegram_ready": telegram_ok,
    }

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "ok": readiness["monitor_ready"],
        "checks": {
            "env": env_checks,
            "files": file_checks,
            "cache_verify": {
                "ok": verification["ok"] and not verification["warnings"],
                "critical": verification["critical"],
                "warnings": verification["warnings"],
            },
        },
        "readiness": readiness,
        "manifest_generated_at": manifest.get("generated_at"),
        "refresh_info": refresh_info,
        "sports": sports,
    }


def format_doctor_report(report: Dict[str, Any]) -> str:
    lines = []
    lines.append("SYSTEM DOCTOR")
    lines.append("=" * 72)
    lines.append(f"Timestamp: {report.get('timestamp', '-')}")
    lines.append(f"Manifest: {report.get('manifest_generated_at') or '-'}")
    lines.append("")
    lines.append("Readiness")
    lines.append("-" * 72)
    for name, ok in report.get("readiness", {}).items():
        lines.append(f"{name:<16} {'OK' if ok else 'MISSING'}")

    lines.append("")
    lines.append("Environment")
    lines.append("-" * 72)
    for key, item in report.get("checks", {}).get("env", {}).items():
        required = "required" if item.get("required") else "optional"
        lines.append(f"{key:<20} {'OK' if item.get('ok') else 'MISSING'} ({required})")

    lines.append("")
    lines.append("Files")
    lines.append("-" * 72)
    for key, item in report.get("checks", {}).get("files", {}).items():
        lines.append(f"{key:<20} {'OK' if item.get('ok') else 'MISSING'}  {item.get('path')}")

    lines.append("")
    lines.append("Cache")
    lines.append("-" * 72)
    cache_verify = report.get("checks", {}).get("cache_verify", {})
    lines.append(f"verify               {'OK' if cache_verify.get('ok') else 'WARN'}")
    for warning in cache_verify.get("warnings", []):
        lines.append(f"  warning: {warning}")
    for critical in cache_verify.get("critical", []):
        lines.append(f"  critical: {critical}")

    lines.append("")
    lines.append("Sports")
    lines.append("-" * 72)
    for sport, item in sorted(report.get("sports", {}).items()):
        lines.append(f"{sport:<12} leagues={item.get('league_count', 0):<3} matches={item.get('matches', 0)}")

    refresh_info = report.get("refresh_info", {})
    if refresh_info:
        lines.append("")
        lines.append("Refresh")
        lines.append("-" * 72)
        lines.append(f"last_refresh         {refresh_info.get('last_refresh') or '-'}")
        if "hours_since" in refresh_info:
            lines.append(f"hours_since          {refresh_info.get('hours_since')}")
        if "needs_refresh" in refresh_info:
            lines.append(f"needs_refresh        {refresh_info.get('needs_refresh')}")

    return "\n".join(lines)
