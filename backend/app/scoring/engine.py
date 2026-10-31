"""Детерминированный движок скоринга (аналитика, «Движок скоринга»).

Порядок: стоп-факторы → частичные баллы правил → баллы групп → итог. LLM не участвует.
Вход и выход — общие контракты app.schemas.scoring / app.schemas.score.
"""

import math
from collections.abc import Callable

from app.core.config import get_settings
from app.schemas.score import (
    GroupScore,
    Recommendation,
    RuleOutcome,
    RuleStatus,
    ScoreResultData,
)
from app.schemas.scoring import (
    FIELD_CATALOG,
    FieldType,
    Operator,
    RuleGroup,
    RuleKind,
    ScoringProfileData,
    ScoringRule,
)
from app.scoring.fields import FieldValue
from app.scoring.justification import build_justification
from app.scoring.operators import (
    NUMERIC_OPERATORS,
    SemanticThresholds,
    as_number,
    as_pair,
    boolean_holds,
    numeric_score,
    semantic_score,
)
from app.scoring.templates import rule_text

# (текст закупки, описание из правила) → косинусная близость; None — посчитать не удалось
Similarity = Callable[[str, str], float | None]

LOW_DATA_SHARE = 0.5


def _round(x: float) -> int:
    return math.floor(x + 0.5)


def semantic_thresholds() -> SemanticThresholds:
    s = get_settings()
    return SemanticThresholds(c0=s.semantic_c0, c1=s.semantic_c1)


def _partial(
    rule: ScoringRule,
    x: FieldValue,
    similarity: Similarity | None,
    semantic: SemanticThresholds,
    closeness: dict[str, float],
) -> float | None:
    """s ∈ [0; 1] или None, если данных нет. Близость по смыслу запоминается в closeness."""
    if x is None:
        return None
    op = rule.operator
    if op == Operator.semantic_match:
        if similarity is None or not isinstance(x, str):
            return None
        c = similarity(x, str(rule.value))
        if c is None:
            return None
        closeness[rule.id] = c
        return semantic_score(c, semantic)
    if op in NUMERIC_OPERATORS:
        if not isinstance(x, int | float) or isinstance(x, bool):
            return None
        margin = 0.0 if rule.kind == RuleKind.stop else (rule.soft_margin or 0.0)
        return numeric_score(op, float(x), rule.value, margin)
    return 1.0 if boolean_holds(op, x, rule.value) else 0.0


def _applied(results: list[RuleOutcome], *groups: RuleGroup) -> list[RuleOutcome]:
    return [
        r
        for r in results
        if r.group in groups and r.kind == RuleKind.weighted and r.status == RuleStatus.applied
    ]


def subject_mismatch(
    results: list[RuleOutcome],
    groups: list[GroupScore],
    fit_min: float,
    closeness: dict[str, float],
    lift: float,
) -> list[str]:
    """Предмет не тот: проверено сравнение по смыслу, а балл группы «Соответствие» ниже fit_min.
    Совпавший код ОКПД2 поднимает балл группы и снимает ограничение. Очень близкий смысл
    (близость ≥ lift) тоже снимает: кода деятельности компании может не быть в справочнике.
    Возвращает rule_id правил группы для ссылки в обосновании."""
    fit = _applied(results, RuleGroup.fit)
    fit_score = next((g.score for g in groups if g.group == RuleGroup.fit), None)
    semantic = [r for r in fit if r.operator == Operator.semantic_match]
    if any(closeness.get(r.rule_id, 0.0) >= lift for r in semantic):
        return []
    if semantic and fit_score is not None and fit_score < fit_min:
        return [r.rule_id for r in fit]
    return []


def okpd2_misses(results: list[RuleOutcome]) -> list[str]:
    """Правила по кодам ОКПД2, которые не совпали, когда предмет проверен и по смыслу.
    Их штраф смягчается (важность okpd2_miss_weight): кода деятельности компании может не быть
    в справочнике категорий, и тогда неверный код один уводил бы закупку в «Пропустить».
    Без сравнения по смыслу код остаётся обычным правилом."""
    fit = _applied(results, RuleGroup.fit)
    if not any(r.operator == Operator.semantic_match for r in fit):
        return []
    return [r.rule_id for r in fit if r.field == "okpd2_codes" and (r.partial_score or 0.0) == 0.0]


def failed_conditions(results: list[RuleOutcome]) -> list[str]:
    """Явные условия профиля о закупке и заказчике, которые не выполнены совсем (балл 0):
    чужой регион, другой способ, сумма за пределами допуска. С ними — не выше «Рассмотреть»."""
    applied = _applied(results, RuleGroup.procurement, RuleGroup.customer)
    return [r.rule_id for r in applied if (r.partial_score or 0.0) == 0.0]


def money_far_outside(
    profile: ScoringProfileData, fields: dict[str, FieldValue], factor: float
) -> list[str]:
    """Сумма закупки за границей диапазона профиля больше чем в factor раз:
    компании такая закупка не по силам или не интересна. Возвращает rule_id правил о суммах."""
    far: list[str] = []
    for rule in profile.rules:
        spec = FIELD_CATALOG.get(rule.field)
        x = fields.get(rule.field)
        if (
            not rule.enabled
            or rule.kind != RuleKind.weighted
            or spec is None
            or spec.type != FieldType.money
            or rule.operator not in NUMERIC_OPERATORS
            or not isinstance(x, int | float)
            or isinstance(x, bool)
        ):
            continue
        if rule.operator == Operator.between:
            lo, hi = as_pair(rule.value)
        elif rule.operator == Operator.gte:
            lo, hi = as_number(rule.value), math.inf
        else:
            lo, hi = 0.0, as_number(rule.value)
        if x > hi * factor or x * factor < lo:
            far.append(rule.id)
    return far


