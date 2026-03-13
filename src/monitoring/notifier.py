"""
Notification dispatcher -- sends predictions to Telegram and logs
match decisions to the system logger.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """
    Wraps all notification and logging side-effects so that the monitor
    loop and decision engine stay pure.
    """

    # -- Telegram -----------------------------------------------------------

    @staticmethod
    def send_prediction(prediction: dict) -> bool:
        """Send a prediction notification via Telegram."""
        try:
            from src.telegram_bot import send_prediction_notification
            return send_prediction_notification(prediction)
        except ImportError:
            return False
        except Exception as e:
            logger.error(f"Notification error: {e}")
            return False

    # -- decision logging ---------------------------------------------------

    @staticmethod
    def log_match_decision(decision: dict, prediction_id: Optional[int] = None) -> None:
        """Persist a match decision to the system log DB."""
        try:
            from src.system_logger import LOG_TYPES, log_to_db

            level = "INFO" if decision.get("status") in {"candidate", "shadow_only"} else "WARNING"
            message = (
                f"Match gate: {decision.get('league')} | "
                f"{decision.get('home_team')} vs {decision.get('away_team')} -> "
                f"{decision.get('status')} ({decision.get('reason')})"
            )
            decision_copy = dict(decision)
            if prediction_id:
                decision_copy["prediction_id"] = prediction_id
            log_to_db(
                log_type=LOG_TYPES["MONITORING"],
                message=message,
                level=level,
                details={
                    "source": "AutoMonitor",
                    "decision": decision_copy,
                },
            )
        except Exception as e:
            logger.error(f"Decision log error: {e}")

    # -- monitoring summary -------------------------------------------------

    @staticmethod
    def log_monitoring_summary(
        matches_found: int,
        predictions_created: int,
        notifications_sent: int,
        details: Optional[dict] = None,
    ) -> None:
        """Log the per-cycle monitoring summary."""
        try:
            from src.system_logger import log_monitoring
            log_monitoring(matches_found, predictions_created, notifications_sent, details=details)
        except Exception as e:
            logger.error(f"Monitoring summary log error: {e}")

    # -- error logging ------------------------------------------------------

    @staticmethod
    def log_error(message: str) -> None:
        """Write an error entry via the system logger."""
        try:
            from src.system_logger import log_error
            log_error(message, {"source": "AutoMonitor"})
        except Exception:
            pass
