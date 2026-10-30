"""Офлайн-профили `data/customers/<inn>.json` для тестового набора и демо.

Формат файла — сохранённый ответ DaData: весь ответ `{"suggestions": [...]}` или одна
подсказка `{"value": ..., "data": {...}}`.
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
        return party_to_customer(raw), raw
    except (OSError, ValueError, LookupError, ValidationError) as e:
        log.warning("offline profile %s is broken: %s", path.name, e)
        return None
