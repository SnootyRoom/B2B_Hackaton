"""Правила по умолчанию (аналитика, «Правила по умолчанию»). Добавляются в каждый профиль."""

from decimal import Decimal

from app.schemas.scoring import (
    FIELD_CATALOG,
    FieldType,
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


STOP_REORGANIZING = ScoringRule(
    id="stop_customer_reorganizing",
    group=RuleGroup.customer,
    kind=RuleKind.stop,
    field="customer.status",
    operator=Operator.in_,
    value=["reorganizing"],
    label="Заказчик в процессе реорганизации",
)


def _scale_money(rule: ScoringRule, low: Decimal, high: Decimal) -> ScoringRule:
    """Диапазон суммы: нижняя граница × low, верхняя × high."""
    v = rule.value
    if rule.operator == Operator.between and isinstance(v, list) and len(v) == 2:
        lo, hi = (Decimal(str(x)) for x in v)
        return rule.model_copy(update={"value": [lo * low, hi * high]})
    if rule.operator == Operator.lte and isinstance(v, Decimal):
        return rule.model_copy(update={"value": v * high})
    if rule.operator == Operator.gte and isinstance(v, Decimal):
        return rule.model_copy(update={"value": v * low})
    return rule


def _is_money(rule: ScoringRule) -> bool:
    spec = FIELD_CATALOG.get(rule.field)
    return spec is not None and spec.type == FieldType.money and rule.kind == RuleKind.weighted


def _cautious(rules: list[ScoringRule]) -> list[ScoringRule]:
    out = []
    for r in rules:
        # Суммы и возраст заказчика — строго, без допуска за границами.
        # Важность правил шаблоны не меняют: иначе сместятся оценки выполненных условий.
        if _is_money(r) or r.id == "customer_age":
            r = r.model_copy(update={"soft_margin": None})
        out.append(r)
    if all(r.id != STOP_REORGANIZING.id for r in out):
        out.append(STOP_REORGANIZING.model_copy())
    return out


def _aggressive(rules: list[ScoringRule]) -> list[ScoringRule]:
    out = []
    for r in rules:
        if r.id == STOP_REORGANIZING.id:
            continue
        if _is_money(r):
            r = _scale_money(r, Decimal("0.5"), Decimal(2))
        elif r.id == "customer_active" and isinstance(r.value, list):
            r = r.model_copy(update={"value": [*r.value, "reorganizing"]})
        elif r.id == "customer_age":
            r = r.model_copy(update={"value": Decimal(1)})
        out.append(r)
    return out


def template_profile(template: str, base: ScoringProfileData | None = None) -> ScoringProfileData:
    """Шаблоны для задачи A — вариации профиля base (по умолчанию — профиля по умолчанию):
    «Осторожный» (cautious) — только действующие заказчики, стоп на реорганизацию,
    суммы строго в диапазоне, пороги выше; «Агрессивный» (aggressive) — диапазон сумм
    вдвое шире, реорганизация допустима, молодые заказчики не штрафуются, пороги ниже."""
    data = (base or default_profile()).model_copy(deep=True)
    if template == "cautious":
        data.rules = _cautious(with_defaults(data.rules))
        data.thresholds = Thresholds(participate=75, consider=45)
    elif template == "aggressive":
        data.rules = _aggressive(with_defaults(data.rules))
        data.thresholds = Thresholds(participate=60, consider=30)
    return ScoringProfileData.model_validate(data.model_dump(mode="json"))
