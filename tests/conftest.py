import importlib
import os
import sys
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def disable_network(monkeypatch):
    import requests.sessions

    def _blocked_request(*args, **kwargs):
        raise AssertionError("Сеть в тестах запрещена")

    monkeypatch.setattr(requests.sessions.Session, "request", _blocked_request)


@pytest.fixture
def games_factory():
    def _build(rows):
        records = []
        for index, row in enumerate(rows, start=1):
            if len(row) == 4:
                date, home_team, away_team, home_win = row
                game_id = f"game-{index}"
            else:
                date, home_team, away_team, home_win, game_id = row

            records.append(
                {
                    "game_id": game_id,
                    "date": pd.Timestamp(date),
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_win": int(home_win),
                }
            )

        return pd.DataFrame(records)

    return _build


@pytest.fixture(scope="session")
def app_module():
    previous_env = {
        "TESTING": os.environ.get("TESTING"),
        "SESSION_SECRET": os.environ.get("SESSION_SECRET"),
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
        "SUPABASE_URL": os.environ.get("SUPABASE_URL"),
        "SUPABASE_ANON_KEY": os.environ.get("SUPABASE_ANON_KEY"),
    }

    os.environ["TESTING"] = "1"
    os.environ["SESSION_SECRET"] = "test-secret-key"
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    os.environ.pop("SUPABASE_URL", None)
    os.environ.pop("SUPABASE_ANON_KEY", None)

    module = importlib.import_module("app")
    module = importlib.reload(module)

    yield module

    for key, value in previous_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def app(app_module):
    flask_app = app_module.create_app(testing=True, start_background=False)
    with flask_app.app_context():
        app_module.db.session.remove()
        app_module.db.drop_all()
        app_module.db.create_all()
    yield flask_app
    with flask_app.app_context():
        app_module.db.session.remove()
        app_module.db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def authenticated_client(client):
    with client.session_transaction() as session:
        session["user_id"] = 1
    return client
