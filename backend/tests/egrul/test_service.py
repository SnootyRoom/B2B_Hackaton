"""Цепочка получения профиля заказчика: кэш → DaData → устаревший кэш → офлайн. Нужна БД."""

import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.egrul import dadata, service
from app.models import CustomerProfile, utcnow

FIXTURES = Path(__file__).parent / "fixtures"
INN = "7017000019"


def _suggestion() -> dict[str, Any]:
    return json.loads((FIXTURES / f"{INN}.json").read_text())["suggestions"][0]  # type: ignore[no-any-return]


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Session]:
    monkeypatch.setattr(get_settings(), "customers_dir", tmp_path)
    with SessionLocal() as session:
        yield session


def _dadata_ok(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def find(inn: str) -> dict[str, Any]:
        calls.append(inn)
        return _suggestion()

    monkeypatch.setattr(dadata, "find_party", find)
    return calls


def _dadata_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def find(inn: str) -> dict[str, Any]:
        raise dadata.DadataUnavailable("down")

    monkeypatch.setattr(dadata, "find_party", find)


def test_invalid_inn(db: Session) -> None:
    r = service.lookup(db, "7017000010")
    assert r.profile is None and r.error == "CUSTOMER_NOT_FOUND"


def test_dadata_then_cache(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _dadata_ok(monkeypatch)
    first = service.lookup(db, INN)
    assert first.profile is not None and first.profile.source == "dadata"
    assert first.profile.status == "active"
    second = service.lookup(db, INN)
    assert second.profile is not None and second.profile.source == "cache"
    assert calls == [INN]
    row = db.get(CustomerProfile, INN)
    assert row is not None and row.raw is not None and row.region == "Томская область"


def test_stale_cache_when_dadata_down(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    _dadata_ok(monkeypatch)
    service.lookup(db, INN)
    row = db.get(CustomerProfile, INN)
    assert row is not None
    row.fetched_at = utcnow() - timedelta(days=8)
    db.flush()
    _dadata_down(monkeypatch)
    r = service.lookup(db, INN)
    assert r.profile is not None and r.profile.source == "stale_cache"


def test_offline_profile(db: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _dadata_down(monkeypatch)
    assert service.lookup(db, INN).error == "EGRUL_UNAVAILABLE"
    (tmp_path / f"{INN}.json").write_text((FIXTURES / f"{INN}.json").read_text())
    r = service.lookup(db, INN)
    assert r.profile is not None and r.profile.source == "offline"
    # Конвейер читает заказчика из таблицы — офлайн-профиль тоже сохраняется
    assert db.get(CustomerProfile, INN) is not None
    assert service.get_cached(db, INN) is not None


def test_not_found_in_dadata(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dadata, "find_party", lambda inn: None)
    r = service.lookup(db, INN)
    assert r.profile is None and r.error == "CUSTOMER_NOT_FOUND"


def test_lookup_never_raises(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(inn: str) -> dict[str, Any]:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(dadata, "find_party", boom)
    r = service.lookup(db, INN)
    assert r.profile is None and r.error == "EGRUL_UNAVAILABLE"


def test_get_cached_offline_without_db_write(
    db: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / f"{INN}.json").write_text((FIXTURES / f"{INN}.json").read_text())
    profile = service.get_cached(db, INN)
    assert profile is not None and profile.source == "offline"
    assert db.get(CustomerProfile, INN) is None
