from typing import Any

from celery import Celery
from celery.signals import worker_init

from app.core.config import get_settings
from app.embeddings import service as embeddings

_s = get_settings()

celery_app = Celery("procurement", broker=_s.redis_url, backend=None, include=["app.tasks.jobs"])
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_always_eager=_s.celery_eager,
    task_eager_propagates=False,
    broker_connection_retry_on_startup=True,
)


@worker_init.connect
def preload_embedding_model(**_: Any) -> None:
    """Модель грузится до запуска процессов: первая закупка не ждёт, память общая."""
    embeddings.preload()
