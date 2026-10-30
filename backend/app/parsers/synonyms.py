"""Словарь синонимов тегов для универсального адаптера (локальные имена, нижний регистр).

Порядок важен: сначала самые точные пути. Пополняется по образцам; таблица синонимов
продублирована в docs/eis-fields.md.
"""

from app.parsers.extract import Spec


def _any(*tags: str) -> tuple[str, ...]:
    return tuple(f".//{t}" for t in tags)


SPEC = Spec(
    reg_number=_any(
        "purchasenumber",
        "registrationnumber",
        "notificationnumber",
        "purchasenoticenumber",
        "noticenumber",
        "purchaseregnumber",
    ),
    subject=_any(
        "purchaseobjectinfo",
        "lotdata/subject",
        "lot/subject",
        "purchasename",
        "lotname",
        "objectname",
        "subject",
    )
    + ("./name", "./*/name"),
    nmck=_any(
        "maxpriceinfo/maxprice",
        "maxprice",
        "initialsum",
        "contractmaxprice",
        "maxcontractprice",
        "startprice",
        "initialprice",
        "nmck",
    ),
    currency=_any("currency/code", "currencycode"),
    method_raw=_any(
        "placingway/name",
        "placingwayinfo/name",
        "purchasecodename",
        "purchasemethodname",
        "methodname",
    ),
    customer_inn=_any(
        "customer//inn",
        "customerinfo//inn",
        "responsibleorginfo/inn",
        "responsibleorg/inn",
        "organizer//inn",
        "placer//inn",
        "inn",
    ),
    customer_name=_any(
        "customer//fullname",
        "customerinfo//fullname",
        "responsibleorginfo/fullname",
        "responsibleorg/fullname",
        "fullname",
    ),
    customer_address=_any("factaddress", "legaladdress", "postaddress", "postaladdress"),
    delivery_place=_any("garaddress", "deliveryplace/address", "deliveryplace", "deliveryaddress"),
    published_at=_any(
        "publishdtineis", "publicationdatetime", "docpublishdate", "publishdate", "createdatetime"
    ),
    application_deadline=_any(
        "collectinginfo/enddt",
        "collecting/enddate",
        "submissionclosedatetime",
        "collectingenddate",
        "applicationenddate",
        "enddt",
        "enddate",
    ),
    delivery_term=_any("deliveryterm", "deliverytermsinfo", "deliverytime", "deliveryperiod"),
    bid_security=_any("applicationguarantee/amount", "applicationsupplyamount"),
    bid_security_pct=_any("applicationguarantee/part"),
    contract_security=_any("contractguarantee/amount"),
    contract_security_pct=_any("contractguarantee/part"),
    restrictions=_any("preferenseinfo//name", "preferense/name", "restrictioninfo//name"),
    smp_flag=_any("forsmallormiddle"),
    okpd2=_any("okpdcode", "okpd2/code", "ktru/code", "okpd2code"),
    url=_any("href", "urleis"),
    region=_any("deliveryplace/region"),
    items=_any("purchaseobject", "drugpurchaseobjectinfo", "lotitem"),
    item_name=("name", "okpd2/name", "okpd2/okpdname", "additionalinfo"),
    item_quantity=("quantity/value", "quantity", "qty"),
    item_unit=("okei/name", "okei/nationalcode"),
    item_price=("price",),
    item_okpd2=("okpd2/okpdcode", "okpd2/code", "ktru/code"),
)
