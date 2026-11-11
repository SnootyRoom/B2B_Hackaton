"""Устаревшие оценки и досчёт по профилю без дублей задач (задача A)."""

import uuid
from datetime import datetime

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session

from app.models import Procurement, ScoreResult, ScoringProfile, Task
from app.schemas.scoring import ScoringProfileData
from app.schemas.task import TaskKind, TaskStatus
from app.scoring.version import engine_version, profile_version

ACTIVE_STATUSES = (TaskStatus.queued, TaskStatus.processing)


def versions(profile: ScoringProfile) -> tuple[str, str]:
    data = ScoringProfileData.model_validate(profile, from_attributes=True)
    return profile_version(data), engine_version()


def _join(profile_id: uuid.UUID) -> ColumnElement[bool]:
    return and_(ScoreResult.procurement_id == Procurement.id, ScoreResult.profile_id == profile_id)


def _stale(pv: str, ev: str) -> ColumnElement[bool]:
    """Условие для Procurement OUTER JOIN ScoreResult: оценки нет или она устарела."""
    return or_(
        ScoreResult.id.is_(None),
        ScoreResult.profile_version.is_distinct_from(pv),
        ScoreResult.engine_version.is_distinct_from(ev),
        ScoreResult.computed_at < Procurement.updated_at,
    )


def is_stale(score: ScoreResult | None, procurement_updated_at: datetime, pv: str, ev: str) -> bool:
    return (
        score is None
        or score.profile_version != pv
        or score.engine_version != ev
        or score.computed_at < procurement_updated_at
    )


def stale_procurements(
    db: Session, owner_id: uuid.UUID, profile: ScoringProfile
) -> list[Procurement]:
    pv, ev = versions(profile)
    return list(
        db.scalars(
            select(Procurement)
            .outerjoin(ScoreResult, _join(profile.id))
            .where(Procurement.owner_id == owner_id, _stale(pv, ev))
        )
    )


def count_stale(db: Session, owner_id: uuid.UUID, profile: ScoringProfile) -> int:
    pv, ev = versions(profile)
    return (
        db.scalar(
            select(func.count())
            .select_from(Procurement)
            .outerjoin(ScoreResult, _join(profile.id))
            .where(Procurement.owner_id == owner_id, _stale(pv, ev))
        )
        or 0
    )


def running_rescore(db: Session, owner_id: uuid.UUID, profile_id: uuid.UUID) -> Task | None:
    return db.scalar(
        select(Task)
        .where(
            Task.owner_id == owner_id,
            Task.kind == TaskKind.rescore,
            Task.status.in_(ACTIVE_STATUSES),
            Task.params["profile_id"].astext == str(profile_id),
            Task.params["only_stale"].as_boolean().is_(True),
        )
        .order_by(Task.created_at.desc())
    )


def stale_rescore_task(
    db: Session, owner_id: uuid.UUID, profile: ScoringProfile
) -> tuple[Task | None, bool]:
    """Задача досчёта устаревших оценок профиля.

    → (уже идущая задача, False) | (новая задача, True — поставить в очередь после commit)
    | (None, False), если все оценки актуальны.
    """
    running = running_rescore(db, owner_id, profile.id)
    if running is not None:
        return running, False
    if count_stale(db, owner_id, profile) == 0:
        return None, False
    task = Task(
        owner_id=owner_id,
        kind=TaskKind.rescore,
        params={"profile_id": str(profile.id), "only_stale": True},
    )
    db.add(task)
    return task, True
