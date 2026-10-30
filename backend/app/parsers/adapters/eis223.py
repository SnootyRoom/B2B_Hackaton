"""Извещения 223-ФЗ (purchaseNotice*): общие сведения в *Data, НМЦК и позиции — в лотах.

Пути и образцы — docs/eis-fields.md.
"""

from app.parsers.extract import Spec, build_lot
from app.parsers.normalize import digits
from app.parsers.xmltree import Element, first, nodes
from app.schemas.procurement import Law, ProcurementData

NAME = "eis223"

SPEC = Spec(
    reg_number=("registrationnumber", ".//registrationnumber"),
    subject=("lotdata/subject", "subject", "name"),
    nmck=(
        "lotdata/initialsum",
        "lotdata/maxcontractprice",
        "initialsum",
        ".//initialsum",
        ".//maxcontractprice",
        ".//lotdata/startprice",
    ),
    currency=("lotdata/currency/code", "currency/code", ".//currency/code"),
    method_raw=("purchasecodename", ".//purchasecodename", ".//purchasemethodname"),
    customer_inn=("customer/maininfo/inn", ".//customer//inn", ".//placer//inn"),
    customer_name=("customer/maininfo/fullname", ".//customer//fullname"),
    customer_address=(
        "customer/maininfo/legaladdress",
        "customer/maininfo/postaladdress",
        ".//customer//legaladdress",
    ),
    region=("lotdata/deliveryplace/region", ".//deliveryplace/region"),
    delivery_place=(
        "lotdata/deliveryplace/address",
        "lotdata/deliveryplace/region",
        "lotdata/deliveryplace",
        ".//deliveryplace/address",
    ),
    published_at=("publicationdatetime", ".//publicationdatetime", "createdatetime"),
    application_deadline=("submissionclosedatetime", ".//submissionclosedatetime"),
    delivery_term=(".//deliveryterm",),
    bid_security_pct=("lotdata/applicationsupplyinfo/sum",),
    contract_security_pct=("lotdata/completingsupplyinfo/sum",),
    smp_flag=("lotdata/forsmallormiddle", ".//forsmallormiddle"),
    url=("urleis", ".//urleis"),
    items=(".//lotitem",),
    item_name=("name", "additionalinfo", "okpd2/name"),
    item_quantity=("qty", "quantity"),
    item_unit=("okei/name",),
    item_price=("price",),
    item_okpd2=("okpd2/code",),
)


def match(tag: str) -> bool:
    return tag.startswith("purchasenotice")


def _data_node(doc: Element) -> Element:
    """Узел purchaseNotice*Data внутри body/item; если его нет — сам документ."""
    for el in doc.iter():
        if (
            isinstance(el.tag, str)
            and el.tag.startswith("purchasenotice")
            and el.tag.endswith("data")
        ):
            return el
    return doc


def parse(doc: Element) -> list[ProcurementData]:
    data = _data_node(doc)
    lots = nodes(data, (".//lots/lot", ".//lot"))
    parsed_by = f"adapter:{NAME}"
    if len(lots) <= 1:
        lot = lots[0] if lots else data
        return [build_lot(data, lot, SPEC, parsed_by=parsed_by, law=Law.l223)]
    result = []
    for i, lot in enumerate(lots, start=1):
        number = int(digits(first(lot, ("ordinalnumber", "lotdata/ordinalnumber"))) or i)
        result.append(
            build_lot(data, lot, SPEC, parsed_by=parsed_by, law=Law.l223, lot_number=number)
        )
    return result
