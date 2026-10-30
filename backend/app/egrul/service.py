"""Данные заказчика по ИНН (роль 2).

Контракт для конвейера:
- `lookup(db, inn) -> CustomerLookup` — полная цепочка (кэш → DaData → устаревший кэш →
  офлайн-профиль). Только в воркере. Сохраняет результат в `customer_profiles`.
  Никогда не бросает исключений: ошибка → `CustomerLookup(profile=None, error=...)`.
- `get_cached(db, inn) -> CustomerProfileOut | None` — без сети, для API.
"""

import logging
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.egrul import cache, dadata, offline
from app.models import utcnow
from app.parsers.normalize import inn_is_valid
from app.schemas.common import ErrorCode
from app.schemas.customer import CustomerProfileOut, CustomerSource

log = logging.getLogger(__name__)


@dataclass
class CustomerLookup:
    profile: CustomerProfileOut | None
    error: ErrorCode | None = None  # CUSTOMER_NOT_FOUND | EGRUL_UNAVAILABLE


def get_cached(db: Session, inn: str) -> CustomerProfileOut | None:
    row = cache.get(db, inn)
    if row is not None:
        return cache.to_out(row)
    found = offline.load(inn)
    if found is None:
        return None
    data, _ = found
    return CustomerProfileOut(
        **data.model_dump(), fetched_at=utcnow(), source=CustomerSource.offline
    )


def _from_offline(db: Session, inn: str) -> CustomerProfileOut | None:
    found = offline.load(inn)
    if found is None:
        return None
    data, raw = found
    if data.inn != inn:
        log.warning("offline profile %s.json contains INN %s", inn, data.inn)
        return None
    return cache.to_out(cache.save(db, data, CustomerSource.offline, raw))


def _lookup(db: Session, inn: str) -> CustomerLookup:
    if not inn_is_valid(inn):
        return CustomerLookup(None, ErrorCode.CUSTOMER_NOT_FOUND)

    row = cache.get(db, inn)
    if row is not None and cache.is_fresh(row):
        return CustomerLookup(cache.to_out(row, CustomerSource.cache))

    not_found = False
    try:
        suggestion = dadata.find_party(inn)
    except dadata.DadataUnavailable:
        suggestion = None
    else:
        not_found = suggestion is None
    if suggestion is not None:
        try:
            data = dadata.party_to_customer(suggestion)
        except ValidationError as e:
            log.warning("dadata: unexpected response for %s: %s", inn, e)
        else:
            saved = cache.save(db, data, CustomerSource.dadata, suggestion)
            return CustomerLookup(cache.to_out(saved, CustomerSource.dadata))

    if row is not None and row.source == CustomerSource.dadata:
        return CustomerLookup(cache.to_out(row, CustomerSource.stale_cache))
    profile = _from_offline(db, inn)
    if profile is not None:
        return CustomerLookup(profile)
    if row is not None:
        return CustomerLookup(cache.to_out(row))
    return CustomerLookup(
        None, ErrorCode.CUSTOMER_NOT_FOUND if not_found else ErrorCode.EGRUL_UNAVAILABLE
    )


def lookup(db: Session, inn: str) -> CustomerLookup:
    try:
        # Точка сохранения: сбой кэша не должен откатить закупку, которую пишет конвейер
        with db.begin_nested():
            return _lookup(db, inn)
    except Exception:
        log.exception("egrul lookup failed for %s", inn)
        return CustomerLookup(None, ErrorCode.EGRUL_UNAVAILABLE)
