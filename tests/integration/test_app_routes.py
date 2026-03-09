import io
import json
from types import SimpleNamespace

import pandas as pd


def test_root_redirects_to_predictions(authenticated_client):
    response = authenticated_client.get("/")

    assert response.status_code == 302
    assert "/predictions" in response.headers["Location"]


def test_api_upcoming_returns_matches(app_module, authenticated_client, monkeypatch):
    monkeypatch.setattr(
        app_module,
        "get_upcoming_games",
        lambda: [{"home_team": "ANA", "away_team": "BOS"}],
    )

    response = authenticated_client.get("/api/upcoming")

    assert response.status_code == 200
    assert response.get_json()["matches"] == [{"home_team": "ANA", "away_team": "BOS"}]


def test_api_upcoming_supports_sport_and_league_query(app_module, authenticated_client, monkeypatch):
    calls = []

    def _get_upcoming(sport=None, leagues=None, days_ahead=1):
        calls.append((sport, leagues, days_ahead))
        return [{"home_team": "Pyunik Yerevan", "away_team": "Shirak Gyumri", "league": "EPL", "sport": "football"}]

    monkeypatch.setattr(app_module, "get_upcoming_games", _get_upcoming)

    response = authenticated_client.get("/api/upcoming?sport=football&league=EPL&days=2")

    assert response.status_code == 200
    assert response.get_json()["sport"] == "football"
    assert response.get_json()["league"] == "EPL"
    assert response.get_json()["matches"][0]["league"] == "EPL"
    assert calls == [("football", ["EPL"], 2)]


def test_api_analyze_uses_uppercase_and_returns_error(app_module, authenticated_client, monkeypatch):
    calls = []

    def _analyze(home, away):
        calls.append((home, away))
        return None if home == "BAD" else {"home_team": home, "away_team": away}

    monkeypatch.setattr(app_module, "analyze_game", _analyze)

    ok_response = authenticated_client.get("/api/analyze/ana/bos")
    bad_response = authenticated_client.get("/api/analyze/bad/bos")

    assert ok_response.status_code == 200
    assert ok_response.get_json()["home_team"] == "ANA"
    assert bad_response.status_code == 400
    assert calls == [("ANA", "BOS"), ("BAD", "BOS")]


def test_api_analyze_all_merges_odds_and_sorts_by_signal(app_module, authenticated_client, monkeypatch):
    monkeypatch.setattr(
        app_module,
        "get_upcoming_games",
        lambda: [
            {"home_team": "AAA", "away_team": "BBB"},
            {"home_team": "CCC", "away_team": "DDD"},
        ],
    )
    monkeypatch.setattr(
        app_module,
        "fetch_odds",
        lambda: {
            "AAA_BBB": {"home_odds": 2.0, "away_odds": 1.8, "bookmaker": "Book A"},
            "CCC_DDD": {"home_odds": 2.7, "away_odds": 1.5, "bookmaker": "Book B"},
        },
    )

    def _analyze(home, away):
        if home == "AAA":
            return {
                "home_team": home,
                "away_team": away,
                "strong_signal": {"max": 2},
                "prediction": {
                    "predicted_winner": "home",
                    "home_probability": 60.0,
                    "away_probability": 40.0,
                },
            }
        return {
            "home_team": home,
            "away_team": away,
            "strong_signal": {"max": 5},
            "prediction": {
                "predicted_winner": "away",
                "home_probability": 35.0,
                "away_probability": 65.0,
            },
        }

    monkeypatch.setattr(app_module, "analyze_game", _analyze)

    response = authenticated_client.get("/api/analyze-all")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["odds_available"] is True
    assert [match["home_team"] for match in payload["matches"]] == ["CCC", "AAA"]
    assert payload["matches"][0]["odds"]["target"] == "away"
    assert payload["matches"][0]["odds"]["profitable"] is False
    assert payload["matches"][1]["odds"]["target"] == "home"
    assert payload["matches"][1]["odds"]["profitable"] is True


def test_api_odds_returns_count(app_module, authenticated_client, monkeypatch):
    monkeypatch.setattr(app_module, "fetch_odds", lambda: {"AAA_BBB": {"home_odds": 2.1}})

    response = authenticated_client.get("/api/odds")

    assert response.status_code == 200
    assert response.get_json()["count"] == 1


