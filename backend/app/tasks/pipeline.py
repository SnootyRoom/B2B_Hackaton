"""Фоновая обработка: файл → парсинг → ЕГРЮЛ → эмбеддинг → оценка.

Каждый файл обрабатывается независимо и коммитится отдельно: прогресс виден сразу,
ошибка в одном файле не срывает пакет.
"""

import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.egrul import service as egrul
from app.embeddings import service as embeddings
from app.llm.client import LLMError, parse_profile_text
from app.models import CustomerProfile, Procurement, ScoreResult, ScoringProfile, Task, utcnow
from app.parsers.registry import ParseError, parse_file
from app.schemas.common import ErrorCode, ErrorInfo
from app.schemas.customer import CustomerData, CustomerProfileOut
from app.schemas.procurement import ProcurementData
from app.schemas.score import ScoreResultData
from app.schemas.scoring import ScoringProfileData
from app.schemas.task import FileStatus, TaskStatus
from app.scoring import types as scoring_types
from app.scoring.engine import score
from app.scoring.fields import extract_fields

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
            select(ScoringProfile)
            .where(ScoringProfile.owner_id == task.owner_id, ScoringProfile.is_active.is_(True))
            .order_by(ScoringProfile.updated_at.desc())
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
    vec: list[float] | None,
) -> ScoreResultData:
    """Мост между контрактами (app.schemas) и типами движка роли 3 (app.scoring.types)."""
    s = get_settings()
    engine_profile = scoring_types.ScoringProfileData.model_validate(
        {
            **profile_data.model_dump(mode="json", exclude_none=True),
            "semantic": {"c0": s.semantic_c0, "c1": s.semantic_c1},
        }
    )
    result = score(
        engine_profile,
        extract_fields(data, customer, utcnow()),
        similarity=lambda _text, query: embeddings.similarity(vec, query),
    )
    rules = {r.id: r for r in profile_data.rules}
    out = result.model_dump(mode="json")
    for r in out["rules"]:
        rule = rules[r["rule_id"]]
        r["field"] = rule.field
        r["operator"] = rule.operator
        r["partial_score"] = r.pop("partial")
    return ScoreResultData.model_validate(out)


def score_procurement(
    db: Session, p: Procurement, profile: ScoringProfile, profile_data: ScoringProfileData
) -> None:
    """Оценка одной закупки по профилю; результат сохраняется (upsert)."""
    data = ProcurementData.model_validate(p.data)
    vec = list(p.embedding) if p.embedding is not None else None
    result = run_engine(data, _customer_data(db, p.customer_inn), profile_data, vec)
    row = db.scalar(
        select(ScoreResult).where(
            ScoreResult.procurement_id == p.id, ScoreResult.profile_id == profile.id
        )
    )
    if row is None:
        row = ScoreResult(owner_id=p.owner_id, procurement_id=p.id, profile_id=profile.id)
        db.add(row)
    for key, value in result.model_dump(mode="json").items():
        setattr(row, key, value)
    row.computed_at = utcnow()


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


def process_upload(db: Session, task: Task) -> None:
    profile, profile_data = _load_profile(db, task)
    task.total = len(task.files)
    customers: dict[str, egrul.CustomerLookup] = {}
    ok = 0
    for f in task.files:
        try:
            lots = parse_file(Path(f.stored_path).read_bytes(), f.filename)
            ids, warnings = [], []
            for lot in lots:
                p = _upsert_procurement(db, task.owner_id, lot, f.stored_path)
                p.customer_error = None
                if lot.customer_inn:
                    if lot.customer_inn not in customers:
                        customers[lot.customer_inn] = egrul.lookup(db, lot.customer_inn)
                    lookup = customers[lot.customer_inn]
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
                score_procurement(db, p, profile, profile_data)
                ids.append(str(p.id))
            f.status = FileStatus.ok
            f.procurement_ids = ids
            f.warnings = warnings
            ok += 1
        except ParseError as e:
            db.rollback()
            f.status = FileStatus.error
            f.error = _err(e.code, e.message, e.details)
        except Exception:
            log.exception("task %s: file %s failed", task.id, f.filename)
            db.rollback()
            f.status = FileStatus.error
            f.error = _err(ErrorCode.INTERNAL_ERROR, "Не удалось обработать файл")
        task.processed += 1
        db.commit()
        log.info("task %s: %s/%s %s %s", task.id, task.processed, task.total, f.filename, f.status)
    task.status = _final_status(ok, task.total)


def process_rescore(db: Session, task: Task) -> None:
    profile, profile_data = _load_profile(db, task)
    query = select(Procurement).where(Procurement.owner_id == task.owner_id)
    if ids := task.params.get("procurement_ids"):
        query = query.where(Procurement.id.in_([uuid.UUID(i) for i in ids]))
    procurements = list(db.scalars(query))
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
