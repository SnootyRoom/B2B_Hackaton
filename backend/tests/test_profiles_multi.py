"""Задача A: несколько профилей, переключение, устаревшие оценки."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal
from app.models import ScoringProfile
from app.schemas.scoring import MAX_PROFILES
from tests.conftest import make_client

P = "/api/scoring-profiles"


def _notice(n: int) -> bytes:
    return json.dumps(
        {
            "reg_number": f"03650000000000000{n:02d}",
            "law": "44",
            "subject": "Сопровождение программного обеспечения",
            "nmck": 1_000_000 * n,
            "method": "auction",
            "customer_inn": "7017000019",
            "region": "Томская область",
        }
    ).encode()


def _upload(client: TestClient, count: int = 3) -> None:
    files = [("files", (f"{i}.json", _notice(i), "application/json")) for i in range(1, count + 1)]
    r = client.post("/api/procurements/upload", files=files)
    assert r.status_code == 202, r.text


def _profiles(client: TestClient) -> list[dict[str, Any]]:
    return client.get(P).json()


def _active_count(client: TestClient) -> int:
    return sum(p["is_active"] for p in _profiles(client))


def _create(client: TestClient, name: str, **extra: Any) -> dict[str, Any]:
    r = client.post(P, json={"name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _results(client: TestClient, profile_id: str | None = None) -> list[dict[str, Any]]:
    params = {"profile_id": profile_id} if profile_id else {}
    r = client.get("/api/results", params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- создание, имя, лимит


def test_create_is_inactive_with_default_rules(client: TestClient) -> None:
    created = _create(client, "Осторожный")
    assert created["is_active"] is False
    assert created["rules"]
    assert _active_count(client) == 1
    assert [p["name"] for p in _profiles(client)] == ["Мой профиль", "Осторожный"]


def test_create_from_template(client: TestClient) -> None:
    created = _create(client, "Агрессивный", template="aggressive")
    assert created["name"] == "Агрессивный"
    assert created["rules"]


def test_name_taken(client: TestClient) -> None:
    _create(client, "Осторожный")
    r = client.post(P, json={"name": "  Осторожный "})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "PROFILE_NAME_TAKEN"


def test_profiles_limit(client: TestClient) -> None:
    for i in range(MAX_PROFILES - 1):
        _create(client, f"П{i}")
    r = client.post(P, json={"name": "Лишний"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "TOO_MANY_PROFILES"


def test_rename(client: TestClient) -> None:
    a = _create(client, "А")
    _create(client, "Б")
    r = client.patch(f"{P}/{a['id']}", json={"name": "Новое"})
    assert r.status_code == 200
    assert r.json()["name"] == "Новое"
    r = client.patch(f"{P}/{a['id']}", json={"name": "Б"})
    assert r.status_code == 409


# ---------- дублирование


def test_duplicate_names_and_not_active(client: TestClient) -> None:
    src = _profiles(client)[0]
    c1 = client.post(f"{P}/{src['id']}/duplicate").json()
    c2 = client.post(f"{P}/{src['id']}/duplicate").json()
    assert c1["name"] == "Мой профиль (копия)"
    assert c2["name"] == "Мой профиль (копия 2)"
    assert c1["is_active"] is False
    full = client.get(f"{P}/{src['id']}").json()
    assert c1["rules"] == full["rules"]
    assert _active_count(client) == 1


def test_duplicate_does_not_copy_scores(client: TestClient) -> None:
    _upload(client)
    src = _profiles(client)[0]
    copy = client.post(f"{P}/{src['id']}/duplicate").json()
    rows = _results(client, copy["id"])
    assert len(rows) == 3
    assert all(r["total"] is None and r["stale"] for r in rows)


# ---------- удаление


def test_cannot_delete_last(client: TestClient) -> None:
    only = _profiles(client)[0]
    r = client.delete(f"{P}/{only['id']}")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "LAST_PROFILE"


def test_delete_inactive(client: TestClient) -> None:
    extra = _create(client, "Лишний")
    r = client.delete(f"{P}/{extra['id']}")
    assert r.status_code == 200
    assert r.json() == {"task_id": None}
    assert len(_profiles(client)) == 1


def test_delete_active_promotes_another_and_rescores(client: TestClient) -> None:
    _upload(client)
    active = _profiles(client)[0]
    other = _create(client, "Другой")
    r = client.delete(f"{P}/{active['id']}")
    assert r.status_code == 200
    task_id = r.json()["task_id"]
    assert task_id is not None
    assert client.get(f"/api/tasks/{task_id}").json()["status"] == "done"
    rows = _profiles(client)
    assert [(p["id"], p["is_active"]) for p in rows] == [(other["id"], True)]
    assert all(not r["stale"] for r in _results(client))


# ---------- переключение


def test_activate_switches_and_rescores_only_stale(client: TestClient) -> None:
    _upload(client)
    first = _profiles(client)[0]
    second = _create(client, "Второй")

    r = client.post(f"{P}/{second['id']}/activate")
    assert r.status_code == 200
    task = client.get(f"/api/tasks/{r.json()['task_id']}").json()
    assert task["status"] == "done"
    assert task["total"] == 3
    assert _active_count(client) == 1
    assert _profiles(client)[0]["id"] == second["id"]
    assert all(not row["stale"] and row["total"] is not None for row in _results(client))

    # Обратно и снова туда — оценки обоих актуальны, пересчёта нет
    assert client.post(f"{P}/{first['id']}/activate").json() == {"task_id": None}
    assert client.post(f"{P}/{second['id']}/activate").json() == {"task_id": None}
    assert len(client.get("/api/procurements").json()) == 3


def test_edit_inactive_makes_scores_stale(client: TestClient) -> None:
    _upload(client)
    first = client.get(f"{P}/active").json()
    second = _create(client, "Второй")
    client.post(f"{P}/{second['id']}/activate")
    assert not any(r["stale"] for r in _results(client, first["id"]))

    body = {**first, "thresholds": {"participate": 90, "consider": 10}}
    r = client.put(f"{P}/{first['id']}", json=body)
    assert r.status_code == 200
    assert r.json()["task_id"] is None
    assert all(r["stale"] for r in _results(client, first["id"]))

    # Переименование версию не меняет
    client.patch(f"{P}/{second['id']}", json={"name": "Переименован"})
    assert not any(r["stale"] for r in _results(client, second["id"]))


def test_engine_change_makes_scores_stale(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _upload(client, 1)
    assert not _results(client)[0]["stale"]
    monkeypatch.setattr("app.scoring.version.ENGINE_REVISION", "test")
    assert _results(client)[0]["stale"]


def test_rescore_only_stale_via_score_endpoint(client: TestClient) -> None:
    _upload(client)
    other = _create(client, "Другой")
    r = client.post("/api/score", json={"profile_id": other["id"], "only_stale": True})
    task = client.get(f"/api/tasks/{r.json()['task_id']}").json()
    assert task["total"] == 3
    assert not any(row["stale"] for row in _results(client, other["id"]))
    r = client.post("/api/score", json={"profile_id": other["id"], "only_stale": True})
    assert client.get(f"/api/tasks/{r.json()['task_id']}").json()["total"] == 0


# ---------- изоляция и гарантии базы


def test_foreign_profile_404(client: TestClient) -> None:
    other = make_client("other@example.com")
    pid = _profiles(other)[0]["id"]
    full = other.get(f"{P}/{pid}").json()
    assert client.patch(f"{P}/{pid}", json={"name": "x"}).status_code == 404
    assert client.put(f"{P}/{pid}", json=full).status_code == 404
    assert client.post(f"{P}/{pid}/duplicate").status_code == 404
    assert client.post(f"{P}/{pid}/activate").status_code == 404
    assert client.delete(f"{P}/{pid}").status_code == 404
    assert _profiles(other)[0]["is_active"] is True


def test_db_forbids_two_active(client: TestClient) -> None:
    _create(client, "Второй")
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.execute(update(ScoringProfile).values(is_active=True))
        db.commit()


def test_one_active_after_any_sequence(client: TestClient) -> None:
    ids = [_profiles(client)[0]["id"]]
    ids.append(_create(client, "Б")["id"])
    ids.append(client.post(f"{P}/{ids[1]}/duplicate").json()["id"])
    client.post(f"{P}/{ids[2]}/activate")
    assert _active_count(client) == 1
    client.delete(f"{P}/{ids[2]}")
    assert _active_count(client) == 1
    client.post(f"{P}/{ids[0]}/activate")
    client.delete(f"{P}/{ids[0]}")
    assert _active_count(client) == 1
    assert client.get(f"{P}/active").json()["id"] == ids[1]
