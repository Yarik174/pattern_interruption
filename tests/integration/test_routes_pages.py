from datetime import datetime, timedelta
from types import SimpleNamespace

from models import Prediction, SystemLog, UserDecision
import src.routes as routes_module


def _capture_template(monkeypatch):
    captured = {}

    def _fake_render(template_name, **context):
        captured["template"] = template_name
        captured["context"] = context
        return template_name

    monkeypatch.setattr(routes_module, "render_template", _fake_render)
    return captured


def _seed_prediction(app_module, app, **overrides):
    payload = {
        "created_at": datetime.utcnow(),
        "match_date": datetime(2026, 1, 10, 12, 0),
        "league": "NHL",
        "home_team": "Anaheim Ducks",
        "away_team": "Boston Bruins",
        "prediction_type": "Money Line",
        "predicted_outcome": "Anaheim Ducks",
        "confidence": 0.7,
        "confidence_1_10": 7,
        "home_odds": 2.4,
        "away_odds": 1.6,
        "bookmaker": "FlashLive",
        "patterns_data": {"bet_on": "home", "target_odds": 2.4, "pattern_type": "streak"},
        "model_version": "test",
        "is_win": None,
        "rl_recommendation": None,
    }
    payload.update(overrides)

    with app.app_context():
        prediction = Prediction(**payload)
        app_module.db.session.add(prediction)
        app_module.db.session.commit()
        return prediction.id


def _seed_user_decision(app_module, app, prediction_id, decision="accepted"):
    with app.app_context():
        user_decision = UserDecision(prediction_id=prediction_id, decision=decision)
        app_module.db.session.add(user_decision)
        app_module.db.session.commit()


