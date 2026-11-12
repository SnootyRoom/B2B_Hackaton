import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentUser, get_active_profile, get_owned
from app.core.config import get_settings
from app.core.errors import AppError
from app.models import ScoringProfile, Task, User
from app.parsers.regions import REGIONS
from app.schemas.common import ErrorCode, ErrorResponse
from app.schemas.scoring import (
    FIELD_CATALOG,
    MAX_PROFILES,
    CreateProfileRequest,
    FieldCatalogOut,
    ParseProfileRequest,
    ProfileSummary,
    ProfileTaskResponse,
    RenameProfileRequest,
    SaveProfileRequest,
    SaveProfileResponse,
    ScoringProfileData,
    ScoringProfileOut,
)
from app.schemas.task import TaskCreated, TaskKind
from app.scoring.defaults import default_profile, template_profile
from app.tasks import staleness
from app.tasks.jobs import enqueue

router = APIRouter(prefix="/scoring-profiles", tags=["scoring-profiles"])

_ERRORS: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}
_COPY_SUFFIX = " (копия)"


# ---------- Общее


def _summary(p: ScoringProfile) -> ProfileSummary:
    return ProfileSummary(
        id=p.id,
        name=p.name,
        is_active=p.is_active,
        rules_count=len(p.rules or []),
        updated_at=p.updated_at,
    )


def _lock_user(db: Session, user: User) -> None:
    """Операции с набором профилей пользователя выполняются по очереди."""
    db.execute(select(User.id).where(User.id == user.id).with_for_update())


def _name_taken(db: Session, user: User, name: str, exclude: uuid.UUID | None = None) -> bool:
    query = select(ScoringProfile.id).where(
        ScoringProfile.owner_id == user.id, ScoringProfile.name == name
    )
    if exclude is not None:
        query = query.where(ScoringProfile.id != exclude)
    return db.scalar(query) is not None


def _name_taken_error(name: str) -> AppError:
    return AppError(
        ErrorCode.PROFILE_NAME_TAKEN, f"Профиль с именем «{name}» уже есть", 409, {"name": name}
    )


def _commit(db: Session, name: str) -> None:
    """Commit; гонка за имя, проигранная параллельному запросу, — тоже 409."""
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise _name_taken_error(name) from e


def _check_limit(db: Session, user: User) -> None:
    count = db.scalar(
        select(func.count()).select_from(ScoringProfile).where(ScoringProfile.owner_id == user.id)
    )
    if (count or 0) >= MAX_PROFILES:
        raise AppError(
            ErrorCode.TOO_MANY_PROFILES,
            f"Можно держать не больше {MAX_PROFILES} профилей — удалите ненужные",
            400,
        )


def _enqueue_new(task: Task | None, new: bool) -> uuid.UUID | None:
    if task is not None and new:
        enqueue(task)
    return task.id if task is not None else None


def _save(
    db: Session, user: User, profile: ScoringProfile, body: SaveProfileRequest
) -> SaveProfileResponse:
    if body.name != profile.name and _name_taken(db, user, body.name, profile.id):
        raise _name_taken_error(body.name)
    for key, value in body.model_dump(mode="json", exclude={"rescore"}).items():
        setattr(profile, key, value)
    task = None
    if body.rescore:
        task = Task(owner_id=user.id, kind=TaskKind.rescore, params={"profile_id": str(profile.id)})
        db.add(task)
    _commit(db, body.name)
    task_id = _enqueue_new(task, True)
    return SaveProfileResponse(profile=ScoringProfileOut.model_validate(profile), task_id=task_id)


# ---------- Маршруты без {profile_id} — первыми, иначе «active» совпадёт с {profile_id}


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
    "/active",
    response_model=SaveProfileResponse,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def save_active(body: SaveProfileRequest, db: DB, user: CurrentUser) -> SaveProfileResponse:
    return _save(db, user, get_active_profile(db, user.id), body)


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


def _template_source(db: Session, user: User, active: ScoringProfile) -> ScoringProfile:
    """От какого профиля строить шаблон: от базы активного, если он сам из шаблона и база
    ещё есть; иначе от активного."""
    if active.template_base_id is not None:
        base = db.get(ScoringProfile, active.template_base_id)
        if base is not None and base.owner_id == user.id:
            return base
    return active


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
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def create_profile(body: CreateProfileRequest, db: DB, user: CurrentUser) -> ScoringProfile:
    """Пустой (правила по умолчанию), с готовыми правилами или из шаблона. Шаблон —
    вариация базовой стратегии пользователя: активного профиля, а если он сам построен
    из шаблона — того профиля, от которого построен. Не активный."""
    active = get_active_profile(db, user.id)  # первый профиль пользователя всегда активный
    _lock_user(db, user)
    _check_limit(db, user)
    if _name_taken(db, user, body.name):
        raise _name_taken_error(body.name)
    base_id: uuid.UUID | None = None
    if body.template:
        source = _template_source(db, user, active)
        base_id = source.id
        source_data = ScoringProfileData.model_validate(source, from_attributes=True)
        base = template_profile(body.template, source_data)
    else:
        base = default_profile()
    fields = base.model_dump(mode="json", exclude_none=True)
    fields.update(body.model_dump(mode="json", exclude={"template"}, exclude_unset=True))
    data = ScoringProfileData.model_validate(fields)
    profile = ScoringProfile(
        owner_id=user.id,
        is_active=False,
        template_base_id=base_id,
        **data.model_dump(mode="json"),
    )
    db.add(profile)
    _commit(db, body.name)
    return profile


