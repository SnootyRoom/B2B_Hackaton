"""Задача B: загрузка закупок по реестровому номеру."""

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.procurements import split_numbers
from app.core.config import get_settings
from app.eis import EisError
from app.schemas.common import ErrorCode
from app.tasks import notice_source

FIXTURES = Path(__file__).parent / "parsers" / "fixtures"
N44 = "0365200000026000123"  # notice44_ef2020.xml
N223 = "32616481510"  # notice223_multilot.xml, несколько лотов


@pytest.fixture
def samples(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """data/samples теста: два образца; модуля ЕИС нет."""
    shutil.copy(FIXTURES / "notice44_ef2020.xml", tmp_path / f"{N44}.xml")
    shutil.copy(FIXTURES / "notice223_multilot.xml", tmp_path / f"{N223}.xml")
    monkeypatch.setattr(get_settings(), "samples_dir", tmp_path)
    monkeypatch.setattr(notice_source, "_eis_fetch", lambda: None)
    yield tmp_path


def _eis(monkeypatch: pytest.MonkeyPatch, fn: Callable[[str], bytes]) -> None:
    monkeypatch.setattr(notice_source, "_eis_fetch", lambda: fn)


def _fetch(client: TestClient, *numbers: str) -> dict[str, Any]:
    r = client.post("/api/procurements/fetch", json={"numbers": list(numbers)})
    assert r.status_code == 202, r.text
    task: dict[str, Any] = client.get(f"/api/tasks/{r.json()['task_id']}").json()
    assert task["kind"] == "fetch"
    return task


def _by_number(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["filename"]: f for f in task["files"]}


# ---------- разбор списка


def test_split_numbers() -> None:
    url = "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html"
    valid, invalid = split_numbers(
        [f"{N44}, {N223}\n№ {N44}", f"{url}?regNumber=0101300020326000001", "123;abc"]
    )
    assert valid == [N44, N223, "0101300020326000001"]
    assert invalid == ["123", "abc"]


def test_all_invalid_is_400(client: TestClient) -> None:
    r = client.post("/api/procurements/fetch", json={"numbers": ["123 abc"]})
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "INVALID_REG_NUMBER"
    assert err["details"]["invalid"] == ["123", "abc"]


def test_too_many_numbers(client: TestClient) -> None:
    numbers = [f"{i:019d}" for i in range(1, 202)]
    r = client.post("/api/procurements/fetch", json={"numbers": numbers})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "TOO_MANY_NUMBERS"


# ---------- обработка


def test_fetch_from_samples(client: TestClient, samples: Path) -> None:
    task = _fetch(client, f"{N44}\n{N223}")
    assert task["status"] == "done"
    assert task["processed"] == task["total"] == 2
    files = _by_number(task)
    assert files[N44]["status"] == "ok"
    assert len(files[N223]["procurement_ids"]) >= 2  # все лоты
    assert any(w["code"] == "EIS_FALLBACK_SAMPLE" for w in files[N44]["warnings"])
    rows = client.get("/api/results").json()
    assert len(rows) == 1 + len(files[N223]["procurement_ids"])
    assert all(r["total"] is not None for r in rows)


def test_one_bad_number_does_not_break_batch(client: TestClient, samples: Path) -> None:
    unknown = "0000000000000000001"
    task = _fetch(client, N44, unknown, "123")
    assert task["status"] == "partial"
    files = _by_number(task)
    assert files[N44]["status"] == "ok"
    assert files[unknown]["error"]["code"] == "EIS_UNAVAILABLE"
    assert "вручную" in files[unknown]["error"]["message"]
    assert files["123"]["error"]["code"] == "INVALID_REG_NUMBER"


def test_repeat_updates_not_duplicates(client: TestClient, samples: Path) -> None:
    first = _by_number(_fetch(client, N44, N223))
    second = _by_number(_fetch(client, N44, N223))
    assert first[N44]["procurement_ids"] == second[N44]["procurement_ids"]
    lots = len(first[N223]["procurement_ids"])
    assert len(client.get("/api/procurements").json()) == 1 + lots


def test_same_record_as_uploaded_file(client: TestClient, samples: Path) -> None:
    content = (FIXTURES / "notice44_ef2020.xml").read_bytes()
    r = client.post("/api/procurements/upload", files=[("files", ("a.xml", content, "text/xml"))])
    uploaded = client.get(f"/api/tasks/{r.json()['task_id']}").json()
    fetched = _by_number(_fetch(client, N44))
    assert uploaded["files"][0]["procurement_ids"] == fetched[N44]["procurement_ids"]


def test_eis_used_first(client: TestClient, samples: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fetch(number: str) -> bytes:
        calls.append(number)
        return (FIXTURES / "notice44_ef2020.xml").read_bytes()

    _eis(monkeypatch, fetch)
    f = _by_number(_fetch(client, N44))[N44]
    assert calls == [N44]
    assert f["status"] == "ok"
    assert all(w["code"] != "EIS_FALLBACK_SAMPLE" for w in f["warnings"])


@pytest.mark.parametrize("code", [ErrorCode.EIS_NOT_FOUND, ErrorCode.EIS_UNAVAILABLE])
def test_eis_error_without_sample(
    client: TestClient, samples: Path, monkeypatch: pytest.MonkeyPatch, code: ErrorCode
) -> None:
    def fetch(number: str) -> bytes:
        raise EisError(code, "x")

    _eis(monkeypatch, fetch)
    task = _fetch(client, "0101300020326000001")
    assert task["status"] == "failed"
    assert task["files"][0]["error"]["code"] == code


def test_eis_down_falls_back_to_sample(
    client: TestClient, samples: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fetch(number: str) -> bytes:
        raise EisError(ErrorCode.EIS_UNAVAILABLE, "captcha")

    _eis(monkeypatch, fetch)
    f = _by_number(_fetch(client, N44))[N44]
    assert f["status"] == "ok"
    assert any(w["code"] == "EIS_FALLBACK_SAMPLE" for w in f["warnings"])


def test_html_instead_of_xml_is_clear_error(
    client: TestClient, samples: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _eis(monkeypatch, lambda n: b"<html><body>captcha</body></html>")
    task = _fetch(client, "0101300020326000001")
    assert task["files"][0]["status"] == "error"
    assert task["files"][0]["error"]["code"] != "INTERNAL_ERROR"


def test_history_lists_fetch(client: TestClient, samples: Path) -> None:
    _fetch(client, N44)
    tasks = client.get("/api/tasks", params={"kind": "fetch"}).json()
    assert len(tasks) == 1
    assert tasks[0]["files"][0]["filename"] == N44
