"""
Backwards-compatibility shim.

All classes and functions have moved to ``src.monitoring.*``.
This module re-exports them so that existing ``from src.odds_monitor import ...``
statements continue to work unchanged.

Module-level functions (get_auto_monitor, set_auto_monitor,
start_auto_monitoring) are redefined here so that tests that
monkeypatch attributes on this module (e.g. ``_monitor_thread_started``,
``MonitorGuard``, ``get_auto_monitor``) still work correctly.
"""
import time  # noqa: F401 -- kept so monkeypatch targets still resolve
import os    # noqa: F401

from src.monitoring.monitor import (  # noqa: F401
    OddsMonitor,
    AutoMonitor,
    MonitorGuard,
    MockOddsLoader,
)

import src.monitoring.monitor as _monitor_mod  # canonical module for globals

import logging as _logging

_logger = _logging.getLogger(__name__)

# Module-level state -- mirrored from src.monitoring.monitor so that
# monkeypatching ``odds_monitor_module._guard`` etc. works in tests.
_global_monitor = None
_monitor_thread_started = False
_guard = None


def get_auto_monitor() -> AutoMonitor:
    """Return the global AutoMonitor singleton."""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = AutoMonitor(check_interval=43200)
    # Keep the canonical module in sync
    _monitor_mod._global_monitor = _global_monitor
    return _global_monitor


def set_auto_monitor(monitor):
    """Explicitly set the global AutoMonitor instance."""
    global _global_monitor
    _global_monitor = monitor
    _monitor_mod._global_monitor = monitor
    return _global_monitor


def start_auto_monitoring():
    """Start auto-monitoring (called at server startup)."""
    global _monitor_thread_started, _guard
    if _monitor_thread_started:
        return
    if _guard is None:
        _guard = MonitorGuard()
    if not _guard.acquire():
        _logger.info("AutoMonitor guard active, skipping start")
        return

    monitor = get_auto_monitor()
    if not monitor.is_running():
        monitor.start()
        _monitor_thread_started = True
    # Keep canonical module in sync
    _monitor_mod._monitor_thread_started = _monitor_thread_started
    _monitor_mod._guard = _guard


__all__ = [
    "OddsMonitor",
    "AutoMonitor",
    "MonitorGuard",
    "MockOddsLoader",
    "get_auto_monitor",
    "set_auto_monitor",
    "start_auto_monitoring",
]
