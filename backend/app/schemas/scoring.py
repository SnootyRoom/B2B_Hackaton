from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import Money, ORMModel


class RuleGroup(StrEnum):
    procurement = "procurement"
    fit = "fit"
    customer = "customer"


class RuleKind(StrEnum):
    stop = "stop"
    weighted = "weighted"


class Operator(StrEnum):
    between = "between"
    gte = "gte"
    lte = "lte"
    in_ = "in"
    not_in = "not_in"
    any_in = "any_in"
    none_in = "none_in"
    prefix_in = "prefix_in"
    is_false = "is_false"
    semantic_match = "semantic_match"
    contains_any = "contains_any"


class FieldType(StrEnum):
    number = "number"
    money = "money"
    enum = "enum"
    list = "list"
    text = "text"
    bool = "bool"


class FieldSpec(BaseModel):
    field: str
    label: str = Field(description="Человеческое название для интерфейса")
    group: RuleGroup
    type: FieldType
    unit: str | None = None
    operators: list[Operator]
    options: list[str] | None = Field(default=None, description="Допустимые значения enum")


_NUM = [Operator.gte, Operator.lte, Operator.between]
_LIST_OPS = {
    Operator.in_,
    Operator.not_in,
    Operator.any_in,
    Operator.none_in,
    Operator.prefix_in,
    Operator.contains_any,
}


def _spec(
    field: str,
    label: str,
    group: RuleGroup,
    type_: FieldType,
    operators: list[Operator],
    unit: str | None = None,
    options: list[str] | None = None,
) -> FieldSpec:
    return FieldSpec(
        field=field,
        label=label,
        group=group,
        type=type_,
        unit=unit,
        operators=operators,
        options=options,
    )


_P, _F, _C = RuleGroup.procurement, RuleGroup.fit, RuleGroup.customer

# Каталог полей правил (аналитика, «Каталог полей для правил»).
# Новый критерий = строка здесь + оператор в движке + шаблонная фраза + тест.
FIELD_CATALOG: dict[str, FieldSpec] = {
    s.field: s
    for s in [
        _spec("nmck", "НМЦК", _P, FieldType.money, _NUM, unit="₽"),
        _spec(
            "method",
            "Способ закупки",
            _P,
            FieldType.enum,
            [Operator.in_, Operator.not_in],
            options=["auction", "contest", "quotation", "proposals", "single", "other"],
        ),
        _spec(
            "law",
            "Закон",
            _P,
            FieldType.enum,
            [Operator.in_],
            options=["44", "223", "615", "94", "other"],
        ),
        _spec("region", "Регион поставки", _P, FieldType.enum, [Operator.in_, Operator.not_in]),
        _spec(
            "days_to_deadline",
            "Дней до окончания подачи заявок",
            _P,
            FieldType.number,
            _NUM,
            unit="дн.",
        ),
        _spec("delivery_days", "Срок поставки", _P, FieldType.number, _NUM, unit="дн."),
        _spec(
            "bid_security_pct",
            "Обеспечение заявки",
            _P,
            FieldType.number,
            [Operator.lte],
            unit="% НМЦК",
        ),
        _spec(
            "contract_security_pct",
            "Обеспечение контракта",
            _P,
            FieldType.number,
            [Operator.lte],
            unit="% НМЦК",
        ),
        _spec(
            "restrictions",
            "Ограничения и преимущества",
            _P,
            FieldType.list,
            [Operator.any_in, Operator.none_in],
            options=["smp_only", "national_regime", "prefs_uis", "prefs_disabled", "other"],
        ),
        _spec("okpd2_codes", "Коды ОКПД2", _F, FieldType.list, [Operator.prefix_in]),
        _spec(
            "subject",
            "Предмет закупки",
            _F,
            FieldType.text,
            [Operator.semantic_match, Operator.contains_any],
        ),
        _spec(
            "items_coverage",
            "Доля подходящих позиций",
            _F,
            FieldType.number,
            [Operator.gte, Operator.lte],
        ),
        _spec(
            "customer.status",
            "Статус заказчика",
            _C,
            FieldType.enum,
            [Operator.in_, Operator.not_in],
            options=["active", "reorganizing", "liquidating", "liquidated", "bankrupt", "unknown"],
        ),
        _spec(
            "customer.age_years",
            "Возраст заказчика",
            _C,
            FieldType.number,
            [Operator.gte, Operator.between],
            unit="лет",
        ),
        _spec(
            "customer.has_unreliable_flags",
            "Отметки о недостоверности",
            _C,
            FieldType.bool,
            [Operator.is_false],
        ),
        _spec("customer.region", "Регион заказчика", _C, FieldType.enum, [Operator.in_]),
    ]
}

