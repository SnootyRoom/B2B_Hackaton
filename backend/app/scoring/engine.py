"""Детерминированный движок скоринга (аналитика, «Движок скоринга»).

Порядок: стоп-факторы → частичные баллы правил → баллы групп → итог. LLM не участвует.
Вход и выход — общие контракты app.schemas.scoring / app.schemas.score.
"""

import math
from collections.abc import Callable, Mapping

from app.core.config import get_settings
from app.schemas.score import (
    GroupScore,
    Recommendation,
    RuleOutcome,
    RuleStatus,
    ScoreResultData,
)
from app.schemas.scoring import Operator, RuleGroup, RuleKind, ScoringProfileData, ScoringRule
from app.scoring.fields import FieldValue
from app.scoring.justification import build_justification
from app.scoring.operators import (
    NUMERIC_OPERATORS,
    SemanticThresholds,
    boolean_holds,
    numeric_score,
    prefix_share,
    semantic_score,
)
from app.scoring.templates import rule_text

# (текст закупки, описание из правила) → косинусная близость; None — посчитать не удалось
Similarity = Callable[[str, str], float | None]

LOW_DATA_SHARE = 0.5
# Важность «высокая»: невыполненное условие закупки с таким весом не даёт рекомендации «Участвовать»
IMPORTANT_WEIGHT = 3


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
    shares: FieldValue = None,
) -> float | None:
    """s ∈ [0; 1] или None, если данных нет; shares — доли стоимости по кодам ОКПД2."""
    if x is None:
        return None
    op = rule.operator
    if op == Operator.semantic_match:
        if similarity is None or not isinstance(x, str):
            return None
        c = similarity(x, str(rule.value))
        return None if c is None else semantic_score(c, semantic)
    if op == Operator.prefix_in and rule.kind == RuleKind.weighted:
        return prefix_share(x, rule.value, shares if isinstance(shares, dict) else None)
    if op in NUMERIC_OPERATORS:
        if not isinstance(x, int | float) or isinstance(x, bool):
            return None
        margin = 0.0 if rule.kind == RuleKind.stop else (rule.soft_margin or 0.0)
        return numeric_score(op, float(x), rule.value, margin)
    return 1.0 if boolean_holds(op, x, rule.value) else 0.0


def _limit(
    profile: ScoringProfileData,
    groups: list[GroupScore],
    results: list[RuleOutcome],
    weights: Mapping[str, int],
    total: int,
) -> tuple[int, str] | None:
    """Потолок итога и его причина (аналитика, «Ограничения итога») или None.

    Средневзвешенная оценка не умеет «вето»: непрофильная закупка с подходящей суммой и
    надёжным заказчиком набирает 65, а одно невыполненное важное условие снимает лишь 8–12
    баллов. Поэтому: соответствие предмета ниже fit_min → не выше «Пропустить»; не выполнено
    условие закупки высокой важности → не выше «Рассмотреть». Вклады правил при этом не
    пересчитываются: их сумма может быть больше итога.
    """
    t = profile.thresholds
    fit = next(g for g in groups if g.group == RuleGroup.fit)
    # Смысловая близость одна профильный предмет от непрофильного не отличает: без кодов ОКПД2
    # или ключевых слов закупку не отсекаем, чтобы не потерять подходящую
    exact = any(
        r.group == RuleGroup.fit
        and r.kind == RuleKind.weighted
        and r.status == RuleStatus.applied
        and r.operator != Operator.semantic_match
        for r in results
    )
    if (
        exact
        and fit.score is not None
        and fit.effective_weight > 0
        and fit.score < t.fit_min
        and total >= t.consider
    ):
        return max(t.consider - 1, 0), (
            f"предмет закупки не соответствует профилю — соответствие {fit.score:.0f} из 100, "
            f"порог {t.fit_min}"
        )
    if total >= t.participate:
        weak = [
            r
            for r in results
            if r.group == RuleGroup.procurement
            and r.kind == RuleKind.weighted
            and r.status == RuleStatus.applied
            and weights[r.rule_id] == IMPORTANT_WEIGHT
            and (r.partial_score or 0.0) < 1.0
        ]
        if weak:
            return max(t.participate - 1, 0), "не выполнено важное условие — " + "; ".join(
                f"{r.text} [{r.rule_id}]" for r in weak
            )
    return None


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
) -> ScoreResultData:
    semantic = semantic or semantic_thresholds()
    results: list[RuleOutcome] = []
    stop_ids: list[str] = []

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
            s = _partial(rule, x, similarity, semantic, fields.get("okpd2_shares"))
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

    weights = {r.id: r.weight or 0 for r in profile.rules}

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
    limit = None if stopped or no_data else _limit(profile, groups, results, weights, total)
    if limit is not None:
        total = min(total, limit[0])

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
        result, no_data=no_data, limit=limit[1] if limit else None
    )
    return result
