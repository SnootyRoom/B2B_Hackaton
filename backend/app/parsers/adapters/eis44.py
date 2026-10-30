"""Извещения 44-ФЗ: формат 2020+ (epNotification*2020) и прежний (fcsNotification*).

Пути и образцы — docs/eis-fields.md.
"""

from app.parsers.extract import Spec, build_lot
from app.parsers.normalize import clean_text, digits, normalize_inn
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
        ".//deliveryplaceinfo/garinfo/garaddress",
        ".//deliveryplaceinfo/deliveryplace",
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
    items=(".//purchaseobject",),
    item_name=("name", "okpd2/okpdname", "ktru/name"),
    item_quantity=("quantity/value", "quantity"),
    item_unit=("okei/name", "okei/nationalcode"),
    item_price=("price",),
    item_okpd2=("okpd2/okpdcode", "okpd2/code", "ktru/code", "okpd/code"),
)


def match(tag: str) -> bool:
    return tag.startswith(("epnotification", "fcsnotification"))


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
    for i, p in enumerate(result):
        if p.customer_inn is None:
            inn = _responsible_inn(doc, p.customer_name)
            if inn:
                result[i] = p.model_copy(update={"customer_inn": inn})
    return result
