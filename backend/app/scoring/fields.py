"""Значения полей каталога из ProcurementData и CustomerData (или словарей с теми же полями).

None = «нет данных».
"""

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal

# dict — служебное поле okpd2_shares, в каталоге правил его нет
FieldValue = float | str | list[str] | bool | dict[str, float] | None


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


def _pct(procurement: object, name: str, nmck: float | None) -> float | None:
    """Процент из документа, если парсер его сохранил, иначе сумма / НМЦК."""
    pct = _num(_get(procurement, f"{name}_pct"))
    if pct is not None:
        return pct
    p = _num(_get(procurement, name))
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


def okpd2_shares(procurement: object) -> dict[str, float] | None:
    """Доля стоимости позиций по кодам ОКПД2; None — цена известна меньше чем у половины позиций.

    Капремонт на 41 млн ₽ со светильниками и огнетушителем на 2 млн ₽ — профильная закупка,
    хотя профильный код у одной позиции из пяти.
    """
    cost: dict[str, float] = {}
    coded = priced = 0
    for item in _get(procurement, "items") or []:  # type: ignore[attr-defined]
        code = _get(item, "okpd2")
        if not code:
            continue
        coded += 1
        price = _num(_get(item, "price"))
        if not price or price <= 0:
            continue
        priced += 1
        qty = _num(_get(item, "quantity"))
        key = str(code).strip()
        cost[key] = cost.get(key, 0.0) + price * (qty if qty and qty > 0 else 1.0)
    total = sum(cost.values())
    if total <= 0 or priced * 2 < coded:
        return None
    return {c: v / total for c, v in cost.items()}


def extract_fields(
    procurement: object, customer: object | None, now: datetime
) -> dict[str, FieldValue]:
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
        "bid_security_pct": _pct(procurement, "bid_security", nmck),
        "contract_security_pct": _pct(procurement, "contract_security", nmck),
        "restrictions": _str_list(_get(procurement, "restrictions")),
        # пустой список от парсера = кодов в документе нет, а не «коды не совпали»
        "okpd2_codes": _str_list(_get(procurement, "okpd2_codes")) or None,
        "okpd2_shares": okpd2_shares(procurement),
        "subject": subject_text(procurement) or None,
        "customer.status": s(_get(customer, "status")),
        "customer.age_years": age_years,
        "customer.has_unreliable_flags": has_flags,
        "customer.region": s(_get(customer, "region")),
    }
