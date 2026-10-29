from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue

from app.schemas.common import ORMModel
from app.schemas.scoring import Operator, RuleGroup, RuleKind


class Recommendation(StrEnum):
    participate = "participate"  # Участвовать
    consider = "consider"  # Рассмотреть
    skip = "skip"  # Пропустить


class RuleStatus(StrEnum):
    applied = "applied"
    no_data = "no_data"
    disabled = "disabled"


class JustificationSource(StrEnum):
    template = "template"
    llm = "llm"


class RuleOutcome(BaseModel):
    rule_id: str
    label: str
    group: RuleGroup
    kind: RuleKind
    field: str
    operator: Operator
    field_value: JsonValue = Field(description="Значение поля закупки или заказчика")
    status: RuleStatus
    triggered: bool = Field(default=False, description="Для стоп-фактора: сработал")
    partial_score: float | None = Field(default=None, description="s ∈ [0; 1]")
    contribution: float | None = Field(default=None, description="Вклад в итог в баллах")
    lost: float | None = Field(default=None, description="Потеря баллов относительно s = 1")
    text: str = Field(description="Фраза обоснования по шаблону")


class GroupScore(BaseModel):
    group: RuleGroup
    score: float | None = Field(description="0–100; None — группа исключена (нет правил)")
    weight: float = Field(description="Вес из профиля")
    effective_weight: float = Field(description="Вес после перераспределения, сумма = 1")
    low_data: bool = Field(description="Пропущено > 50% веса группы")


class ScoreResultData(BaseModel):
    """Выход движка скоринга (роль 3)."""

    total: int = Field(ge=0, le=100)
    recommendation: Recommendation
    incomplete: bool = Field(description="Хотя бы одна группа «мало данных»")
    stop_factors: list[str] = Field(default_factory=list, description="rule_id сработавших")
    groups: list[GroupScore]
    rules: list[RuleOutcome]
    justification: str
    justification_source: JustificationSource = JustificationSource.template


class ScoreResultOut(ScoreResultData, ORMModel):
    id: UUID
    procurement_id: UUID
    profile_id: UUID
    computed_at: datetime


class ScoreRequest(BaseModel):
    procurement_ids: list[UUID] | None = Field(
        default=None, description="None — пересчитать все закупки пользователя"
    )
