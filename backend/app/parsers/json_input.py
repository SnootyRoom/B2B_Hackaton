"""JSON на входе: наш собственный формат — объект ProcurementData или список таких объектов."""

import json

from pydantic import ValidationError

from app.parsers.errors import REQUIRED_LABELS, missing_fields, not_a_notice, unsupported_format
from app.schemas.procurement import ProcurementData


def parse_json(content: bytes) -> list[ProcurementData]:
    try:
        raw = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise unsupported_format() from e
    items = raw if isinstance(raw, list) else [raw]
    result = []
    for item in items:
        if not isinstance(item, dict):
            raise not_a_notice()
        item.setdefault("parsed_by", "json")
        missing = [k for k in REQUIRED_LABELS if item.get(k) in (None, "")]
        # Как в XML: нет ни одного обязательного поля — это не закупка (например, профиль заказчика)
        if len(missing) == len(REQUIRED_LABELS):
            raise not_a_notice()
        if missing:
            raise missing_fields(missing)
        try:
            result.append(ProcurementData.model_validate(item))
        except ValidationError as e:
            err = unsupported_format()
            err.details = {"errors": e.errors(include_url=False, include_context=False)}
            raise err from e
    return result
