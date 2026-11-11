import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, get_active_profile, get_owned
from app.core.config import get_settings
from app.core.errors import AppError, not_implemented
from app.models import ScoringProfile, Task
from app.parsers.regions import REGIONS
from app.schemas.common import ErrorCode, ErrorResponse
from app.schemas.scoring import (
    FIELD_CATALOG,
    CreateProfileRequest,
    FieldCatalogOut,
    ParseProfileRequest,
    ProfileSummary,
    ProfileTaskResponse,
    RenameProfileRequest,
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


# ---------- Несколько профилей (задача A). Маршруты с {profile_id} — после /active, /catalog,
# /parse, иначе FastAPI сопоставит «active» с {profile_id}.

_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse},
    501: {"model": ErrorResponse},
}


def _summary(p: ScoringProfile) -> ProfileSummary:
    return ProfileSummary(
        id=p.id,
        name=p.name,
        is_active=p.is_active,
        rules_count=len(p.rules or []),
        updated_at=p.updated_at,
    )


@router.get("", response_model=list[ProfileSummary])
def list_profiles(db: DB, user: CurrentUser) -> list[ProfileSummary]:
    """Профили пользователя: активный первым, затем недавно изменённые."""
    get_active_profile(db, user.id)  # новый пользователь получает профиль по умолчанию
    rows = db.scalars(
        select(ScoringProfile)
        .where(ScoringProfile.owner_id == user.id)
        .order_by(ScoringProfile.is_active.desc(), ScoringProfile.updated_at.desc())
    )
    return [_summary(p) for p in rows]


@router.post(
    "",
    response_model=ScoringProfileOut,
    status_code=201,
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, **_ERRORS},
)
def create_profile(body: CreateProfileRequest, db: DB, user: CurrentUser) -> ScoringProfile:
    """Пустой (правила по умолчанию), из шаблона или с готовыми правилами. Не активный."""
    raise not_implemented()


@router.get("/{profile_id}", response_model=ScoringProfileOut, responses=_ERRORS)
def get_profile(profile_id: uuid.UUID, db: DB, user: CurrentUser) -> ScoringProfile:
    return get_owned(db, ScoringProfile, profile_id, user)


@router.put(
    "/{profile_id}",
    response_model=SaveProfileResponse,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, **_ERRORS},
)
def save_profile(
    profile_id: uuid.UUID, body: SaveProfileRequest, db: DB, user: CurrentUser
) -> SaveProfileResponse:
    """Правила, веса, пороги. rescore=true имеет смысл только для активного профиля;
    у неактивного оценки просто становятся устаревшими (stale)."""
    raise not_implemented()


@router.patch(
    "/{profile_id}",
    response_model=ProfileSummary,
    responses={409: {"model": ErrorResponse}, **_ERRORS},
)
def rename_profile(
    profile_id: uuid.UUID, body: RenameProfileRequest, db: DB, user: CurrentUser
) -> ProfileSummary:
    """Только имя, без пересчёта. Занято → 409 PROFILE_NAME_TAKEN."""
    raise not_implemented()


@router.post(
    "/{profile_id}/duplicate",
    response_model=ScoringProfileOut,
    status_code=201,
    responses={400: {"model": ErrorResponse}, **_ERRORS},
)
def duplicate_profile(profile_id: uuid.UUID, db: DB, user: CurrentUser) -> ScoringProfile:
    """Копия «<имя> (копия)», при повторе «(копия 2)». Не активная, оценки не копируются."""
    raise not_implemented()


@router.delete(
    "/{profile_id}",
    response_model=ProfileTaskResponse,
    responses={400: {"model": ErrorResponse}, **_ERRORS},
)
def delete_profile(profile_id: uuid.UUID, db: DB, user: CurrentUser) -> ProfileTaskResponse:
    """Последний профиль → 400 LAST_PROFILE. Удалили активный → активным становится
    недавно изменённый, task_id — его пересчёт; иначе task_id = null."""
    raise not_implemented()


@router.post("/{profile_id}/activate", response_model=ProfileTaskResponse, responses=_ERRORS)
def activate_profile(profile_id: uuid.UUID, db: DB, user: CurrentUser) -> ProfileTaskResponse:
    """Сделать активным (сразу, в транзакции) и досчитать устаревшие оценки.
    task_id = null — все оценки актуальны. Повторный вызов во время пересчёта
    возвращает тот же task_id."""
    raise not_implemented()
