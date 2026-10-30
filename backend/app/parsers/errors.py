from typing import Any

from app.schemas.common import ErrorCode

# Подписи обязательных полей для текста «В файле не найдено: …»
REQUIRED_LABELS = {"reg_number": "реестровый номер", "subject": "предмет закупки", "nmck": "НМЦК"}


class ParseError(Exception):
    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def unsupported_format() -> ParseError:
    return ParseError(ErrorCode.UNSUPPORTED_FORMAT, "Файл не похож на выгрузку из ЕИС")


def not_a_notice() -> ParseError:
    return ParseError(ErrorCode.NOT_A_NOTICE, "Это не извещение о закупке")


def missing_fields(fields: list[str]) -> ParseError:
    labels = [REQUIRED_LABELS[f] for f in fields]
    return ParseError(
        ErrorCode.MISSING_REQUIRED_FIELD,
        f"В файле не найдено: {', '.join(labels)}",
        {"fields": labels},
    )
