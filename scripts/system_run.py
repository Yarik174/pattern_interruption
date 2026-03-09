#!/usr/bin/env python3
"""
Операционный запуск системы: doctor, dry-run monitor и единый web run.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.odds_monitor import AutoMonitor, set_auto_monitor
from src.system_runtime import build_doctor_report, format_doctor_report


def _print_json(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _load_app_module(start_background: bool = False):
    os.environ["START_BACKGROUND"] = "1" if start_background else "0"
    app_module = importlib.import_module("app")
    flask_app = app_module.create_app(testing=False, start_background=start_background)
    return app_module, flask_app


def _format_dry_run_result(result: dict) -> str:
    lines = []
    lines.append("DRY RUN MONITOR")
    lines.append("=" * 72)
    lines.append(f"matches_found: {result.get('matches_found', 0)}")
    lines.append(f"candidates: {result.get('predictions_created', 0)}")
    lines.append("")
    for decision in result.get("decisions", []):
        match_line = f"{decision.get('league') or '-'} | {decision.get('home_team') or '-'} vs {decision.get('away_team') or '-'}"
        detail_line = (
            f"  status={decision.get('status')} reason={decision.get('reason')} "
            f"bet_on={decision.get('bet_on')} odds={decision.get('target_odds')}"
        )
        lines.append(match_line)
        lines.append(detail_line)
    return "\n".join(lines)


def cmd_doctor(args) -> int:
    report = build_doctor_report()
    if args.json:
        _print_json(report)
    else:
        print(format_doctor_report(report))
    return 0 if report.get("ok") else 1


def cmd_monitor(args) -> int:
    os.environ["START_BACKGROUND"] = "0"
    if not args.dry_run:
        _load_app_module(start_background=False)

    monitor = AutoMonitor(
        check_interval=args.interval,
        dry_run=args.dry_run,
    )
    set_auto_monitor(monitor)

    if args.once:
        result = monitor.check_now()
        if args.json:
            _print_json(result)
        elif args.dry_run:
            print(_format_dry_run_result(result))
        else:
            _print_json(result)
        return 0

    monitor.start()
    print(
        f"Monitor started: dry_run={monitor.dry_run}, interval={monitor.check_interval}s. "
        f"Press Ctrl+C to stop."
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        monitor.stop()
        return 0


def cmd_run(args) -> int:
    report = build_doctor_report()
    if not report["readiness"]["web_ready"]:
        print(format_doctor_report(report))
        return 1
    if args.with_monitor and not report["readiness"]["monitor_ready"]:
        print(format_doctor_report(report))
        return 1

    app_module, flask_app = _load_app_module(start_background=False)

    if args.with_monitor:
        monitor = AutoMonitor(
            check_interval=args.interval,
            dry_run=args.dry_run_monitor,
        )
        set_auto_monitor(monitor)
        monitor.start()

        def _stop_monitor(*_args):
            try:
                monitor.stop()
            finally:
                raise SystemExit(0)

        signal.signal(signal.SIGINT, _stop_monitor)
        signal.signal(signal.SIGTERM, _stop_monitor)

    flask_app.run(
        host=args.host,
        port=args.port,
        debug=args.debug,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operational runtime CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check runtime readiness")
    doctor.add_argument("--json", action="store_true", help="Print JSON instead of human-readable report")
    doctor.set_defaults(func=cmd_doctor)

    monitor = subparsers.add_parser("monitor", help="Run monitor once or as a long-running process")
    monitor.add_argument("--once", action="store_true", help="Run one check and exit")
    monitor.add_argument("--dry-run", action="store_true", help="Inspect matches without creating predictions or sending notifications")
    monitor.add_argument("--json", action="store_true", help="Print JSON result")
    monitor.add_argument("--interval", type=int, default=43200, help="Loop interval in seconds")
    monitor.set_defaults(func=cmd_monitor)

    run = subparsers.add_parser("run", help="Start web server and optional monitor")
    run.add_argument("--host", default="0.0.0.0", help="Bind host")
    run.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5001)), help="Bind port")
    run.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    run.add_argument("--no-monitor", dest="with_monitor", action="store_false", help="Start web without monitor")
    run.add_argument("--dry-run-monitor", action="store_true", help="Start monitor in dry-run mode")
    run.add_argument("--interval", type=int, default=43200, help="Monitor interval in seconds")
    run.set_defaults(with_monitor=True, func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
