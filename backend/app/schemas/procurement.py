from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import Money, ORMModel
from app.schemas.customer import CustomerProfileOut
from app.schemas.score import Recommendation, ScoreResultOut


class Law(StrEnum):
    l44 = "44"
    l223 = "223"
    l615 = "615"
    l94 = "94"
    other = "other"


class Method(StrEnum):
    auction = "auction"
    contest = "contest"
    quotation = "quotation"
    proposals = "proposals"
    single = "single"
    other = "other"


class Restriction(StrEnum):
    smp_only = "smp_only"
    national_regime = "national_regime"
    prefs_uis = "prefs_uis"
    prefs_disabled = "prefs_disabled"
    other = "other"


class ProcurementItem(BaseModel):
    name: str
    quantity: Decimal | None = None
    unit: str | None = None
    price: Money | None = None
    okpd2: str | None = None


class ProcurementData(BaseModel):
    """Один лот извещения. Выход парсера (роль 2) и формат JSON-файла на входе."""

    reg_number: str = Field(
        pattern=r"^\d+(-\d+)?$",
        description="Реестровый номер; для многолотовых — <номер>-<лот>",
    )
    lot_number: int | None = None
    law: Law | None = None
    subject: str = Field(min_length=1)
    nmck: Money
    currency: str = "RUB"
    method: Method | None = None
    method_raw: str | None = None
    customer_inn: str | None = None
    customer_name: str | None = None
    region: str | None = None
    delivery_place: str | None = None
    published_at: datetime | None = None
    application_deadline: datetime | None = None
    delivery_term_text: str | None = None
    delivery_days: int | None = None
    okpd2_codes: list[str] = Field(default_factory=list)
    items: list[ProcurementItem] = Field(default_factory=list)
    bid_security: Money | None = None
    bid_security_pct: Decimal | None = None
    contract_security: Money | None = None
    contract_security_pct: Decimal | None = None
    restrictions: list[Restriction] = Field(default_factory=list)
    source_url: str | None = None
    parsed_by: str = Field(description="adapter:<имя> | universal | llm | json")


class ProcurementSummary(ORMModel):
    """Строка списка закупок."""

    id: UUID
    reg_number: str
    law: Law | None
    subject: str
    nmck: Money
    currency: str
    method: Method | None
    method_raw: str | None
    customer_inn: str | None
    customer_name: str | None
    region: str | None
    application_deadline: datetime | None
    parsed_by: str
    updated_at: datetime


class ProcurementDetail(BaseModel):
    """Карточка закупки: все поля, заказчик, оценка по активному профилю."""

    id: UUID
    data: ProcurementData
    customer: CustomerProfileOut | None
    customer_error: str | None = Field(
        default=None, description="CUSTOMER_NOT_FOUND / EGRUL_UNAVAILABLE, если данных нет"
    )
    score: ScoreResultOut | None
    created_at: datetime
    updated_at: datetime


class ProcurementBrief(BaseModel):
    """Данные закупки для строк таблиц «Результаты» и «Сравнение»."""

    procurement_id: UUID
    reg_number: str
    subject: str
    customer_name: str | None
    nmck: Money
    currency: str
    region: str | None
    law: Law | None
    application_deadline: datetime | None


class ResultRow(ProcurementBrief):
    """Строка таблицы «Результаты». GET /results?profile_id= (по умолчанию активный)."""

    total: int | None
    recommendation: Recommendation | None
    incomplete: bool
    has_stop_factor: bool
    stale: bool = Field(
        default=False,
        description="Оценки нет или она устарела (профиль или закупка изменились) — "
        "на фронте «пересчитывается»",
    )


# ---------- Сравнение двух профилей (задача A) ----------


class ScoreBrief(BaseModel):
    total: int | None = Field(description="None — оценки по профилю ещё нет")
    recommendation: Recommendation | None
    stale: bool = False


class Change(StrEnum):
    """Изменение рекомендации от профиля A к профилю B (participate > consider > skip)."""

    better = "better"
    worse = "worse"
    same = "same"
    unknown = "unknown"  # хотя бы в одном профиле нет актуальной оценки


class CompareRow(ProcurementBrief):
    a: ScoreBrief
    b: ScoreBrief
    change: Change
    delta: int | None = Field(description="b.total − a.total; None — нет одной из оценок")
    explanation: str = Field(
        description="Почему рекомендации разные: до 3 фраз со ссылками [rule_id], "
        "по шаблонам. Пусто при change=same и одинаковом итоге"
    )


class CompareSummary(BaseModel):
    better: int
    worse: int
    same: int
    unknown: int


class CompareOut(BaseModel):
    """GET /results/compare?a=&b=. Только чтение, задачи не запускает.

    missing > 0 → фронт запускает POST /score {profile_id, only_stale: true} для A и B,
    показывает прогресс и перезапрашивает сравнение.
    """

    profile_a: UUID
    profile_b: UUID
    rows: list[CompareRow] = Field(description="Сначала изменившиеся, затем по |delta|")
    summary: CompareSummary
    missing: int = Field(description="Сколько оценок (по A и B вместе) нет или устарело")


# ---------- Загрузка по реестровому номеру (задача B) ----------

MAX_FETCH_NUMBERS = 200
# 44-ФЗ — 19 цифр, 223-ФЗ — 11 цифр, старые извещения 223-ФЗ — 18 цифр
REG_NUMBER_PATTERN = r"\d{11}|\d{18}|\d{19}"


class FetchRequest(BaseModel):
    """POST /procurements/fetch → 202 TaskCreated (kind=fetch).

    Элементы списка можно передавать как есть из поля ввода: сервер дополнительно делит их
    по пробелам, переносам, запятым и «;», убирает повторы. Номера неверного формата
    попадают в задачу строками со статусом error и кодом INVALID_REG_NUMBER.
    Все номера неверные или их нет → 400 INVALID_REG_NUMBER (details.invalid).
    Больше MAX_FETCH_NUMBERS после удаления повторов → 400 TOO_MANY_NUMBERS.
    Повторный номер обновляет существующую закупку.
    """

    numbers: list[str] = Field(min_length=1, max_length=2000)
