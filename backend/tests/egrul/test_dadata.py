"""Разбор ответа DaData и офлайн-профили — без БД и сети."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import get_settings
from app.egrul import dadata, offline

FIXTURES = Path(__file__).parent / "fixtures"
INN = "7017000019"


def _suggestion() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads((FIXTURES / f"{INN}.json").read_text())
    return raw["suggestions"][0]  # type: ignore[no-any-return]


def test_party_to_customer() -> None:
    c = dadata.party_to_customer(_suggestion())
    assert c.inn == INN
    assert c.ogrn == "1027000000001"
    assert c.name.startswith("ОБЛАСТНОЕ ГОСУДАРСТВЕННОЕ")
    assert c.org_type == "legal"
    assert c.status == "active"
    assert c.registration_date == date(2002, 10, 31)
    assert c.liquidation_date is None
    assert c.okved_main == "84.11.21"
    assert c.address == "634050, Томская обл, г Томск, пр-кт Ленина, д 36"
    assert c.region == "Томская область"
    assert c.unreliable_flags == []


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("LIQUIDATING", "liquidating"),
        ("LIQUIDATED", "liquidated"),
        ("BANKRUPT", "bankrupt"),
        ("REORGANIZING", "reorganizing"),
        ("SOMETHING", "unknown"),
    ],
)
def test_statuses(status: str, expected: str) -> None:
    s = _suggestion()
    s["data"]["state"]["status"] = status
    assert dadata.party_to_customer(s).status == expected


def test_unreliable_flags() -> None:
    s = _suggestion()
    s["data"]["invalid"] = True
    s["data"]["address"]["invalidity"] = {"code": "FNS"}
    s["data"]["management"]["disqualified"] = True
    assert dadata.party_to_customer(s).unreliable_flags == [
        "Недостоверные сведения об организации",
        "Недостоверный адрес",
        "Руководитель дисквалифицирован",
    ]


def test_offline_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "customers_dir", FIXTURES)
    found = offline.load(INN)
    assert found is not None and found[0].inn == INN
    assert offline.load("7707083893") is None

    (tmp_path / f"{INN}.json").write_text("{broken")
    monkeypatch.setattr(get_settings(), "customers_dir", tmp_path)
    assert offline.load(INN) is None


class _Resp:
    def __init__(self, status: int, body: object) -> None:
        self.status_code = status
        self._body = body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)  # type: ignore[arg-type]

    def json(self) -> object:
        return self._body


def test_find_party(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "dadata_api_key", "test-key")
    calls: list[dict[str, Any]] = []

    def post(url: str, **kwargs: Any) -> _Resp:
        calls.append(kwargs)
        return _Resp(200, {"suggestions": [_suggestion()]})

    monkeypatch.setattr(httpx, "post", post)
    assert dadata.find_party(INN) == _suggestion()
    assert calls[0]["json"]["query"] == INN
    assert calls[0]["headers"]["Authorization"] == "Token test-key"

    monkeypatch.setattr(httpx, "post", lambda url, **kw: _Resp(200, {"suggestions": []}))
    assert dadata.find_party(INN) is None


@pytest.mark.parametrize(
    "post",
    [
        lambda url, **kw: _Resp(403, {}),
        lambda url, **kw: _Resp(200, "not json object"),
        lambda url, **kw: (_ for _ in ()).throw(httpx.ConnectTimeout("timeout")),
    ],
)
def test_find_party_unavailable(monkeypatch: pytest.MonkeyPatch, post: Any) -> None:
    monkeypatch.setattr(get_settings(), "dadata_api_key", "test-key")
    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(dadata.DadataUnavailable):
        dadata.find_party(INN)


def test_no_key_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "dadata_api_key", "")
    with pytest.raises(dadata.DadataUnavailable):
        dadata.find_party(INN)
