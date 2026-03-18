"""
Core monitoring loops and process guards.

Contains:
- OddsMonitor  -- simple callback-driven monitor (original API)
- AutoMonitor  -- full-featured monitor with decision engine
- MonitorGuard -- file-lock based singleton guard
- Module-level helpers (get_auto_monitor, start_auto_monitoring, ...)
"""
from __future__ import annotations

import atexit
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional

from src.monitoring.decision_engine import DecisionEngine
from src.monitoring.notifier import NotificationDispatcher
from src.monitoring.odds_fetcher import OddsFetcher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Module-level state (mirrors the old odds_monitor.py globals)
_global_monitor: Optional[AutoMonitor] = None
_monitor_thread_started: bool = False
_guard: Optional[MonitorGuard] = None  # type: ignore[name-defined]  # forward ref


# ---------------------------------------------------------------------------
# OddsMonitor -- simple callback-driven monitor
# ---------------------------------------------------------------------------

class OddsMonitor:
    """Simple background odds monitor using loader + callbacks."""

    def __init__(
        self,
        odds_loader: Any,
        prediction_callback: Callable,
        notification_callback: Optional[Callable] = None,
        check_interval: int = 7200,
    ) -> None:
        self.odds_loader = odds_loader
        self.prediction_callback = prediction_callback
        self.notification_callback = notification_callback
        self.check_interval = check_interval

        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._processed_events: set[str] = set()
        self._last_check: Optional[datetime] = None
        self._stats: dict[str, int] = {
            "total_checks": 0,
            "matches_found": 0,
            "predictions_created": 0,
            "notifications_sent": 0,
            "errors": 0,
        }

    def start(self) -> None:
        if self._running:
            logger.warning("Monitor already running")
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info(f"Odds monitor started (interval: {self.check_interval}s)")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Odds monitor stopped")

    def is_running(self) -> bool:
        return self._running

    def get_stats(self) -> dict:
        return {
            **self._stats,
            "is_running": self._running,
            "last_check": self._last_check.isoformat() if self._last_check else None,
            "processed_events": len(self._processed_events),
        }

    def check_now(self) -> dict:
        return self._check_odds()

    def _monitor_loop(self) -> None:
        while self._running:
            try:
                self._check_odds()
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                self._stats["errors"] += 1
            time.sleep(self.check_interval)

    def _check_odds(self) -> dict:
        self._last_check = datetime.utcnow()
        self._stats["total_checks"] += 1

        result: dict[str, Any] = {
            "timestamp": self._last_check.isoformat(),
            "matches_found": 0,
            "new_predictions": 0,
            "notifications_sent": 0,
        }

        try:
            if hasattr(self.odds_loader, "get_matches_with_odds"):
                matches = self.odds_loader.get_matches_with_odds(days_ahead=2)
            else:
                matches = self.odds_loader.get_upcoming_games(days_ahead=2)
            result["matches_found"] = len(matches)
            self._stats["matches_found"] += len(matches)

            # Deduplicate matches by event_id within this scan
            seen_events: set[str] = set()
            for match in matches:
                event_id = match.get("event_id")
                if event_id:
                    if event_id in self._processed_events or event_id in seen_events:
                        continue
                    seen_events.add(event_id)
                try:
                    prediction = self.prediction_callback(match)
                    if prediction:
                        result["new_predictions"] += 1
                        self._stats["predictions_created"] += 1
                        if event_id:
                            self._processed_events.add(event_id)
                        if self.notification_callback:
                            if self.notification_callback(prediction):
                                result["notifications_sent"] += 1
                                self._stats["notifications_sent"] += 1
                except Exception as e:
                    logger.error(
                        f"Error processing match {match.get('home_team')} vs {match.get('away_team')}: {e}"
                    )

            logger.info(
                f"Check complete: {result['matches_found']} matches, "
                f"{result['new_predictions']} new predictions"
            )
        except Exception as e:
            logger.error(f"Error checking odds: {e}")
            result["error"] = str(e)
            self._stats["errors"] += 1

        return result

    def clear_processed(self, older_than_hours: int = 48) -> None:
        old_count = len(self._processed_events)
        self._processed_events.clear()
        logger.info(f"Cleared {old_count} processed events")


