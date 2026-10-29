"""Шаблонное обоснование (аналитика, «Структура обоснования»).

1) вывод, 2) стоп-фактор первым, 3) 2–3 плюса, 4) 1–2 минуса, 5) чего не хватает.
Каждое утверждение ссылается на правило: [rule_id].
"""

from app.scoring.types import Recommendation, RuleKind, RuleStatus, ScoreResultData

REC_LABELS = {
    Recommendation.participate: "Участвовать",
    Recommendation.consider: "Рассмотреть",
    Recommendation.skip: "Пропустить",
}

MAX_PROS = 3
MAX_CONS = 2
MAX_MISSING = 3


def _lc(s: str) -> str:
    return s[:1].lower() + s[1:] if s else s


def build_justification(r: ScoreResultData) -> str:
    rules = {x.rule_id: x for x in r.rules}
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
    pros = sorted((x for x in weighted if x.contribution > 0), key=lambda x: -x.contribution)[
        :MAX_PROS
    ]
    cons = sorted((x for x in weighted if x.lost > 0), key=lambda x: -x.lost)[:MAX_CONS]
    missing = [
        x for x in r.rules if x.kind == RuleKind.weighted and x.status == RuleStatus.no_data
    ][:MAX_MISSING]

    if pros:
        parts.append("Плюсы: " + "; ".join(f"{_lc(x.text)} [{x.rule_id}]" for x in pros) + ".")
    if cons:
        parts.append("Минусы: " + "; ".join(f"{_lc(x.text)} [{x.rule_id}]" for x in cons) + ".")
    if missing:
        parts.append(
            "Не хватает данных: "
            + "; ".join(f"{_lc(x.text.split(':')[0])} [{x.rule_id}]" for x in missing)
            + "."
        )
    return " ".join(parts)
