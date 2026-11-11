"""Почему два профиля дают разную оценку одной закупке (задача A, экран «Сравнение»).

По шаблонам, без LLM: детерминированно и мгновенно. Фразы упорядочены по влиянию на итог,
не больше трёх; каждая ссылается на правило [rule_id].
"""

from dataclasses import dataclass

from app.schemas.score import RuleOutcome, RuleStatus, ScoreResultData
from app.schemas.scoring import RuleKind, ScoringProfileData

MAX_PHRASES = 3
_STOP_IMPACT = 1000.0  # стоп-фактор обнуляет итог — всегда первым


@dataclass(frozen=True)
class _Phrase:
    impact: float
    text: str


def _lc(s: str) -> str:
    if len(s) > 1 and s[1].isupper():
        return s
    return s[:1].lower() + s[1:]


def _points(r: RuleOutcome) -> float:
    return r.contribution or 0.0


def _max_points(r: RuleOutcome) -> float:
    return (r.contribution or 0.0) + (r.lost or 0.0)


def _counted(r: RuleOutcome) -> bool:
    return r.kind == RuleKind.weighted and r.status == RuleStatus.applied


def _stops(name: str, own: ScoreResultData, other: ScoreResultData) -> list[_Phrase]:
    rules = {r.rule_id: r for r in own.rules}
    return [
        _Phrase(_STOP_IMPACT, f"В «{name}» стоп: {_lc(rules[i].text)} [{i}]")
        for i in own.stop_factors
        if i not in other.stop_factors and i in rules
    ]


def _only_in(
    name: str, other_name: str, own: ScoreResultData, other_ids: set[str]
) -> list[_Phrase]:
    out = []
    for r in own.rules:
        if r.rule_id in other_ids or not _counted(r):
            continue
        sign = "плюс" if (r.partial_score or 0.0) >= 0.5 else "минус"
        out.append(
            _Phrase(
                _max_points(r),
                f"В «{other_name}» нет условия «{_lc(r.label)}», в «{name}» оно {sign}: "
                f"{_lc(r.text)} [{r.rule_id}]",
            )
        )
    return out


def explain_difference(
    a: ScoreResultData,
    b: ScoreResultData,
    profile_a: ScoringProfileData,
    profile_b: ScoringProfileData,
) -> str:
    """Объяснение разницы оценок закупки по профилям A и B. Пусто, если разницы нет."""
    if a.total == b.total and a.recommendation == b.recommendation:
        return ""
    na, nb = profile_a.name, profile_b.name
    phrases = [*_stops(na, a, b), *_stops(nb, b, a)]

    ra = {r.rule_id: r for r in a.rules}
    rb = {r.rule_id: r for r in b.rules}
    phrases += _only_in(na, nb, a, set(rb))
    phrases += _only_in(nb, na, b, set(ra))

    wa = {r.id: r.weight for r in profile_a.rules}
    wb = {r.id: r.weight for r in profile_b.rules}
    for rule_id in sorted(ra.keys() & rb.keys()):
        x, y = ra[rule_id], rb[rule_id]
        if x.kind == RuleKind.stop or (not _counted(x) and not _counted(y)):
            continue
        impact = abs(_points(x) - _points(y)) + abs(_max_points(x) - _max_points(y)) / 2
        if impact < 0.5:
            continue
        if _counted(x) and _counted(y) and x.partial_score == y.partial_score:
            # Условие выполнено одинаково — разница только от важности правила
            if wa.get(rule_id) != wb.get(rule_id):
                phrases.append(
                    _Phrase(
                        impact,
                        f"Условие «{_lc(x.label)}» важнее в «"
                        f"{na if (wa.get(rule_id) or 0) > (wb.get(rule_id) or 0) else nb}» "
                        f"[{rule_id}]",
                    )
                )
            continue
        phrases.append(
            _Phrase(
                impact,
                f"«{na}»: {_lc(x.text)}; «{nb}»: {_lc(y.text)} [{rule_id}]",
            )
        )

    ta, tb = profile_a.thresholds, profile_b.thresholds
    # Пороги влияют и на рекомендацию, и на итог: ограничители движка держат его ниже порога
    if (a.recommendation != b.recommendation or not phrases) and (
        ta.participate != tb.participate or ta.consider != tb.consider
    ):
        phrases.append(
            _Phrase(
                abs(a.total - b.total) / 2 + 0.1,
                f"Разные пороги: «участвовать» от {ta.participate} в «{na}» и от {tb.participate}"
                f" в «{nb}», «рассмотреть» от {ta.consider} и от {tb.consider}",
            )
        )
    if profile_a.group_weights != profile_b.group_weights:
        phrases.append(_Phrase(0.05, "Разный вес групп «Закупка», «Соответствие», «Заказчик»"))

    phrases.sort(key=lambda p: -p.impact)
    texts = [p.text for p in phrases[:MAX_PHRASES]]
    return ". ".join(texts) + "." if texts else ""
