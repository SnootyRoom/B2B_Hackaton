"""XML через весь конвейер: загрузка → парсинг → ЕГРЮЛ (офлайн) → оценка. Нужна БД."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings

FIXTURES = Path(__file__).parent / "fixtures"
CUSTOMERS = Path(__file__).parents[1] / "egrul" / "fixtures"


def test_upload_xml_batch(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "customers_dir", CUSTOMERS)
    names = ["notice44_ef2020.xml", "notice223_multilot.xml", "protocol44.xml"]
    r = client.post(
        "/api/procurements/upload",
        files=[("files", (n, (FIXTURES / n).read_bytes(), "text/xml")) for n in names],
    )
    assert r.status_code == 202, r.text
    task = client.get(f"/api/tasks/{r.json()['task_id']}").json()
    assert task["status"] == "partial"
    by_name = {f["filename"]: f for f in task["files"]}
    assert len(by_name["notice223_multilot.xml"]["procurement_ids"]) == 2
    assert by_name["protocol44.xml"]["error"]["code"] == "NOT_A_NOTICE"

    rows = {row["reg_number"]: row for row in client.get("/api/results").json()}
    assert set(rows) == {"0365200000026000123", "32616481510-1", "32616481510-2"}
    assert all(row["total"] is not None for row in rows.values())


def test_offline_customer_in_card(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "customers_dir", CUSTOMERS)
    xml = (FIXTURES / "notice44_ef2020.xml").read_bytes().replace(b"7707083893", b"7017000019")
    r = client.post("/api/procurements/upload", files=[("files", ("n.xml", xml, "text/xml"))])
    f = client.get(f"/api/tasks/{r.json()['task_id']}").json()["files"][0]
    assert f["status"] == "ok" and f["warnings"] == []
    detail = client.get(f"/api/procurements/{f['procurement_ids'][0]}").json()
    assert detail["customer"]["source"] == "offline"
    assert detail["customer"]["status"] == "active"
    assert detail["data"]["region"] == "Томская область"
