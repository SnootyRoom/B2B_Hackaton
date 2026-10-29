"""Данные заказчика по ИНН (роль 2).

Контракт для конвейера:
- `lookup(db, inn) -> CustomerLookup` — полная цепочка (кэш → DaData → устаревший кэш →
  офлайн-профиль). Только в воркере. Сохраняет результат в `customer_profiles`.
  Никогда не бросает исключений: ошибка → `CustomerLookup(profile=None, error=...)`.
- `get_cached(db, inn) -> CustomerProfileOut | None` — без сети, для API.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import CustomerProfile
from app.schemas.common import ErrorCode
from app.schemas.customer import CustomerProfileOut


@dataclass
class CustomerLookup:
    profile: CustomerProfileOut | None
    error: ErrorCode | None = None  # CUSTOMER_NOT_FOUND | EGRUL_UNAVAILABLE


def get_cached(db: Session, inn: str) -> CustomerProfileOut | None:
    # TODO(роль 2): офлайн-профиль data/customers/<inn>.json, если в кэше нет.
    row = db.get(CustomerProfile, inn)
    return CustomerProfileOut.model_validate(row) if row else None


def lookup(db: Session, inn: str) -> CustomerLookup:
    # TODO(роль 2): проверка контрольной суммы, TTL кэша, DaData, офлайн-профили.
    cached = get_cached(db, inn)
    if cached is not None:
        return CustomerLookup(cached)
    return CustomerLookup(None, ErrorCode.EGRUL_UNAVAILABLE)
