from src.system_logger import (
    LOG_TYPES,
    get_recent_logs,
    log_data_update,
    log_error,
    log_monitoring,
    log_prediction,
    log_system,
    log_to_db,
)


def test_log_to_db_writes_record_and_get_recent_logs_reads_it(app):
    log_to_db("system", "Boot ok", level="INFO", details={"source": "test"})

    logs = get_recent_logs(limit=5)

    assert len(logs) == 1
    assert logs[0]["log_type"] == "system"
    assert logs[0]["message"] == "Boot ok"
    assert logs[0]["details"]["source"] == "test"


def test_logger_helpers_write_expected_log_types_and_filters(app):
    log_data_update("NHL", 15, True, {"season": "20252026"})
    log_monitoring(5, 2, 1)
    log_prediction("Anaheim Ducks", "Boston Bruins", "Anaheim Ducks", 0.72)
    log_error("broken api", {"service": "flashlive"})
    log_system("manual override", level="WARNING")

    monitoring_logs = get_recent_logs(limit=10, log_type=LOG_TYPES["MONITORING"])
    error_logs = get_recent_logs(limit=10, level="ERROR")

    assert len(monitoring_logs) == 1
    assert monitoring_logs[0]["details"]["predictions_created"] == 2
    assert len(error_logs) == 1
    assert error_logs[0]["message"] == "broken api"


def test_logger_does_not_import_app_when_runtime_is_not_loaded(monkeypatch):
    import builtins
    import sys

    real_import = builtins.__import__

    def _guarded_import(name, *args, **kwargs):
        if name == "app":
            raise AssertionError("system_logger should not import app directly")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "app", raising=False)
    monkeypatch.setattr(builtins, "__import__", _guarded_import)

    log_to_db("system", "offline log", level="INFO", details={"mode": "no-app"})
    logs = get_recent_logs(limit=5)

    assert logs == []
