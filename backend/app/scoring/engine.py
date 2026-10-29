"""Движок скоринга (роль 3).

Контракт: `score(procurement, customer, profile, similarity=..., now=...) -> ScoreResultData`.
Детерминирован: одинаковый вход → одинаковый результат. Без LLM и без сети.
`similarity(text)` — косинусная близость текста закупки к `text` (значению правила
semantic_match); None — эмбеддинги недоступны, правило считается «нет данных».
"""

from collections.abc import Callable
from datetime import datetime

from app.schemas.customer import CustomerData
from app.schemas.procurement import ProcurementData
from app.schemas.score import GroupScore, Recommendation, ScoreResultData
from app.schemas.scoring import RuleGroup, ScoringProfileData

SimilarityFn = Callable[[str], float | None]


def score(
    procurement: ProcurementData,
    customer: CustomerData | None,
    profile: ScoringProfileData,
    *,
    similarity: SimilarityFn,
    now: datetime,
) -> ScoreResultData:
    # TODO(роль 3): формулы из аналитики, раздел «Движок скоринга». Сейчас — заглушка.
    w = profile.group_weights
    weights = {RuleGroup.procurement: w.procurement, RuleGroup.fit: w.fit,
               RuleGroup.customer: w.customer}  # fmt: skip
    total_w = sum(weights.values())
    return ScoreResultData(
        total=50,
        recommendation=Recommendation.consider,
        incomplete=True,
        groups=[
            GroupScore(group=g, score=None, weight=v, effective_weight=v / total_w, low_data=True)
            for g, v in weights.items()
        ],
        rules=[],
        justification="Оценка предварительная: движок скоринга ещё не подключён.",
    )
