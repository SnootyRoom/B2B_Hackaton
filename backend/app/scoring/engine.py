"""Детерминированный движок скоринга (аналитика, «Движок скоринга»).

Порядок: стоп-факторы → частичные баллы правил → баллы групп → итог. LLM не участвует.
"""

import math
from collections.abc import Callable

from app.scoring.catalog import NUMERIC_OPERATORS, Group, Operator
from app.scoring.fields import FieldValue
from app.scoring.justification import build_justification
from app.scoring.operators import boolean_holds, numeric_score, semantic_score
from app.scoring.templates import rule_text
from app.scoring.types import (
    GroupResult,
    Recommendation,
    RuleKind,
    RuleResult,
    RuleStatus,
    ScoreResultData,
    ScoringProfileData,
    ScoringRule,
)

# (текст закупки, описание из правила) → косинусная близость; None — посчитать не удалось
Similarity = Callable[[str, str], float | None]

LOW_DATA_SHARE = 0.5


def _round(x: float) -> int:
    return math.floor(x + 0.5)


def _partial(
    rule: ScoringRule, x: FieldValue, profile: ScoringProfileData, similarity: Similarity | None
) -> float | None:
    """s ∈ [0; 1] или None, если данных нет."""
    if x is None:
        return None
    op = rule.operator
    if op == Operator.semantic_match:
        if similarity is None or not isinstance(x, str):
            return None
        c = similarity(x, str(rule.value))
        return None if c is None else semantic_score(c, profile.semantic)
    if op in NUMERIC_OPERATORS:
        if not isinstance(x, int | float) or isinstance(x, bool):
            return None
        margin = 0.0 if rule.kind == RuleKind.stop else rule.soft_margin
        return numeric_score(op, float(x), rule.value, margin)
    return 1.0 if boolean_holds(op, x, rule.value) else 0.0


def recommend(total: int, stopped: bool, profile: ScoringProfileData) -> Recommendation:
    if stopped:
        return Recommendation.skip
    if total >= profile.thresholds.participate:
        return Recommendation.participate
    if total >= profile.thresholds.consider:
        return Recommendation.consider
    return Recommendation.skip


def score(
    profile: ScoringProfileData,
    fields: dict[str, FieldValue],
    similarity: Similarity | None = None,
) -> ScoreResultData:
    results: list[RuleResult] = []
    stop_ids: list[str] = []

    for rule in profile.rules:
        x = fields.get(rule.field)
        res = RuleResult(
            rule_id=rule.id,
            group=rule.group,
            kind=rule.kind,
            label=rule.label,
            status=RuleStatus.disabled,
            field_value=x,
        )
        if rule.enabled:
            s = _partial(rule, x, profile, similarity)
            if s is None:
                res.status = RuleStatus.no_data
            else:
                res.status = RuleStatus.applied
                if rule.kind == RuleKind.stop:
                    res.triggered = s >= 1.0
                    if res.triggered:
                        stop_ids.append(rule.id)
                else:
                    res.partial = s
        results.append(res)

    rules_by_id = {r.id: r for r in profile.rules}

    # Баллы групп
    raw: dict[Group, tuple[float, float, bool]] = {}  # group → (G_g, Σw применённых, low_data)
    for g in Group:
        weighted = [
            r for r in results if r.group == g and r.kind == RuleKind.weighted and r.status != RuleStatus.disabled
        ]
        total_w = sum(rules_by_id[r.rule_id].weight or 0 for r in weighted)
        applied = [r for r in weighted if r.status == RuleStatus.applied]
        applied_w = sum(rules_by_id[r.rule_id].weight or 0 for r in applied)
        skipped_w = total_w - applied_w
        low_data = total_w > 0 and skipped_w > LOW_DATA_SHARE * total_w
        if applied_w > 0:
            num = sum((rules_by_id[r.rule_id].weight or 0) * (r.partial or 0.0) for r in applied)
            raw[g] = (100 * num / applied_w, applied_w, low_data)
        else:
            raw[g] = (math.nan, 0.0, low_data)

    included_w = sum(profile.group_weights.of(g) for g, (_, aw, _) in raw.items() if aw > 0)
    groups: list[GroupResult] = []
    total_f = 0.0
    for g, (gs, aw, low) in raw.items():
        w = profile.group_weights.of(g)
        eff = w / included_w if aw > 0 and included_w > 0 else 0.0
        groups.append(
            GroupResult(group=g, score=None if aw == 0 else round(gs, 2), weight=w, effective_weight=eff, low_data=low)
        )
        if eff == 0:
            continue
        total_f += eff * gs
        for r in results:
            if r.group == g and r.kind == RuleKind.weighted and r.status == RuleStatus.applied:
                share = eff * (rules_by_id[r.rule_id].weight or 0) / aw * 100
                r.contribution = round(share * (r.partial or 0.0), 2)
                r.lost = round(share * (1 - (r.partial or 0.0)), 2)

    stopped = bool(stop_ids)
    total = 0 if stopped else _round(total_f)
    incomplete = any(gr.low_data for gr in groups) or included_w == 0

    for r in results:
        r.text = rule_text(rules_by_id[r.rule_id], r)

    result = ScoreResultData(
        total=total,
        recommendation=recommend(total, stopped, profile),
        incomplete=incomplete,
        stop_factors=stop_ids,
        groups=groups,
        rules=results,
    )
    result.justification = build_justification(result)
    return result
