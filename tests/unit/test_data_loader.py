from datetime import datetime

import pandas as pd

import src.data_loader as data_loader_module
from src.data_loader import NHLDataLoader


def test_get_all_teams_parses_successful_response(monkeypatch, tmp_path):
    loader = NHLDataLoader(cache_dir=str(tmp_path))

    class _Response:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "standings": [
                    {
                        "teamAbbrev": {"default": "ANA"},
                        "teamName": {"default": "Anaheim Ducks"},
                    },
                    {
                        "teamAbbrev": {"default": "BOS"},
                        "teamName": {"default": "Boston Bruins"},
                    },
                    {
                        "teamAbbrev": {"default": ""},
                        "teamName": {"default": "Ignored"},
                    },
                ]
            }

    monkeypatch.setattr("src.data_loader.requests.get", lambda *args, **kwargs: _Response())

    teams = loader.get_all_teams()

    assert teams == {
        "ANA": {"name": "Anaheim Ducks", "abbrev": "ANA"},
        "BOS": {"name": "Boston Bruins", "abbrev": "BOS"},
    }
    assert loader.teams["ANA"]["name"] == "Anaheim Ducks"


def test_parse_game_handles_overtime_and_missing_abbrev(tmp_path):
    loader = NHLDataLoader(cache_dir=str(tmp_path))

    game = loader._parse_game(
        {
            "id": 123,
            "gameDate": "2026-03-10",
            "gameType": 2,
            "homeTeam": {"abbrev": "ANA", "score": 4},
            "awayTeam": {"abbrev": "BOS", "score": 3},
            "periodDescriptor": {"periodType": "OT"},
        }
    )

    assert game == {
        "game_id": 123,
        "date": "2026-03-10",
        "home_team": "ANA",
        "away_team": "BOS",
        "home_score": 4,
        "away_score": 3,
        "home_win": 1,
        "game_type": 2,
        "overtime": 1,
    }

    assert loader._parse_game({"homeTeam": {"abbrev": "ANA"}, "awayTeam": {"abbrev": ""}}) is None


def test_load_team_schedule_keeps_only_finished_games(monkeypatch, tmp_path):
    loader = NHLDataLoader(cache_dir=str(tmp_path))

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "games": [
                    {
                        "id": 1,
                        "gameDate": "2026-03-10",
                        "gameState": "FINAL",
                        "homeTeam": {"abbrev": "ANA", "score": 2},
                        "awayTeam": {"abbrev": "BOS", "score": 5},
                    },
                    {
                        "id": 2,
                        "gameDate": "2026-03-11",
                        "gameState": "LIVE",
                        "homeTeam": {"abbrev": "CGY", "score": 2},
                        "awayTeam": {"abbrev": "EDM", "score": 1},
                    },
                    {
                        "id": 3,
                        "gameDate": "2026-03-12",
                        "gameState": "OFF",
                        "homeTeam": {"abbrev": "NYR", "score": 1},
                        "awayTeam": {"abbrev": "PHI", "score": 0},
                    },
                ]
            }

    monkeypatch.setattr("src.data_loader.requests.get", lambda *args, **kwargs: _Response())

    games = loader.load_team_schedule("ANA", "20252026")

    assert [game["game_id"] for game in games] == [1, 3]
    assert games[0]["home_win"] == 0
    assert games[1]["home_win"] == 1


def test_cache_roundtrip_and_cache_info(tmp_path):
    loader = NHLDataLoader(cache_dir=str(tmp_path))
    season = "20252026"
    games = [
        {"game_id": 1, "date": "2026-01-10", "home_team": "ANA", "away_team": "BOS", "home_score": 2, "away_score": 1}
    ]

    loader._save_to_cache(season, games)
    loaded = loader._load_from_cache(season)
    info = loader.get_cache_info()

    assert loaded == games
    assert info["total_games"] == 1
    assert info["seasons"][0]["season"] == season
    assert info["seasons"][0]["games"] == 1


