"""Извещения 223-ФЗ (purchaseNotice*): общие сведения в *Data, НМЦК и позиции — в лотах.

Пути и образцы — docs/eis-fields.md.
"""

from decimal import Decimal

from app.parsers.extract import Spec, build_lot
from app.parsers.normalize import digits, money
from app.parsers.xmltree import Element, first, nodes, text
from app.schemas.procurement import Law, ProcurementData

NAME = "eis223"

# Своя цена лота. Бывает 0: у централизованной закупки цены — у заказчиков лота,
# у запроса цен для формирования НМЦК начальной цены нет вовсе
_LOT_PRICE = ("lotdata/initialsum[. > 0]", "lotdata/maxcontractprice[. > 0]")

SPEC = Spec(
    reg_number=("registrationnumber", ".//registrationnumber"),
    subject=("lotdata/subject", "subject", "name"),
    nmck=(
        *_LOT_PRICE,
        "initialsum[. > 0]",
        ".//initialsum[. > 0]",
        ".//maxcontractprice[. > 0]",
        ".//lotdata/startprice",
        "lotdata/initialsum",
    ),
    currency=("lotdata/currency/code", "currency/code", ".//currency/code"),
    method_raw=("purchasecodename", ".//purchasecodename", ".//purchasemethodname"),
    customer_inn=("customer/maininfo/inn", ".//customer//inn", ".//placer//inn"),
    customer_name=("customer/maininfo/fullname", ".//customer//fullname"),
    customer_address=(
        "customer/maininfo/legaladdress",
        "customer/maininfo/postaladdress",
        "customer/maininfo/region",
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
    # даты без смещения — местное время заказчика: «10:00 (МСК+4)» на сайте ЕИС
    tz_offset=("customer/maininfo/timezone/offset", ".//customer//timezone/offset"),
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


def _customers_nmck(lot: Element) -> Decimal | None:
    """Централизованная закупка: у лота цена 0, НМЦК — сумма цен заказчиков
    (`jointLotData/lotCustomers/lotCustomer/lotCustomerData/initialSum`).

    Если у лота своя цена есть, она главнее: None.
    """
    if first(lot, _LOT_PRICE):
        return None
    paths = ("jointlotdata/lotcustomers/lotcustomer/lotcustomerdata/initialsum",)
    prices = [money(text(n)) for n in nodes(lot, paths)]
    return sum((p for p in prices if p), Decimal(0)) or None


def parse(doc: Element) -> list[ProcurementData]:
    data = _data_node(doc)
    lots = nodes(data, (".//lots/lot", ".//lot"))
    parsed_by = f"adapter:{NAME}"
    if len(lots) <= 1:
        lot = lots[0] if lots else data
        nmck = _customers_nmck(lot)
        return [build_lot(data, lot, SPEC, parsed_by=parsed_by, law=Law.l223, nmck=nmck)]
    result = []
    for i, lot in enumerate(lots, start=1):
        number = int(digits(first(lot, ("ordinalnumber", "lotdata/ordinalnumber"))) or i)
        result.append(
            build_lot(
                data,
                lot,
                SPEC,
                parsed_by=parsed_by,
                law=Law.l223,
                lot_number=number,
                nmck=_customers_nmck(lot),
            )
        )
    return result
