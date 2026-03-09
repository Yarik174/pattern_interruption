import json

from src.multi_league_loader import MultiLeagueLoader


def test_get_available_seasons_uses_cached_files_when_present(tmp_path):
    cache_dir = tmp_path / "leagues"
    cache_dir.mkdir()
    (cache_dir / "seasons_35.json").write_text(json.dumps([2025, 2024, 2023]))

    loader = MultiLeagueLoader()
    loader.api_key = ""

    from src import multi_league_loader as module

    original_cache_dir = module.CACHE_DIR
    module.CACHE_DIR = cache_dir
    try:
        assert loader.get_available_seasons(35) == [2025, 2024, 2023]
    finally:
        module.CACHE_DIR = original_cache_dir


def test_get_available_seasons_falls_back_to_cached_game_files(tmp_path):
    cache_dir = tmp_path / "leagues"
    cache_dir.mkdir()
    (cache_dir / "games_35_2022.json").write_text("[]")
    (cache_dir / "games_35_2024.json").write_text("[]")
    (cache_dir / "games_35_2023.json").write_text("[]")

    loader = MultiLeagueLoader()
    loader.api_key = ""

    from src import multi_league_loader as module

    original_cache_dir = module.CACHE_DIR
    module.CACHE_DIR = cache_dir
    try:
        assert loader.get_available_seasons(35) == [2024, 2023, 2022]
    finally:
        module.CACHE_DIR = original_cache_dir


def test_get_games_prefers_cache_and_skips_request_without_api_key(tmp_path, monkeypatch):
    cache_dir = tmp_path / "leagues"
    cache_dir.mkdir()
    cached_games = [{"id": 1, "home_team": "SKA"}]
    (cache_dir / "games_35_2024.json").write_text(json.dumps(cached_games))

    loader = MultiLeagueLoader()
    loader.api_key = ""

    from src import multi_league_loader as module

    original_cache_dir = module.CACHE_DIR
    module.CACHE_DIR = cache_dir
    try:
        assert loader.get_games(35, 2024) == cached_games

        monkeypatch.setattr(loader, "_make_request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("API should not be called")))
        assert loader.get_games(35, 2025) == []
    finally:
        module.CACHE_DIR = original_cache_dir


def test_get_games_parses_finished_statuses_from_api(tmp_path, monkeypatch):
    cache_dir = tmp_path / "leagues"
    cache_dir.mkdir()

    loader = MultiLeagueLoader()
    loader.api_key = "token"

    from src import multi_league_loader as module

    original_cache_dir = module.CACHE_DIR
    module.CACHE_DIR = cache_dir
    try:
        monkeypatch.setattr(
            loader,
            "_make_request",
            lambda endpoint, params=None: {
                "response": [
                    {
                        "id": 10,
                        "date": "2026-03-10T19:00:00Z",
                        "status": {"short": "FT"},
                        "teams": {"home": {"name": "Frolunda", "id": 1}, "away": {"name": "Lulea", "id": 2}},
                        "scores": {"home": 3, "away": 2},
                    },
                    {
                        "id": 11,
                        "date": "2026-03-11T19:00:00Z",
                        "status": {"short": "NS"},
                        "teams": {"home": {"name": "Ignored", "id": 3}, "away": {"name": "Ignored", "id": 4}},
                        "scores": {"home": 0, "away": 0},
                    },
                    {
                        "id": 12,
                        "date": "2026-03-12T19:00:00Z",
                        "status": {"short": "AOT"},
                        "teams": {"home": {"name": "Skelleftea", "id": 5}, "away": {"name": "Farjestad", "id": 6}},
                        "scores": {"home": 1, "away": 2},
                    },
                ]
            },
        )

        games = loader.get_games(47, 2024)

        assert [game["id"] for game in games] == [10, 12]
        assert games[0]["home_win"] is True
        assert games[1]["home_win"] is False
        assert (cache_dir / "games_47_2024.json").exists()
    finally:
        module.CACHE_DIR = original_cache_dir


def test_load_league_data_skips_empty_latest_season_and_uses_older_cache(tmp_path, monkeypatch):
    cache_dir = tmp_path / "leagues"
    cache_dir.mkdir()
    (cache_dir / "seasons_35.json").write_text(json.dumps([2025, 2024, 2023]))
    cached_games = [{"id": 101, "season": 2024}, {"id": 102, "season": 2024}]
    (cache_dir / "games_35_2024.json").write_text(json.dumps(cached_games))

    loader = MultiLeagueLoader()
    loader.api_key = ""

    from src import multi_league_loader as module

    original_cache_dir = module.CACHE_DIR
    module.CACHE_DIR = cache_dir
    try:
        monkeypatch.setattr(loader, "_make_request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("API should not be called without key")))

        games = loader.load_league_data("KHL", n_seasons=1)

        assert games == cached_games
    finally:
        module.CACHE_DIR = original_cache_dir


def test_load_league_data_with_unlimited_seasons_uses_all_cached_non_empty_seasons(tmp_path, monkeypatch):
    cache_dir = tmp_path / "leagues"
    cache_dir.mkdir()
    (cache_dir / "seasons_47.json").write_text(json.dumps([2025, 2024, 2023, 2022]))
    (cache_dir / "games_47_2024.json").write_text(json.dumps([{"id": 1, "season": 2024}]))
    (cache_dir / "games_47_2023.json").write_text(json.dumps([{"id": 2, "season": 2023}]))
    (cache_dir / "games_47_2022.json").write_text(json.dumps([{"id": 3, "season": 2022}]))

    loader = MultiLeagueLoader()
    loader.api_key = ""

    from src import multi_league_loader as module

    original_cache_dir = module.CACHE_DIR
    module.CACHE_DIR = cache_dir
    try:
        monkeypatch.setattr(loader, "_make_request", lambda *args, **kwargs: None)
        games = loader.load_league_data("SHL", n_seasons=None)

        assert [game["id"] for game in games] == [1, 2, 3]
    finally:
        module.CACHE_DIR = original_cache_dir