def test_dashboard_page_reports_live_stats(app_module, app, authenticated_client, monkeypatch):
    captured = _capture_template(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(routes_module, "odds_monitor", SimpleNamespace(get_stats=lambda: {"is_running": True}))
    now_local = datetime.now()

    today_prediction = _seed_prediction(
        app_module,
        app,
        created_at=now_local,
        confidence_1_10=8,
    )
    old_prediction = _seed_prediction(
        app_module,
        app,
        created_at=now_local - timedelta(days=1),
        confidence_1_10=6,
        home_team="Calgary Flames",
        away_team="Edmonton Oilers",
    )
    _seed_user_decision(app_module, app, old_prediction)

    response = authenticated_client.get("/dashboard")

    assert response.status_code == 200
    assert captured["template"] == "dashboard.html"
    assert captured["context"]["total_predictions"] == 2
    assert captured["context"]["today_predictions"] == 1
    assert captured["context"]["pending_decisions"] == 1
    assert captured["context"]["avg_confidence"] == 7.0
    assert captured["context"]["telegram_configured"] is True
    assert captured["context"]["monitor_running"] is True


def test_prediction_detail_uses_loader_for_prediction_sport(app_module, app, authenticated_client, monkeypatch):
    captured = _capture_template(monkeypatch)
    prediction_id = _seed_prediction(
        app_module,
        app,
        sport_type="football",
        league="EPL",
        home_team="Arsenal",
        away_team="Chelsea",
        predicted_outcome="Arsenal",
        flashlive_event_id="football-evt-1",
    )

    class _FootballLoader:
        @staticmethod
        def get_h2h_data(event_id):
            assert event_id == "football-evt-1"
            return {
                "home_team_matches": [{"date": "09.03", "opponent": "Chelsea", "score": "2:1", "result": "WIN"}],
                "away_team_matches": [{"date": "09.03", "opponent": "Arsenal", "score": "1:2", "result": "LOSS"}],
            }

    class _WrongLoader:
        @staticmethod
        def get_h2h_data(event_id):
            raise AssertionError("Должен использоваться loader соответствующего спорта")

    monkeypatch.setattr(
        routes_module,
        "odds_loader",
        lambda sport: _FootballLoader() if sport in ("football", routes_module.SportType.FOOTBALL) else _WrongLoader(),
    )

    response = authenticated_client.get(f"/prediction/{prediction_id}")

    assert response.status_code == 200
    assert captured["template"] == "prediction_detail.html"
    assert captured["context"]["home_history"][0]["opponent"] == "Chelsea"
    assert captured["context"]["away_history"][0]["opponent"] == "Arsenal"


def test_statistics_page_builds_model_rl_and_monthly_stats(app_module, app, authenticated_client, monkeypatch):
    captured = _capture_template(monkeypatch)

    first = _seed_prediction(
        app_module,
        app,
        match_date=datetime(2026, 1, 15, 18, 0),
        home_team="Anaheim Ducks",
        away_team="Boston Bruins",
        predicted_outcome="Anaheim Ducks",
        patterns_data={"bet_on": "home", "target_odds": 3.0, "pattern_type": "streak"},
        home_odds=3.0,
        away_odds=1.4,
        confidence_1_10=7,
        is_win=True,
        rl_recommendation="BET",
    )
    second = _seed_prediction(
        app_module,
        app,
        match_date=datetime(2026, 1, 20, 18, 0),
        home_team="Chicago Blackhawks",
        away_team="Dallas Stars",
        predicted_outcome="Dallas Stars",
        patterns_data={"bet_on": "away", "target_odds": 1.8, "pattern_type": "streak"},
        home_odds=2.1,
        away_odds=1.8,
        confidence_1_10=7,
        is_win=False,
        rl_recommendation="BET",
    )
    third = _seed_prediction(
        app_module,
        app,
        match_date=datetime(2026, 2, 10, 18, 0),
        league="SHL",
        home_team="Frolunda HC",
        away_team="Skelleftea AIK",
        predicted_outcome="Frolunda HC",
        patterns_data={"bet_on": "home", "target_odds": 2.2, "pattern_type": "streak"},
        home_odds=2.2,
        away_odds=1.7,
        confidence_1_10=5,
        is_win=False,
        rl_recommendation="SKIP",
    )
    _seed_prediction(
        app_module,
        app,
        match_date=datetime(2026, 2, 14, 21, 0),
        league="EPL",
        sport_type="football",
        home_team="Arsenal",
        away_team="Chelsea",
        predicted_outcome="Arsenal",
        patterns_data={"bet_on": "home", "target_odds": 2.5, "pattern_type": "streak"},
        home_odds=2.5,
        away_odds=2.8,
        confidence_1_10=8,
        is_win=True,
        rl_recommendation=None,
    )
    _seed_prediction(
        app_module,
        app,
        match_date=datetime(2026, 2, 12, 18, 0),
        league="DEL",
        home_team="Eisbaren Berlin",
        away_team="Adler Mannheim",
        patterns_data={"bet_on": "away", "target_odds": 1.9, "pattern_type": "alt"},
        home_odds=2.0,
        away_odds=1.9,
        confidence_1_10=4,
        is_win=None,
        rl_recommendation="SKIP",
    )
    _seed_user_decision(app_module, app, first)
    _seed_user_decision(app_module, app, third)

    response = authenticated_client.get("/statistics")

    assert response.status_code == 200
    assert captured["template"] == "statistics.html"

    model_stats = captured["context"]["model_stats"]
    manual_stats = captured["context"]["manual_stats"]
    rl_stats = captured["context"]["rl_stats"]
    sport_stats = captured["context"]["sport_stats"]
    league_stats = captured["context"]["league_stats"]
    confidence_stats = captured["context"]["confidence_stats"]
    pattern_stats = captured["context"]["pattern_stats"]
    monthly_stats = captured["context"]["monthly_stats"]
    chart_data = captured["context"]["chart_data"]
    league_order = captured["context"]["league_order"]

    assert model_stats["total"] == 4
    assert model_stats["wins"] == 2
    assert model_stats["losses"] == 2
    assert model_stats["pending"] == 1
    assert model_stats["win_rate"] == 50.0
    assert model_stats["roi"] == 37.5

    assert manual_stats["total"] == 2
    assert manual_stats["wins"] == 1
    assert manual_stats["losses"] == 1
    assert manual_stats["win_rate"] == 50.0
    assert manual_stats["roi"] == 50.0

    assert rl_stats["bet_count"] == 2
    assert rl_stats["skip_count"] == 2
    assert rl_stats["total"] == 2
    assert rl_stats["wins"] == 1
    assert rl_stats["losses"] == 1
    assert rl_stats["win_rate"] == 50.0
    assert rl_stats["roi"] == 50.0
    assert rl_stats["skip_saved"] == 1

    assert sport_stats["hockey"]["total"] == 3
    assert round(sport_stats["hockey"]["roi"], 1) == 0.0
    assert sport_stats["football"]["wins"] == 1
    assert round(sport_stats["football"]["roi"], 1) == 150.0

    assert league_order == ["EPL", "NHL", "SHL"]
    assert league_stats["EPL"]["sport_slug"] == "football"
    assert league_stats["NHL"]["total"] == 2
    assert league_stats["NHL"]["roi"] == 50.0
    assert league_stats["SHL"]["roi"] == -100.0
    assert confidence_stats[7]["total"] == 2
    assert confidence_stats[7]["wins"] == 1
    assert confidence_stats[8]["wins"] == 1
    assert pattern_stats["streak"]["total"] == 4
    assert pattern_stats["streak"]["win_rate"] == 50.0
    assert [row["month"] for row in monthly_stats] == ["2026-01", "2026-02"]
    assert chart_data["labels"] == ["2026-01", "2026-02"]
    assert chart_data["cumulative_roi"][-1] == 37.5


def test_telegram_routes_show_status_and_validate_token(authenticated_client, monkeypatch):
    captured = _capture_template(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(
        routes_module,
        "telegram_notifier",
        SimpleNamespace(test_connection=lambda: {"ok": True, "username": "pattern_bot"}),
    )

    page_response = authenticated_client.get("/settings/telegram")

    assert page_response.status_code == 200
    assert captured["template"] == "telegram_setup.html"
    assert captured["context"]["is_active"] is True
    assert captured["context"]["bot_info"]["username"] == "pattern_bot"

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "ok": True,
                "result": {"username": "pattern_bot", "first_name": "Pattern Bot"},
            }

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: _Response())

    api_response = authenticated_client.post("/api/telegram/test", json={"bot_token": "token"})

    assert api_response.status_code == 200
    assert api_response.get_json() == {
        "ok": True,
        "bot_username": "pattern_bot",
        "bot_name": "Pattern Bot",
    }


