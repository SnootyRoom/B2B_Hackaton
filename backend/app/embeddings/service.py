"""Эмбеддинги e5 (роль 3).

Контракт для конвейера:
- `embed_passage(text) -> list[float] | None` — вектор текста закупки (префикс `passage: `),
  хранится в `procurements.embedding`.
- `similarity(passage_vec, query) -> float | None` — косинусная близость к тексту правила
  (префикс `query: `). None — модель недоступна.

Модель скачивается в образ при сборке; без неё правила semantic_match получают «нет данных».
Векторы нормированы, поэтому косинусная близость = скалярное произведение.
"""

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

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


@lru_cache(maxsize=MAX_QUERY_CACHE)
def _query_vec(query: str) -> tuple[float, ...] | None:
    vec = _encode(f"query: {' '.join(query.split())}")
    return tuple(vec) if vec is not None else None


def similarity(passage_vec: list[float] | None, query: str) -> float | None:
    if passage_vec is None or not query.strip():
        return None
    q = _query_vec(query)
    if q is None or len(q) != len(passage_vec):
        return None
    return sum(a * b for a, b in zip(passage_vec, q, strict=True))
