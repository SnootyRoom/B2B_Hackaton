from fastapi import APIRouter

from app.api.deps import DB, CurrentUser, get_active_profile
from app.core.config import get_settings
from app.core.errors import AppError
from app.models import ScoringProfile, Task
from app.parsers.regions import REGIONS
from app.schemas.common import ErrorCode, ErrorResponse
from app.schemas.scoring import (
    FIELD_CATALOG,
    FieldCatalogOut,
    ParseProfileRequest,
    SaveProfileRequest,
    SaveProfileResponse,
    ScoringProfileOut,
)
from app.schemas.task import TaskCreated, TaskKind
from app.tasks.jobs import enqueue

router = APIRouter(prefix="/scoring-profiles", tags=["scoring-profiles"])


@router.get("/catalog", response_model=FieldCatalogOut)
def catalog(_: CurrentUser) -> FieldCatalogOut:
    """Поля для «Добавить правило», справочник регионов, доступность разбора текстом."""
    return FieldCatalogOut(
        fields=list(FIELD_CATALOG.values()),
        regions=REGIONS,
        llm_enabled=get_settings().llm_enabled,
    )


@router.get("/active", response_model=ScoringProfileOut)
def get_active(db: DB, user: CurrentUser) -> ScoringProfile:
    return get_active_profile(db, user.id)


@router.put(
    "/active", response_model=SaveProfileResponse, responses={422: {"model": ErrorResponse}}
)
def save_active(body: SaveProfileRequest, db: DB, user: CurrentUser) -> SaveProfileResponse:
    profile = get_active_profile(db, user.id)
    for key, value in body.model_dump(mode="json", exclude={"rescore"}).items():
        setattr(profile, key, value)
    task_id = None
    if body.rescore:
        task = Task(owner_id=user.id, kind=TaskKind.rescore, params={"profile_id": str(profile.id)})
        db.add(task)
        db.commit()
        enqueue(task)
        task_id = task.id
    else:
        db.commit()
    return SaveProfileResponse(profile=ScoringProfileOut.model_validate(profile), task_id=task_id)


@router.post(
    "/parse",
    response_model=TaskCreated,
    status_code=202,
    responses={400: {"model": ErrorResponse}},
)
def parse_text(body: ParseProfileRequest, db: DB, user: CurrentUser) -> TaskCreated:
    """Текст → черновик правил. Результат — в TaskOut.result (ParseProfileResult)."""
    if not get_settings().llm_enabled:
        raise AppError(
            ErrorCode.LLM_UNAVAILABLE, "Разбор текста недоступен, задайте правила вручную"
        )
    task = Task(owner_id=user.id, kind=TaskKind.parse_profile, params={"text": body.text})
    db.add(task)
    db.commit()
    enqueue(task)
    return TaskCreated(task_id=task.id)
