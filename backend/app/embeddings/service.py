"""Эмбеддинги e5 (роль 3).

Контракт для конвейера:
- `embed_passage(text) -> list[float] | None` — вектор текста закупки (префикс `passage: `),
  хранится в `procurements.embedding`.
- `similarity_in_db(db, procurement_id, query) -> float | None` — косинусная близость вектора
  закупки к тексту правила (префикс `query: `). Считает PostgreSQL: оператор pgvector `<=>`.
  None — у закупки нет вектора или модель недоступна.

Модель скачивается в образ при сборке; без неё правила semantic_match получают «нет данных».
"""

import logging
import uuid
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Procurement

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)

MODEL_NAME = "intfloat/multilingual-e5-small"
MAX_QUERY_CACHE = 1024


@lru_cache(maxsize=1)
def _model() -> "SentenceTransformer | None":
    try:
        # импорт здесь: torch грузится только при первом обращении к модели
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(MODEL_NAME, device="cpu")
    except Exception:
        log.exception("Модель эмбеддингов %s не загрузилась", MODEL_NAME)
        return None


def _encode(text: str) -> list[float] | None:
    model = _model()
    if model is None:
        return None
    vecs = model.encode([text], normalize_embeddings=True, convert_to_numpy=True)
    return [float(x) for x in vecs[0]]


def embed_passage(text: str) -> list[float] | None:
    text = " ".join(text.split())
    return _encode(f"passage: {text}") if text else None


def embed_passages(texts: list[str]) -> "NDArray[np.float32] | None":
    """Векторы многих текстов за раз (справочники), строка на текст, нормированы."""
    model = _model()
    if model is None:
        return None
    vecs = model.encode(
        [f"passage: {' '.join(t.split())}" for t in texts],
        normalize_embeddings=True,
        convert_to_numpy=True,
        batch_size=64,
    )
    return np.asarray(vecs, dtype=np.float32)


@lru_cache(maxsize=MAX_QUERY_CACHE)
def _query_vec(query: str) -> tuple[float, ...] | None:
    vec = _encode(f"query: {' '.join(query.split())}")
    return tuple(vec) if vec is not None else None


def query_vector(query: str) -> list[float] | None:
    """Вектор текста правила; одинаковые тексты считаются один раз."""
    if not query.strip():
        return None
    q = _query_vec(query)
    return list(q) if q is not None else None


def similarity_in_db(db: Session, procurement_id: uuid.UUID, query: str) -> float | None:
    q = query_vector(query)
    if q is None:
        return None
    # cosine_distance — оператор pgvector <=>; близость = 1 − расстояние
    distance = db.scalar(
        select(Procurement.embedding.cosine_distance(q)).where(Procurement.id == procurement_id)
    )
    return None if distance is None else 1.0 - float(distance)
