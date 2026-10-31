"""Индекс векторов полного справочника ОКПД2 для подбора кодов профиля.

    python scripts/build_okpd2_index.py [--csv /repo/data/okpd2.csv]

Читает `okpd2.csv` (code;name), считает векторы названий моделью проекта (e5, `passage: `)
и пишет `okpd2.npy` рядом (float16, строка на код в порядке CSV). Без файла индекс считается
в памяти при первом подборе кодов — дольше, но работает.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.llm.okpd2_search import build_vectors, index_path, load_catalog  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=get_settings().okpd2_csv)
    args = ap.parse_args()
    catalog = load_catalog(args.csv)
    vectors = build_vectors(catalog)
    if vectors is None:
        print("Модель эмбеддингов не загрузилась", file=sys.stderr)
        return 1
    out = index_path(args.csv)
    np.save(out, vectors.astype(np.float16))
    print(f"{out}: {vectors.shape[0]} кодов, размерность {vectors.shape[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