# ---------------------------------------------------------------------------
# AutoMonitor -- full-featured production monitor
# ---------------------------------------------------------------------------

class AutoMonitor:
    """
    Production monitor with decision engine, quality gates, and
    notification dispatch.
    """

    def __init__(
        self,
        check_interval: int = 43200,
        dry_run: bool = False,
    ) -> None:
        self.check_interval = check_interval
        self.dry_run = dry_run

        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._last_check: Optional[datetime] = None
        self._last_data_refresh: Optional[datetime] = None
        self._check_lock = threading.Lock()  # Prevent concurrent checks
        self._check_in_progress: bool = False

        # Sub-components
        self._decision_engine = DecisionEngine()
        self._notifier = NotificationDispatcher()
        self._fetcher = OddsFetcher()

        # Expose _history_context through the decision engine so that
        # monkeypatching in tests still works via the AutoMonitor instance.
        self._history_context = self._decision_engine._history_context

        self._stats: dict[str, int] = {
            "total_checks": 0,
            "matches_found": 0,
            "predictions_created": 0,
            "notifications_sent": 0,
            "data_refreshes": 0,
            "errors": 0,
            "dry_run_candidates": 0,
            "shadow_logged": 0,
            "shadow_only": 0,
            "rejected_matches": 0,
        }

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._running:
            logger.warning("AutoMonitor already running")
            return
        self._running = True
        self._thread = threading.Thread(target=self._main_loop, daemon=True)
        self._thread.start()
        logger.info(
            f"AutoMonitor started (interval: {self.check_interval}s = "
            f"{self.check_interval // 3600}h)"
        )

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("AutoMonitor stopped")

    def is_running(self) -> bool:
        return self._running

    def get_stats(self) -> dict:
        return {
            **self._stats,
            "is_running": self._running,
            "dry_run": self.dry_run,
            "last_check": self._last_check.isoformat() if self._last_check else None,
            "last_data_refresh": (
                self._last_data_refresh.isoformat() if self._last_data_refresh else None
            ),
            "check_interval_hours": self.check_interval // 3600,
        }

    def check_now(self) -> dict:
        return self._check_matches()

    # -- main loop ----------------------------------------------------------

    def _main_loop(self) -> None:
        time.sleep(10)
        while self._running:
            try:
                self._maybe_refresh_data()
                self._check_matches()
            except Exception as e:
                logger.error(f"AutoMonitor error: {e}")
                self._stats["errors"] += 1
                self._log_error(str(e))
            time.sleep(self.check_interval)

    # -- data refresh -------------------------------------------------------

    def _maybe_refresh_data(self) -> None:
        if self.dry_run:
            return
        try:
            from src.data_refresh import should_refresh, refresh_all_historical_data

            if should_refresh():
                logger.info("AutoMonitor: refreshing historical data...")
                result = refresh_all_historical_data()
                if not result.get("skipped"):
                    self._last_data_refresh = datetime.utcnow()
                    self._stats["data_refreshes"] += 1
        except ImportError as e:
            logger.warning(f"Data refresh module not available: {e}")
        except Exception as e:
            logger.error(f"Data refresh error: {e}")

    # -- match checking -----------------------------------------------------

    def _check_matches(self) -> dict:
        # Prevent concurrent checks
        if not self._check_lock.acquire(blocking=False):
            logger.warning("Check already in progress, skipping concurrent request")
            return {
                "matches_found": 0,
                "predictions_created": 0,
                "notifications_sent": 0,
                "decision_breakdown": {"candidate": 0, "shadow_only": 0, "rejected": 0},
                "skipped": "check_in_progress",
            }

        try:
            self._check_in_progress = True
            self._last_check = datetime.utcnow()
            self._stats["total_checks"] += 1

            result: dict[str, Any] = {
                "matches_found": 0,
                "predictions_created": 0,
                "notifications_sent": 0,
                "decision_breakdown": {
                    "candidate": 0,
                    "shadow_only": 0,
                    "rejected": 0,
                },
            }
            if self.dry_run:
                result["dry_run"] = True
                result["decisions"] = []

            loader = self._get_live_loader()
            if not loader.is_configured():
                logger.warning("FlashLive not configured, skipping check")
                return result

            matches = loader.get_matches_with_odds(days_ahead=2)
            result["matches_found"] = len(matches)
            self._stats["matches_found"] += len(matches)

            for match in matches:
                try:
                    decision = self.evaluate_match(match)
                    result["decision_breakdown"][decision["status"]] += 1

                    if decision["status"] == "shadow_only":
                        self._stats["shadow_only"] += 1
                    elif decision["status"] == "rejected":
                        self._stats["rejected_matches"] += 1

                    if self.dry_run:
                        result["decisions"].append(decision)
                        self._log_match_decision(decision)
                        if decision["status"] == "candidate":
                            result["predictions_created"] += 1
                            self._stats["predictions_created"] += 1
                            self._stats["dry_run_candidates"] += 1
                        continue

                    prediction = self._process_match(match, decision=decision)
                    prediction_id = prediction.id if prediction else None
                    self._log_match_decision(decision, prediction_id=prediction_id)

                    if prediction:
                        result["predictions_created"] += 1
                        self._stats["predictions_created"] += 1

                        if self._send_notification(prediction):
                            result["notifications_sent"] += 1
                            self._stats["notifications_sent"] += 1
                except Exception as e:
                    logger.error(f"Error processing match: {e}")

            self._notifier.log_monitoring_summary(
                result["matches_found"],
                result["predictions_created"],
                result["notifications_sent"],
                details={
                    "decision_breakdown": result["decision_breakdown"],
                    "dry_run": self.dry_run,
                },
            )

            logger.info(
                f"AutoMonitor check: {result['matches_found']} matches, "
                f"{result['predictions_created']} predictions"
            )

            # Always check results, even in dry_run mode
            # (dry_run only prevents creating new predictions)
            try:
                self.check_results()
            except Exception as e:
                logger.error(f"Results check error in _check_matches: {e}")

        except Exception as e:
            logger.error(f"AutoMonitor check error: {e}")
            self._log_error(f"Check error: {e}")
            result = {
                "matches_found": 0,
                "predictions_created": 0,
                "notifications_sent": 0,
                "decision_breakdown": {"candidate": 0, "shadow_only": 0, "rejected": 0},
                "error": str(e),
            }
        finally:
            self._check_in_progress = False
            self._check_lock.release()

        return result

    # -- live loader --------------------------------------------------------

    def _get_live_loader(self) -> Any:
        from src.flashlive_loader import MultiSportFlashLiveLoader
        return MultiSportFlashLiveLoader()

    # -- evaluation ---------------------------------------------------------
    # The pipeline is orchestrated here (not inside DecisionEngine) so that
    # each step is a patchable method on AutoMonitor -- existing tests
    # monkeypatch ``auto._evaluate_history_verdict`` etc.

    def evaluate_match(self, match: dict) -> dict:
        """Evaluate a single match without side effects."""
        sport_type = self._decision_engine._resolve_sport_type(match)
        decision = self._decision_engine._build_decision_shell(match, sport_type)

        technical_verdict = self._decision_engine._gate.evaluate_technical(match, sport_type)
        decision["technical_verdict"] = technical_verdict
        if technical_verdict["status"] != "pass":
            decision["reason"] = technical_verdict["reason"]
            return decision

        odds_verdict = self._decision_engine._gate.evaluate_odds(match)
        decision["odds_verdict"] = odds_verdict
        if odds_verdict["status"] != "pass":
            decision["reason"] = odds_verdict["reason"]
            return decision

        decision["bet_on"] = odds_verdict.get("bet_on")
        decision["target_odds"] = odds_verdict.get("target_odds")

        history_verdict = self._evaluate_history_verdict(match, sport_type)
        decision["history_verdict"] = history_verdict
        if history_verdict["status"] != "pass":
            decision["reason"] = history_verdict["reason"]
            return decision

        pattern_verdict, model_verdict = self._evaluate_pattern_and_model(
            match, sport_type, history_verdict
        )
        decision["pattern_verdict"] = pattern_verdict
        decision["model_verdict"] = model_verdict

        agreement_verdict = self._decision_engine._gate.evaluate_agreement(
            decision["bet_on"], pattern_verdict, model_verdict
        )
        decision["agreement_verdict"] = agreement_verdict

        final_status, final_reason = self._decision_engine._gate.finalize_decision(
            pattern_verdict=pattern_verdict,
            model_verdict=model_verdict,
            agreement_verdict=agreement_verdict,
        )
        decision["status"] = final_status
        decision["reason"] = final_reason
        return decision

    def _evaluate_history_verdict(self, match: dict, sport_type: str) -> dict:
        normalized_home = self._decision_engine._normalize_team_for_history(
            sport_type, match.get("league"), match.get("home_team")
        )
        normalized_away = self._decision_engine._normalize_team_for_history(
            sport_type, match.get("league"), match.get("away_team")
        )
        context = self._get_history_context(sport_type, match.get("league") or "")
        return self._decision_engine._gate.evaluate_history(
            match, sport_type, context, normalized_home, normalized_away
        )

    def _evaluate_pattern_and_model(
        self, match: dict, sport_type: str, history_verdict: dict
    ) -> tuple[dict, dict]:
        # Pre-populate the engine's history cache via *our* (patchable)
        # _get_history_context so that sport-specific evaluators inside
        # the engine hit the cached value that tests may have injected.
        league = match.get("league") or ""
        context = self._get_history_context(sport_type, league)
        cache_key = (sport_type, league)
        self._decision_engine._history_context[cache_key] = context
        return self._decision_engine._evaluate_pattern_and_model(match, sport_type, history_verdict)

    def _get_history_context(self, sport_type: str, league: str) -> Dict[str, Any]:
        return self._decision_engine._get_history_context(sport_type, league)

    # -- match processing ---------------------------------------------------

    def _process_match(
        self, match: dict, decision: Optional[dict] = None
    ) -> Optional[dict]:
        decision = decision or self.evaluate_match(match)
        if decision["status"] != "candidate":
            return None

        if self.dry_run:
            return {
                **decision,
                "dry_run": True,
                "created": False,
            }

        target_odds = decision["target_odds"]
        bet_on = decision["bet_on"]

        try:
            from src.prediction_service import create_prediction_from_match
            return create_prediction_from_match(match, bet_on, target_odds, decision=decision)
        except ImportError:
            return None
        except Exception as e:
            logger.error(f"Prediction creation error: {e}")
            return None

    # -- notifications (delegates to NotificationDispatcher) ----------------

    def _send_notification(self, prediction: dict) -> bool:
        return self._notifier.send_prediction(prediction)

    def _log_match_decision(self, decision: dict) -> None:
        self._notifier.log_match_decision(decision)
        self._stats["shadow_logged"] += 1

    def _log_error(self, message: str) -> None:
        self._notifier.log_error(message)

    # -- result checking ----------------------------------------------------

    def check_results(self) -> dict:
        result: dict[str, Any] = {
            "checked": 0,
            "updated": 0,
            "wins": 0,
            "losses": 0,
            "errors": 0,
        }

        try:
            from app import app, db
            from models import Prediction

            loader = self._get_live_loader()
            if not loader.is_configured():
                logger.warning("FlashLive not configured for result checking")
                return result

            with app.app_context():
                pending = Prediction.query.filter(
                    Prediction.is_win == None,  # noqa: E711
                    Prediction.match_date < datetime.utcnow(),
                    Prediction.flashlive_event_id != None,  # noqa: E711
                ).all()

                result["checked"] = len(pending)
                logger.info(f"Checking results for {len(pending)} predictions")

                for pred in pending:
                    try:
                        event_id = pred.flashlive_event_id
                        if not event_id:
                            continue

                        match_result = loader.get_match_result(
                            event_id,
                            sport=getattr(pred, "sport_type", None),
                            league=pred.league,
                        )
                        if not match_result:
                            continue
                        if match_result["status"] != "FINISHED":
                            continue

                        winner = match_result.get("winner")
                        if not winner:
                            continue

                        home_score = match_result.get("home_score", 0)
                        away_score = match_result.get("away_score", 0)
                        pred.actual_result = f"{home_score}:{away_score}"
                        pred.result_updated_at = datetime.utcnow()

                        predicted_team = pred.predicted_outcome
                        if winner == "home" and predicted_team == pred.home_team:
                            pred.is_win = True
                            result["wins"] += 1
                        elif winner == "away" and predicted_team == pred.away_team:
                            pred.is_win = True
                            result["wins"] += 1
                        else:
                            pred.is_win = False
                            result["losses"] += 1

                        result["updated"] += 1

                    except Exception as e:
                        logger.error(f"Error checking result for prediction {pred.id}: {e}")
                        result["errors"] += 1

                db.session.commit()

            self._stats["results_checked"] = (
                self._stats.get("results_checked", 0) + result["checked"]
            )
            self._stats["results_updated"] = (
                self._stats.get("results_updated", 0) + result["updated"]
            )

            logger.info(
                f"Results check: {result['updated']} updated "
                f"({result['wins']} wins, {result['losses']} losses)"
            )

        except Exception as e:
            logger.error(f"Results check error: {e}")
            result["errors"] += 1

        return result


