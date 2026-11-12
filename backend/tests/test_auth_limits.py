"""Пароль длиннее 72 байт и ограничение попыток входа."""

from typing import Any

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from tests.conftest import make_client

LOGIN = "/api/auth/login"


def _login(c: TestClient, email: str, password: str, **kw: Any) -> int:
    return c.post(LOGIN, json={"email": email, "password": password}, **kw).status_code


def test_long_password_register_is_422() -> None:
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"email": "a@example.com", "password": "я" * 40})
    assert r.status_code == 422
    assert "72" in r.text


def test_long_password_login_is_401_not_500(client: TestClient) -> None:
    assert _login(client, "user@example.com", "я" * 100) == 401


def test_password_72_bytes_ok() -> None:
    c = make_client("b@example.com", "x" * 72)
    assert _login(c, "b@example.com", "x" * 72) == 200


def test_login_locked_after_failures() -> None:
    make_client("victim@example.com", "password123")
    c = TestClient(app)
    for _ in range(get_settings().login_max_failures):
        assert _login(c, "victim@example.com", "wrong-pass") == 401
    r = c.post(LOGIN, json={"email": "Victim@example.com", "password": "password123"})
    assert r.status_code == 429
    err = r.json()["error"]
    assert err["code"] == "TOO_MANY_ATTEMPTS"
    assert err["details"]["retry_after"] > 0
    # другой аккаунт с того же адреса входит
    make_client("other@example.com", "password123")
    assert _login(c, "other@example.com", "password123") == 200


def test_success_resets_counter() -> None:
    make_client("u@example.com", "password123")
    c = TestClient(app)
    for _ in range(2):
        for _ in range(get_settings().login_max_failures - 1):
            _login(c, "u@example.com", "wrong-pass")
        assert _login(c, "u@example.com", "password123") == 200


def test_ip_limit() -> None:
    c = TestClient(app)
    ip = {"X-Real-IP": "203.0.113.7"}
    for i in range(get_settings().login_max_failures_ip):
        _login(c, f"n{i}@example.com", "wrong-pass", headers=ip)
    assert _login(c, "fresh@example.com", "x", headers=ip) == 429
    assert _login(c, "fresh@example.com", "x", headers={"X-Real-IP": "203.0.113.8"}) == 401
