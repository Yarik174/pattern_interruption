import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from models import Prediction
from src.prediction_service import (
    calculate_confidence,
    create_prediction_from_match,
    is_target_league,
    parse_match_date,
)


@pytest.mark.parametrize(
    ("odds", "expected"),
    [
        (None, 0.5),
        (0.9, 0.5),
        (2.0, 0.70),
        (2.5, 0.65),
        (3.0, 0.55),
        (3.5, 0.45),
        (5.0, 0.30),
    ],
)
def test_calculate_confidence_matches_current_formula(odds, expected):
    assert calculate_confidence(odds) == pytest.approx(expected)


def test_parse_match_date_supports_datetime_iso_and_date_string():
    exact = datetime(2026, 1, 10, 12, 30)

    assert parse_match_date({"match_date": exact}) == exact
    assert parse_match_date({"match_date": "2026-01-10T12:30:00Z"}) == exact
    assert parse_match_date({"date": "2026-01-10"}) == datetime(2026, 1, 10)


def test_parse_match_date_falls_back_to_now_for_invalid_input():
    before = datetime.utcnow() - timedelta(seconds=1)
    parsed = parse_match_date({"match_date": "not-a-date"})
    after = datetime.utcnow() + timedelta(seconds=1)

    assert before <= parsed <= after


@pytest.mark.parametrize(
    ("league", "expected"),
    [("NHL", True), ("khl", True), ("LiIgA", True), ("nba", True), ("epl", True), ("mls", False), ("", False), (None, False)],
)
def test_is_target_league_is_case_insensitive(league, expected):
    assert is_target_league(league) is expected


def test_create_prediction_from_match_skips_non_target_league(app):
    result = create_prediction_from_match(
        {
            "league": "MLS",
            "home_team": "LA Galaxy",
            "away_team": "Inter Miami",
            "match_date": "2026-01-10",
        },
        bet_on="home",
        target_odds=2.4,
        flask_app=app,
    )

    assert result is None


def test_create_prediction_from_match_creates_and_deduplicates_prediction(app, monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "src.rl_agent",
        SimpleNamespace(
            get_rl_recommendation=lambda **kwargs: {
                "action": "BET",
                "confidence": 0.88,
                "comment": "ok",
            }
        ),
    )
    match = {
        "league": "NHL",
        "home_team": "Anaheim Ducks",
        "away_team": "Boston Bruins",
        "event_id": "flash_12345",
        "match_date": "2026-03-10",
        "home_odds": 2.4,
        "away_odds": 1.6,
    }

    created = create_prediction_from_match(match, bet_on="home", target_odds=2.4, flask_app=app)
    duplicate = create_prediction_from_match(match, bet_on="home", target_odds=2.4, flask_app=app)

    assert created["predicted_outcome"] == "Anaheim Ducks"
    assert duplicate is None

    with app.app_context():
        prediction = Prediction.query.one()
        assert prediction.flashlive_event_id == "12345"
        assert prediction.sport_type == "hockey"
        assert prediction.rl_recommendation == "BET"
        assert prediction.rl_confidence == pytest.approx(0.88)


def test_create_prediction_from_match_handles_rl_errors_without_failing(app, monkeypatch):
    def _raise(**kwargs):
        raise RuntimeError("RL unavailable")

    monkeypatch.setitem(sys.modules, "src.rl_agent", SimpleNamespace(get_rl_recommendation=_raise))

    result = create_prediction_from_match(
        {
            "league": "NHL",
            "home_team": "Chicago Blackhawks",
            "away_team": "Detroit Red Wings",
            "event_id": "flash_999",
            "match_date": "2026-01-12",
            "home_odds": 2.8,
            "away_odds": 1.5,
        },
        bet_on="away",
        target_odds=2.8,
        flask_app=app,
    )

    assert result["predicted_outcome"] == "Detroit Red Wings"

    with app.app_context():
        prediction = Prediction.query.one()
        assert prediction.rl_recommendation is None
        assert prediction.rl_confidence is None


def test_create_prediction_from_match_sets_multisport_fields(app):
    result = create_prediction_from_match(
        {
            "league": "NBA",
            "home_team": "Cleveland Cavaliers",
            "away_team": "Philadelphia 76ers",
            "event_id": "flash_nba-1",
            "match_date": "2026-03-10",
            "home_odds": 1.8,
            "away_odds": 3.4,
            "bookmaker": "bet365",
        },
        bet_on="home",
        target_odds=1.8,
        decision={
            "status": "candidate",
            "reason": "quality_gate_passed",
            "pattern_verdict": {"status": "pass", "reason": "pattern_signal_ready", "signal_side": "home", "confidence": 0.68},
            "model_verdict": {"status": "pass", "reason": "model_signal_ready", "signal_side": "home", "confidence": 0.77},
            "history_verdict": {"status": "pass", "reason": "history_ready"},
            "odds_verdict": {"status": "pass", "reason": "odds_in_target_range", "bet_on": "home", "target_odds": 1.8},
            "agreement_verdict": {"status": "pass", "reason": "signals_aligned"},
        },
        flask_app=app,
    )

    assert result["sport_type"] == "basketball"

    with app.app_context():
        prediction = Prediction.query.one()
        assert prediction.sport_type == "basketball"
        assert prediction.bet_type == "winner"
        assert prediction.bookmaker == "bet365"
        assert prediction.confidence == pytest.approx(0.77)
        assert prediction.patterns_data["decision_status"] == "candidate"
        assert prediction.patterns_data["source"] == "AutoMonitorQualityGate"