def test_api_odds_supports_sport_query(app_module, authenticated_client, monkeypatch):
    calls = []

    def _fetch_odds(sport=None, leagues=None, days_ahead=1):
        calls.append((sport, leagues, days_ahead))
        return {"Arsenal__Chelsea": {"home_odds": 1.8, "away_odds": 4.2, "draw_odds": 3.4}}

    monkeypatch.setattr(app_module, "fetch_odds", _fetch_odds)

    response = authenticated_client.get("/api/odds?sport=football&league=EPL&days=3")

    assert response.status_code == 200
    assert response.get_json()["sport"] == "football"
    assert response.get_json()["league"] == "EPL"
    assert response.get_json()["count"] == 1
    assert calls == [("football", ["EPL"], 3)]


def test_api_sports_returns_supported_catalog(authenticated_client):
    response = authenticated_client.get("/api/sports")

    assert response.status_code == 200
    payload = response.get_json()
    assert {sport["slug"] for sport in payload["sports"]} >= {"hockey", "football", "basketball", "volleyball"}


def test_sequence_status_reports_not_trained_and_ready(app_module, authenticated_client, monkeypatch):
    monkeypatch.setattr(app_module.os.path, "exists", lambda path: False)
    not_ready = authenticated_client.get("/api/sequence/status")

    assert not_ready.status_code == 200
    assert not_ready.get_json()["status"] == "not_trained"

    monkeypatch.setattr(app_module.os.path, "exists", lambda path: True)
    monkeypatch.setattr(
        "builtins.open",
        lambda *args, **kwargs: io.StringIO(json.dumps({"sequence_length": 10})),
    )
    ready = authenticated_client.get("/api/sequence/status")

    assert ready.status_code == 200
    assert ready.get_json()["status"] == "ready"
    assert ready.get_json()["config"]["sequence_length"] == 10


def test_sequence_predict_returns_expected_error_branches(app_module, authenticated_client, monkeypatch):
    monkeypatch.setattr(app_module, "init_system", lambda: None)
    monkeypatch.setattr(app_module, "init_sequence_model", lambda: (None, None))

    missing_model = authenticated_client.get("/api/sequence/predict/ana/bos")
    assert missing_model.status_code == 400
    assert "не загружена" in missing_model.get_json()["error"]

    preparer = SimpleNamespace(build_team_history=lambda df: {})
    monkeypatch.setattr(app_module, "init_sequence_model", lambda: (object(), preparer))
    monkeypatch.setattr(app_module, "all_games", pd.DataFrame())

    missing_data = authenticated_client.get("/api/sequence/predict/ana/bos")
    assert missing_data.status_code == 400
    assert "не загружены" in missing_data.get_json()["error"]

    monkeypatch.setattr(app_module, "all_games", pd.DataFrame([{"x": 1}]))
    no_team = authenticated_client.get("/api/sequence/predict/ana/bos")
    assert no_team.status_code == 400
    assert "Команда не найдена" in no_team.get_json()["error"]


def test_fetch_odds_selects_best_lines_and_uses_cache(app_module, monkeypatch):
    calls = []

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return [
                {
                    "home_team": "Anaheim Ducks",
                    "away_team": "Boston Bruins",
                    "commence_time": "2026-03-10T19:00:00Z",
                    "bookmakers": [
                        {
                            "title": "Book A",
                            "markets": [
                                {
                                    "key": "h2h",
                                    "outcomes": [
                                        {"name": "Anaheim Ducks", "price": 2.1},
                                        {"name": "Boston Bruins", "price": 1.7},
                                    ],
                                }
                            ],
                        },
                        {
                            "title": "Book B",
                            "markets": [
                                {
                                    "key": "h2h",
                                    "outcomes": [
                                        {"name": "Anaheim Ducks", "price": 2.35},
                                        {"name": "Boston Bruins", "price": 1.85},
                                    ],
                                }
                            ],
                        },
                    ],
                }
            ]

    def _get(*args, **kwargs):
        calls.append(kwargs.get("params", {}))
        return _Response()

    monkeypatch.setattr(app_module, "ODDS_API_KEY", "token")
    monkeypatch.setattr(app_module.requests, "get", _get)
    app_module.odds_cache = {}
    app_module.odds_cache_time = None

    first = app_module.fetch_odds()
    second = app_module.fetch_odds()

    assert calls and len(calls) == 1
    assert first == second
    assert first["ANA_BOS"]["home_odds"] == 2.35
    assert first["ANA_BOS"]["away_odds"] == 1.85
    assert first["ANA_BOS"]["bookmaker"] == "Book B"


