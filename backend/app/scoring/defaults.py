"""Правила по умолчанию (аналитика, «Правила по умолчанию»). Добавляются в каждый профиль."""

from decimal import Decimal

from app.schemas.scoring import (
    Operator,
    RuleGroup,
    RuleKind,
    ScoringProfileData,
    ScoringRule,
    Thresholds,
)

DEFAULT_RULES: list[ScoringRule] = [
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

DEFAULT_RULE_IDS = frozenset(r.id for r in DEFAULT_RULES)


def with_defaults(rules: list[ScoringRule]) -> list[ScoringRule]:
    """Правила пользователя + недостающие правила по умолчанию."""
    present = {r.id for r in rules}
    return [*rules, *(r.model_copy() for r in DEFAULT_RULES if r.id not in present)]


def default_profile() -> ScoringProfileData:
    return ScoringProfileData(rules=with_defaults([]))


def _cautious() -> ScoringProfileData:
    """Только надёжные заказчики: реорганизация — стоп, возраст строже, пороги выше."""
    rules = [r.model_copy(deep=True) for r in DEFAULT_RULES]
    by_id = {r.id: r for r in rules}
    stop = by_id["stop_customer_status"]
    stop.value = ["reorganizing", "liquidating", "liquidated", "bankrupt"]
    stop.label = "Заказчик реорганизуется, ликвидируется, ликвидирован или банкрот"
    age = by_id["customer_age"]
    age.weight, age.soft_margin = 3, 0.0
    return ScoringProfileData(
        name="Осторожный",
        rules=rules,
        thresholds=Thresholds(participate=75, consider=50),
    )


def _aggressive() -> ScoringProfileData:
    """Шире круг закупок: реорганизация допустима, молодые заказчики, пороги ниже."""
    rules = [r.model_copy(deep=True) for r in DEFAULT_RULES]
    by_id = {r.id: r for r in rules}
    by_id["customer_active"].value = ["active", "reorganizing"]
    by_id["customer_active"].label = "Заказчик действующий или реорганизуется"
    age = by_id["customer_age"]
    age.value, age.weight = Decimal(1), 1
    age.label = "Заказчик работает не меньше года"
    return ScoringProfileData(
        name="Агрессивный",
        rules=rules,
        thresholds=Thresholds(participate=60, consider=30),
    )


# Шаблоны стратегий: правила о заказчике и пороги. «Новый профиль из шаблона» — template_profile,
# «применить стратегию к своему профилю» — apply_strategy (условия компании сохраняются).
TEMPLATES = {"cautious": _cautious, "aggressive": _aggressive}


def template_profile(name: str) -> ScoringProfileData:
    """Профиль по шаблону стратегии; неизвестное имя — KeyError."""
    return TEMPLATES[name]()


# Правила, которые задаёт стратегия; остальные правила профиля — условия самой компании
STRATEGY_RULE_IDS = frozenset(
    {"stop_customer_status", "customer_active", "customer_reliable", "customer_age"}
)


def apply_strategy(profile: ScoringProfileData, name: str) -> ScoringProfileData:
    """Стратегия поверх своего профиля: правила о заказчике и пороги — из шаблона, условия
    компании (предмет, сумма, регион, способ, свои правила о заказчике), имя, описание
    и веса групп — свои. Выключенное пользователем правило стратегии остаётся выключенным.
    Исходный профиль не меняется; неизвестная стратегия — KeyError."""
    strategy = {r.id: r for r in template_profile(name).rules if r.id in STRATEGY_RULE_IDS}
    rules = []
    for rule in profile.rules:
        own = strategy.pop(rule.id, None)
        rules.append(
            own.model_copy(update={"enabled": rule.enabled}) if own else rule.model_copy(deep=True)
        )
    rules.extend(strategy.values())  # правила стратегии, которых в профиле не было
    return profile.model_copy(
        update={"rules": rules, "thresholds": template_profile(name).thresholds}, deep=True
    )
