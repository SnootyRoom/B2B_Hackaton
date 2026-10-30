"""Сборка ProcurementData из XML по набору путей (`Spec`).

Адаптеры и универсальный адаптер отличаются только путями и тем, как делят документ на лоты:
сами значения извлекаются и нормализуются здесь одинаково.
"""

import re
from dataclasses import dataclass

from app.parsers.errors import missing_fields, not_a_notice
from app.parsers.normalize import (
    clean_text,
    delivery_days,
    digits,
    money,
    normalize_inn,
    normalize_method,
    normalize_okpd2,
    normalize_region,
    normalize_restrictions,
    parse_datetime,
    security_amount,
)
from app.parsers.xmltree import Element, all_texts, first, nodes
from app.schemas.procurement import Law, ProcurementData, ProcurementItem, Restriction

Paths = tuple[str, ...]


@dataclass(frozen=True)
class Spec:
    """Пути XPath (локальные имена в нижнем регистре) для каждого поля.

    Значение ищется сначала в узле лота, затем во всём документе.
    """

    reg_number: Paths
    subject: Paths
    nmck: Paths
    currency: Paths = ()
    method_raw: Paths = ()
    customer_inn: Paths = ()
    customer_name: Paths = ()
    customer_address: Paths = ()
    delivery_place: Paths = ()
    published_at: Paths = ()
    application_deadline: Paths = ()
    delivery_term: Paths = ()
    bid_security: Paths = ()
    bid_security_pct: Paths = ()
    contract_security: Paths = ()
    contract_security_pct: Paths = ()
    restrictions: Paths = ()  # тексты преимуществ, требований и запретов
    smp_flag: Paths = ()  # значение true → только для СМП
    okpd2: Paths = ()  # коды на уровне лота (кроме кодов позиций)
    url: Paths = ()
    items: Paths = ()  # узлы позиций
    item_name: Paths = ()
    item_quantity: Paths = ()
    item_unit: Paths = ()
    item_price: Paths = ()
    item_okpd2: Paths = ()


def guess_law(reg_number: str, doc_tag: str) -> Law:
    """Закон для документа без адаптера: по признакам в имени и формату номера."""
    if "615" in doc_tag:
        return Law.l615
    if re.fullmatch(r"\d{19}", reg_number):
        return Law.l44
    if re.fullmatch(r"\d{11}", reg_number):
        return Law.l223
    return Law.other


def source_url(reg_number: str) -> str:
    return f"https://zakupki.gov.ru/epz/order/extendedsearch/results.html?searchString={reg_number}"


def _items(lot: Element, spec: Spec) -> list[ProcurementItem]:
    result = []
    for node in nodes(lot, spec.items):
        name = clean_text(first(node, spec.item_name))
        if not name:
            continue
        result.append(
            ProcurementItem(
                name=name,
                quantity=money(first(node, spec.item_quantity)),
                unit=clean_text(first(node, spec.item_unit)),
                price=money(first(node, spec.item_price)),
                okpd2=normalize_okpd2(first(node, spec.item_okpd2)),
            )
        )
    return result


def build_lot(
    doc: Element,
    lot: Element,
    spec: Spec,
    *,
    parsed_by: str,
    law: Law | None = None,
    lot_number: int | None = None,
) -> ProcurementData:
    """Один лот → ProcurementData. `lot_number` задаётся только у многолотовых извещений."""

    def get(paths: Paths) -> str | None:
        value = first(lot, paths)
        if value is None and lot is not doc:
            value = first(doc, paths)
        return value

    reg = digits(get(spec.reg_number))
    subject = clean_text(get(spec.subject))
    nmck = money(get(spec.nmck))
    missing = [k for k, v in (("reg_number", reg), ("subject", subject), ("nmck", nmck)) if not v]
    if len(missing) == 3:
        raise not_a_notice()
    if missing:
        raise missing_fields(missing)
    assert reg and subject and nmck is not None

    published_at = parse_datetime(get(spec.published_at))
    delivery_place = clean_text(get(spec.delivery_place))
    term = clean_text(get(spec.delivery_term))
    method_raw = clean_text(get(spec.method_raw))

    bid, bid_pct = security_amount(
        money(get(spec.bid_security)), money(get(spec.bid_security_pct)), nmck
    )
    contract, contract_pct = security_amount(
        money(get(spec.contract_security)), money(get(spec.contract_security_pct)), nmck
    )

    restrictions = normalize_restrictions(all_texts(lot, spec.restrictions))
    if (get(spec.smp_flag) or "").lower() == "true" and Restriction.smp_only not in restrictions:
        restrictions.insert(0, Restriction.smp_only)

    items = _items(lot, spec)
    okpd2: list[str] = []
    for code in [*all_texts(lot, spec.okpd2), *(i.okpd2 or "" for i in items)]:
        norm = normalize_okpd2(code)
        if norm and norm not in okpd2:
            okpd2.append(norm)

    region = normalize_region(delivery_place) or normalize_region(get(spec.customer_address))

    return ProcurementData(
        reg_number=f"{reg}-{lot_number}" if lot_number else reg,
        lot_number=lot_number,
        law=law or guess_law(reg, doc.tag),
        subject=subject,
        nmck=nmck,
        currency=(clean_text(get(spec.currency)) or "RUB").upper().replace("RUR", "RUB"),
        method=normalize_method(method_raw),
        method_raw=method_raw,
        customer_inn=normalize_inn(get(spec.customer_inn)),
        customer_name=clean_text(get(spec.customer_name)),
        region=region,
        delivery_place=delivery_place,
        published_at=published_at,
        application_deadline=parse_datetime(get(spec.application_deadline)),
        delivery_term_text=term,
        delivery_days=delivery_days(term, published_at),
        okpd2_codes=okpd2,
        items=items,
        bid_security=bid,
        bid_security_pct=bid_pct,
        contract_security=contract,
        contract_security_pct=contract_pct,
        restrictions=restrictions,
        source_url=clean_text(get(spec.url)) or source_url(reg),
        parsed_by=parsed_by,
    )