# ---------------------------------------------------------------------------
# MonitorGuard -- file-lock based singleton guard
# ---------------------------------------------------------------------------

class MonitorGuard:
    """Prevent multiple monitor instances via file lock."""

    def __init__(self, lock_path: Optional[str] = None) -> None:
        self.lock_path = lock_path or os.environ.get("MONITOR_LOCK_PATH") or "/tmp/arena_monitor.lock"
        self.pid = os.getpid()
        self.fd: Any = None
        self.mode: Optional[str] = None

    def acquire(self) -> bool:
        try:
            import fcntl
            self.fd = open(self.lock_path, "w")
            fcntl.lockf(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.mode = "fcntl"
            self.fd.write(str(self.pid))
            self.fd.flush()
            return True
        except Exception:
            if self.fd:
                try:
                    self.fd.close()
                except Exception:
                    pass
                self.fd = None

        try:
            if os.path.exists(self.lock_path):
                try:
                    with open(self.lock_path, "r") as f:
                        content = f.read().strip()
                        existing = int(content) if content else 0
                except Exception:
                    existing = 0
                if existing:
                    try:
                        os.kill(existing, 0)
                        return False
                    except OSError:
                        try:
                            os.unlink(self.lock_path)
                        except Exception:
                            pass
                else:
                    try:
                        os.unlink(self.lock_path)
                    except Exception:
                        pass
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, str(self.pid).encode())
            os.close(fd)
            self.mode = "pid"
            return True
        except Exception:
            return False

    def release(self) -> None:
        if self.mode == "fcntl":
            try:
                import fcntl
                fcntl.lockf(self.fd, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self.fd.close()
            except Exception:
                pass
            try:
                os.unlink(self.lock_path)
            except Exception:
                pass
        elif self.mode == "pid":
            try:
                with open(self.lock_path, "r") as f:
                    content = f.read().strip()
                if content == str(self.pid):
                    os.unlink(self.lock_path)
            except Exception:
                pass
        self.mode = None


# ---------------------------------------------------------------------------
# MockOddsLoader
# ---------------------------------------------------------------------------

class MockOddsLoader:
    """Test/demo loader."""

    def is_configured(self) -> bool:
        return True

    def get_upcoming_games(self, days_ahead: int = 2) -> list[dict]:
        from src.apisports_odds_loader import get_demo_odds
        return get_demo_odds()


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def get_auto_monitor() -> AutoMonitor:
    """Return the global AutoMonitor singleton."""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = AutoMonitor(check_interval=43200)
    return _global_monitor


def set_auto_monitor(monitor: Optional[AutoMonitor]) -> Optional[AutoMonitor]:
    """Explicitly set the global AutoMonitor instance."""
    global _global_monitor
    _global_monitor = monitor
    return _global_monitor


def start_auto_monitoring() -> None:
    """Start auto-monitoring (called at server startup)."""
    global _monitor_thread_started, _guard
    if _monitor_thread_started:
        return
    if _guard is None:
        _guard = MonitorGuard()
    if not _guard.acquire():
        logger.info("AutoMonitor guard active, skipping start")
        return

    monitor = get_auto_monitor()
    if not monitor.is_running():
        monitor.start()
        _monitor_thread_started = True


def _release_guard() -> None:
    global _guard
    try:
        if _guard:
            _guard.release()
    except Exception:
        pass


atexit.register(_release_guard)
