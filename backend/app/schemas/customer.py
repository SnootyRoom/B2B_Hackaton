from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class OrgType(StrEnum):
    legal = "legal"
    individual = "individual"


class CustomerStatus(StrEnum):
    active = "active"
    reorganizing = "reorganizing"
    liquidating = "liquidating"
    liquidated = "liquidated"
    bankrupt = "bankrupt"
    unknown = "unknown"


class CustomerSource(StrEnum):
    dadata = "dadata"
    cache = "cache"
    stale_cache = "stale_cache"
    offline = "offline"


class CustomerData(BaseModel):
    """Данные ЕГРЮЛ о заказчике. Выход модуля egrul (роль 2)."""

    inn: str = Field(pattern=r"^\d{10}(\d{2})?$")
    ogrn: str | None = None
    name: str
    org_type: OrgType | None = None
    status: CustomerStatus = CustomerStatus.unknown
    registration_date: date | None = None
    liquidation_date: date | None = None
    okved_main: str | None = None
    okved_main_name: str | None = None
    address: str | None = None
    region: str | None = None
    unreliable_flags: list[str] = Field(default_factory=list)


class CustomerProfileOut(CustomerData, ORMModel):
    fetched_at: datetime
    source: CustomerSource
