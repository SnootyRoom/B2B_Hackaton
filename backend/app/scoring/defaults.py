"""Правила по умолчанию (аналитика, «Правила по умолчанию»). Владелец — роль 3."""

from decimal import Decimal

from app.schemas.scoring import (
    Operator,
    RuleGroup,
    RuleKind,
    ScoringProfileData,
    ScoringRule,
)


def default_rules() -> list[ScoringRule]:
    return [
        ScoringRule(
            id="stop_deadline",
            group=RuleGroup.procurement,
            kind=RuleKind.stop,
            field="days_to_deadline",
            operator=Operator.lte,
            value=Decimal(0),
            label="Приём заявок завершён",
        ),
        ScoringRule(
            id="stop_customer_status",
            group=RuleGroup.customer,
            kind=RuleKind.stop,
            field="customer.status",
            operator=Operator.in_,
            value=["liquidating", "liquidated", "bankrupt"],
            label="Заказчик ликвидируется, ликвидирован или банкрот",
        ),
        ScoringRule(
            id="customer_active",
            group=RuleGroup.customer,
            kind=RuleKind.weighted,
            field="customer.status",
            operator=Operator.in_,
            value=["active"],
            weight=3,
            label="Заказчик действующий",
        ),
        ScoringRule(
            id="customer_reliable",
            group=RuleGroup.customer,
            kind=RuleKind.weighted,
            field="customer.has_unreliable_flags",
            operator=Operator.is_false,
            weight=3,
            label="Нет отметок о недостоверности сведений",
        ),
        ScoringRule(
            id="customer_age",
            group=RuleGroup.customer,
            kind=RuleKind.weighted,
            field="customer.age_years",
            operator=Operator.gte,
            value=Decimal(3),
            weight=2,
            soft_margin=0.67,
            label="Заказчик работает не меньше 3 лет",
        ),
    ]


def default_profile() -> ScoringProfileData:
    return ScoringProfileData(rules=default_rules())
