"""Контракты задач A (несколько профилей) и B (загрузка по номеру).

Готовое — проверяется полностью; заглушки — что маршрут есть, изолирован и отвечает 501.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.schemas.procurement import REG_NUMBER_PATTERN
from tests.conftest import make_client


def _profiles(client: TestClient) -> list[dict[str, object]]:
    r = client.get("/api/scoring-profiles")
    assert r.status_code == 200, r.text
    return r.json()


def test_list_profiles_creates_default(client: TestClient) -> None:
    rows = _profiles(client)
    assert len(rows) == 1
    assert rows[0]["is_active"] is True
    assert rows[0]["name"] == "Мой профиль"
    assert isinstance(rows[0]["rules_count"], int)


def test_get_profile_by_id_and_fixed_routes_still_work(client: TestClient) -> None:
    pid = _profiles(client)[0]["id"]
    r = client.get(f"/api/scoring-profiles/{pid}")
    assert r.status_code == 200
    assert r.json()["id"] == pid
    assert client.get("/api/scoring-profiles/active").json()["id"] == pid
    assert client.get("/api/scoring-profiles/catalog").status_code == 200


def test_foreign_profile_is_404_everywhere(client: TestClient) -> None:
    other = make_client("other@example.com")
    pid = _profiles(other)[0]["id"]
    assert client.get(f"/api/scoring-profiles/{pid}").status_code == 404
    assert client.get("/api/results", params={"profile_id": pid}).status_code == 404
    assert client.post("/api/score", json={"profile_id": pid}).status_code == 404
    mine = _profiles(client)[0]["id"]
    r = client.get("/api/results/compare", params={"a": mine, "b": pid})
    assert r.status_code == 404
    assert client.get(f"/api/scoring-profiles/{uuid.uuid4()}").status_code == 404


def test_results_by_profile_id(client: TestClient) -> None:
    pid = _profiles(client)[0]["id"]
    r = client.get("/api/results", params={"profile_id": pid})
    assert r.status_code == 200
    assert r.json() == []


def test_score_accepts_profile_and_only_stale(client: TestClient) -> None:
    pid = _profiles(client)[0]["id"]
    r = client.post("/api/score", json={"profile_id": pid, "only_stale": True})
    assert r.status_code == 202
    assert "task_id" in r.json()


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/api/scoring-profiles", {"name": "Агрессивный", "template": "aggressive"}),
        ("patch", "/api/scoring-profiles/{pid}", {"name": "Новое имя"}),
        ("post", "/api/scoring-profiles/{pid}/duplicate", None),
        ("post", "/api/scoring-profiles/{pid}/activate", None),
        ("delete", "/api/scoring-profiles/{pid}", None),
        ("post", "/api/procurements/fetch", {"numbers": ["0101300020326000001"]}),
    ],
)
def test_stubs_answer_501(
    client: TestClient, method: str, path: str, body: dict[str, object] | None
) -> None:
    pid = _profiles(client)[0]["id"]
    r = client.request(method, path.format(pid=pid), json=body)
    assert r.status_code == 501, r.text
    assert r.json()["error"]["code"] == "NOT_IMPLEMENTED"


def test_create_profile_validation(client: TestClient) -> None:
    r = client.post("/api/scoring-profiles", json={"name": "   "})
    assert r.status_code == 422
    r = client.post(
        "/api/scoring-profiles", json={"name": "x", "template": "cautious", "rules": []}
    )
    assert r.status_code == 422


def test_reg_number_pattern() -> None:
    import re

    ok = ["0101300020326000001", "32514850391", "203950000012401084"]
    bad = ["123", "0101300020326000001-1", "abc", "010130002032600000"[:15]]
    assert all(re.fullmatch(REG_NUMBER_PATTERN, n) for n in ok)
    assert not any(re.fullmatch(REG_NUMBER_PATTERN, n) for n in bad)
