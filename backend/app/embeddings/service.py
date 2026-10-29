"""Эмбеддинги e5 (роль 3).

Контракт для конвейера:
- `embed_passage(text) -> list[float] | None` — вектор текста закупки (префикс `passage: `),
  хранится в `procurements.embedding`.
- `similarity(passage_vec, query) -> float | None` — косинусная близость к тексту правила
  (префикс `query: `). None — модель недоступна.
"""

MODEL_NAME = "intfloat/multilingual-e5-small"


def embed_passage(text: str) -> list[float] | None:
    # TODO(роль 3): sentence-transformers, модель уже скачана в образ при сборке.
    return None


def similarity(passage_vec: list[float] | None, query: str) -> float | None:
    # TODO(роль 3)
    return None