RuleValue = Money | bool | str | list[Money] | list[str] | None


class ScoringRule(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    group: RuleGroup
    kind: RuleKind
    field: str
    operator: Operator
    value: RuleValue = None
    weight: Literal[1, 2, 3] | None = Field(
        default=None, description="1/2/3 = низкая/средняя/высокая; у стоп-факторов нет"
    )
    soft_margin: float | None = Field(default=None, ge=0, le=1)
    label: str
    enabled: bool = True

    @model_validator(mode="after")
    def _check(self) -> Self:
        spec = FIELD_CATALOG.get(self.field)
        if spec is None:
            raise ValueError(f"Поле «{self.field}» отсутствует в каталоге")
        if self.operator not in spec.operators:
            raise ValueError(f"Условие {self.operator} недопустимо для поля «{spec.label}»")
        if self.group != spec.group:
            raise ValueError(f"Поле «{spec.label}» относится к группе {spec.group}")
        if self.kind == RuleKind.weighted and self.weight is None:
            raise ValueError("У критерия должна быть задана важность")
        if self.kind == RuleKind.stop:
            self.weight = None
        _check_value(self.operator, self.value, spec)
        return self


def _check_value(op: Operator, v: RuleValue, spec: FieldSpec) -> None:
    if op == Operator.between:
        if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, Decimal) for x in v)):
            raise ValueError("Для диапазона нужны два числа")
        lo, hi = v
        assert isinstance(lo, Decimal) and isinstance(hi, Decimal)
        if lo > hi:
            raise ValueError("Левая граница диапазона больше правой")
    elif op in (Operator.gte, Operator.lte):
        if not isinstance(v, Decimal):
            raise ValueError("Нужно число")
    elif op in _LIST_OPS:
        if not (isinstance(v, list) and v and all(isinstance(x, str) for x in v)):
            raise ValueError("Нужен непустой список значений")
        if spec.options is not None and any(x not in spec.options for x in v):
            raise ValueError(f"Недопустимое значение для поля «{spec.label}»")
    elif op == Operator.semantic_match:
        if not (isinstance(v, str) and v.strip()):
            raise ValueError("Нужно описание текстом")
    elif op == Operator.is_false and v is not None:
        raise ValueError("У этого условия нет значения")


class GroupWeights(BaseModel):
    procurement: float = Field(default=0.40, ge=0)
    fit: float = Field(default=0.35, ge=0)
    customer: float = Field(default=0.25, ge=0)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.procurement + self.fit + self.customer <= 0:
            raise ValueError("Сумма весов групп должна быть больше нуля")
        return self


class Thresholds(BaseModel):
    participate: int = Field(default=70, ge=0, le=100)
    consider: int = Field(default=40, ge=0, le=100)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.consider > self.participate:
            raise ValueError("Порог «рассмотреть» выше порога «участвовать»")
        return self


class ScoringProfileData(BaseModel):
    """Профиль скоринга: вход движка и тело PUT /scoring-profiles/active."""

    name: str = "Мой профиль"
    company_description: str = ""
    source_text: str = ""
    group_weights: GroupWeights = Field(default_factory=GroupWeights)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    rules: list[ScoringRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("Идентификаторы правил повторяются")
        return self


class ScoringProfileOut(ScoringProfileData, ORMModel):
    id: UUID
    is_active: bool
    updated_at: datetime


class SaveProfileRequest(ScoringProfileData):
    rescore: bool = Field(default=False, description="«Сохранить и пересчитать»")


class SaveProfileResponse(BaseModel):
    profile: ScoringProfileOut
    task_id: UUID | None = Field(default=None, description="Задача пересчёта, если rescore=true")


class ParseProfileRequest(BaseModel):
    text: str = Field(min_length=3, max_length=5000)


class ParseProfileResult(BaseModel):
    """Результат задачи parse_profile (лежит в TaskOut.result)."""

    rules: list[ScoringRule]
    company_description: str
    unparsed: list[str]


class FieldCatalogOut(BaseModel):
    fields: list[FieldSpec]
    regions: list[str]
    llm_enabled: bool = Field(description="false → кнопку «Разобрать» скрыть")
