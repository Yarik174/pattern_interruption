import importlib.util
import json
from pathlib import Path

from src import system_runtime


ROOT = Path(__file__).resolve().parents[2]


def _load_system_run_module():
    module_path = ROOT / "scripts" / "system_run.py"
    spec = importlib.util.spec_from_file_location("system_run_script", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_doctor_report_marks_runtime_ready(monkeypatch):
    manifest = {
        "generated_at": "2026-03-10T01:00:00",
        "summary": {
            "hockey": {"NHL": {"full_cache_matches": 10}},
            "football": {"EPL": {"full_cache_matches": 20}},
        },
        "datasets": [],
    }

    monkeypatch.setenv("SESSION_SECRET", "secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///local.db")
    monkeypatch.setenv("RAPIDAPI_KEY", "rapid")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(system_runtime, "load_manifest", lambda: manifest)
    monkeypatch.setattr(system_runtime, "verify_manifest", lambda manifest=None: {"ok": True, "critical": [], "warnings": []})
    monkeypatch.setattr(system_runtime, "get_cache_summary", lambda manifest=None: (manifest or {}).get("summary", {}))
    monkeypatch.setattr(system_runtime, "get_last_refresh_info", lambda: {"last_refresh": "2026-03-10T02:00:00", "needs_refresh": False})
    monkeypatch.setattr(system_runtime, "MANIFEST_FILE", Path("data/cache/cache_manifest.json"))
    monkeypatch.setattr(system_runtime, "REFRESH_STATE_FILE", str(Path("data/cache/refresh_state.json")))
    monkeypatch.setattr(system_runtime.Path, "exists", lambda self: True)

    report = system_runtime.build_doctor_report()

    assert report["ok"] is True
    assert report["readiness"]["monitor_ready"] is True
    assert report["sports"]["football"]["matches"] == 20
    assert report["checks"]["cache_verify"]["warnings"] == []


def test_format_doctor_report_includes_readiness_and_sports():
    report = {
        "timestamp": "2026-03-10T03:00:00",
        "manifest_generated_at": "2026-03-10T02:00:00",
        "readiness": {"web_ready": True, "cache_ready": True, "monitor_ready": False, "telegram_ready": True},
        "checks": {
            "env": {
                "session_secret": {"ok": True, "required": True},
            },
            "files": {
                "cache_manifest": {"ok": True, "path": "data/cache/cache_manifest.json"},
            },
            "cache_verify": {"ok": True, "warnings": [], "critical": []},
        },
        "sports": {"hockey": {"league_count": 5, "matches": 1000}},
        "refresh_info": {"last_refresh": "2026-03-10T02:00:00", "hours_since": 1.0, "needs_refresh": False},
    }

    text = system_runtime.format_doctor_report(report)

    assert "SYSTEM DOCTOR" in text
    assert "monitor_ready" in text
    assert "hockey" in text
    assert "last_refresh" in text


def test_system_run_doctor_and_monitor_once_dry_run(monkeypatch, capsys):
    module = _load_system_run_module()

    monkeypatch.setattr(
        module,
        "build_doctor_report",
        lambda: {
            "ok": True,
            "timestamp": "2026-03-10T03:00:00",
            "manifest_generated_at": "2026-03-10T02:00:00",
            "readiness": {"web_ready": True, "cache_ready": True, "monitor_ready": True, "telegram_ready": False},
            "checks": {"env": {}, "files": {}, "cache_verify": {"ok": True, "warnings": [], "critical": []}},
            "sports": {},
            "refresh_info": {},
        },
    )

    assert module.main(["doctor", "--json"]) == 0
    doctor_payload = json.loads(capsys.readouterr().out)
    assert doctor_payload["ok"] is True

    class _Monitor:
        def __init__(self, check_interval, dry_run):
            self.check_interval = check_interval
            self.dry_run = dry_run

        def check_now(self):
            return {
                "matches_found": 2,
                "predictions_created": 1,
                "notifications_sent": 0,
                "dry_run": True,
                "decisions": [
                    {"league": "NHL", "home_team": "AAA", "away_team": "BBB", "status": "candidate", "reason": "odds_in_target_range", "bet_on": "home", "target_odds": 2.4},
                    {"league": "NBA", "home_team": "CCC", "away_team": "DDD", "status": "skipped", "reason": "odds_out_of_range", "bet_on": None, "target_odds": None},
                ],
            }

    monkeypatch.setattr(module, "AutoMonitor", _Monitor)
    monkeypatch.setattr(module, "set_auto_monitor", lambda monitor: monitor)

    assert module.main(["monitor", "--once", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "DRY RUN MONITOR" in output
    assert "status=candidate" in output


def test_system_run_parser_uses_dry_run_monitor_by_default():
    module = _load_system_run_module()
    parser = module.build_parser()

    args = parser.parse_args(["run"])
    live_args = parser.parse_args(["run", "--live-monitor"])

    assert args.dry_run_monitor is True
    assert live_args.dry_run_monitor is False
