"""Универсальный адаптер: извещение неизвестного формата (ПП 615, 94-ФЗ, новые схемы).

Обходит всё дерево и ищет поля по словарю синонимов; документ считается одним лотом.
"""

from app.parsers.extract import build_lot
from app.parsers.synonyms import SPEC
from app.parsers.xmltree import Element
from app.schemas.procurement import ProcurementData


def parse(doc: Element) -> list[ProcurementData]:
    return [build_lot(doc, doc, SPEC, parsed_by="universal")]
