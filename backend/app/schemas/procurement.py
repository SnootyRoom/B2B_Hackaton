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


class ResultRow(BaseModel):
    """Строка таблицы «Результаты»."""

    procurement_id: UUID
    reg_number: str
    subject: str
    customer_name: str | None
    nmck: Money
    currency: str
    region: str | None
    law: Law | None
    application_deadline: datetime | None
    total: int | None
    recommendation: Recommendation | None
    incomplete: bool
    has_stop_factor: bool
