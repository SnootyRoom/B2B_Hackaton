"""Шаблон строится от базового профиля, а не от уже «агрессивного»;
запасной путь загрузки по номеру — только при недоступной ЕИС."""

import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.eis import EisError
from app.schemas.common import ErrorCode
from app.tasks import notice_source

P = "/api/scoring-profiles"
NMCK_RULE = {
    "id": "nmck_range",
    "group": "procurement",
    "kind": "weighted",
    "field": "nmck",
    "operator": "between",
    "value": [1_000_000, 3_000_000],
    "weight": 3,
    "label": "НМЦК в диапазоне",
}


def _setup_base(client: TestClient) -> dict[str, Any]:
    active = client.get(f"{P}/active").json()
    body = {**active, "rules": [*active["rules"], NMCK_RULE]}
    assert client.put(f"{P}/active", json=body).status_code == 200
    return client.get(f"{P}/active").json()


def _create(client: TestClient, name: str, template: str) -> dict[str, Any]:
    r = client.post(P, json={"name": name, "template": template})
    assert r.status_code == 201, r.text
    return r.json()


def _nmck(profile: dict[str, Any]) -> list[float]:
    rule = next(r for r in profile["rules"] if r["id"] == "nmck_range")
    return [float(x) for x in rule["value"]]


def test_template_from_template_does_not_compound(client: TestClient) -> None:
    _setup_base(client)
    agg1 = _create(client, "Агрессивный", "aggressive")
    assert _nmck(agg1) == [500_000, 6_000_000]

    client.post(f"{P}/{agg1['id']}/activate")
    agg2 = _create(client, "Агрессивный 2", "aggressive")
    assert _nmck(agg2) == _nmck(agg1)  # а не ×4 от исходного
    assert agg2["rules"] == agg1["rules"]

    cautious = _create(client, "Осторожный", "cautious")
    ids = {r["id"] for r in cautious["rules"]}
    assert _nmck(cautious) == [1_000_000, 3_000_000]  # от базы, не от «Агрессивного»
    assert "stop_customer_reorganizing" in ids
    statuses = next(r for r in cautious["rules"] if r["id"] == "customer_active")["value"]
    assert "reorganizing" not in statuses


def test_duplicate_of_template_keeps_base(client: TestClient) -> None:
    _setup_base(client)
    agg = _create(client, "Агрессивный", "aggressive")
    copy = client.post(f"{P}/{agg['id']}/duplicate").json()
    client.post(f"{P}/{copy['id']}/activate")
    again = _create(client, "Ещё агрессивный", "aggressive")
    assert _nmck(again) == _nmck(agg)


def test_base_deleted_falls_back_to_active(client: TestClient) -> None:
    base = _setup_base(client)
    agg = _create(client, "Агрессивный", "aggressive")
    client.post(f"{P}/{agg['id']}/activate")
    assert client.delete(f"{P}/{base['id']}").status_code == 200
    again = _create(client, "Агрессивный 2", "aggressive")
    assert _nmck(again) == [250_000, 12_000_000]  # базы нет — от активного


# ---------- запасной путь загрузки по номеру

FIXTURES = Path(__file__).parent / "parsers" / "fixtures"
N44 = "0365200000026000123"


@pytest.fixture
def samples(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copy(FIXTURES / "notice44_ef2020.xml", tmp_path / f"{N44}.xml")
    monkeypatch.setattr(get_settings(), "samples_dir", tmp_path)
    return tmp_path


def _fetch_one(client: TestClient, number: str) -> dict[str, Any]:
    r = client.post("/api/procurements/fetch", json={"numbers": [number]})
    assert r.status_code == 202, r.text
    file: dict[str, Any] = client.get(f"/api/tasks/{r.json()['task_id']}").json()["files"][0]
    return file


def test_not_found_does_not_use_sample(
    client: TestClient, samples: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fetch(number: str) -> bytes:
        raise EisError(ErrorCode.EIS_NOT_FOUND, "нет")

    monkeypatch.setattr(notice_source, "_eis_fetch", lambda: fetch)
    f = _fetch_one(client, N44)
    assert f["status"] == "error"
    assert f["error"]["code"] == "EIS_NOT_FOUND"


def test_unavailable_uses_sample(
    client: TestClient, samples: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fetch(number: str) -> bytes:
        raise EisError(ErrorCode.EIS_UNAVAILABLE, "таймаут")

    monkeypatch.setattr(notice_source, "_eis_fetch", lambda: fetch)
    f = _fetch_one(client, N44)
    assert f["status"] == "ok"
    assert any(w["code"] == "EIS_FALLBACK_SAMPLE" for w in f["warnings"])