def recommend(
    total: int, stopped: bool, no_data: bool, profile: ScoringProfileData
) -> Recommendation:
    if stopped:
        return Recommendation.skip
    if no_data:
        # ни одно правило не проверено — решение за человеком, закупку не теряем
        return Recommendation.consider
    if total >= profile.thresholds.participate:
        return Recommendation.participate
    if total >= profile.thresholds.consider:
        return Recommendation.consider
    return Recommendation.skip


def score(
    profile: ScoringProfileData,
    fields: dict[str, FieldValue],
    similarity: Similarity | None = None,
    semantic: SemanticThresholds | None = None,
    fit_min: float | None = None,
    far_factor: float | None = None,
) -> ScoreResultData:
    semantic = semantic or semantic_thresholds()
    fit_min = get_settings().fit_min if fit_min is None else fit_min
    far_factor = get_settings().money_far_factor if far_factor is None else far_factor
    results: list[RuleOutcome] = []
    stop_ids: list[str] = []
    closeness: dict[str, float] = {}

    for rule in profile.rules:
        x = fields.get(rule.field)
        res = RuleOutcome(
            rule_id=rule.id,
            label=rule.label,
            group=rule.group,
            kind=rule.kind,
            field=rule.field,
            operator=rule.operator,
            field_value=x,
            status=RuleStatus.disabled,
            text="",
        )
        if rule.enabled:
            s = _partial(rule, x, similarity, semantic, closeness)
            if s is None:
                res.status = RuleStatus.no_data
            else:
                res.status = RuleStatus.applied
                if rule.kind == RuleKind.stop:
                    res.triggered = s >= 1.0
                    if res.triggered:
                        stop_ids.append(rule.id)
                else:
                    res.partial_score = s
        res.text = rule_text(rule, res, x)
        results.append(res)

    weights: dict[str, float] = {r.id: r.weight or 0 for r in profile.rules}
    miss_weight = get_settings().okpd2_miss_weight
    for rule_id in okpd2_misses(results):
        weights[rule_id] = min(weights[rule_id], miss_weight)

    # Баллы групп
    raw: dict[RuleGroup, tuple[float, float, bool]] = {}  # → (G_g, Σw применённых, low_data)
    for g in RuleGroup:
        weighted = [
            r
            for r in results
            if r.group == g and r.kind == RuleKind.weighted and r.status != RuleStatus.disabled
        ]
        total_w = sum(weights[r.rule_id] for r in weighted)
        applied = [r for r in weighted if r.status == RuleStatus.applied]
        applied_w = sum(weights[r.rule_id] for r in applied)
        low_data = total_w > 0 and total_w - applied_w > LOW_DATA_SHARE * total_w
        if applied_w > 0:
            num = sum(weights[r.rule_id] * (r.partial_score or 0.0) for r in applied)
            raw[g] = (100 * num / applied_w, applied_w, low_data)
        else:
            raw[g] = (math.nan, 0.0, low_data)

    def group_weight(g: RuleGroup) -> float:
        return float(getattr(profile.group_weights, g.value))

    included_w = sum(group_weight(g) for g, (_, aw, _) in raw.items() if aw > 0)
    groups: list[GroupScore] = []
    total_f = 0.0
    for g, (gs, aw, low) in raw.items():
        w = group_weight(g)
        eff = w / included_w if aw > 0 and included_w > 0 else 0.0
        groups.append(
            GroupScore(
                group=g,
                score=None if aw == 0 else round(gs, 2),
                weight=w,
                effective_weight=eff,
                low_data=low,
            )
        )
        if eff == 0:
            continue
        total_f += eff * gs
        for r in results:
            if r.group == g and r.kind == RuleKind.weighted and r.status == RuleStatus.applied:
                share = eff * weights[r.rule_id] / aw * 100
                r.contribution = round(share * (r.partial_score or 0.0), 2)
                r.lost = round(share * (1 - (r.partial_score or 0.0)), 2)

    stopped = bool(stop_ids)
    no_data = included_w == 0
    total = 0 if stopped or no_data else _round(total_f)

    # Предмет совсем не похож на деятельность компании или сумма далеко за диапазоном —
    # остальные условия не вытягивают закупку в «Рассмотреть»: итог не выше порога «Пропустить».
    lift = get_settings().semantic_lift
    mismatch = subject_mismatch(results, groups, fit_min, closeness, lift)
    far = [] if mismatch else money_far_outside(profile, fields, far_factor)
    failed = [] if mismatch or far else failed_conditions(results)
    if (mismatch or far) and not stopped:
        total = min(total, max(profile.thresholds.consider - 1, 0))
    # «Участвовать» — только если выполнены все явные условия профиля
    elif failed and not stopped and not no_data:
        total = min(total, max(profile.thresholds.participate - 1, 0))

    result = ScoreResultData(
        total=total,
        recommendation=recommend(total, stopped, no_data, profile),
        incomplete=no_data or any(gr.low_data for gr in groups),
        stop_factors=stop_ids,
        groups=groups,
        rules=results,
        justification="",
    )
    result.justification = build_justification(
        result, no_data=no_data, mismatch=mismatch, far=far, failed=failed
    )
    return result