def test_get_upcoming_games_keeps_only_future_or_pre_games(app_module, monkeypatch):
    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "gameWeek": [
                    {
                        "date": "2026-03-10",
                        "games": [
                            {
                                "id": 1,
                                "gameState": "FUT",
                                "startTimeUTC": "2026-03-10T19:00:00Z",
                                "homeTeam": {"abbrev": "ANA", "placeName": {"default": "Anaheim"}},
                                "awayTeam": {"abbrev": "BOS", "placeName": {"default": "Boston"}},
                                "venue": {"default": "Honda Center"},
                            },
                            {
                                "id": 2,
                                "gameState": "PRE",
                                "startTimeUTC": "2026-03-10T21:00:00Z",
                                "homeTeam": {"abbrev": "CGY", "placeName": {"default": "Calgary"}},
                                "awayTeam": {"abbrev": "EDM", "placeName": {"default": "Edmonton"}},
                                "venue": {"default": "Scotiabank Saddledome"},
                            },
                            {
                                "id": 3,
                                "gameState": "LIVE",
                                "startTimeUTC": "2026-03-10T22:00:00Z",
                                "homeTeam": {"abbrev": "NYR", "placeName": {"default": "New York"}},
                                "awayTeam": {"abbrev": "PHI", "placeName": {"default": "Philadelphia"}},
                                "venue": {"default": "MSG"},
                            },
                        ],
                    }
                ]
            }

    monkeypatch.setattr(app_module.requests, "get", lambda *args, **kwargs: _Response())

    games = app_module.get_upcoming_games()

    assert len(games) == 2
    assert [game["home_team"] for game in games] == ["ANA", "CGY"]
    assert games[0]["venue"] == "Honda Center"


def test_multi_league_routes_return_summary_matches_and_errors(app_module, authenticated_client, monkeypatch):
    class _Engine:
        @staticmethod
        def analyze_team_patterns(league):
            return {
                f"{league} A": {"overall_critical": True, "overall_streak": 4, "overall_alt": 0},
                f"{league} B": {"alt_critical": True, "overall_streak": -3, "overall_alt": 5},
                f"{league} C": {"overall_streak": 1, "overall_alt": 0},
            }

        @staticmethod
        def calc_strong_signal(pattern):
            return abs(pattern.get("overall_streak", 0)) + pattern.get("overall_alt", 0)

        @staticmethod
        def get_all_upcoming_with_analysis(leagues, include_odds=True):
            return [
                {
                    "league": "KHL",
                    "home_team": "SKA",
                    "away_team": "CSKA",
                    "date": "2026-03-11",
                    "time": "19:00",
                    "home_pattern": {"overall_streak": 4},
                    "away_pattern": {"overall_streak": -2},
                    "recommendation": "SKA",
                    "odds": {"home": 2.1, "away": 1.8},
                    "ev": 6.5,
                }
            ]

        @staticmethod
        def analyze_match(league, home, away):
            return {"league": league, "home_team": home, "away_team": away, "score": 4}

    monkeypatch.setattr(app_module, "init_multi_league", lambda: _Engine())

    summary = authenticated_client.get("/api/multi-league/summary")
    upcoming = authenticated_client.get("/api/multi-league/upcoming")
    valid = authenticated_client.get("/api/multi-league/analyze/KHL/ska/cska")
    invalid = authenticated_client.get("/api/multi-league/analyze/ABC/ska/cska")

    assert summary.status_code == 200
    assert summary.get_json()["KHL"]["total_teams"] == 3
    assert summary.get_json()["KHL"]["critical_count"] == 2
    assert upcoming.get_json()["leagues"]["KHL"] == 1
    assert upcoming.get_json()["matches"][0]["recommendation"] == "SKA"
    assert valid.get_json()["home_team"] == "ska"
    assert invalid.status_code == 400


def test_match_euro_odds_matches_partial_team_names(app_module):
    odds = app_module.match_euro_odds(
        "IFK Helsinki",
        "TPS Turku",
        {
            "HIFK_TPS": {
                "home_team": "HIFK Helsinki",
                "away_team": "TPS",
                "home_odds": 2.05,
                "away_odds": 1.82,
                "bookmaker": "NordicBet",
            }
        },
    )

    assert odds["bookmaker"] == "NordicBet"
    assert odds["home_odds"] == 2.05


