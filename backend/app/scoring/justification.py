"""Шаблонное обоснование (аналитика, «Структура обоснования»).

1) вывод, 2) стоп-фактор первым, 3) 2–3 плюса, 4) 1–2 минуса, 5) чего не хватает.
Каждое утверждение ссылается на правило: [rule_id].
"""

from app.schemas.score import Recommendation, RuleStatus, ScoreResultData
from app.schemas.scoring import RuleKind

REC_LABELS = {
    Recommendation.participate: "Участвовать",
    Recommendation.consider: "Рассмотреть",
    Recommendation.skip: "Пропустить",
}

NO_DATA_TEXT = "Недостаточно данных для оценки — проверьте закупку вручную."

MAX_PROS = 3
MAX_CONS = 2
MAX_MISSING = 3


def _lc(s: str) -> str:
    """Первую букву — строчной, но аббревиатуры («НМЦК», «ОКПД2») не трогаем."""
    if len(s) > 1 and s[1].isupper():
        return s
    return s[:1].lower() + s[1:]


def build_justification(r: ScoreResultData, no_data: bool = False) -> str:
    """no_data — не удалось применить ни одного взвешенного правила."""
    rules = {x.rule_id: x for x in r.rules}
    missing = [
        x for x in r.rules if x.kind == RuleKind.weighted and x.status == RuleStatus.no_data
    ][:MAX_MISSING]
    missing_text = (
        "Не хватает данных: "
        + "; ".join(f"{_lc(x.text.split(':')[0])} [{x.rule_id}]" for x in missing)
        + "."
    )

    if no_data and not r.stop_factors:
        parts = [f"Рекомендация: {REC_LABELS[r.recommendation]} (оценка неполная).", NO_DATA_TEXT]
        if missing:
            parts.append(missing_text)
        return " ".join(parts)

    head = f"Рекомендация: {REC_LABELS[r.recommendation]}, оценка {r.total}%"
    if r.incomplete:
        head += " (оценка неполная — мало данных)"
    parts = [head + "."]

    if r.stop_factors:
        stops = "; ".join(f"{_lc(rules[i].text)} [{i}]" for i in r.stop_factors)
        parts.append(f"Стоп-фактор: {stops}.")
        return " ".join(parts)

    weighted = [
        x for x in r.rules if x.kind == RuleKind.weighted and x.status == RuleStatus.applied
    ]
    pros = sorted(
        (x for x in weighted if (x.contribution or 0) > 0), key=lambda x: -(x.contribution or 0)
    )[:MAX_PROS]
    cons = sorted((x for x in weighted if (x.lost or 0) > 0), key=lambda x: -(x.lost or 0))[
        :MAX_CONS
    ]

    if pros:
        parts.append("Плюсы: " + "; ".join(f"{_lc(x.text)} [{x.rule_id}]" for x in pros) + ".")
    if cons:
        parts.append("Минусы: " + "; ".join(f"{_lc(x.text)} [{x.rule_id}]" for x in cons) + ".")
    if missing:
        parts.append(missing_text)
    return " ".join(parts)
