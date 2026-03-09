import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

from models import Prediction
import src.odds_monitor as odds_monitor_module
from src.odds_monitor import AutoMonitor, MonitorGuard, OddsMonitor, start_auto_monitoring


class _StaticLoader:
    def __init__(self, matches):
        self._matches = matches

    def get_upcoming_games(self, days_ahead=2):
        return list(self._matches)


def test_odds_monitor_counts_predictions_notifications_and_skips_duplicates():
    matches = [
        {"event_id": "evt-1", "home_team": "AAA", "away_team": "BBB"},
        {"event_id": "evt-2", "home_team": "CCC", "away_team": "DDD"},
    ]
    monitor = OddsMonitor(
        odds_loader=_StaticLoader(matches),
        prediction_callback=lambda match: {"event_id": match["event_id"]},
        notification_callback=lambda prediction: True,
        check_interval=1,
    )

    first = monitor.check_now()
    second = monitor.check_now()

    assert first["matches_found"] == 2
    assert first["new_predictions"] == 2
    assert first["notifications_sent"] == 2
    assert second["new_predictions"] == 0
    assert monitor.get_stats()["processed_events"] == 2


def test_odds_monitor_returns_error_when_loader_fails():
    class _BrokenLoader:
        def get_upcoming_games(self, days_ahead=2):
            raise RuntimeError("loader down")

    monitor = OddsMonitor(
        odds_loader=_BrokenLoader(),
        prediction_callback=lambda match: None,
        check_interval=1,
    )

    result = monitor.check_now()

    assert "error" in result
    assert monitor.get_stats()["errors"] == 1


def test_odds_monitor_continues_when_single_match_processing_fails():
    matches = [
        {"event_id": "evt-1", "home_team": "AAA", "away_team": "BBB"},
        {"event_id": "evt-2", "home_team": "CCC", "away_team": "DDD"},
    ]
    processed = []

    def _predict(match):
        processed.append(match["event_id"])
        if match["event_id"] == "evt-1":
            raise RuntimeError("broken prediction")
        return {"event_id": match["event_id"]}

    monitor = OddsMonitor(
        odds_loader=_StaticLoader(matches),
        prediction_callback=_predict,
        notification_callback=lambda prediction: False,
        check_interval=1,
    )

    result = monitor.check_now()

    assert processed == ["evt-1", "evt-2"]
    assert result["matches_found"] == 2
    assert result["new_predictions"] == 1
    assert result["notifications_sent"] == 0
    assert monitor.get_stats()["processed_events"] == 1


def test_odds_monitor_clear_processed_resets_seen_events():
    monitor = OddsMonitor(
        odds_loader=_StaticLoader([]),
        prediction_callback=lambda match: None,
        check_interval=1,
    )
    monitor._processed_events.update({"evt-1", "evt-2"})

    monitor.clear_processed()

    assert monitor.get_stats()["processed_events"] == 0


def test_odds_monitor_monitor_loop_tracks_errors(monkeypatch):
    monitor = OddsMonitor(
        odds_loader=_StaticLoader([]),
        prediction_callback=lambda match: None,
        check_interval=1,
    )
    calls = []

    def _check():
        calls.append("check")
        raise RuntimeError("loop fail")

    def _sleep(delay):
        monitor._running = False

    monkeypatch.setattr(monitor, "_check_odds", _check)
    monkeypatch.setattr(odds_monitor_module.time, "sleep", _sleep)

    monitor._running = True
    monitor._monitor_loop()

    assert calls == ["check"]
    assert monitor.get_stats()["errors"] == 1


def test_auto_monitor_process_match_selects_home_or_away_target(monkeypatch):
    auto = AutoMonitor()
    calls = []

    def _fake_create_prediction(match, bet_on, target_odds):
        calls.append((match["event_id"], bet_on, target_odds))
        return {"ok": True}

    monkeypatch.setitem(
        sys.modules,
        "src.prediction_service",
        SimpleNamespace(create_prediction_from_match=_fake_create_prediction),
    )

    home_result = auto._process_match({"event_id": "evt-1", "home_odds": 2.4, "away_odds": 1.5})
    away_result = auto._process_match({"event_id": "evt-2", "home_odds": 1.7, "away_odds": 2.6})
    skipped = auto._process_match({"event_id": "evt-3", "home_odds": 1.5, "away_odds": 1.6})

    assert home_result == {"ok": True}
    assert away_result == {"ok": True}
    assert skipped is None
    assert calls == [("evt-1", "home", 2.4), ("evt-2", "away", 2.6)]


