"""JSON на входе: наш собственный формат — объект ProcurementData или список таких объектов."""

import json

from pydantic import ValidationError

from app.schemas.common import ErrorCode
from app.schemas.procurement import ProcurementData

_LABELS = {"reg_number": "реестровый номер", "subject": "предмет закупки", "nmck": "НМЦК"}


def parse_json(content: bytes) -> list[ProcurementData]:
    from app.parsers.registry import ParseError

    try:
        raw = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ParseError(ErrorCode.UNSUPPORTED_FORMAT, "Файл не похож на выгрузку из ЕИС") from e
    items = raw if isinstance(raw, list) else [raw]
    result = []
    for item in items:
        if not isinstance(item, dict):
            raise ParseError(ErrorCode.NOT_A_NOTICE, "Это не извещение о закупке")
        item.setdefault("parsed_by", "json")
        missing = [_LABELS[k] for k in _LABELS if item.get(k) in (None, "")]
        if missing:
            raise ParseError(
                ErrorCode.MISSING_REQUIRED_FIELD,
                f"В файле не найдено: {', '.join(missing)}",
                {"fields": missing},
            )
        try:
            result.append(ProcurementData.model_validate(item))
        except ValidationError as e:
            raise ParseError(
                ErrorCode.UNSUPPORTED_FORMAT,
                "Файл не похож на выгрузку из ЕИС",
                {"errors": e.errors(include_url=False, include_context=False)},
            ) from e
    return result
