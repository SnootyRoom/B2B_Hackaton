import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

EMBEDDING_DIM = 384  # intfloat/multilingual-e5-small


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


def _owner() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))


class ScoringProfile(TimestampMixin, Base):
    __tablename__ = "scoring_profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = _owner()
    name: Mapped[str] = mapped_column(String(200))
    company_description: Mapped[str] = mapped_column(Text, default="")
    source_text: Mapped[str] = mapped_column(Text, default="")
    group_weights: Mapped[dict[str, Any]] = mapped_column(JSONB)
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSONB)
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CustomerProfile(Base):
    """Кэш ЕГРЮЛ. Общий для всех пользователей (публичные сведения)."""

    __tablename__ = "customer_profiles"

    inn: Mapped[str] = mapped_column(String(12), primary_key=True)
    ogrn: Mapped[str | None] = mapped_column(String(15))
    name: Mapped[str] = mapped_column(Text)
    org_type: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    registration_date: Mapped[date | None] = mapped_column(Date)
    liquidation_date: Mapped[date | None] = mapped_column(Date)
    okved_main: Mapped[str | None] = mapped_column(String(20))
    okved_main_name: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(String(200))
    unreliable_flags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="Исходный ответ DaData")
    source: Mapped[str] = mapped_column(String(20))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Procurement(TimestampMixin, Base):
    """Один лот извещения. Полные данные — в `data` (ProcurementData)."""

    __tablename__ = "procurements"
    __table_args__ = (UniqueConstraint("owner_id", "reg_number"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = _owner()
    reg_number: Mapped[str] = mapped_column(String(64))
    law: Mapped[str | None] = mapped_column(String(10))
    subject: Mapped[str] = mapped_column(Text)
    nmck: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    method: Mapped[str | None] = mapped_column(String(20))
    method_raw: Mapped[str | None] = mapped_column(Text)
    customer_inn: Mapped[str | None] = mapped_column(String(12), index=True)
    customer_name: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(String(200))
    application_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parsed_by: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    customer_error: Mapped[str | None] = mapped_column(String(40))
    source_file: Mapped[str | None] = mapped_column(Text, comment="Путь к исходному файлу")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))


class ScoreResult(Base):
    __tablename__ = "score_results"
    __table_args__ = (UniqueConstraint("procurement_id", "profile_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = _owner()
    procurement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("procurements.id", ondelete="CASCADE"), index=True
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scoring_profiles.id", ondelete="CASCADE"), index=True
    )
    total: Mapped[int] = mapped_column(Integer)
    recommendation: Mapped[str] = mapped_column(String(20))
    incomplete: Mapped[bool] = mapped_column(Boolean)
    stop_factors: Mapped[list[str]] = mapped_column(JSONB)
    groups: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    justification: Mapped[str] = mapped_column(Text)
    justification_source: Mapped[str] = mapped_column(String(20))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = _owner()
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[Any] = mapped_column(JSONB, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    files: Mapped[list["TaskFile"]] = relationship(
        back_populates="task", order_by="TaskFile.position", cascade="all, delete-orphan"
    )


class TaskFile(Base):
    __tablename__ = "task_files"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(Text)
    stored_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    procurement_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)

    task: Mapped[Task] = relationship(back_populates="files")

    __table_args__ = (Index("ix_task_files_task_id_position", "task_id", "position"),)


class LLMCache(Base):
    """Кэш ответов LLM по хэшу (вход + модель + версия промпта)."""

    __tablename__ = "llm_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(100))
    response: Mapped[Any] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
