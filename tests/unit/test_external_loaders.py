from types import SimpleNamespace

import requests

import src.flashlive_loader as flash_module
from src.apisports_odds_loader import APISportsOddsLoader
from src.data_loader import NHLDataLoader
from src.flashlive_loader import (
    FlashLiveLoader,
    MultiSportFlashLiveLoader,
    _send_error_alert,
    set_error_alert_callback,
)


def test_nhl_data_loader_falls_back_to_static_team_list(monkeypatch, tmp_path):
    loader = NHLDataLoader(cache_dir=str(tmp_path))

    def _raise(*args, **kwargs):
        raise requests.exceptions.ConnectionError("offline")

    monkeypatch.setattr("src.data_loader.requests.get", _raise)

    teams = loader.get_all_teams()

    assert "ANA" in teams
    assert teams["ANA"]["name"] == "Anaheim Ducks"
    assert loader.teams["BOS"]["abbrev"] == "BOS"


def test_api_sports_make_request_returns_none_without_api_key():
    loader = APISportsOddsLoader(api_key="")

    result = loader._make_request("games", {"league": 57})

    assert result is None


def test_api_sports_get_upcoming_games_uses_cache_before_request(monkeypatch):
    loader = APISportsOddsLoader(api_key="token")
    cached_games = [{"event_id": "evt-1", "match_date": None}]
    now = loader._last_reset_date = None

    from datetime import datetime

    loader._games_cache["games_NHL"] = (cached_games, datetime.utcnow())

    def _fail(*args, **kwargs):
        raise AssertionError("API should not be called when cache is warm")

    monkeypatch.setattr(loader, "_make_request", _fail)

    result = loader.get_upcoming_games(leagues=["NHL"])

    assert result == cached_games


def test_flashlive_loader_returns_empty_without_api_key():
    loader = FlashLiveLoader(api_key="")

    result = loader.get_upcoming_games()

    assert result == []


def test_flashlive_loader_prefers_flash_specific_proxy_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://system-proxy:8080")
    monkeypatch.setenv("FLASH_PROXY_URL", "http://flash-fallback:8080")
    monkeypatch.setenv("FLASH_API_PROXY_URL", "http://flash-primary:8080")

    loader = FlashLiveLoader(api_key="token")

    assert loader.proxy_url == "http://flash-primary:8080"
    assert loader._get_request_proxies() == {
        "http": "http://flash-primary:8080",
        "https": "http://flash-primary:8080",
    }


