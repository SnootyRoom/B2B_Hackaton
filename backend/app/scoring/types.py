"""Схемы профиля скоринга и результата оценки.

Временно живут здесь, пока роль 1 не выложит контракты в app/schemas — затем переедут туда.
"""

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from app.scoring.catalog import (
    FIELD_CATALOG,
    LIST_VALUE_OPERATORS,
    NUMERIC_OPERATORS,
    FieldType,
    Group,
    Operator,
)

RuleValue = float | str | list[float] | list[str] | None


class RuleKind(StrEnum):
    stop = "stop"
    weighted = "weighted"


class Recommendation(StrEnum):
    participate = "participate"
    consider = "consider"
    skip = "skip"


class ScoringRule(BaseModel):
    id: str
    group: Group
    kind: RuleKind
    field: str
    operator: Operator
    value: RuleValue = None
    weight: int | None = Field(default=None, ge=1, le=3)
    soft_margin: float = Field(default=0.0, ge=0.0, le=1.0)
    label: str
    enabled: bool = True

    @model_validator(mode="after")
    def _check(self) -> "ScoringRule":
        spec = FIELD_CATALOG.get(self.field)
        if spec is None:
            raise ValueError(f"Поле «{self.field}» отсутствует в каталоге")
        if self.operator not in spec.operators:
            raise ValueError(f"Оператор «{self.operator}» недопустим для поля «{spec.label}»")
        if self.group != spec.group:
            raise ValueError(
                f"Поле «{spec.label}» относится к группе {spec.group}, а не {self.group}"
            )
        if self.kind == RuleKind.weighted and self.weight is None:
            raise ValueError("У критерия должна быть указана важность (1–3)")
        if self.kind == RuleKind.stop:
            self.weight = None

        v = self.value
        op = self.operator
        if op == Operator.is_false:
            self.value = None
        elif op == Operator.between:
            if not (
                isinstance(v, list) and len(v) == 2 and all(isinstance(x, int | float) for x in v)
            ):
                raise ValueError("Для диапазона нужны два числа")
            if v[0] > v[1]:  # type: ignore[operator]
                raise ValueError("Левая граница диапазона больше правой")
        elif op in NUMERIC_OPERATORS:
            if not isinstance(v, int | float) or isinstance(v, bool):
                raise ValueError("Значение должно быть числом")
        elif op in LIST_VALUE_OPERATORS:
            if not (isinstance(v, list) and v and all(isinstance(x, str) for x in v)):
                raise ValueError("Нужен непустой список значений")
        elif op == Operator.semantic_match and not (isinstance(v, str) and v.strip()):
            raise ValueError("Нужно описание для смыслового сравнения")
        if (
            spec.type == FieldType.text
            and op == Operator.semantic_match
            and self.kind == RuleKind.stop
        ):
            raise ValueError("Смысловое сравнение не может быть стоп-фактором")
        return self


class GroupWeights(BaseModel):
    procurement: float = Field(default=0.40, ge=0)
    fit: float = Field(default=0.35, ge=0)
    customer: float = Field(default=0.25, ge=0)

    @model_validator(mode="after")
    def _check(self) -> "GroupWeights":
        if self.procurement + self.fit + self.customer <= 0:
            raise ValueError("Сумма весов групп должна быть больше нуля")
        return self

    def of(self, group: Group) -> float:
        return float(getattr(self, group.value))


class Thresholds(BaseModel):
    participate: int = Field(default=70, ge=0, le=100)
    consider: int = Field(default=40, ge=0, le=100)

    @model_validator(mode="after")
    def _check(self) -> "Thresholds":
        if self.consider > self.participate:
            raise ValueError("Порог «рассмотреть» выше порога «участвовать»")
        return self


class SemanticThresholds(BaseModel):
    """Калибруемые пороги semantic_match: s = 0 при c ≤ c0, 1 при c ≥ c1."""

    c0: float = 0.55
    c1: float = 0.80

    @model_validator(mode="after")
    def _check(self) -> "SemanticThresholds":
        if self.c1 <= self.c0:
            raise ValueError("c1 должен быть больше c0")
        return self


class ScoringProfileData(BaseModel):
    """Содержимое ScoringProfile, нужное движку."""

    name: str = "Мой профиль"
    company_description: str | None = None
    source_text: str | None = None
    group_weights: GroupWeights = Field(default_factory=GroupWeights)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    semantic: SemanticThresholds = Field(default_factory=SemanticThresholds)
    rules: list[ScoringRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> "ScoringProfileData":
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("Идентификаторы правил повторяются")
        return self


class RuleStatus(StrEnum):
    applied = "applied"
    no_data = "no_data"
    disabled = "disabled"


class RuleResult(BaseModel):
    rule_id: str
    group: Group
    kind: RuleKind
    label: str
    status: RuleStatus
    field_value: RuleValue | bool = None
    partial: float | None = None  # s ∈ [0; 1]
    triggered: bool = False  # для стоп-факторов
    contribution: float = 0.0  # Δ_r, баллы итога
    lost: float = 0.0  # сколько баллов недобрано по сравнению с s = 1
    text: str = ""


class GroupResult(BaseModel):
    group: Group
    score: float | None  # None — группа исключена (нет применимых правил)
    weight: float  # исходный вес W_g
    effective_weight: float  # W_g' после перераспределения
    low_data: bool


class ScoreResultData(BaseModel):
    total: int
    recommendation: Recommendation
    incomplete: bool
    stop_factors: list[str]  # rule_id сработавших стоп-факторов
    groups: list[GroupResult]
    rules: list[RuleResult]
    justification: str = ""
    justification_source: str = "template"
