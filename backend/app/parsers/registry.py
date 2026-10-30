"""Точка входа парсера (роль 2).

Контракт: `parse_file(content, filename) -> list[ProcurementData]` — по записи на лот.
При ошибке — `ParseError` с кодом из ErrorCode (UNSUPPORTED_FORMAT, NOT_A_NOTICE,
MISSING_REQUIRED_FIELD). Конвейер (роль 1) вызывает только эту функцию.

Цепочка для XML: адаптер известного формата → универсальный адаптер по синонимам.
"""

import logging
import re
from collections.abc import Callable
from pathlib import Path

from app.parsers import universal
from app.parsers.adapters import eis44, eis223
from app.parsers.errors import ParseError, not_a_notice, unsupported_format
from app.parsers.json_input import parse_json
from app.parsers.xmltree import Element, document_root, load_xml
from app.schemas.common import ErrorCode
from app.schemas.procurement import ProcurementData

__all__ = ["ParseError", "parse_file", "parse_xml"]

log = logging.getLogger(__name__)

Parse = Callable[[Element], list[ProcurementData]]

# (проверка корневого элемента, разбор); новый тип документа = новая строка
ADAPTERS: list[tuple[Callable[[str], bool], Parse]] = [
    (eis44.match, eis44.parse),
    (eis223.match, eis223.parse),
]

# Документы ЕИС, которые не являются извещениями: протоколы, контракты, планы, отмены
_NOT_NOTICE = re.compile(r"protocol|contract|plan|cancel|clarification|explanation|complaint")


def parse_file(content: bytes, filename: str) -> list[ProcurementData]:
    ext = Path(filename).suffix.lower()
    if ext == ".json":
        return parse_json(content)
    if ext == ".xml":
        return parse_xml(content)
    raise unsupported_format()


def parse_xml(content: bytes) -> list[ProcurementData]:
    doc = document_root(load_xml(content))
    if _NOT_NOTICE.search(doc.tag) and "notice" not in doc.tag:
        raise not_a_notice()
    adapter = next((parse for match, parse in ADAPTERS if match(doc.tag)), None)
    if adapter is None:
        return universal.parse(doc)
    try:
        return adapter(doc)
    except ParseError as e:
        if e.code == ErrorCode.UNSUPPORTED_FORMAT:
            raise
        log.info("adapter failed on <%s>: %s, trying universal", doc.tag, e.message)
        try:
            return universal.parse(doc)
        except ParseError:
            raise e from None
