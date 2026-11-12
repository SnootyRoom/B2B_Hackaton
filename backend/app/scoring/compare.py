"""Несколько профилей одного пользователя: версия профиля и объяснение разницы оценок.

Контракт для конвейера и API (роль 1):
- `profile_version(profile) -> str` — пишется в оценку; совпадает с текущей — пересчёт не нужен.
- `explain_difference(a, b, profile_a, profile_b) -> str` — почему одна закупка получила
  разную оценку в двух профилях. По шаблонам, без LLM: одинаковый вход — одинаковый текст.
"""

import hashlib
import json
from dataclasses import dataclass

from app.core.config import get_settings
from app.schemas.score import Recommendation, RuleOutcome, RuleStatus, ScoreResultData
from app.schemas.scoring import (
    FIELD_CATALOG,
    GroupWeights,
    Operator,
    RuleKind,
    ScoringProfileData,
    Thresholds,
)
from app.scoring.engine import failed_conditions, money_far_outside
from app.scoring.fields import FieldValue
from app.scoring.justification import REC_LABELS, _lc
from app.scoring.templates import fmt_value

MAX_REASONS = 3
# Разница частичного балла правила, с которой она попадает в объяснение
MIN_PARTIAL_DIFF = 0.25
# Правило есть только в одном профиле: в объяснение, если стоило этому профилю столько баллов
MIN_LOST = 3.0
# Значение поля длиннее — в объяснение не выводится (предмет закупки, списки кодов)
MAX_VALUE_LEN = 60
# Пороги и веса — после правил: если разница есть и в правилах, главная причина в них
THRESHOLDS_IMPACT = 10.0
WEIGHTS_IMPACT = 5.0