def test_auto_monitor_send_notification_uses_telegram_helper(monkeypatch):
    auto = AutoMonitor()
    sent = []

    monkeypatch.setitem(
        sys.modules,
        "src.telegram_bot",
        SimpleNamespace(send_prediction_notification=lambda prediction: sent.append(prediction) or True),
    )

    result = auto._send_notification({"id": 1})

    assert result is True
    assert sent == [{"id": 1}]


def test_auto_monitor_maybe_refresh_data_updates_stats(monkeypatch):
    auto = AutoMonitor()

    monkeypatch.setitem(
        sys.modules,
        "src.data_refresh",
        SimpleNamespace(
            should_refresh=lambda: True,
            refresh_all_historical_data=lambda: {"skipped": False, "updated": 5},
        ),
    )

    auto._maybe_refresh_data()

    assert auto._stats["data_refreshes"] == 1
    assert auto._last_data_refresh is not None


def test_auto_monitor_log_error_uses_system_logger(monkeypatch):
    auto = AutoMonitor()
    logged = []

    monkeypatch.setitem(
        sys.modules,
        "src.system_logger",
        SimpleNamespace(log_error=lambda message, details: logged.append((message, details))),
    )

    auto._log_error("monitor exploded")

    assert logged == [("monitor exploded", {"source": "AutoMonitor"})]


def test_auto_monitor_check_matches_logs_and_checks_results(monkeypatch):
    auto = AutoMonitor()
    logged = []
    checks = []

    class _Loader:
        @staticmethod
        def is_configured():
            return True

        @staticmethod
        def get_matches_with_odds(days_ahead=2):
            return [
                {"event_id": "evt-1", "sport_type": "football", "league": "EPL"},
                {"event_id": "evt-2", "sport_type": "basketball", "league": "NBA"},
            ]

    monkeypatch.setitem(
        sys.modules,
        "src.system_logger",
        SimpleNamespace(log_monitoring=lambda matches, created, sent: logged.append((matches, created, sent))),
    )
    monkeypatch.setattr(auto, "_get_live_loader", lambda: _Loader())
    monkeypatch.setattr(auto, "_process_match", lambda match: {"id": match["event_id"]} if match["event_id"] == "evt-1" else None)
    monkeypatch.setattr(auto, "_send_notification", lambda prediction: True)
    monkeypatch.setattr(auto, "check_results", lambda: checks.append("done") or {"updated": 0})

    result = auto._check_matches()

    assert result == {"matches_found": 2, "predictions_created": 1, "notifications_sent": 1}
    assert logged == [(2, 1, 1)]
    assert checks == ["done"]
    assert auto._stats["matches_found"] == 2
    assert auto._stats["predictions_created"] == 1
    assert auto._stats["notifications_sent"] == 1


