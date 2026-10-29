"""Значения полей каталога из Procurement и CustomerProfile.

Пока нет контрактов роли 1, вход — словари с полями из аналитики (или объекты с атрибутами).
None = «нет данных».
"""

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal

FieldValue = float | str | list[str] | bool | None


def _get(obj: object, name: str) -> object:
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _num(x: object) -> float | None:
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, int | float | Decimal):
        return float(x)
    if isinstance(x, str):
        try:
            return float(Decimal(x.replace(" ", "").replace(",", ".")))
        except ArithmeticError:
            return None
    return None


def _dt(x: object) -> datetime | None:
    if isinstance(x, datetime):
        return x if x.tzinfo else x.replace(tzinfo=UTC)
    if isinstance(x, date):
        return datetime(x.year, x.month, x.day, tzinfo=UTC)
    if isinstance(x, str) and x:
        try:
            return _dt(datetime.fromisoformat(x))
        except ValueError:
            return None
    return None


def _pct(part: object, nmck: float | None) -> float | None:
    p = _num(part)
    if p is None or not nmck:
        return None
    return p / nmck * 100


def _str_list(x: object) -> list[str] | None:
    if x is None:
        return None
    if isinstance(x, list | tuple):
        return [str(i) for i in x]
    return None


def subject_text(procurement: object) -> str:
    """Текст закупки для смыслового сравнения: предмет + наименования позиций."""
    parts = [str(_get(procurement, "subject") or "")]
    for item in _get(procurement, "items") or []:  # type: ignore[attr-defined]
        name = _get(item, "name")
        if name:
            parts.append(str(name))
    return ". ".join(p.strip() for p in parts if p and p.strip())


def extract_fields(procurement: object, customer: object | None, now: datetime) -> dict[str, FieldValue]:
    nmck = _num(_get(procurement, "nmck"))

    deadline = _dt(_get(procurement, "application_deadline"))
    days_to_deadline = (deadline - now).total_seconds() / 86400 if deadline else None

    reg = _dt(_get(customer, "registration_date"))
    age_years = (now - reg).days / 365.25 if reg else None

    flags = _get(customer, "unreliable_flags")
    has_flags: bool | None = None if customer is None or flags is None else bool(flags)

    def s(x: object) -> str | None:
        return str(x) if x not in (None, "") else None

    return {
        "nmck": nmck,
        "method": s(_get(procurement, "method")),
        "law": s(_get(procurement, "law")),
        "region": s(_get(procurement, "region")) or s(_get(customer, "region")),
        "days_to_deadline": days_to_deadline,
        "delivery_days": _num(_get(procurement, "delivery_days")),
        "bid_security_pct": _pct(_get(procurement, "bid_security"), nmck),
        "contract_security_pct": _pct(_get(procurement, "contract_security"), nmck),
        "restrictions": _str_list(_get(procurement, "restrictions")),
        "okpd2_codes": _str_list(_get(procurement, "okpd2_codes")),
        "subject": subject_text(procurement) or None,
        "customer.status": s(_get(customer, "status")),
        "customer.age_years": age_years,
        "customer.has_unreliable_flags": has_flags,
        "customer.region": s(_get(customer, "region")),
    }