def test_european_match_endpoints_attach_cpp_and_odds(app_module, authenticated_client, monkeypatch):
    shl_games = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-03-01"), "home_team": "Frolunda HC", "away_team": "Skelleftea AIK"},
            {"date": pd.Timestamp("2026-03-02"), "home_team": "Skelleftea AIK", "away_team": "Frolunda HC"},
            {"date": pd.Timestamp("2026-03-03"), "home_team": "Frolunda HC", "away_team": "Skelleftea AIK"},
            {"date": pd.Timestamp("2026-03-04"), "home_team": "Skelleftea AIK", "away_team": "Frolunda HC"},
            {"date": pd.Timestamp("2026-03-05"), "home_team": "Frolunda HC", "away_team": "Skelleftea AIK"},
        ]
    )

    monkeypatch.setattr(
        app_module,
        "init_euro_leagues",
        lambda: (
            object(),
            {"KHL": pd.DataFrame(), "SHL": shl_games, "Liiga": pd.DataFrame(), "DEL": pd.DataFrame()},
        ),
    )
    monkeypatch.setattr(
        app_module,
        "fetch_european_odds",
        lambda: {
            "SHL": {
                "Frolunda HC_Skelleftea AIK": {
                    "home_team": "Frolunda HC",
                    "away_team": "Skelleftea AIK",
                    "home_odds": 2.3,
                    "away_odds": 1.7,
                    "bookmaker": "Book SHL",
                }
            }
        },
    )
    monkeypatch.setattr(
        app_module,
        "get_euro_cpp_signals",
        lambda league, home, away: {
            "strong_signal": {"max": 3},
            "patterns": {
                "home": {"overall_streak": 4, "synergy": 2, "alternation_combo": 1},
                "away": {"overall_streak": -2, "synergy": 0, "alternation_combo": 0},
            },
            "cpp_prediction": {"team": "home", "synergy": 2, "patterns": ["signal"]},
        },
    )

    all_matches = authenticated_client.get("/api/european_matches")
    shl_only = authenticated_client.get("/api/european_matches/shl")
    bad_league = authenticated_client.get("/api/european_matches/abc")

    assert all_matches.status_code == 200
    assert all_matches.get_json()["SHL"]["matches"]
    assert all_matches.get_json()["SHL"]["matches"][0]["odds"]["target"] == "home"
    assert shl_only.status_code == 200
    assert shl_only.get_json()["league"] == "SHL"
    assert shl_only.get_json()["matches"][0]["odds"]["bookmaker"] == "Book SHL"
    assert bad_league.status_code == 400


def test_sequence_predict_success_returns_model_payload(app_module, authenticated_client, monkeypatch):
    class _Preparer:
        sequence_length = 2
        feature_columns = ["feature_a", "feature_b"]

        @staticmethod
        def build_team_history(df):
            return {
                "ANA": [
                    {"feature_a": 1.0, "feature_b": 2.0},
                    {"feature_a": 1.5, "feature_b": 2.5},
                ],
                "BOS": [
                    {"feature_a": 0.5, "feature_b": 1.0},
                    {"feature_a": 0.7, "feature_b": 1.2},
                ],
            }

        @staticmethod
        def normalize_sequences(home_seq, away_seq, fit=False):
            return home_seq, away_seq

    class _Model:
        @staticmethod
        def predict_match(home_seq, away_seq):
            assert home_seq.tolist() == [[1.0, 2.0], [1.5, 2.5]]
            assert away_seq.tolist() == [[0.5, 1.0], [0.7, 1.2]]
            return {"predicted_winner": "ANA", "confidence": 0.66}

    monkeypatch.setattr(app_module, "init_system", lambda: None)
    monkeypatch.setattr(app_module, "init_sequence_model", lambda: (_Model(), _Preparer()))
    monkeypatch.setattr(app_module, "all_games", pd.DataFrame([{"game_id": 1}]))

    response = authenticated_client.get("/api/sequence/predict/ana/bos")

    assert response.status_code == 200
    assert response.get_json()["home_team"] == "ANA"
    assert response.get_json()["away_team"] == "BOS"
    assert response.get_json()["sequence_length"] == 2
    assert response.get_json()["prediction"]["predicted_winner"] == "ANA"