def test_auto_monitor_check_matches_returns_empty_when_loader_not_configured(monkeypatch):
    auto = AutoMonitor()

    class _Loader:
        @staticmethod
        def is_configured():
            return False

    monkeypatch.setitem(
        sys.modules,
        "src.system_logger",
        SimpleNamespace(log_monitoring=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(auto, "_get_live_loader", lambda: _Loader())

    result = auto._check_matches()

    assert result == {"matches_found": 0, "predictions_created": 0, "notifications_sent": 0}


def test_auto_monitor_main_loop_tracks_errors_and_logs(monkeypatch):
    auto = AutoMonitor(check_interval=5)
    logged = []
    sleep_calls = []

    def _maybe_refresh():
        raise RuntimeError("refresh failed")

    def _sleep(delay):
        sleep_calls.append(delay)
        if len(sleep_calls) >= 2:
            auto._running = False

    monkeypatch.setattr(auto, "_maybe_refresh_data", _maybe_refresh)
    monkeypatch.setattr(auto, "_check_matches", lambda: {"ok": True})
    monkeypatch.setattr(auto, "_log_error", lambda message: logged.append(message))
    monkeypatch.setattr(odds_monitor_module.time, "sleep", _sleep)

    auto._running = True
    auto._main_loop()

    assert sleep_calls == [10, 5]
    assert auto._stats["errors"] == 1
    assert logged == ["refresh failed"]


def test_auto_monitor_check_results_updates_prediction_statuses(app, app_module, monkeypatch):
    with app.app_context():
        app_module.db.session.add_all(
            [
                Prediction(
                    match_date=datetime.utcnow() - timedelta(hours=3),
                    league="NHL",
                    home_team="Anaheim Ducks",
                    away_team="Boston Bruins",
                    prediction_type="Money Line",
                    predicted_outcome="Anaheim Ducks",
                    confidence=0.7,
                    confidence_1_10=7,
                    home_odds=2.4,
                    away_odds=1.6,
                    bookmaker="FlashLive",
                    model_version="test",
                    flashlive_event_id="evt-win",
                ),
                Prediction(
                    match_date=datetime.utcnow() - timedelta(hours=2),
                    league="NHL",
                    home_team="Chicago Blackhawks",
                    away_team="Detroit Red Wings",
                    prediction_type="Money Line",
                    predicted_outcome="Chicago Blackhawks",
                    confidence=0.6,
                    confidence_1_10=6,
                    home_odds=2.8,
                    away_odds=1.5,
                    bookmaker="FlashLive",
                    model_version="test",
                    flashlive_event_id="evt-loss",
                ),
            ]
        )
        app_module.db.session.commit()

    class _FakeFlashLiveLoader:
        def is_configured(self):
            return True

        def get_match_result(self, event_id, sport=None, league=None):
            return {
                "evt-win": {"status": "FINISHED", "winner": "home", "home_score": 4, "away_score": 2},
                "evt-loss": {"status": "FINISHED", "winner": "away", "home_score": 1, "away_score": 3},
            }[event_id]

    monitor = AutoMonitor()
    monkeypatch.setattr(monitor, "_get_live_loader", lambda: _FakeFlashLiveLoader())
    result = monitor.check_results()

    assert result["checked"] == 2
    assert result["updated"] == 2
    assert result["wins"] == 1
    assert result["losses"] == 1

    with app.app_context():
        predictions = Prediction.query.order_by(Prediction.flashlive_event_id).all()
        assert predictions[0].is_win is False
        assert predictions[0].actual_result == "1:3"
        assert predictions[1].is_win is True
        assert predictions[1].actual_result == "4:2"


def test_auto_monitor_check_results_returns_empty_when_loader_is_not_configured(monkeypatch):
    class _FakeFlashLiveLoader:
        @staticmethod
        def is_configured():
            return False

    monitor = AutoMonitor()
    monkeypatch.setattr(monitor, "_get_live_loader", lambda: _FakeFlashLiveLoader())
    result = monitor.check_results()

    assert result == {"checked": 0, "updated": 0, "wins": 0, "losses": 0, "errors": 0}


def test_monitor_guard_pid_mode_recovers_stale_lock(monkeypatch, tmp_path):
    lock_path = tmp_path / "monitor.lock"
    lock_path.write_text("999999")

    class _BrokenFcntl:
        LOCK_EX = 1
        LOCK_NB = 2
        LOCK_UN = 8

        @staticmethod
        def lockf(*args, **kwargs):
            raise OSError("no fcntl lock")

    monkeypatch.setitem(sys.modules, "fcntl", _BrokenFcntl)
    monkeypatch.setattr(odds_monitor_module.os, "kill", lambda pid, sig: (_ for _ in ()).throw(OSError("stale pid")))

    guard = MonitorGuard(lock_path=str(lock_path))

    assert guard.acquire() is True
    assert guard.mode == "pid"
    assert lock_path.read_text() == str(guard.pid)

    guard.release()

    assert not lock_path.exists()


def test_start_auto_monitoring_respects_guard_and_starts_once(monkeypatch):
    started = []
    fake_monitor = SimpleNamespace(
        is_running=lambda: False,
        start=lambda: started.append("start"),
    )

    monkeypatch.setattr(odds_monitor_module, "_monitor_thread_started", False)
    monkeypatch.setattr(odds_monitor_module, "_guard", None)
    monkeypatch.setattr(odds_monitor_module, "MonitorGuard", lambda: SimpleNamespace(acquire=lambda: False))
    monkeypatch.setattr(odds_monitor_module, "get_auto_monitor", lambda: fake_monitor)

    start_auto_monitoring()
    assert started == []

    monkeypatch.setattr(odds_monitor_module, "_monitor_thread_started", False)
    monkeypatch.setattr(odds_monitor_module, "_guard", None)
    monkeypatch.setattr(odds_monitor_module, "MonitorGuard", lambda: SimpleNamespace(acquire=lambda: True))

    start_auto_monitoring()
    start_auto_monitoring()

    assert started == ["start"]
