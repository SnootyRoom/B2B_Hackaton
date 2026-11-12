"""Почему два профиля дают разную оценку одной закупке (задача A, экран «Сравнение»).

По шаблонам, без LLM: детерминированно и мгновенно. Фразы упорядочены по влиянию на итог,
не больше трёх; каждая ссылается на правило [rule_id].

Правила двух профилей сопоставляются по полю, а не по номеру: профили, разобранные из текста
по отдельности, нумеруют условия по-своему (r1 — регион в одном и сумма в другом).
"""

from dataclasses import dataclass

from app.core.config import get_settings
from app.schemas.score import RuleOutcome, RuleStatus, ScoreResultData
from app.schemas.scoring import RuleKind, ScoringProfileData
from app.scoring.engine import failed_conditions, money_far_outside
from app.scoring.fields import FieldValue

MAX_PHRASES = 3
_STOP_IMPACT = 1000.0  # стоп-фактор обнуляет итог — всегда первым
_LIMIT_IMPACT = 500.0  # ограничитель держит итог ниже порога — сразу после стоп-факторов


@dataclass(frozen=True)
class _Phrase:
    impact: float
    text: str


def _lc(s: str) -> str:
    if len(s) > 1 and s[1].isupper():
        return s
    return s[:1].lower() + s[1:]


def _in(name: str) -> str:
    return f"в профиле «{name}»"


def _in_start(name: str) -> str:  # то же с заглавной, в начале фразы
    return f"В профиле «{name}»"


def _points(r: RuleOutcome) -> float:
    return r.contribution or 0.0


def _max_points(r: RuleOutcome) -> float:
    return (r.contribution or 0.0) + (r.lost or 0.0)


def _counted(r: RuleOutcome) -> bool:
    return r.kind == RuleKind.weighted and r.status == RuleStatus.applied


def _ref(x: RuleOutcome, y: RuleOutcome) -> str:
    return x.rule_id if x.rule_id == y.rule_id else f"{x.rule_id} / {y.rule_id}"


def _pair(
    a: list[RuleOutcome], b: list[RuleOutcome]
) -> tuple[list[tuple[RuleOutcome, RuleOutcome]], list[RuleOutcome], list[RuleOutcome]]:
    """Пары «одно и то же условие в A и в B» и условия, которые есть только в одном профиле.
    Сначала тот же номер при том же поле (дубль профиля, шаблон), затем — то же поле."""
    rest = list(b)
    pairs: list[tuple[RuleOutcome, RuleOutcome]] = []
    unmatched: list[RuleOutcome] = []
    for x in a:
        y = next((y for y in rest if y.rule_id == x.rule_id and y.field == x.field), None)
        if y is None:
            unmatched.append(x)
            continue
        rest.remove(y)
        pairs.append((x, y))
    only_a = []
    for x in unmatched:
        y = next((y for y in rest if y.field == x.field and y.kind == x.kind), None)
        if y is None:
            only_a.append(x)
            continue
        rest.remove(y)
        pairs.append((x, y))
    return pairs, only_a, rest


def _stops(name: str, own: ScoreResultData, other: ScoreResultData) -> list[_Phrase]:
    rules = {r.rule_id: r for r in own.rules}
    return [
        _Phrase(_STOP_IMPACT, f"{_in_start(name)} стоп: {_lc(rules[i].text)} [{i}]")
        for i in own.stop_factors
        if i not in other.stop_factors and i in rules
    ]


def _only_in(name: str, other_name: str, own: list[RuleOutcome]) -> list[_Phrase]:
    out = []
    for r in own:
        if not _counted(r):
            continue
        sign = "плюс" if (r.partial_score or 0.0) >= 0.5 else "минус"
        out.append(
            _Phrase(
                _max_points(r),
                f"{_in_start(other_name)} нет условия «{_lc(r.label)}», {_in(name)} оно {sign}: "
                f"{_lc(r.text)} [{r.rule_id}]",
            )
        )
    return out


