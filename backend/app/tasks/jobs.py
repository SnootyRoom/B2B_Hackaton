import logging
import uuid

from app.core.db import SessionLocal
from app.models import Task, utcnow
from app.schemas.common import ErrorCode
from app.schemas.task import TaskKind, TaskStatus
from app.tasks import pipeline
from app.tasks.celery_app import celery_app

log = logging.getLogger(__name__)

_HANDLERS = {
    TaskKind.upload: pipeline.process_upload,
    TaskKind.rescore: pipeline.process_rescore,
    TaskKind.parse_profile: pipeline.process_parse_profile,
    TaskKind.egrul_lookup: pipeline.process_egrul_lookup,
}


def enqueue(task: Task) -> None:
    run_task.delay(str(task.id))


@celery_app.task(name="run_task")
def run_task(task_id: str) -> None:
    with SessionLocal() as db:
        task = db.get(Task, uuid.UUID(task_id))
        if task is None:
            log.warning("task %s not found", task_id)
            return
        task.status = TaskStatus.processing
        db.commit()
        log.info("task %s: start %s", task_id, task.kind)
        try:
            _HANDLERS[TaskKind(task.kind)](db, task)
        except Exception:
            log.exception("task %s: failed", task_id)
            db.rollback()
            task.status = TaskStatus.failed
            task.error = {
                "code": ErrorCode.INTERNAL_ERROR,
                "message": "Не удалось выполнить обработку, попробуйте ещё раз",
                "details": {},
            }
        task.finished_at = utcnow()
        db.commit()
        log.info("task %s: %s", task_id, task.status)
