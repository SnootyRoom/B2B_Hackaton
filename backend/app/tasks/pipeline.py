"""Фоновая обработка: файл → парсинг → ЕГРЮЛ → эмбеддинг → оценка.

Каждый файл обрабатывается независимо и коммитится отдельно: прогресс виден сразу,
ошибка в одном файле не срывает пакет.
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.egrul import service as egrul
from app.embeddings import service as embeddings
from app.llm.client import LLMError, parse_profile_text
from app.models import (
    CustomerProfile,
    Procurement,
    ScoreResult,
    ScoringProfile,
    Task,
    TaskFile,
    utcnow,
)
from app.parsers.registry import ParseError, parse_file
from app.schemas.common import ErrorCode, ErrorInfo
from app.schemas.customer import CustomerData, CustomerProfileOut
from app.schemas.procurement import ProcurementData
from app.schemas.score import ScoreResultData
from app.schemas.scoring import ScoringProfileData
from app.schemas.task import FileStatus, TaskStatus
from app.scoring.engine import Similarity, score
from app.scoring.fields import extract_fields
from app.scoring.version import engine_version, profile_version
from app.tasks import archive, staleness
from app.tasks.notice_source import FALLBACK_MESSAGE, NoticeError, get_notice

log = logging.getLogger(__name__)

CUSTOMER_MESSAGES = {
    ErrorCode.CUSTOMER_NOT_FOUND: "Заказчик не найден в ЕГРЮЛ",
    ErrorCode.EGRUL_UNAVAILABLE: "Данные о заказчике временно недоступны",
}


def _err(code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return ErrorInfo(code=code, message=message, details=details or {}).model_dump(mode="json")


def _final_status(ok: int, total: int) -> TaskStatus:
    if ok == total:
        return TaskStatus.done
    return TaskStatus.partial if ok else TaskStatus.failed


def _load_profile(db: Session, task: Task) -> tuple[ScoringProfile, ScoringProfileData]:
    profile_id = task.params.get("profile_id")
    profile: ScoringProfile | None
    if profile_id:
        profile = db.get(ScoringProfile, uuid.UUID(profile_id))
    else:
        profile = db.scalars(
            select(ScoringProfile).where(
                ScoringProfile.owner_id == task.owner_id, ScoringProfile.is_active.is_(True)
            )
        ).first()
    if profile is None or profile.owner_id != task.owner_id:
        raise RuntimeError("Нет профиля скоринга")
    data = ScoringProfileData.model_validate(profile, from_attributes=True)
    return profile, data


def _customer_data(db: Session, inn: str | None) -> CustomerData | None:
    if not inn:
        return None
    row = db.get(CustomerProfile, inn)
    return CustomerProfileOut.model_validate(row) if row else None


def run_engine(
    data: ProcurementData,
    customer: CustomerData | None,
    profile_data: ScoringProfileData,
    similarity: Similarity | None,
) -> ScoreResultData:
    """Оценка закупки движком роли 3."""
    return score(profile_data, extract_fields(data, customer, utcnow()), similarity)


def score_procurement(
    db: Session, p: Procurement, profile: ScoringProfile, profile_data: ScoringProfileData
) -> None:
    """Оценка одной закупки по профилю; результат сохраняется (upsert)."""
    data = ProcurementData.model_validate(p.data)
    # близость к тексту правила считает pgvector по сохранённому вектору закупки
    result = run_engine(
        data,
        _customer_data(db, p.customer_inn),
        profile_data,
        lambda _text, query: embeddings.similarity_in_db(db, p.id, query),
    )
    values: dict[str, Any] = {
        **result.model_dump(mode="json"),
        "profile_version": profile_version(profile_data),
        "engine_version": engine_version(),
        "computed_at": utcnow(),
    }
    # Одним запросом: две задачи (загрузка и пересчёт по тому же профилю) могут писать
    # одну пару «закупка + профиль» одновременно — «найти, потом вставить» падало бы
    # на уникальном ключе.
    stmt = pg_insert(ScoreResult).values(
        owner_id=p.owner_id, procurement_id=p.id, profile_id=profile.id, **values
    )
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=[ScoreResult.procurement_id, ScoreResult.profile_id], set_=values
        )
    )


def _upsert_procurement(
    db: Session, owner_id: uuid.UUID, data: ProcurementData, source_file: str
) -> Procurement:
    p = db.scalar(
        select(Procurement).where(
            Procurement.owner_id == owner_id, Procurement.reg_number == data.reg_number
        )
    )
    if p is None:
        p = Procurement(owner_id=owner_id, reg_number=data.reg_number)
        db.add(p)
    p.law = data.law
    p.subject = data.subject
    p.nmck = data.nmck
    p.currency = data.currency
    p.method = data.method
    p.method_raw = data.method_raw
    p.customer_inn = data.customer_inn
    p.customer_name = data.customer_name
    p.region = data.region
    p.application_deadline = data.application_deadline
    p.parsed_by = data.parsed_by
    p.data = data.model_dump(mode="json")
    p.source_file = source_file
    p.updated_at = utcnow()
    text = " ".join([data.subject, *(i.name for i in data.items)])
    p.embedding = embeddings.embed_passage(text)
    return p


@dataclass
class _Batch:
    """Общее для пакета: профиль оценки и кэш заказчиков по ИНН."""

    profile: ScoringProfile
    profile_data: ScoringProfileData
    customers: dict[str, egrul.CustomerLookup] = field(default_factory=dict)


def ingest_document(
    db: Session, owner_id: uuid.UUID, f: TaskFile, content: bytes, filename: str, batch: _Batch
) -> None:
    """Один документ → закупки: парсинг → ЕГРЮЛ → эмбеддинг → оценка.

    Общий путь для загруженного файла и для документа, полученного по реестровому номеру.
    Пишет в f статус ok, procurement_ids и предупреждения; ошибки — исключениями.
    """
    lots = parse_file(content, filename)
    ids: list[str] = []
    warnings: list[dict[str, Any]] = []
    for lot in lots:
        p = _upsert_procurement(db, owner_id, lot, f.stored_path)
        p.customer_error = None
        if lot.customer_inn:
            if lot.customer_inn not in batch.customers:
                batch.customers[lot.customer_inn] = egrul.lookup(db, lot.customer_inn)
            lookup = batch.customers[lot.customer_inn]
            if lookup.profile is not None and lot.customer_name is None:
                p.customer_name = lookup.profile.name
            err_code = lookup.error
        else:
            err_code = ErrorCode.CUSTOMER_NOT_FOUND
        if err_code is not None:
            p.customer_error = err_code
            warning = _err(err_code, CUSTOMER_MESSAGES[err_code])
            if warning not in warnings:
                warnings.append(warning)
        db.flush()
        score_procurement(db, p, batch.profile, batch.profile_data)
        ids.append(str(p.id))
    f.status = FileStatus.ok
    f.procurement_ids = ids
    f.warnings = warnings


def _process_items(
    db: Session, task: Task, handle: Callable[[TaskFile, _Batch], None], what: str
) -> None:
    """Обойти строки задачи: у каждой свой статус, ошибка одной не срывает пакет."""
    profile, profile_data = _load_profile(db, task)
    batch = _Batch(profile, profile_data)
    task.total = len(task.files)
    ok = 0
    for f in task.files:
        try:
            handle(f, batch)
            ok += 1
        except (ParseError, NoticeError) as e:
            db.rollback()
            f.status = FileStatus.error
            details = e.details if isinstance(e, ParseError) else {}
            f.error = _err(e.code, e.message, details)
        except Exception:
            log.exception("task %s: %s %s failed", task.id, what, f.filename)
            db.rollback()
            f.status = FileStatus.error
            f.error = _err(ErrorCode.INTERNAL_ERROR, f"Не удалось обработать {what}")
        task.processed += 1
        db.commit()
        log.info("task %s: %s/%s %s %s", task.id, task.processed, task.total, f.filename, f.status)
    task.status = _final_status(ok, task.total)
    _rescore_if_switched(db, task.owner_id, profile)


def process_upload(db: Session, task: Task) -> None:
    archive_errors = archive.expand_archives(db, task)

    def handle(f: TaskFile, batch: _Batch) -> None:
        if f.id in archive_errors:
            raise archive_errors[f.id]
        if not f.stored_path:
            # файл из архива оказался больше лимита и не распаковывался
            raise archive.too_large(f.filename)
        content = Path(f.stored_path).read_bytes()
        ingest_document(db, task.owner_id, f, content, f.filename, batch)

    _process_items(db, task, handle, "файл")


def process_fetch(db: Session, task: Task) -> None:
    """Реестровые номера: XML из ЕИС (или из образцов) → тот же путь, что у файла."""
    task_dir = get_settings().upload_dir / str(task.id)

    def handle(f: TaskFile, batch: _Batch) -> None:
        notice = get_notice(f.filename)
        task_dir.mkdir(parents=True, exist_ok=True)
        path = task_dir / f"{f.position:04d}_{f.filename}.xml"
        path.write_bytes(notice.content)
        f.stored_path = str(path)
        ingest_document(db, task.owner_id, f, notice.content, path.name, batch)
        if notice.source == "sample":
            f.warnings = [*f.warnings, _err(ErrorCode.EIS_FALLBACK_SAMPLE, FALLBACK_MESSAGE)]

    _process_items(db, task, handle, "номер")


def _rescore_if_switched(db: Session, owner_id: uuid.UUID, used: ScoringProfile) -> None:
    """Активный профиль сменили во время загрузки — новые закупки досчитать по нему."""
    active = db.scalar(
        select(ScoringProfile).where(
            ScoringProfile.owner_id == owner_id, ScoringProfile.is_active.is_(True)
        )
    )
    if active is None or active.id == used.id:
        return
    task, new = staleness.stale_rescore_task(db, owner_id, active)
    db.commit()
    if task is not None and new:
        from app.tasks.jobs import enqueue  # jobs импортирует pipeline

        enqueue(task)


def process_rescore(db: Session, task: Task) -> None:
    profile, profile_data = _load_profile(db, task)
    if task.params.get("only_stale"):
        procurements = staleness.stale_procurements(db, task.owner_id, profile)
    else:
        procurements = list(
            db.scalars(select(Procurement).where(Procurement.owner_id == task.owner_id))
        )
    if ids := task.params.get("procurement_ids"):
        wanted = set(ids)
        procurements = [p for p in procurements if str(p.id) in wanted]
    task.total = len(procurements)
    db.commit()
    ok = 0
    for p in procurements:
        try:
            score_procurement(db, p, profile, profile_data)
            ok += 1
        except Exception:
            log.exception("task %s: rescore %s failed", task.id, p.id)
            db.rollback()
        task.processed += 1
        db.commit()
    task.status = _final_status(ok, task.total)


def process_parse_profile(db: Session, task: Task) -> None:
    try:
        result = parse_profile_text(db, task.params["text"])
    except LLMError as e:
        task.status = TaskStatus.failed
        task.error = _err(e.code, e.message)
        return
    task.result = result.model_dump(mode="json")
    task.total = task.processed = 1
    task.status = TaskStatus.done


def process_egrul_lookup(db: Session, task: Task) -> None:
    inn = task.params["inn"]
    lookup = egrul.lookup(db, inn)
    task.total = task.processed = 1
    if lookup.profile is None:
        code = lookup.error or ErrorCode.EGRUL_UNAVAILABLE
        task.status = TaskStatus.failed
        task.error = _err(code, CUSTOMER_MESSAGES.get(code, "Данные о заказчике недоступны"))
        return
    task.result = lookup.profile.model_dump(mode="json")
    task.status = TaskStatus.done
