from datetime import datetime

from models import Prediction, UserWatchlist


def _seed_prediction(app_module, app, **overrides):
    payload = {
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
        "patterns_data": {"bet_on": "home"},
        "model_version": "test",
    }
    payload.update(overrides)

    with app.app_context():
        prediction = Prediction(**payload)
        app_module.db.session.add(prediction)
        app_module.db.session.commit()
        return prediction.id


def test_api_predictions_respects_limit_and_league_filter(app_module, authenticated_client, app):
    _seed_prediction(app_module, app, league="NHL", home_team="A", away_team="B")
    _seed_prediction(app_module, app, league="KHL", home_team="C", away_team="D")

    response = authenticated_client.get("/api/predictions?league=NHL&limit=1")

    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload["predictions"]) == 1
    assert payload["predictions"][0]["league"] == "NHL"


def test_api_prediction_detail_returns_404_for_missing_prediction(authenticated_client):
    response = authenticated_client.get("/api/predictions/9999")

    assert response.status_code == 404
    assert response.get_json()["error"]


def test_watchlist_flow_add_update_and_remove(app_module, authenticated_client, app):
    prediction_id = _seed_prediction(app_module, app)

    added = authenticated_client.post(f"/api/watchlist/{prediction_id}")
    added_again = authenticated_client.post(f"/api/watchlist/{prediction_id}")
    noted = authenticated_client.patch(
        f"/api/watchlist/{prediction_id}/note",
        json={"note": "Сильный сигнал"},
    )
    removed = authenticated_client.delete(f"/api/watchlist/{prediction_id}")
    missing_note = authenticated_client.patch("/api/watchlist/9999/note", json={"note": "missing"})

    assert added.status_code == 200
    assert added.get_json()["status"] == "added"
    assert added_again.get_json()["status"] == "already_added"
    assert noted.get_json()["status"] == "ok"
    assert removed.get_json()["status"] == "removed"
    assert missing_note.status_code == 404

    with app.app_context():
        assert UserWatchlist.query.count() == 0


def test_watchlist_note_persists_before_removal(app_module, authenticated_client, app):
    prediction_id = _seed_prediction(app_module, app)
    authenticated_client.post(f"/api/watchlist/{prediction_id}")

    response = authenticated_client.patch(
        f"/api/watchlist/{prediction_id}/note",
        json={"note": "Взять в ручной отбор"},
    )

    assert response.status_code == 200
    with app.app_context():
        entry = UserWatchlist.query.one()
        assert entry.note == "Взять в ручной отбор"
