"""Точка входа парсера (роль 2).

Контракт: `parse_file(content, filename) -> list[ProcurementData]` — по записи на лот.
При ошибке — `ParseError` с кодом из ErrorCode (UNSUPPORTED_FORMAT, NOT_A_NOTICE,
MISSING_REQUIRED_FIELD). Конвейер (роль 1) вызывает только эту функцию.
"""

from pathlib import Path
from typing import Any

from app.parsers.json_input import parse_json
from app.schemas.common import ErrorCode
from app.schemas.procurement import ProcurementData


class ParseError(Exception):
    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def parse_file(content: bytes, filename: str) -> list[ProcurementData]:
    ext = Path(filename).suffix.lower()
    if ext == ".json":
        return parse_json(content)
    if ext == ".xml":
        return parse_xml(content)
    raise ParseError(ErrorCode.UNSUPPORTED_FORMAT, "Файл не похож на выгрузку из ЕИС")


def parse_xml(content: bytes) -> list[ProcurementData]:
    # TODO(роль 2): определение типа документа → адаптер 44/223-ФЗ → универсальный адаптер.
    raise ParseError(ErrorCode.NOT_A_NOTICE, "Разбор XML ещё не подключён")
