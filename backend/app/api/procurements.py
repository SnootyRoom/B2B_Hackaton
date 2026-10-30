import re
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, get_active_profile, get_owned
from app.core.config import get_settings
from app.core.errors import AppError
from app.models import CustomerProfile, Procurement, ScoreResult, Task, TaskFile
from app.schemas.common import ErrorCode, ErrorResponse
from app.schemas.customer import CustomerProfileOut
from app.schemas.procurement import ProcurementData, ProcurementDetail, ProcurementSummary
from app.schemas.score import ScoreResultOut
from app.schemas.task import TaskCreated, TaskKind
from app.tasks.jobs import enqueue

router = APIRouter(prefix="/procurements", tags=["procurements"])

ALLOWED_EXTENSIONS = {".xml", ".json"}  # .zip — P1
_CHUNK = 1024 * 1024


def _safe_name(name: str) -> str:
    stem = Path(name).name
    return re.sub(r"[^\w.\-]+", "_", stem)[:150] or "file"


@router.post(
    "/upload",
    response_model=TaskCreated,
    status_code=202,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}},
)
def upload(files: list[UploadFile], db: DB, user: CurrentUser) -> TaskCreated:
    """Принимает файлы и сразу возвращает task_id; разбор — в фоне."""
    s = get_settings()
    if not files:
        raise AppError(ErrorCode.NO_FILES, "Выберите файлы для загрузки")
    if len(files) > s.upload_max_files:
        raise AppError(
            ErrorCode.TOO_MANY_FILES,
            f"Можно загрузить не больше {s.upload_max_files} файлов за раз",
            413,
        )
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise AppError(
                ErrorCode.UNSUPPORTED_FORMAT,
                f"Файл {f.filename} не похож на выгрузку из ЕИС (нужен .xml или .json)",
                details={"filename": f.filename},
            )

    task = Task(owner_id=user.id, kind=TaskKind.upload, total=len(files))
    db.add(task)
    db.flush()
    task_dir = s.upload_dir / str(task.id)
    task_dir.mkdir(parents=True, exist_ok=True)
    limit = s.upload_max_file_mb * 1024 * 1024
    for pos, f in enumerate(files):
        name = f.filename or f"file{pos}"
        path = task_dir / f"{pos:04d}_{_safe_name(name)}"
        size = 0
        with path.open("wb") as out:
            while chunk := f.file.read(_CHUNK):
                size += len(chunk)
                if size > limit:
                    raise AppError(
                        ErrorCode.FILE_TOO_LARGE,
                        f"Файл {name} больше {s.upload_max_file_mb} МБ",
                        413,
                        {"filename": name},
                    )
                out.write(chunk)
        db.add(TaskFile(task_id=task.id, position=pos, filename=name, stored_path=str(path)))
    db.commit()
    enqueue(task)
    return TaskCreated(task_id=task.id)


@router.get("", response_model=list[ProcurementSummary])
def list_procurements(db: DB, user: CurrentUser) -> list[Procurement]:
    return list(
        db.scalars(
            select(Procurement)
            .where(Procurement.owner_id == user.id)
            .order_by(Procurement.updated_at.desc())
        )
    )


@router.get("/{procurement_id}", response_model=ProcurementDetail)
def get_procurement(procurement_id: uuid.UUID, db: DB, user: CurrentUser) -> ProcurementDetail:
    p = get_owned(db, Procurement, procurement_id, user)
    profile = get_active_profile(db, user.id)
    customer = db.get(CustomerProfile, p.customer_inn) if p.customer_inn else None
    score = db.scalar(
        select(ScoreResult).where(
            ScoreResult.procurement_id == p.id, ScoreResult.profile_id == profile.id
        )
    )
    return ProcurementDetail(
        id=p.id,
        data=ProcurementData.model_validate(p.data),
        customer=CustomerProfileOut.model_validate(customer) if customer else None,
        customer_error=p.customer_error,
        score=ScoreResultOut.model_validate(score) if score else None,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )
