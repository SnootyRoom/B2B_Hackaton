"""Каталог полей для правил скоринга (аналитика, «Каталог полей для правил»).

Новый критерий = строка здесь + оператор в operators.py (если нужен) + фраза в templates.py.
"""

from dataclasses import dataclass
from enum import StrEnum

CATALOG_VERSION = "1"


class Group(StrEnum):
    procurement = "procurement"
    fit = "fit"
    customer = "customer"


class FieldType(StrEnum):
    number = "number"
    money = "money"
    percent = "percent"
    days = "days"
    years = "years"
    enum = "enum"
    list = "list"
    text = "text"
    bool = "bool"


class Operator(StrEnum):
    in_ = "in"
    not_in = "not_in"
    any_in = "any_in"
    none_in = "none_in"
    prefix_in = "prefix_in"
    is_false = "is_false"
    contains_any = "contains_any"
    gte = "gte"
    lte = "lte"
    between = "between"
    semantic_match = "semantic_match"


NUMERIC_OPERATORS = frozenset({Operator.gte, Operator.lte, Operator.between})
LIST_VALUE_OPERATORS = frozenset(
    {
        Operator.in_,
        Operator.not_in,
        Operator.any_in,
        Operator.none_in,
        Operator.prefix_in,
        Operator.contains_any,
    }
)


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: FieldType
    group: Group
    operators: frozenset[Operator]
    label: str


def _spec(name: str, type_: FieldType, group: Group, ops: set[Operator], label: str) -> FieldSpec:
    return FieldSpec(name, type_, group, frozenset(ops), label)


O = Operator
FIELD_CATALOG: dict[str, FieldSpec] = {
    s.name: s
    for s in [
        _spec("nmck", FieldType.money, Group.procurement, {O.between, O.gte, O.lte}, "Начальная цена"),
        _spec("method", FieldType.enum, Group.procurement, {O.in_, O.not_in}, "Способ закупки"),
        _spec("law", FieldType.enum, Group.procurement, {O.in_}, "Закон"),
        _spec("region", FieldType.enum, Group.procurement, {O.in_, O.not_in}, "Регион поставки"),
        _spec(
            "days_to_deadline",
            FieldType.days,
            Group.procurement,
            {O.gte, O.lte, O.between},
            "Дней до окончания подачи заявок",
        ),
        _spec("delivery_days", FieldType.days, Group.procurement, {O.gte, O.lte, O.between}, "Срок поставки"),
        _spec("bid_security_pct", FieldType.percent, Group.procurement, {O.lte}, "Обеспечение заявки"),
        _spec(
            "contract_security_pct",
            FieldType.percent,
            Group.procurement,
            {O.lte},
            "Обеспечение исполнения контракта",
        ),
        _spec("restrictions", FieldType.list, Group.procurement, {O.any_in, O.none_in}, "Ограничения и преимущества"),
        _spec("okpd2_codes", FieldType.list, Group.fit, {O.prefix_in}, "Коды ОКПД2"),
        _spec("subject", FieldType.text, Group.fit, {O.semantic_match, O.contains_any}, "Предмет закупки"),
        _spec("customer.status", FieldType.enum, Group.customer, {O.in_, O.not_in}, "Статус заказчика"),
        _spec("customer.age_years", FieldType.years, Group.customer, {O.gte, O.between}, "Возраст заказчика"),
        _spec(
            "customer.has_unreliable_flags",
            FieldType.bool,
            Group.customer,
            {O.is_false},
            "Отметки о недостоверности сведений",
        ),
        _spec("customer.region", FieldType.enum, Group.customer, {O.in_}, "Регион заказчика"),
    ]
}
del O
