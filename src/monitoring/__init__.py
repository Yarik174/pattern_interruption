"""
Monitoring package -- split from the monolithic odds_monitor.py.

Public API re-exports so that ``from src.monitoring import ...`` works as
a drop-in replacement for ``from src.odds_monitor import ...``.
"""
from __future__ import annotations

from src.monitoring.monitor import (
    AutoMonitor,
    MonitorGuard,
    OddsMonitor,
    get_auto_monitor,
    set_auto_monitor,
    start_auto_monitoring,
    MockOddsLoader,
)
from src.monitoring.quality_gate import QualityGate
from src.monitoring.decision_engine import DecisionEngine
from src.monitoring.odds_fetcher import OddsFetcher
from src.monitoring.notifier import NotificationDispatcher

__all__ = [
    # Core monitor classes
    "OddsMonitor",
    "AutoMonitor",
    "MonitorGuard",
    # Module-level helpers
    "get_auto_monitor",
    "set_auto_monitor",
    "start_auto_monitoring",
    "MockOddsLoader",
    # Sub-components
    "QualityGate",
    "DecisionEngine",
    "OddsFetcher",
    "NotificationDispatcher",
]
