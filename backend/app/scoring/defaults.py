"""Правила по умолчанию (аналитика, «Правила по умолчанию»). Добавляются в каждый профиль."""

from app.scoring.catalog import Group, Operator
from app.scoring.types import RuleKind, ScoringProfileData, ScoringRule

DEFAULT_RULES: list[ScoringRule] = [
    ScoringRule(
        id="stop_deadline",
        group=Group.procurement,
        kind=RuleKind.stop,
        field="days_to_deadline",
        operator=Operator.lte,
        value=0,
        label="Приём заявок завершён",
    ),
    ScoringRule(
        id="stop_customer_status",
        group=Group.customer,
        kind=RuleKind.stop,
        field="customer.status",
        operator=Operator.in_,
        value=["liquidating", "liquidated", "bankrupt"],
        label="Заказчик ликвидируется, ликвидирован или банкрот",
    ),
    ScoringRule(
        id="customer_active",
        group=Group.customer,
        kind=RuleKind.weighted,
        field="customer.status",
        operator=Operator.in_,
        value=["active"],
        weight=3,
        label="Заказчик действующий",
    ),
    ScoringRule(
        id="customer_reliable",
        group=Group.customer,
        kind=RuleKind.weighted,
        field="customer.has_unreliable_flags",
        operator=Operator.is_false,
        weight=3,
        label="Нет отметок о недостоверности сведений",
    ),
    ScoringRule(
        id="customer_age",
        group=Group.customer,
        kind=RuleKind.weighted,
        field="customer.age_years",
        operator=Operator.gte,
        value=3,
        weight=2,
        soft_margin=0.67,
        label="Заказчик работает не меньше 3 лет",
    ),
]

DEFAULT_RULE_IDS = frozenset(r.id for r in DEFAULT_RULES)


def with_defaults(rules: list[ScoringRule]) -> list[ScoringRule]:
    """Правила пользователя + недостающие правила по умолчанию."""
    present = {r.id for r in rules}
    return [*rules, *(r.model_copy() for r in DEFAULT_RULES if r.id not in present)]


def default_profile() -> ScoringProfileData:
    return ScoringProfileData(rules=with_defaults([]))