def _labels(profile: ScoringProfileData, ids: list[str]) -> str:
    by_id = {rule.id: rule.label for rule in profile.rules}
    return ", ".join(f"«{_lc(by_id.get(i, i))}» [{i}]" for i in ids)


def _limit(r: ScoreResultData, profile: ScoringProfileData) -> str | None:
    """Ограничитель движка, который снизил итог (engine.score): восстанавливается по сохранённой
    оценке — итог ниже взвешенной суммы групп и стоит ровно у порога."""
    if r.stop_factors or not r.groups:
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
            return f"сумма далеко за пределами условия {labels}: не выше «Пропустить»"
        return "предмет закупки не похож на деятельность компании: не выше «Пропустить»"
    if r.total == max(t.participate - 1, 0):
        failed = failed_conditions(r.rules)
        if failed:
            return f"не выполнено условие {_labels(profile, failed)}: не выше «Рассмотреть»"
    return None


def _limits(
    a: ScoreResultData, b: ScoreResultData, pa: ScoringProfileData, pb: ScoringProfileData
) -> list[_Phrase]:
    la, lb = _limit(a, pa), _limit(b, pb)
    out = []
    if la is not None and la != lb:
        out.append(_Phrase(_LIMIT_IMPACT, f"{_in_start(pa.name)} оценка ограничена: {la}"))
    if lb is not None and lb != la:
        out.append(_Phrase(_LIMIT_IMPACT, f"{_in_start(pb.name)} оценка ограничена: {lb}"))
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
    phrases = [*_stops(na, a, b), *_stops(nb, b, a), *_limits(a, b, profile_a, profile_b)]

    ra = [r for r in a.rules if r.kind != RuleKind.stop]
    rb = [r for r in b.rules if r.kind != RuleKind.stop]
    pairs, only_a, only_b = _pair(ra, rb)
    phrases += _only_in(na, nb, only_a)
    phrases += _only_in(nb, na, only_b)

    wa = {r.id: r.weight for r in profile_a.rules}
    wb = {r.id: r.weight for r in profile_b.rules}
    for x, y in pairs:
        if not _counted(x) and not _counted(y):
            continue
        impact = abs(_points(x) - _points(y)) + abs(_max_points(x) - _max_points(y)) / 2
        if impact < 0.5:
            continue
        ref = _ref(x, y)
        if _counted(x) and _counted(y) and x.partial_score == y.partial_score:
            # Условие выполнено одинаково — разница только от важности правила
            weight_a, weight_b = wa.get(x.rule_id) or 0, wb.get(y.rule_id) or 0
            if weight_a != weight_b:
                phrases.append(
                    _Phrase(
                        impact,
                        f"Условие «{_lc(x.label)}» важнее "
                        f"{_in(na if weight_a > weight_b else nb)} [{ref}]",
                    )
                )
            continue
        phrases.append(_Phrase(impact, f"«{na}»: {_lc(x.text)}; «{nb}»: {_lc(y.text)} [{ref}]"))

    ta, tb = profile_a.thresholds, profile_b.thresholds
    # Пороги влияют и на рекомендацию, и на итог: ограничители движка держат его ниже порога
    if (a.recommendation != b.recommendation or not phrases) and (
        ta.participate != tb.participate or ta.consider != tb.consider
    ):
        phrases.append(
            _Phrase(
                abs(a.total - b.total) / 2 + 0.1,
                f"Разные пороги: «участвовать» от {ta.participate} {_in(na)} и от "
                f"{tb.participate} {_in(nb)}, «рассмотреть» от {ta.consider} и от {tb.consider}",
            )
        )
    if profile_a.group_weights != profile_b.group_weights:
        phrases.append(_Phrase(0.05, "Разный вес групп «Закупка», «Соответствие», «Заказчик»"))

    phrases.sort(key=lambda p: -p.impact)
    texts = [p.text for p in phrases[:MAX_PHRASES]]
    return ". ".join(texts) + "." if texts else ""