def test_load_season_from_api_uses_cache_and_deduplicates(monkeypatch, tmp_path):
    loader = NHLDataLoader(cache_dir=str(tmp_path))
    loader.teams = {"ANA": {}, "BOS": {}}
    season = "20252026"
    cached_games = [{"game_id": 11, "date": "2026-01-10"}]

    monkeypatch.setattr(loader, "_load_from_cache", lambda current_season: cached_games if current_season == season else None)
    monkeypatch.setattr(loader, "load_team_schedule", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("API should not be used when cache exists")))

    assert loader._load_season_from_api(season, use_cache=True) == cached_games

    monkeypatch.setattr(loader, "_load_from_cache", lambda current_season: None)
    monkeypatch.setattr(
        loader,
        "load_team_schedule",
        lambda team_abbr, current_season: [
            {
                "game_id": 100,
                "date": "2026-01-10",
                "home_team": "ANA",
                "away_team": "BOS",
                "home_score": 3,
                "away_score": 2,
                "home_win": 1,
                "game_type": 2,
                "overtime": 0,
            },
            {
                "game_id": 101 if team_abbr == "BOS" else 100,
                "date": "2026-01-11",
                "home_team": "BOS",
                "away_team": "ANA",
                "home_score": 1,
                "away_score": 4,
                "home_win": 0,
                "game_type": 2,
                "overtime": 0,
            },
        ],
    )
    monkeypatch.setattr("src.data_loader.time.sleep", lambda delay: None)

    games = loader._load_season_from_api(season, use_cache=False)

    assert sorted(game["game_id"] for game in games) == [100, 101]


def test_load_all_data_sorts_dates_and_deduplicates_game_ids(monkeypatch, tmp_path):
    loader = NHLDataLoader(cache_dir=str(tmp_path))

    monkeypatch.setattr(loader, "get_all_teams", lambda: {"ANA": {}, "BOS": {}})
    monkeypatch.setattr(
        loader,
        "_load_from_cache",
        lambda season: [{"game_id": 2, "date": "2026-01-12", "home_team": "BOS", "away_team": "ANA", "home_score": 1, "away_score": 2, "home_win": 0, "game_type": 2, "overtime": 0}]
        if season == "20242025"
        else None,
    )
    monkeypatch.setattr(
        loader,
        "_load_season_from_api",
        lambda season, use_cache=True: [
            {"game_id": 1, "date": "2026-01-10", "home_team": "ANA", "away_team": "BOS", "home_score": 2, "away_score": 1, "home_win": 1, "game_type": 2, "overtime": 0},
            {"game_id": 2, "date": "2026-01-12", "home_team": "BOS", "away_team": "ANA", "home_score": 1, "away_score": 2, "home_win": 0, "game_type": 2, "overtime": 0},
        ],
    )

    df = loader.load_all_data(seasons=["20242025", "20252026"], use_cache=True)

    assert list(df["game_id"]) == [1, 2]
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert loader.games[0]["game_id"] == 2


def test_get_default_seasons_respects_current_month(monkeypatch):
    class _OctoberDateTime:
        @staticmethod
        def now():
            return datetime(2026, 10, 5)

    class _MarchDateTime:
        @staticmethod
        def now():
            return datetime(2026, 3, 9)

    monkeypatch.setattr(data_loader_module, "datetime", _OctoberDateTime)
    assert NHLDataLoader.get_default_seasons(n_seasons=3) == ["20242025", "20252026", "20262027"]

    monkeypatch.setattr(data_loader_module, "datetime", _MarchDateTime)
    assert NHLDataLoader.get_default_seasons(n_seasons=3) == ["20232024", "20242025", "20252026"]


def test_clear_cache_and_generate_sample_data(tmp_path):
    loader = NHLDataLoader(cache_dir=str(tmp_path))
    season_file = tmp_path / "season_20252026.json"
    season_file.write_text("[]")

    loader.clear_cache()

    assert list(tmp_path.iterdir()) == []

    df = loader.generate_sample_data(n_games=25)

    assert len(df) == 25
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert all(df["home_team"] != df["away_team"])
    assert all(df["home_score"] != df["away_score"])
    assert set(df["overtime"].unique()).issubset({0, 1})


def test_get_cached_seasons_reads_and_sorts_local_files(tmp_path):
    loader = NHLDataLoader(cache_dir=str(tmp_path))
    (tmp_path / "season_20242025.json").write_text("[]")
    (tmp_path / "season_20222023.json").write_text("[]")
    (tmp_path / "season_20232024.json").write_text("[]")
    (tmp_path / "random.txt").write_text("x")

    assert loader.get_cached_seasons() == ["20222023", "20232024", "20242025"]
