"""Кэш ЕГРЮЛ в таблице customer_profiles (общий для всех пользователей).

В строке `source` хранится происхождение данных: `dadata` или `offline`. Наружу источник
отдаётся с учётом свежести: `cache` (моложе TTL), `stale_cache` (старше), `offline`.
"""

from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import CustomerProfile, utcnow
from app.schemas.customer import CustomerData, CustomerProfileOut, CustomerSource


def get(db: Session, inn: str) -> CustomerProfile | None:
    return db.get(CustomerProfile, inn)


def is_fresh(row: CustomerProfile) -> bool:
    ttl = timedelta(days=get_settings().egrul_cache_ttl_days)
    return row.source == CustomerSource.dadata and utcnow() - row.fetched_at < ttl


def to_out(row: CustomerProfile, source: CustomerSource | None = None) -> CustomerProfileOut:
    """Строка кэша → профиль; источник по умолчанию вычисляется по происхождению и свежести."""
    if source is None:
        if row.source == CustomerSource.offline:
            source = CustomerSource.offline
        else:
            source = CustomerSource.cache if is_fresh(row) else CustomerSource.stale_cache
    out = CustomerProfileOut.model_validate(row)
    return out.model_copy(update={"source": source})


def save(
    db: Session,
    data: CustomerData,
    source: CustomerSource,
    raw: dict[str, Any] | None,
) -> CustomerProfile:
    row = db.get(CustomerProfile, data.inn)
    if row is None:
        row = CustomerProfile(inn=data.inn)
        db.add(row)
    for key, value in data.model_dump(exclude={"inn"}).items():
        setattr(row, key, value)
    row.raw = raw
    row.source = source
    row.fetched_at = utcnow()
    db.flush()
    return row
