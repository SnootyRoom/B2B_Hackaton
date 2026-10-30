"""Извещения 44-ФЗ: формат 2020+ (epNotification*2020) и прежний (fcsNotification*).

Пути и образцы — docs/eis-fields.md.
"""

import re
from decimal import Decimal
from typing import Any

from app.parsers.extract import Spec, build_lot
from app.parsers.normalize import (
    clean_text,
    delivery_days,
    digits,
    money,
    normalize_inn,
)
from app.parsers.xmltree import Element, first, nodes
from app.schemas.procurement import Law, ProcurementData

NAME = "eis44"

SPEC = Spec(
    reg_number=("commoninfo/purchasenumber", ".//purchasenumber"),
    subject=("commoninfo/purchaseobjectinfo", ".//purchaseobjectinfo"),
    nmck=(".//maxpriceinfo/maxprice", "maxprice", ".//lot/maxprice", ".//maxprice"),
    currency=(".//maxpriceinfo/currency/code", "currency/code", ".//currency/code"),
    method_raw=("commoninfo/placingway/name", ".//placingway/name"),
    customer_inn=(".//customerrequirementinfo/customer/inn", ".//customerrequirement/customer/inn"),
    customer_name=(
        ".//customerrequirementinfo/customer/fullname",
        ".//customerrequirement/customer/fullname",
        ".//responsibleorginfo/fullname",
        ".//responsibleorg/fullname",
    ),
    customer_address=(
        ".//responsibleorginfo/factaddress",
        ".//responsibleorginfo/postaddress",
        ".//responsibleorg/factaddress",
        ".//responsibleorg/postaddress",
    ),
    delivery_place=(
        ".//deliveryplacesinfo//garaddress",
        ".//deliveryplacesinfo//deliveryplace",
        ".//deliveryplace",
    ),
    published_at=("commoninfo/publishdtineis", ".//publishdtineis", ".//docpublishdate"),
    application_deadline=(".//collectinginfo/enddt", ".//collecting/enddate", ".//enddt"),
    delivery_term=(".//deliveryterm", ".//deliverytermsinfo"),
    bid_security=(".//applicationguarantee/amount",),
    bid_security_pct=(".//applicationguarantee/part",),
    contract_security=(".//contractguarantee/amount",),
    contract_security_pct=(".//contractguarantee/part",),
    restrictions=(
        ".//preferenseinfo//name",
        ".//preferense/name",
        ".//restrictioninfo//name",
        ".//restriction/name",
        ".//requirementinfo//name[contains(., 'малого')]",
        ".//requirement/name[contains(., 'малого')]",
    ),
    url=("commoninfo/href", ".//href"),
    items=(".//purchaseobject | .//drugpurchaseobjectinfo",),
    item_name=("name", "okpd2/okpdname", "ktru/name"),
    item_quantity=("quantity/value", "quantity", ".//drugquantity"),
    item_unit=("okei/name", "okei/nationalcode", ".//manualuserokei/name"),
    item_price=("price",),
    # у лекарств коды лежат глубже: drugInfo/drugInfoUsingReferenceInfo/OKPD2
    item_okpd2=("okpd2/okpdcode", "okpd2/code", "ktru/code", ".//okpd2/okpdcode", ".//ktru/code"),
)


def match(tag: str) -> bool:
    return tag.startswith(("epnotification", "fcsnotification"))


def _ikz_inn(doc: Element) -> str | None:
    """ИНН заказчика из ИКЗ: customerCode = уровень бюджета (1) + ИНН (10) + КПП (9).

    Когда закупку размещает уполномоченный орган, у заказчика в извещении нет тега ИНН —
    остаётся только код в ИКЗ. В совместной закупке берётся первый заказчик.
    """
    code = digits(first(doc, (".//customerrequirementinfo[1]//customercode", ".//customercode")))
    return normalize_inn(code[1:11]) if code and len(code) == 20 else None


def _responsible_inn(doc: Element, customer_name: str | None) -> str | None:
    """ИНН размещающей организации — только если она и есть заказчик.

    Если закупку размещает уполномоченный орган, его ИНН не подставляем: оценивать
    надо заказчика, а не организатора.
    """
    role = (first(doc, (".//responsiblerole",)) or "").upper()
    org = nodes(doc, (".//responsibleorginfo", ".//responsibleorg"))
    if not org:
        return None
    org_name = clean_text(first(org[0], ("fullname",)))
    if role in {"CU", "CU44"} or (customer_name and customer_name == org_name):
        return normalize_inn(first(org[0], ("inn",)))
    return None


def _date_text(value: str | None) -> str | None:
    """«2027-12-31+03:00» → «31.12.2027» без перевода в UTC: день не должен сдвигаться."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", value or "")
    return f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else None


def _execution_term(doc: Element) -> str | None:
    """Срок исполнения контракта (формат 2020 хранит даты, а не текст) → «с … по …»."""
    terms = nodes(doc, (".//contractexecutiontermsinfo",))
    if not terms:
        return None
    start = _date_text(first(terms[0], (".//startdate",)))
    end = _date_text(first(terms[0], (".//enddate",)))
    if end is None:
        return None
    return f"с {start} по {end}" if start else f"по {end}"


def _joint_security(doc: Element, tag: str) -> Decimal | None:
    """Совместная закупка: обеспечение без процента — сумма долей всех заказчиков."""
    reqs = nodes(doc, (".//customerrequirementsinfo/customerrequirementinfo",))
    amounts = [money(first(r, (f"{tag}/amount",))) for r in reqs]
    return sum((a for a in amounts if a is not None), Decimal(0)) or None


def parse(doc: Element) -> list[ProcurementData]:
    lots = nodes(doc, (".//lots/lot",))
    parsed_by = f"adapter:{NAME}"
    if len(lots) > 1:
        result = []
        for i, lot in enumerate(lots, start=1):
            number = int(digits(first(lot, ("lotnumber",))) or i)
            result.append(
                build_lot(doc, lot, SPEC, parsed_by=parsed_by, law=Law.l44, lot_number=number)
            )
    else:
        result = [build_lot(doc, doc, SPEC, parsed_by=parsed_by, law=Law.l44)]
    joint = len(nodes(doc, (".//customerrequirementsinfo/customerrequirementinfo",))) > 1
    for i, p in enumerate(result):
        update: dict[str, Any] = {}
        if p.customer_inn is None:
            update["customer_inn"] = _ikz_inn(doc) or _responsible_inn(doc, p.customer_name)
        if p.delivery_term_text is None and (term := _execution_term(doc)):
            update["delivery_term_text"] = term
            update["delivery_days"] = delivery_days(term, p.published_at)
        if joint:
            for field, tag in (
                ("bid_security", "applicationguarantee"),
                ("contract_security", "contractguarantee"),
            ):
                if getattr(p, f"{field}_pct") is None and (total := _joint_security(doc, tag)):
                    update[field] = total
                    update[f"{field}_pct"] = (total / p.nmck * 100).quantize(Decimal("0.01"))
        if update:
            result[i] = p.model_copy(update=update)
    return result
