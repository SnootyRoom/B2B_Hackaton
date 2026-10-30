"""Офлайн-профили `data/customers/<inn>.json` для тестового набора и демо.

Два формата файла:
- сохранённый ответ DaData: весь ответ `{"suggestions": [...]}` или одна подсказка
  `{"value": ..., "data": {...}}`;
- готовый профиль по схеме `CustomerData` (`app/schemas/customer.py`) — для заказчиков,
  которых нет в DaData или которые заданы вручную: `{"inn", "name", "status", ...}`.
"""

import json
import logging
from typing import Any

from pydantic import ValidationError

from app.core.config import get_settings
from app.egrul.dadata import party_to_customer
from app.schemas.customer import CustomerData

log = logging.getLogger(__name__)


def load(inn: str) -> tuple[CustomerData, dict[str, Any]] | None:
    """(профиль, исходная подсказка) или None, если файла нет или он испорчен."""
    path = get_settings().customers_dir / f"{inn}.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "suggestions" in raw:
            raw = raw["suggestions"][0]
        if not isinstance(raw, dict):
            raise ValueError("ожидался объект")
        if "data" in raw:
            return party_to_customer(raw), raw
        # Незнакомые поля — ошибка, а не тихий пропуск: иначе статус молча станет unknown
        unknown = set(raw) - set(CustomerData.model_fields)
        if unknown:
            raise ValueError(f"незнакомые поля {sorted(unknown)}")
        return CustomerData.model_validate(raw), raw
    except (OSError, ValueError, LookupError, ValidationError) as e:
        log.warning("offline profile %s is broken: %s", path.name, e)
        return None