def profile_version(profile: ScoringProfileData) -> str:
    """Хэш всего, от чего зависит оценка: правил, весов, порогов и калибровки движка.
    Имя и описание компании не входят: переименование не делает оценки устаревшими."""
    s = get_settings()
    payload = {
        "profile": profile.model_dump(
            mode="json", include={"rules", "group_weights", "thresholds"}
        ),
        "engine": [
            s.semantic_c0,
            s.semantic_c1,
            s.fit_min,
            s.semantic_lift,
            s.okpd2_miss_weight,
            s.money_far_factor,
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class _Reason:
    impact: float  # насколько причина повлияла на разницу, в баллах; больше — раньше в тексте
    text: str


def _q(name: str) -> str:
    return f"«{name}»"


def _in(name: str) -> str:
    return f"в профиле «{name}»"


def _cap1(s: str) -> str:
    return s[:1].upper() + s[1:]


def _state(s: float | None) -> str:
    if s is None:
        return "не проверено"
    if s >= 0.999:
        return "выполнено"
    if s <= 0.001:
        return "не выполнено"
    return "выполнено частично"


def _weighted(r: ScoreResultData) -> dict[str, RuleOutcome]:
    """Применённые взвешенные правила по полю (первое правило поля)."""
    out: dict[str, RuleOutcome] = {}
    for x in r.rules:
        if x.kind == RuleKind.weighted and x.status == RuleStatus.applied:
            out.setdefault(x.field, x)
    return out


def _value(x: RuleOutcome) -> str:
    """« (НМЦК: 12 млн ₽)» — значение поля закупки в конец фразы; длинные не выводятся."""
    if x.operator in (Operator.semantic_match, Operator.prefix_in) or x.field_value is None:
        return ""
    if x.field not in FIELD_CATALOG:
        return ""
    value = fmt_value(x.field, x.field_value)
    if len(value) > MAX_VALUE_LEN:
        return ""
    return f" ({_lc(FIELD_CATALOG[x.field].label)}: {value})"


def _cap(r: ScoreResultData, profile: ScoringProfileData) -> str | None:
    """Ограничитель, который снизил итог: восстанавливается по сохранённой оценке
    (итог ниже взвешенной суммы групп ровно до порога)."""
    if r.stop_factors:
        return None
    raw = sum(g.effective_weight * g.score for g in r.groups if g.score is not None)
    if r.total >= int(raw + 0.5):
        return None
    t = profile.thresholds
    if r.total == max(t.consider - 1, 0):
        fields: dict[str, FieldValue] = {
            x.field: x.field_value
            for x in r.rules
            if isinstance(x.field_value, int | float) and not isinstance(x.field_value, bool)
        }
        far = money_far_outside(profile, fields, get_settings().money_far_factor)
        if far:
            labels = _labels(profile, far)
            return f"сумма далеко за пределами условия {labels}, итог не выше «Пропустить»"
        return "предмет закупки не похож на деятельность компании, итог не выше «Пропустить»"
    if r.total == max(t.participate - 1, 0):
        failed = failed_conditions(r.rules)
        if failed:
            return f"не выполнено условие {_labels(profile, failed)}, итог не выше «Рассмотреть»"
    return None


def _labels(profile: ScoringProfileData, ids: list[str]) -> str:
    by_id = {rule.id: rule.label for rule in profile.rules}
    return ", ".join(f"«{by_id.get(i, i)}» [{i}]" for i in ids)


def _recommend(total: int, t: Thresholds) -> Recommendation:
    if total >= t.participate:
        return Recommendation.participate
    if total >= t.consider:
        return Recommendation.consider
    return Recommendation.skip


def _stop_reasons(
    a: ScoreResultData, b: ScoreResultData, pa: ScoringProfileData, pb: ScoringProfileData
) -> list[_Reason]:
    out = []
    for r, other, p, po in ((a, b, pa, pb), (b, a, pb, pa)):
        b_fields = {rule.field for rule in po.rules if rule.kind == RuleKind.stop}
        by_id = {rule.id: rule for rule in p.rules}
        for rule_id in r.stop_factors:
            if rule_id in other.stop_factors or rule_id not in by_id:
                continue
            rule = by_id[rule_id]
            tail = (
                f"{_in(po.name)} условие другое и не сработало"
                if rule.field in b_fields
                else f"{_in(po.name)} такого стоп-фактора нет"
            )
            text = f"{_cap1(_in(p.name))} сработал стоп-фактор «{rule.label}» [{rule_id}], {tail}"
            out.append(_Reason(1000, text))
    return out


def _rule_reasons(
    a: ScoreResultData, b: ScoreResultData, pa: ScoringProfileData, pb: ScoringProfileData
) -> list[_Reason]:
    out = []
    ra, rb = _weighted(a), _weighted(b)
    for field in dict.fromkeys([*ra, *rb]):
        xa, xb = ra.get(field), rb.get(field)
        if xa is not None and xb is not None:
            if abs((xa.partial_score or 0.0) - (xb.partial_score or 0.0)) < MIN_PARTIAL_DIFF:
                continue
            impact = abs((xa.contribution or 0.0) - (xb.contribution or 0.0))
            text = (
                f"Условие «{xa.label}» {_state(xa.partial_score)} {_in(pa.name)} "
                f"[{xa.rule_id}], а «{xb.label}» {_state(xb.partial_score)} {_in(pb.name)} "
                f"[{xb.rule_id}]{_value(xa)}"
            )
            out.append(_Reason(impact, text))
            continue
        only, p, po = (xa, pa, pb) if xa is not None else (xb, pb, pa)
        if only is None or (only.lost or 0.0) < MIN_LOST:
            continue
        text = (
            f"{_cap1(_in(p.name))} есть условие «{only.label}» [{only.rule_id}] и оно "
            f"{_state(only.partial_score)}{_value(only)}, {_in(po.name)} такого условия нет"
        )
        out.append(_Reason(only.lost or 0.0, text))
    return out


def _profile_reasons(
    a: ScoreResultData, b: ScoreResultData, pa: ScoringProfileData, pb: ScoringProfileData
) -> list[_Reason]:
    out = []
    for r, p, po in ((a, pa, pb), (b, pb, pa)):
        cap = _cap(r, p)
        if cap is not None and _cap(b if r is a else a, po) != cap:
            out.append(_Reason(500, f"{_cap1(_in(p.name))} {cap}"))
    ta, tb = pa.thresholds, pb.thresholds
    if ta != tb and not a.stop_factors and _recommend(a.total, tb) != a.recommendation:
        out.append(
            _Reason(
                THRESHOLDS_IMPACT,
                f"Пороги разные: «Участвовать» от {ta.participate} {_in(pa.name)} "
                f"и от {tb.participate} {_in(pb.name)}, «Рассмотреть» от {ta.consider} "
                f"и от {tb.consider}",
            )
        )
    wa, wb = pa.group_weights, pb.group_weights
    if wa != wb:
        out.append(
            _Reason(
                WEIGHTS_IMPACT,
                f"Веса групп разные: закупка / соответствие / заказчик — {_pct(wa)} "
                f"{_in(pa.name)}, {_pct(wb)} {_in(pb.name)}",
            )
        )
    return out


def _pct(w: GroupWeights) -> str:
    return " / ".join(f"{round(x * 100)}%" for x in (w.procurement, w.fit, w.customer))


def explain_difference(
    a: ScoreResultData,
    b: ScoreResultData,
    profile_a: ScoringProfileData,
    profile_b: ScoringProfileData,
) -> str:
    """Почему одна закупка оценена по-разному в профилях A и B: до трёх причин по убыванию
    влияния, со ссылками на правила. Пустая строка — оценки совпадают."""
    if a.total == b.total and a.recommendation == b.recommendation:
        return ""
    reasons = [
        *_stop_reasons(a, b, profile_a, profile_b),
        *_profile_reasons(a, b, profile_a, profile_b),
        *_rule_reasons(a, b, profile_a, profile_b),
    ]
    reasons.sort(key=lambda r: -r.impact)
    head = (
        f"{_q(profile_a.name)}: {REC_LABELS[a.recommendation]}, {a.total}%; "
        f"{_q(profile_b.name)}: {REC_LABELS[b.recommendation]}, {b.total}%."
    )
    if not reasons:
        return f"{head} Разница складывается из нескольких небольших отличий в правилах."
    return " ".join([head, *(f"{r.text}." for r in reasons[:MAX_REASONS])])
