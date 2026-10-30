from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import make_client


def test_register_sets_httponly_cookie() -> None:
    client = TestClient(app)
    r = client.post(
        "/api/auth/register", json={"email": "A@Example.com", "password": "password123"}
    )
    assert r.status_code == 201
    assert r.json()["email"] == "a@example.com"
    assert "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").json()["email"] == "a@example.com"


def test_register_duplicate_email() -> None:
    make_client("dup@example.com")
    r = TestClient(app).post(
        "/api/auth/register", json={"email": "dup@example.com", "password": "password123"}
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "EMAIL_TAKEN"


def test_login_logout() -> None:
    make_client("u@example.com", "secret-pass")
    client = TestClient(app)
    bad = client.post("/api/auth/login", json={"email": "u@example.com", "password": "wrong"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "INVALID_CREDENTIALS"
    ok = client.post("/api/auth/login", json={"email": "u@example.com", "password": "secret-pass"})
    assert ok.status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_protected_endpoints_require_login() -> None:
    client = TestClient(app)
    for path in (
        "/api/auth/me",
        "/api/procurements",
        "/api/results",
        "/api/scoring-profiles/active",
    ):
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.json() == {
            "error": {"code": "NOT_AUTHENTICATED", "message": "Войдите в систему", "details": {}}
        }


def test_validation_error_format(client: TestClient) -> None:
    r = TestClient(app).post("/api/auth/register", json={"email": "bad", "password": "x"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