def test_flashlive_loader_request_with_retry_passes_proxy_settings(monkeypatch):
    monkeypatch.setenv("FLASH_API_PROXY_URL", "http://127.0.0.1:25345")
    loader = FlashLiveLoader(api_key="token")
    captured = {}

    class _Response:
        status_code = 200

    def _get(url, headers=None, params=None, timeout=None, proxies=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["params"] = params
        captured["timeout"] = timeout
        captured["proxies"] = proxies
        return _Response()

    monkeypatch.setattr("src.flashlive_loader.requests.get", _get)

    response = loader._request_with_retry("https://example.com", params={"sport_id": 4}, max_retries=1)

    assert response.status_code == 200
    assert captured["url"] == "https://example.com"
    assert captured["params"] == {"sport_id": 4}
    assert captured["proxies"] == {
        "http": "http://127.0.0.1:25345",
        "https": "http://127.0.0.1:25345",
    }


def test_flashlive_loader_retries_and_sends_error_alert(monkeypatch):
    loader = FlashLiveLoader(api_key="token")
    sleeps = []
    alerts = []

    monkeypatch.setattr("src.flashlive_loader.time.sleep", lambda delay: sleeps.append(delay))

    def _timeout(*args, **kwargs):
        raise requests.exceptions.Timeout()

    monkeypatch.setattr("src.flashlive_loader.requests.get", _timeout)
    set_error_alert_callback(lambda message: alerts.append(message))

    response = loader._request_with_retry("https://example.com", params={}, max_retries=3, base_delay=1)

    assert response is None
    assert sleeps == [1, 2, 4]
    assert len(alerts) == 1
    assert "failed after 3 retries" in alerts[0]

    set_error_alert_callback(None)


def test_send_error_alert_falls_back_to_telegram_notifier_when_callback_breaks(monkeypatch):
    sent = []

    class _Notifier:
        @staticmethod
        def is_configured():
            return True

        @staticmethod
        def send_error_alert(message):
            sent.append(message)

    def _broken_callback(message):
        raise RuntimeError("callback unavailable")

    set_error_alert_callback(_broken_callback)
    monkeypatch.setattr(flash_module, "_telegram_notifier_instance", _Notifier())

    _send_error_alert("critical outage")

    assert sent == ["critical outage"]

    set_error_alert_callback(None)
    monkeypatch.setattr(flash_module, "_telegram_notifier_instance", None)


def test_flashlive_parse_events_skips_finished_and_filters_leagues():
    loader = FlashLiveLoader(api_key="token")

    matches = loader._parse_events(
        {
            "DATA": [
                {
                    "NAME": "USA: NHL",
                    "EVENTS": [
                        {
                            "EVENT_ID": "1",
                            "STAGE_TYPE": "FINISHED",
                            "HOME_NAME": "Old Home",
                            "AWAY_NAME": "Old Away",
                        },
                        {
                            "EVENT_ID": "2",
                            "STAGE_TYPE": "Scheduled",
                            "HOME_NAME": "Anaheim Ducks",
                            "AWAY_NAME": "Boston Bruins",
                            "START_TIME": 1760000000,
                            "ODDS": {"1": 2.15, "2": 1.75, "X": 3.9},
                        },
                    ],
                }
            ]
        }
    )

    assert len(matches) == 1
    assert matches[0]["event_id"] == "flash_2"
    assert matches[0]["league"] == "NHL"
    assert matches[0]["home_odds"] == 2.15
    assert matches[0]["away_odds"] == 1.75
    assert matches[0]["draw_odds"] == 3.9
    assert matches[0]["match_date"] is not None
    assert loader._filter_by_leagues(matches, ["KHL"]) == []


def test_flashlive_get_event_odds_parses_full_time_market(monkeypatch):
    loader = FlashLiveLoader(api_key="token")

    class _Response:
        @staticmethod
        def json():
            return {
                "DATA": [
                    {"BETTING_TYPE": "Handicap", "PERIODS": []},
                    {
                        "BETTING_TYPE": "*1X2",
                        "PERIODS": [
                            {"ODDS_STAGE": "1st Period", "GROUPS": []},
                            {
                                "ODDS_STAGE": "Full Time",
                                "GROUPS": [
                                    {
                                        "MARKETS": [
                                            {
                                                "ODD_CELL_FIRST": {"VALUE": "2.30"},
                                                "ODD_CELL_SECOND": {"VALUE": "3.70"},
                                                "ODD_CELL_THIRD": {"VALUE": "1.65"},
                                                "BOOKMAKER_NAME": "Bet365",
                                            }
                                        ]
                                    }
                                ],
                            },
                        ],
                    },
                ]
            }

    monkeypatch.setattr(loader, "_request_with_retry", lambda *args, **kwargs: _Response())

    odds = loader.get_event_odds("flash_123")

    assert odds == {
        "home_odds": 2.3,
        "draw_odds": 3.7,
        "away_odds": 1.65,
        "bookmaker": "Bet365",
    }


def test_flashlive_get_event_odds_supports_home_away_market(monkeypatch):
    loader = FlashLiveLoader(api_key="token", sport_type=flash_module.SportType.BASKETBALL)

    class _Response:
        @staticmethod
        def json():
            return {
                "DATA": [
                    {
                        "BETTING_TYPE": "*Home/Away",
                        "PERIODS": [
                            {
                                "ODDS_STAGE": "*FT including OT",
                                "GROUPS": [
                                    {
                                        "MARKETS": [
                                            {
                                                "ODD_CELL_SECOND": {"VALUE": 1.48},
                                                "ODD_CELL_THIRD": {"VALUE": 2.55},
                                                "BOOKMAKER_NAME": "bet365",
                                            }
                                        ]
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }

    monkeypatch.setattr(loader, "_request_with_retry", lambda *args, **kwargs: _Response())

    odds = loader.get_event_odds("flash_456")

    assert odds == {
        "home_odds": 1.48,
        "draw_odds": None,
        "away_odds": 2.55,
        "bookmaker": "bet365",
    }


def test_flashlive_get_event_odds_treats_404_as_missing_market(monkeypatch):
    loader = FlashLiveLoader(api_key="token")

    class _Response:
        status_code = 404

    monkeypatch.setattr(loader, "_request_with_retry", lambda *args, **kwargs: _Response())

    assert loader.get_event_odds("flash_missing") is None


def test_flashlive_get_h2h_data_parses_last_matches_and_uses_cache(monkeypatch):
    loader = FlashLiveLoader(api_key="token")
    calls = []

    class _Response:
        @staticmethod
        def json():
            return {
                "DATA": [
                    {
                        "GROUP_LABEL": "Last matches: Anaheim Ducks",
                        "ITEMS": [
                            {
                                "START_TIME": 1760000000,
                                "HOME_PARTICIPANT": "Anaheim Ducks",
                                "AWAY_PARTICIPANT": "Boston Bruins",
                                "CURRENT_RESULT": "3:2",
                                "H_RESULT": "WIN",
                            },
                            {
                                "START_TIME": 1760086400,
                                "HOME_PARTICIPANT": "New York Rangers",
                                "AWAY_PARTICIPANT": "Anaheim Ducks",
                                "CURRENT_RESULT": "1:4",
                                "H_RESULT": "LOSS",
                            },
                        ],
                    },
                    {
                        "GROUP_LABEL": "Last matches: Boston Bruins",
                        "ITEMS": [
                            {
                                "START_TIME": 1760172800,
                                "HOME_PARTICIPANT": "Boston Bruins",
                                "AWAY_PARTICIPANT": "Toronto Maple Leafs",
                                "CURRENT_RESULT": "2:1",
                                "H_RESULT": "1",
                            }
                        ],
                    },
                ]
            }

    def _request(*args, **kwargs):
        calls.append(kwargs["params"]["event_id"])
        return _Response()

    monkeypatch.setattr(loader, "_request_with_retry", _request)

    first = loader.get_h2h_data("flash_evt-1")
    second = loader.get_h2h_data("flash_evt-1")

    assert calls == ["evt-1"]
    assert first == second
    assert len(first["home_team_matches"]) == 2
    assert first["home_team_matches"][0]["opponent"] == "Boston Bruins"
    assert first["home_team_matches"][0]["result"] == "WIN"
    assert first["away_team_matches"][0]["opponent"] == "Toronto Maple Leafs"


def test_flashlive_get_h2h_data_supports_nested_live_format(monkeypatch):
    loader = FlashLiveLoader(api_key="token")

    class _Response:
        @staticmethod
        def json():
            return {
                "DATA": [
                    {
                        "TAB_NAME": "Overall",
                        "GROUPS": [
                            {
                                "GROUP_LABEL": "Last matches: Trinec",
                                "ITEMS": [
                                    {
                                        "START_TIME": 1760000000,
                                        "HOME_PARTICIPANT": "Trinec",
                                        "AWAY_PARTICIPANT": "Olomouc",
                                        "HOME_SCORE_FULL": "3",
                                        "AWAY_SCORE_FULL": "1",
                                    }
                                ],
                            },
                            {
                                "GROUP_LABEL": "Last matches: Olomouc",
                                "ITEMS": [
                                    {
                                        "START_TIME": 1760086400,
                                        "HOME_PARTICIPANT": "*Kometa Brno",
                                        "AWAY_PARTICIPANT": "Olomouc",
                                        "HOME_SCORE_FULL": "4",
                                        "AWAY_SCORE_FULL": "5",
                                    }
                                ],
                            },
                        ],
                    }
                ]
            }

    monkeypatch.setattr(loader, "_request_with_retry", lambda *args, **kwargs: _Response())

    result = loader.get_h2h_data("flash_evt-live")

    assert result["home_team_matches"][0]["opponent"] == "Olomouc"
    assert result["home_team_matches"][0]["score"] == "3:1"
    assert result["home_team_matches"][0]["result"] == "WIN"
    assert result["away_team_matches"][0]["opponent"] == "Kometa Brno"
    assert result["away_team_matches"][0]["result"] == "WIN"


def test_flashlive_get_match_result_and_matches_with_odds(monkeypatch):
    loader = FlashLiveLoader(api_key="token")

    class _Response:
        @staticmethod
        def json():
            return {
                "DATA": {
                    "EVENT": {
                        "STAGE_TYPE": "FINISHED",
                        "HOME_NAME": "Anaheim Ducks",
                        "AWAY_NAME": "Boston Bruins",
                        "HOME_SCORE_CURRENT": "2",
                        "AWAY_SCORE_CURRENT": "5",
                    }
                }
            }

    monkeypatch.setattr(loader, "_request_with_retry", lambda *args, **kwargs: _Response())

    result = loader.get_match_result("flash_evt-2")

    assert result["status"] == "FINISHED"
    assert result["home_score"] == 2
    assert result["away_score"] == 5
    assert result["winner"] == "away"

    monkeypatch.setattr(
        loader,
        "get_upcoming_games",
        lambda days_ahead=2, leagues=None: [
            {"event_id": "flash_1", "league": "NHL", "home_team": "A", "away_team": "B"},
            {"event_id": "flash_2", "league": "KHL", "home_team": "C", "away_team": "D"},
        ],
    )
    monkeypatch.setattr(
        loader,
        "get_event_odds",
        lambda event_id: {"home_odds": 2.05, "away_odds": 1.8, "bookmaker": "Book"}
        if event_id == "flash_1"
        else None,
    )

    matches = loader.get_matches_with_odds(leagues=["NHL", "KHL"])

    assert len(matches) == 1
    assert matches[0]["event_id"] == "flash_1"
    assert matches[0]["bookmaker"] == "Book"
    assert matches[0]["home_odds"] == 2.05


def test_flashlive_get_matches_with_odds_uses_sport_supported_leagues_by_default(monkeypatch):
    loader = FlashLiveLoader(api_key="token", sport_type=flash_module.SportType.FOOTBALL)

    monkeypatch.setattr(
        loader,
        "get_upcoming_games",
        lambda days_ahead=2, leagues=None: [
            {"event_id": "flash_1", "league": "EPL", "home_team": "A", "away_team": "B"},
            {"event_id": "flash_2", "league": "NHL", "home_team": "C", "away_team": "D"},
        ],
    )
    monkeypatch.setattr(
        loader,
        "get_event_odds",
        lambda event_id: {"home_odds": 1.8, "away_odds": 4.1, "draw_odds": 3.2, "bookmaker": "Book"},
    )

    matches = loader.get_matches_with_odds()

    assert len(matches) == 1
    assert matches[0]["league"] == "EPL"
    assert matches[0]["draw_odds"] == 3.2


def test_multisport_flashlive_loader_aggregates_and_routes_by_sport(monkeypatch):
    loader = MultiSportFlashLiveLoader(api_key="token", sport_types=[flash_module.SportType.FOOTBALL, flash_module.SportType.BASKETBALL])

    class _FootballLoader:
        def get_upcoming_games(self, days_ahead=2, leagues=None):
            return [{"event_id": "f-1", "league": "EPL", "home_team": "Arsenal", "away_team": "Chelsea"}]

        def get_matches_with_odds(self, days_ahead=2, leagues=None):
            return [{"event_id": "f-1", "league": "EPL", "home_odds": 1.8, "away_odds": 4.2}]

        def get_match_result(self, event_id):
            return {"status": "FINISHED", "winner": "home"} if event_id == "f-1" else None

    class _BasketballLoader:
        def get_upcoming_games(self, days_ahead=2, leagues=None):
            return [{"event_id": "b-1", "league": "NBA", "home_team": "Cavs", "away_team": "Sixers"}]

        def get_matches_with_odds(self, days_ahead=2, leagues=None):
            return [{"event_id": "b-1", "league": "NBA", "home_odds": 1.5, "away_odds": 2.7}]

        def get_match_result(self, event_id):
            return {"status": "FINISHED", "winner": "away"} if event_id == "b-1" else None

    monkeypatch.setattr(
        loader,
        "_get_loader",
        lambda sport_type: _FootballLoader() if sport_type == flash_module.SportType.FOOTBALL else _BasketballLoader(),
    )

    upcoming = loader.get_upcoming_games()
    with_odds = loader.get_matches_with_odds()
    nba_only = loader.get_matches_with_odds(leagues=["NBA"])

    assert {match["sport_type"] for match in upcoming} == {"football", "basketball"}
    assert {match["league"] for match in with_odds} == {"EPL", "NBA"}
    assert [match["league"] for match in nba_only] == ["NBA"]
    assert loader.get_match_result("f-1", sport="football")["winner"] == "home"
    assert loader.get_match_result("b-1", league="NBA")["winner"] == "away"


def test_api_sports_make_request_tracks_daily_limit(monkeypatch):
    loader = APISportsOddsLoader(api_key="token")
    loader._daily_limit = 1

    class _Response:
        status_code = 200
        headers = {"x-ratelimit-requests-remaining": "42"}
        text = ""

        @staticmethod
        def json():
            return {"response": [{"id": 1}]}

    monkeypatch.setattr("src.apisports_odds_loader.requests.get", lambda *args, **kwargs: _Response())

    first = loader._make_request("games", {"league": 57})
    second = loader._make_request("games", {"league": 57})

    assert first == {"response": [{"id": 1}]}
    assert second is None
    assert loader._daily_requests == 1
    assert loader.get_requests_remaining() == 0


def test_api_sports_get_upcoming_games_filters_statuses_and_sorts(monkeypatch):
    loader = APISportsOddsLoader(api_key="token")

    def _make_request(endpoint, params):
        league_id = params["league"]
        if league_id == 57:
            return {
                "response": [
                    {
                        "id": 100,
                        "date": "2026-03-11T12:00:00Z",
                        "teams": {"home": {"name": "Boston Bruins"}, "away": {"name": "Anaheim Ducks"}},
                        "status": {"short": "NS", "long": "Not Started"},
                        "venue": {"name": "TD Garden"},
                    },
                    {
                        "id": 101,
                        "date": "2026-03-10T12:00:00Z",
                        "teams": {"home": {"name": "Live Team"}, "away": {"name": "Skip Team"}},
                        "status": {"short": "LIVE", "long": "Live"},
                        "venue": {"name": "Arena"},
                    },
                ]
            }
        return {
            "response": [
                {
                    "id": 200,
                    "date": "2026-03-09T12:00:00Z",
                    "teams": {"home": {"name": "SKA"}, "away": {"name": "CSKA"}},
                    "status": {"short": "PST", "long": "Postponed"},
                    "venue": {"name": "Ice Palace"},
                }
            ]
        }

    monkeypatch.setattr(loader, "_make_request", _make_request)

    games = loader.get_upcoming_games(leagues=["NHL", "KHL", "UNKNOWN"])

    assert [game["league"] for game in games] == ["KHL", "NHL"]
    assert [game["game_id"] for game in games] == [200, 100]
    assert games[0]["match_date"].isoformat() == "2026-03-09T12:00:00"
    assert games[1]["venue"] == "TD Garden"


def test_api_sports_parse_odds_get_upcoming_matches_and_live_games(monkeypatch):
    loader = APISportsOddsLoader(api_key="token")

    parsed = loader._parse_odds(
        {
            "bookmakers": [
                {
                    "name": "Book A",
                    "bets": [
                        {
                            "name": "1X2",
                            "values": [
                                {"value": "Home", "odd": "2.10"},
                                {"value": "Draw", "odd": "3.40"},
                                {"value": "Away", "odd": "1.72"},
                            ],
                        }
                    ],
                },
                {
                    "name": "Book B",
                    "bets": [
                        {
                            "name": "Match Winner",
                            "values": [
                                {"value": "1", "odd": "2.25"},
                                {"value": "2", "odd": "1.80"},
                            ],
                        }
                    ],
                },
            ]
        }
    )

    assert parsed["best_home_odds"] == 2.25
    assert parsed["best_away_odds"] == 1.8
    assert parsed["best_draw_odds"] == 3.4
    assert len(parsed["bookmakers"]) == 2

    monkeypatch.setattr(
        loader,
        "get_upcoming_games",
        lambda hours_ahead=48: [
            {
                "event_id": "apisports_1",
                "game_id": 1,
                "league": "NHL",
                "home_team": "Anaheim Ducks",
                "away_team": "Boston Bruins",
                "match_date": None,
            },
            {
                "event_id": "apisports_2",
                "game_id": 2,
                "league": "KHL",
                "home_team": "SKA",
                "away_team": "CSKA",
                "match_date": None,
            },
        ],
    )
    monkeypatch.setattr(
        loader,
        "get_odds_for_game",
        lambda game_id: parsed if game_id == 1 else None,
    )

    matches = loader.get_upcoming_matches()

    assert len(matches) == 2
    assert matches[0]["home_odds"] == 2.25
    assert matches[0]["bookmakers"][0]["bookmaker"] == "Book A"
    assert matches[1]["home_odds"] is None

    monkeypatch.setattr(
        loader,
        "_make_request",
        lambda endpoint, params: {
            "response": [
                {
                    "id": 10,
                    "league": {"id": 57},
                    "date": "2026-03-10T15:00:00Z",
                    "teams": {"home": {"name": "Boston Bruins"}, "away": {"name": "Toronto Maple Leafs"}},
                    "status": {"long": "Live", "short": "LIVE"},
                    "periods": {"current": 3},
                    "scores": {"home": 3, "away": 2},
                    "venue": {"name": "TD Garden"},
                },
                {
                    "id": 11,
                    "league": {"id": 999},
                    "date": "2026-03-10T15:00:00Z",
                    "teams": {"home": {"name": "Ignored"}, "away": {"name": "Ignored"}},
                    "status": {"long": "Live", "short": "LIVE"},
                    "periods": {"current": 2},
                    "scores": {"home": 1, "away": 1},
                    "venue": {"name": "Unknown"},
                },
            ]
        },
    )

    live_games = loader.get_live_games()

    assert len(live_games) == 1
    assert live_games[0]["league"] == "NHL"
    assert live_games[0]["is_live"] is True
    assert live_games[0]["current_period"] == 3
    assert live_games[0]["home_score"] == 3
    assert live_games[0]["away_score"] == 2
