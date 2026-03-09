from datetime import datetime

from src.telegram_bot import TelegramNotifier


def test_send_prediction_alert_includes_sport_bookmaker_and_named_team_odds(monkeypatch):
    notifier = TelegramNotifier(bot_token="token", chat_id="chat")
    captured = {}

    def _capture_message(text, parse_mode="HTML"):
        captured["text"] = text
        captured["parse_mode"] = parse_mode
        return True

    monkeypatch.setattr(notifier, "send_message", _capture_message)

    result = notifier.send_prediction_alert(
        {
            "sport_type": "basketball",
            "league": "NBA",
            "home_team": "Los Angeles Lakers",
            "away_team": "Boston Celtics",
            "predicted_outcome": "Los Angeles Lakers",
            "match_date": datetime(2026, 3, 9, 19, 30),
            "home_odds": 2.15,
            "away_odds": 1.72,
            "confidence": 0.82,
            "bet_type": "winner",
            "bookmaker": "FlashLive",
            "patterns_data": {"bet_on": "home", "target_odds": 2.15, "pattern_type": "streak"},
        }
    )

    assert result is True
    assert "🏀 Баскетбол" in captured["text"]
    assert "<b>Лига:</b> NBA" in captured["text"]
    assert "<b>Прогноз:</b> Los Angeles Lakers" in captured["text"]
    assert "<b>Коэффициент:</b> 2.15" in captured["text"]
    assert "<b>Уверенность:</b> 8/10" in captured["text"]
    assert "<b>Рынок:</b> winner" in captured["text"]
    assert "<b>Букмекер:</b> FlashLive" in captured["text"]
    assert "<b>Паттерн:</b> streak" in captured["text"]


def test_send_prediction_alert_parses_patterns_json_and_away_side(monkeypatch):
    notifier = TelegramNotifier(bot_token="token", chat_id="chat")
    captured = {}

    def _capture_message(text, parse_mode="HTML"):
        captured["text"] = text
        captured["parse_mode"] = parse_mode
        return True

    monkeypatch.setattr(notifier, "send_message", _capture_message)

    result = notifier.send_prediction_alert(
        {
            "sport_type": "football",
            "league": "EPL",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "predicted_outcome": "Chelsea",
            "home_odds": 2.6,
            "away_odds": 3.1,
            "confidence_1_10": 7,
            "patterns_data": '{"bet_on":"away","target_odds":3.4,"pattern_type":"alternation"}',
        }
    )

    assert result is True
    assert "⚽ Футбол" in captured["text"]
    assert "<b>Прогноз:</b> Chelsea" in captured["text"]
    assert "<b>Коэффициент:</b> 3.4" in captured["text"]
    assert "<b>Паттерн:</b> alternation" in captured["text"]


def test_send_daily_summary_groups_predictions_by_sport(monkeypatch):
    notifier = TelegramNotifier(bot_token="token", chat_id="chat")
    captured = {}

    def _capture_message(text, parse_mode="HTML"):
        captured["text"] = text
        captured["parse_mode"] = parse_mode
        return True

    monkeypatch.setattr(notifier, "send_message", _capture_message)

    result = notifier.send_daily_summary(
        predictions=[
            {"sport_type": "football"},
            {"sport_type": "football"},
            {"sport_type": "hockey"},
            {},
        ],
        stats={"wins": 2, "losses": 1, "pending": 1, "win_rate": 66.7, "roi": 12.5},
    )

    assert result is True
    assert "<b>Всего прогнозов:</b> 4" in captured["text"]
    assert "<b>По видам спорта:</b>" in captured["text"]
    assert "🏒 Хоккей: 2" in captured["text"]
    assert "⚽ Футбол: 2" in captured["text"]
