"""Клиент DaData: поиск организации по ИНН и разбор ответа в CustomerData.

Ответ DaData (findById/party) также служит форматом офлайн-профилей `data/customers/<inn>.json`.
"""

import logging
from datetime import UTC, date, datetime
from typing import Any

import httpx

from app.core.config import get_settings
from app.parsers.normalize import normalize_region
from app.schemas.customer import CustomerData, CustomerStatus, OrgType

log = logging.getLogger(__name__)

URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
TIMEOUT = httpx.Timeout(5.0)

_STATUSES = {
    "ACTIVE": CustomerStatus.active,
    "REORGANIZING": CustomerStatus.reorganizing,
    "LIQUIDATING": CustomerStatus.liquidating,
    "LIQUIDATED": CustomerStatus.liquidated,
    "BANKRUPT": CustomerStatus.bankrupt,
}


class DadataUnavailable(Exception):
    """Сеть, таймаут, неверный ключ, лимит — любой сбой, после которого идём в кэш."""


def find_party(inn: str) -> dict[str, Any] | None:
    """Первая подсказка DaData по ИНН (основная организация); None — ИНН не найден."""
    key = get_settings().dadata_api_key
    if not key:
        raise DadataUnavailable("DADATA_API_KEY не задан")
    try:
        r = httpx.post(
            URL,
            json={"query": inn, "branch_type": "MAIN"},
            headers={"Authorization": f"Token {key}", "Accept": "application/json"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        suggestions = r.json().get("suggestions") or []
    except (httpx.HTTPError, ValueError, AttributeError) as e:
        log.warning("dadata: запрос по ИНН %s не удался: %s", inn, type(e).__name__)
        raise DadataUnavailable(str(e)) from e
    return suggestions[0] if suggestions else None


def _date(ms: object) -> date | None:
    """DaData отдаёт даты в миллисекундах от эпохи."""
    if isinstance(ms, int | float):
        return datetime.fromtimestamp(ms / 1000, tz=UTC).date()
    return None


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _unreliable_flags(d: dict[str, Any]) -> list[str]:
    flags = []
    if d.get("invalid"):
        flags.append("Недостоверные сведения об организации")
    if _dict(d.get("address")).get("invalidity") or _dict(_dict(d.get("address")).get("data")).get(
        "invalidity"
    ):
        flags.append("Недостоверный адрес")
    management = _dict(d.get("management"))
    if management.get("invalidity"):
        flags.append("Недостоверные сведения о руководителе")
    if management.get("disqualified"):
        flags.append("Руководитель дисквалифицирован")
    return flags


def party_to_customer(suggestion: dict[str, Any]) -> CustomerData:
    """Подсказка DaData `{value, data: {...}}` → CustomerData."""
    d = _dict(suggestion.get("data"))
    name = _dict(d.get("name"))
    state = _dict(d.get("state"))
    address = _dict(d.get("address"))
    addr_data = _dict(address.get("data"))
    okveds = d.get("okveds")
    main_okved = (
        next((o for o in okveds if isinstance(o, dict) and o.get("main")), None)
        if isinstance(okveds, list)
        else None
    )
    region = normalize_region(addr_data.get("region_with_type")) or normalize_region(
        address.get("value")
    )
    return CustomerData(
        inn=str(d.get("inn") or ""),
        ogrn=d.get("ogrn"),
        name=name.get("full_with_opf") or suggestion.get("value") or name.get("short_with_opf"),
        org_type={"LEGAL": OrgType.legal, "INDIVIDUAL": OrgType.individual}.get(str(d.get("type"))),
        status=_STATUSES.get(str(state.get("status")), CustomerStatus.unknown),
        registration_date=_date(state.get("registration_date")),
        liquidation_date=_date(state.get("liquidation_date")),
        okved_main=d.get("okved"),
        okved_main_name=main_okved.get("name") if main_okved else None,
        address=address.get("unrestricted_value") or address.get("value"),
        region=region,
        unreliable_flags=_unreliable_flags(d),
    )
