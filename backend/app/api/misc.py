"""Небольшие роутеры: организации, пересчёт, результаты, задачи."""

import re
import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser, get_active_profile
from app.core.errors import AppError, not_found
from app.egrul.service import get_cached
from app.models import Procurement, ScoreResult, Task
from app.schemas.common import ErrorCode, ErrorResponse
from app.schemas.customer import CustomerProfileOut
from app.schemas.procurement import ResultRow
from app.schemas.score import Recommendation, ScoreRequest
from app.schemas.task import TaskCreated, TaskKind, TaskOut
from app.tasks.jobs import enqueue

organizations = APIRouter(prefix="/organizations", tags=["organizations"])
score = APIRouter(tags=["score"])
results = APIRouter(prefix="/results", tags=["results"])
tasks = APIRouter(prefix="/tasks", tags=["tasks"])


@organizations.get(
    "/{inn}",
    response_model=CustomerProfileOut,
    responses={202: {"model": TaskCreated}, 400: {"model": ErrorResponse}},
)
def get_organization(inn: str, db: DB, user: CurrentUser) -> CustomerProfileOut | JSONResponse:
    """Из кэша или офлайн-профиля сразу; иначе 202 + task_id (запрос в ЕГРЮЛ в фоне).

    После завершения задачи egrul_lookup данные лежат в TaskOut.result.
    """
    if not re.fullmatch(r"\d{10}|\d{12}", inn):
        raise AppError(ErrorCode.VALIDATION_ERROR, "ИНН должен состоять из 10 или 12 цифр")
    cached = get_cached(db, inn)
    if cached is not None:
        return cached
    task = Task(owner_id=user.id, kind=TaskKind.egrul_lookup, params={"inn": inn})
    db.add(task)
    db.commit()
    enqueue(task)
    return JSONResponse(TaskCreated(task_id=task.id).model_dump(mode="json"), status_code=202)


@score.post("/score", response_model=TaskCreated, status_code=202)
def rescore(body: ScoreRequest, db: DB, user: CurrentUser) -> TaskCreated:
    """Пересчёт по активному профилю без повторного парсинга и запросов в ЕГРЮЛ."""
    profile = get_active_profile(db, user.id)
    params: dict[str, object] = {"profile_id": str(profile.id)}
    if body.procurement_ids is not None:
        params["procurement_ids"] = [str(i) for i in body.procurement_ids]
    task = Task(owner_id=user.id, kind=TaskKind.rescore, params=params)
    db.add(task)
    db.commit()
    enqueue(task)
    return TaskCreated(task_id=task.id)


@results.get("", response_model=list[ResultRow])
def list_results(db: DB, user: CurrentUser) -> list[ResultRow]:
    """Все закупки пользователя с оценкой по активному профилю, по убыванию оценки."""
    profile = get_active_profile(db, user.id)
    rows = db.execute(
        select(Procurement, ScoreResult)
        .outerjoin(
            ScoreResult,
            and_(
                ScoreResult.procurement_id == Procurement.id,
                ScoreResult.profile_id == profile.id,
            ),
        )
        .where(Procurement.owner_id == user.id)
        .order_by(ScoreResult.total.desc().nulls_last(), Procurement.updated_at.desc())
    ).all()
    return [
        ResultRow(
            procurement_id=p.id,
            reg_number=p.reg_number,
            subject=p.subject,
            customer_name=p.customer_name,
            nmck=p.nmck,
            currency=p.currency,
            region=p.region,
            law=p.law,
            application_deadline=p.application_deadline,
            total=s.total if s else None,
            recommendation=Recommendation(s.recommendation) if s else None,
            incomplete=s.incomplete if s else False,
            has_stop_factor=bool(s.stop_factors) if s else False,
        )
        for p, s in rows
    ]


@tasks.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: uuid.UUID, db: DB, user: CurrentUser) -> Task:
    task = db.scalar(
        select(Task)
        .options(selectinload(Task.files))
        .where(Task.id == task_id, Task.owner_id == user.id)
    )
    if task is None:
        raise not_found()
    return task