def test_monitor_routes_return_actions_and_counts(app_module, app, authenticated_client, monkeypatch):
    class _Monitor:
        def __init__(self):
            self.running = False

        def start(self):
            self.running = True

        def stop(self):
            self.running = False

        def check_now(self):
            return {"ok": True, "checked": 2}

        def get_stats(self):
            return {"is_running": self.running, "checks": 5}

    monitor = _Monitor()
    monkeypatch.setattr(routes_module, "odds_monitor", monitor)
    monkeypatch.setattr(
        routes_module,
        "odds_loader",
        SimpleNamespace(get_upcoming_games=lambda days_ahead=1: [{"id": 1}, {"id": 2}, {"id": 3}]),
    )

    _seed_prediction(app_module, app, created_at=datetime.utcnow())
    _seed_prediction(app_module, app, created_at=datetime.utcnow(), home_team="A", away_team="B")
    _seed_prediction(
        app_module,
        app,
        created_at=datetime.utcnow() - timedelta(days=2),
        home_team="C",
        away_team="D",
    )

    started = authenticated_client.post("/api/monitor/start")
    checked = authenticated_client.post("/api/monitor/check")
    stats = authenticated_client.get("/api/monitor/stats")
    stopped = authenticated_client.post("/api/monitor/stop")

    assert started.get_json()["ok"] is True
    assert checked.get_json() == {"ok": True, "checked": 2}
    assert stats.get_json()["is_running"] is True
    assert stats.get_json()["checks"] == 5
    assert stats.get_json()["matches_available"] == 3
    assert stats.get_json()["bets_suggested"] == 2
    assert stopped.get_json()["ok"] is True


def test_logs_and_auto_monitor_routes_apply_filters(app_module, app, authenticated_client, monkeypatch):
    captured = _capture_template(monkeypatch)

    with app.app_context():
        app_module.db.session.add_all(
            [
                SystemLog(log_type="system", level="ERROR", message="boom", details={"scope": "api"}),
                SystemLog(log_type="monitoring", level="INFO", message="ok", details={"checks": 2}),
            ]
        )
        app_module.db.session.commit()

    fake_monitor = SimpleNamespace(
        get_stats=lambda: {"is_running": True, "processed_events": 4},
        check_now=lambda: {"matches_found": 3, "predictions_created": 1},
    )
    monkeypatch.setattr("src.odds_monitor.get_auto_monitor", lambda: fake_monitor)
    monkeypatch.setattr(
        "src.data_refresh.get_last_refresh_info",
        lambda: {"last_refresh": "2026-03-09T10:00:00", "hours_since": 2.0},
    )

    page_response = authenticated_client.get("/logs?type=system&level=ERROR&limit=1")
    api_response = authenticated_client.get("/api/logs?type=system&level=ERROR&limit=1")
    auto_stats = authenticated_client.get("/api/auto-monitor/stats")
    auto_check = authenticated_client.post("/api/auto-monitor/check")

    assert page_response.status_code == 200
    assert captured["template"] == "logs.html"
    assert len(captured["context"]["logs"]) == 1
    assert captured["context"]["logs"][0].message == "boom"
    assert captured["context"]["selected_type"] == "system"
    assert captured["context"]["selected_level"] == "ERROR"
    assert captured["context"]["monitor_stats"]["processed_events"] == 4
    assert captured["context"]["refresh_info"]["hours_since"] == 2.0

    assert len(api_response.get_json()["logs"]) == 1
    assert api_response.get_json()["logs"][0]["message"] == "boom"
    assert auto_stats.get_json()["is_running"] is True
    assert auto_stats.get_json()["last_data_refresh_info"]["hours_since"] == 2.0
    assert auto_check.get_json() == {
        "ok": True,
        "result": {"matches_found": 3, "predictions_created": 1},
    }


