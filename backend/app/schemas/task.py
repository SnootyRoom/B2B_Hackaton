from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue

from app.schemas.common import ErrorInfo, ORMModel


class TaskKind(StrEnum):
    upload = "upload"
    rescore = "rescore"
    parse_profile = "parse_profile"
    egrul_lookup = "egrul_lookup"


class TaskStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    done = "done"
    partial = "partial"
    failed = "failed"


class FileStatus(StrEnum):
    pending = "pending"
    ok = "ok"
    error = "error"


class TaskFileOut(ORMModel):
    id: UUID
    filename: str
    status: FileStatus
    error: ErrorInfo | None = None
    warnings: list[ErrorInfo] = Field(
        default_factory=list, description="Например CUSTOMER_NOT_FOUND при статусе ok"
    )
    procurement_ids: list[UUID] = Field(default_factory=list, description="По одной на лот")


class TaskOut(ORMModel):
    id: UUID
    kind: TaskKind
    status: TaskStatus
    total: int = Field(description="M в «Обработано N из M»")
    processed: int = Field(description="N")
    files: list[TaskFileOut] = Field(default_factory=list)
    result: JsonValue = Field(
        default=None,
        description="parse_profile → ParseProfileResult, egrul_lookup → CustomerProfileOut",
    )
    error: ErrorInfo | None = None
    created_at: datetime
    finished_at: datetime | None = None


class TaskCreated(BaseModel):
    task_id: UUID
