from werkzeug.security import generate_password_hash

from models import User


def test_protected_page_redirects_to_login(client):
    response = client.get("/predictions")

    assert response.status_code == 302
    assert "/auth/login?next=/predictions" in response.headers["Location"]


def test_register_login_and_logout_flow(app_module, client, app):
    register_response = client.post(
        "/auth/register",
        data={
            "email": "user@example.com",
            "password": "secret123",
            "confirm": "secret123",
        },
        follow_redirects=False,
    )

    assert register_response.status_code == 302
    assert "/predictions" in register_response.headers["Location"]

    with client.session_transaction() as session:
        assert session["user_id"]

    logout_response = client.get("/auth/logout", follow_redirects=False)
    assert logout_response.status_code == 302

    with client.session_transaction() as session:
        assert "user_id" not in session

    login_response = client.post(
        "/auth/login",
        data={"email": "user@example.com", "password": "secret123"},
        follow_redirects=False,
    )

    assert login_response.status_code == 302
    assert "/predictions" in login_response.headers["Location"]

    with client.session_transaction() as session:
        assert session["user_id"]


def test_login_with_invalid_password_shows_error(app_module, client, app):
    with app.app_context():
        user = User(
            email="wrong@example.com",
            password_hash=generate_password_hash("right-pass", method="pbkdf2:sha256", salt_length=16),
        )
        app_module.db.session.add(user)
        app_module.db.session.commit()

    response = client.post(
        "/auth/login",
        data={"email": "wrong@example.com", "password": "bad-pass"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Неверный email или пароль".encode() in response.data


def test_auth_forgot_reports_found_and_missing_users(app_module, client, app):
    missing_response = client.post(
        "/auth/forgot",
        data={"email": "missing@example.com"},
        follow_redirects=True,
    )

    assert missing_response.status_code == 200
    assert "Пользователь не найден.".encode() in missing_response.data

    with app.app_context():
        user = User(
            email="found@example.com",
            password_hash=generate_password_hash("secret123", method="pbkdf2:sha256", salt_length=16),
        )
        app_module.db.session.add(user)
        app_module.db.session.commit()

    found_response = client.post(
        "/auth/forgot",
        data={"email": "found@example.com"},
        follow_redirects=True,
    )

    assert found_response.status_code == 200
    assert "Пользователь найден. Инструкция отправлена.".encode() in found_response.data


def test_auth_db_init_and_app_hooks_are_registered_once(app, client):
    before_hooks = [func.__name__ for func in app.before_request_funcs[None]]
    after_hooks = [func.__name__ for func in app.after_request_funcs[None]]

    assert before_hooks.count("require_login") == 1
    assert after_hooks.count("add_header") == 1

    response = client.get("/auth/db-init")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert "users" in payload["tables"]


def test_auth_routes_include_no_cache_headers(client):
    response = client.get("/auth/login")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, no-cache, must-revalidate, max-age=0"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Expires"] == "0"
