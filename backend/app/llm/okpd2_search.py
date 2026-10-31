"""Шаг 1 подбора кодов ОКПД2 профиля: кандидаты по смыслу из полного справочника.

Справочник — `data/okpd2.csv` (code;name, от класса XX до вида XX.XX.XX). Векторы названий
(e5, `passage: `) считаются один раз: файл `okpd2.npy` рядом с CSV (scripts/build_okpd2_index.py),
а если его нет или он не от этого CSV — в памяти при первом обращении. Описание деятельности
ищется как `query: `. Кандидаты — группы, подгруппы и виды (XX.XX … XX.XX.XX): класс и подкласс
слишком широки для `prefix_in` и отсекаются. Услуги торговли (46, 47) тоже: в закупках товар
кодируется кодом товара, а не услугой оптовой торговли им. Шаг 2 (выбор LLM) — в parse_profile.py.
"""

import csv
import logging
from functools import lru_cache
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from app.core.config import get_settings
from app.embeddings import service as embeddings

log = logging.getLogger(__name__)

Catalog = list[tuple[str, str]]


def load_catalog(path: Path) -> Catalog:
    with path.open(encoding="utf-8", newline="") as f:
        rows = csv.DictReader(f, delimiter=";")
        return [(row["code"].strip(), row["name"].strip()) for row in rows]


def index_path(csv_path: Path) -> Path:
    return csv_path.with_suffix(".npy")


def passage_text(code: str, name: str, names: dict[str, str]) -> str:
    """Название с названием родителя: «Прочие …» без родителя по смыслу не найти."""
    parent = names.get(code.rsplit(".", 1)[0] if "." in code else "")
    return f"{name} ({parent})" if parent and parent != name else name


def build_vectors(catalog: Catalog) -> NDArray[np.float32] | None:
    names = dict(catalog)
    return embeddings.embed_passages([passage_text(c, n, names) for c, n in catalog])


TRADE_CLASSES = ("46", "47")


def is_candidate_level(code: str) -> bool:
    """Группа XX.XX, подгруппа XX.XX.X или вид XX.XX.XX, кроме услуг торговли."""
    parts = code.split(".")
    return 2 <= len(parts) <= 3 and len(parts[1]) == 2 and parts[0] not in TRADE_CLASSES


def group_code(code: str) -> str:
    """Код группы XX.XX для подгруппы и вида: prefix_in по виду пропускает свои закупки."""
    return code[:5] if len(code) > 5 else code


def okpd2_name(code: str) -> str | None:
    index = _index()
    return index[2].get(code) if index is not None else None


@lru_cache(maxsize=1)
def _index() -> tuple[Catalog, NDArray[np.float32], dict[str, str]] | None:
    path = get_settings().okpd2_csv
    if not path.exists():
        log.warning("Справочник ОКПД2 %s не найден: коды профиля — по категориям", path)
        return None
    catalog = load_catalog(path)
    vectors: NDArray[np.float32] | None = None
    npy = index_path(path)
    if npy.exists():
        loaded = np.load(npy)
        if loaded.shape[0] == len(catalog):
            vectors = loaded.astype(np.float32)
        else:
            log.warning("Индекс %s не от этого справочника: считаю заново", npy)
    if vectors is None:
        vectors = build_vectors(catalog)
        if vectors is None:
            return None
    keep = [i for i, (code, _) in enumerate(catalog) if is_candidate_level(code)]
    return [catalog[i] for i in keep], vectors[keep], dict(catalog)


def okpd2_candidates(activities: list[str], k: int) -> Catalog | None:
    """Top-k позиций справочника на каждое описание деятельности, без повторов, в порядке
    близости. None — нет справочника или модели эмбеддингов: тогда работает запасной путь."""
    index = _index()
    if index is None:
        return None
    catalog, vectors, _ = index
    found: dict[str, str] = {}
    for text in activities:
        query = embeddings.query_vector(text)
        if query is None:
            return None
        sims = vectors @ np.asarray(query, dtype=np.float32)
        for i in np.argsort(-sims)[:k]:
            code, name = catalog[int(i)]
            found.setdefault(code, name)
    return list(found.items())