def test_explainability_page_builds_summary_and_applies_filters(app_module, app, authenticated_client, monkeypatch):
    captured = _capture_template(monkeypatch)

    with app.app_context():
        app_module.db.session.add_all(
            [
                SystemLog(
                    log_type="monitoring",
                    level="WARNING",
                    message="Match gate: NHL | A vs B -> rejected (no_pattern_signal)",
                    details={
                        "decision": {
                            "status": "rejected",
                            "reason": "no_pattern_signal",
                            "sport_type": "hockey",
                            "league": "NHL",
                            "home_team": "A",
                            "away_team": "B",
                            "bet_on": "home",
                            "target_odds": 2.2,
                            "home_odds": 2.2,
                            "away_odds": 1.8,
                            "history_verdict": {"status": "pass", "reason": "history_ready"},
                            "pattern_verdict": {"status": "fail", "reason": "no_pattern_signal"},
                            "model_verdict": {"status": "fail", "reason": "model_below_threshold"},
                            "agreement_verdict": {"status": "pending", "reason": None},
                        }
                    },
                ),
                SystemLog(
                    log_type="monitoring",
                    level="INFO",
                    message="Match gate: NBA | C vs D -> shadow_only (model_not_implemented_for_sport)",
                    details={
                        "decision": {
                            "status": "shadow_only",
                            "reason": "model_not_implemented_for_sport",
                            "sport_type": "basketball",
                            "league": "NBA",
                            "home_team": "C",
                            "away_team": "D",
                            "bet_on": "away",
                            "target_odds": 2.6,
                            "home_odds": 1.5,
                            "away_odds": 2.6,
                            "history_verdict": {"status": "pass", "reason": "history_ready"},
                            "pattern_verdict": {"status": "pass", "reason": "pattern_signal_ready"},
                            "model_verdict": {"status": "unsupported", "reason": "model_not_implemented_for_sport"},
                            "agreement_verdict": {"status": "pass", "reason": "signals_aligned"},
                        }
                    },
                ),
                SystemLog(log_type="monitoring", level="INFO", message="Мониторинг: 2 матчей, 0 прогнозов, 0 уведомлений", details={"matches_found": 2}),
            ]
        )
        app_module.db.session.commit()

    response = authenticated_client.get("/explainability?status=shadow_only&sport=basketball&limit=10")

    assert response.status_code == 200
    assert captured["template"] == "explainability.html"
    assert len(captured["context"]["items"]) == 1
    assert captured["context"]["items"][0]["league"] == "NBA"
    assert captured["context"]["summary"]["total"] == 1
    assert captured["context"]["summary"]["status_counts"] == {"shadow_only": 1}
    assert captured["context"]["selected_status"] == "shadow_only"
    assert captured["context"]["selected_sport"] == "basketball"


def test_api_explainability_decisions_returns_items_and_summary(app_module, app, authenticated_client):
    with app.app_context():
        app_module.db.session.add(
            SystemLog(
                log_type="monitoring",
                level="INFO",
                message="Match gate: Serie A | Torino vs Parma -> shadow_only (market_mismatch)",
                details={
                    "decision": {
                        "status": "shadow_only",
                        "reason": "market_mismatch",
                        "sport_type": "football",
                        "league": "Serie A",
                        "home_team": "Torino",
                        "away_team": "Parma",
                        "bet_on": "home",
                        "target_odds": 2.15,
                        "home_odds": 2.15,
                        "away_odds": 3.4,
                        "history_verdict": {"status": "pass", "reason": "history_ready"},
                        "pattern_verdict": {"status": "fail", "reason": "market_mismatch"},
                        "model_verdict": {"status": "unsupported", "reason": "model_not_implemented_for_sport"},
                        "agreement_verdict": {"status": "pass", "reason": "signals_aligned"},
                    }
                },
            )
        )
        app_module.db.session.commit()

    response = authenticated_client.get("/api/explainability/decisions?status=shadow_only&league=Serie%20A&limit=5")
    payload = response.get_json()

    assert response.status_code == 200
    assert len(payload["items"]) == 1
    assert payload["items"][0]["reason"] == "market_mismatch"
    assert payload["items"][0]["sport_type"] == "football"
    assert payload["summary"]["status_counts"] == {"shadow_only": 1}
    assert payload["summary"]["reason_counts"][0] == ["market_mismatch", 1]