# ---------- Маршруты с {profile_id}


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
    """Правила, веса, пороги (и имя). rescore=true — «Сохранить и пересчитать»;
    без него оценки профиля становятся устаревшими (stale)."""
    return _save(db, user, get_owned(db, ScoringProfile, profile_id, user), body)


@router.patch(
    "/{profile_id}",
    response_model=ProfileSummary,
    responses={409: {"model": ErrorResponse}, **_ERRORS},
)
def rename_profile(
    profile_id: uuid.UUID, body: RenameProfileRequest, db: DB, user: CurrentUser
) -> ProfileSummary:
    """Только имя, без пересчёта. Занято → 409 PROFILE_NAME_TAKEN."""
    profile = get_owned(db, ScoringProfile, profile_id, user)
    if body.name != profile.name:
        if _name_taken(db, user, body.name, profile.id):
            raise _name_taken_error(body.name)
        profile.name = body.name
        _commit(db, body.name)
    return _summary(profile)


def _copy_name(db: Session, user: User, name: str) -> str:
    base = name[: 100 - len(_COPY_SUFFIX) - 4]
    candidate = f"{base}{_COPY_SUFFIX}"
    n = 2
    while _name_taken(db, user, candidate):
        candidate = f"{base} (копия {n})"
        n += 1
    return candidate


@router.post(
    "/{profile_id}/duplicate",
    response_model=ScoringProfileOut,
    status_code=201,
    responses={400: {"model": ErrorResponse}, **_ERRORS},
)
def duplicate_profile(profile_id: uuid.UUID, db: DB, user: CurrentUser) -> ScoringProfile:
    """Копия «<имя> (копия)», при повторе «(копия 2)». Не активная, оценки не копируются."""
    _lock_user(db, user)
    src = get_owned(db, ScoringProfile, profile_id, user)
    _check_limit(db, user)
    data = ScoringProfileData.model_validate(src, from_attributes=True)
    data.name = _copy_name(db, user, src.name)
    copy = ScoringProfile(
        owner_id=user.id,
        is_active=False,
        template_base_id=src.template_base_id,  # копия шаблона ведёт к той же базе
        **data.model_dump(mode="json"),
    )
    db.add(copy)
    _commit(db, data.name)
    return copy


@router.delete(
    "/{profile_id}",
    response_model=ProfileTaskResponse,
    responses={400: {"model": ErrorResponse}, **_ERRORS},
)
def delete_profile(profile_id: uuid.UUID, db: DB, user: CurrentUser) -> ProfileTaskResponse:
    """Последний профиль → 400 LAST_PROFILE. Удалили активный → активным становится
    недавно изменённый, task_id — досчёт его оценок; иначе task_id = null.
    Оценки удалённого профиля удаляются каскадом."""
    _lock_user(db, user)
    profile = get_owned(db, ScoringProfile, profile_id, user)
    others = list(
        db.scalars(
            select(ScoringProfile)
            .where(ScoringProfile.owner_id == user.id, ScoringProfile.id != profile.id)
            .order_by(ScoringProfile.updated_at.desc())
        )
    )
    if not others:
        raise AppError(ErrorCode.LAST_PROFILE, "Нельзя удалить единственный профиль", 400)
    was_active = profile.is_active
    db.delete(profile)
    db.flush()
    task: Task | None = None
    new = False
    if was_active:
        others[0].is_active = True
        db.flush()
        task, new = staleness.stale_rescore_task(db, user.id, others[0])
    db.commit()
    return ProfileTaskResponse(task_id=_enqueue_new(task, new))


@router.post("/{profile_id}/activate", response_model=ProfileTaskResponse, responses=_ERRORS)
def activate_profile(profile_id: uuid.UUID, db: DB, user: CurrentUser) -> ProfileTaskResponse:
    """Сделать активным (сразу, в транзакции) и досчитать устаревшие оценки.
    task_id = null — все оценки актуальны. Повторный вызов во время пересчёта
    возвращает тот же task_id."""
    _lock_user(db, user)
    profile = get_owned(db, ScoringProfile, profile_id, user)
    if not profile.is_active:
        db.execute(
            update(ScoringProfile)
            .where(ScoringProfile.owner_id == user.id, ScoringProfile.is_active.is_(True))
            .values(is_active=False)
            .execution_options(synchronize_session="fetch")
        )
        profile.is_active = True
        db.flush()
    task, new = staleness.stale_rescore_task(db, user.id, profile)
    db.commit()
    return ProfileTaskResponse(task_id=_enqueue_new(task, new))
