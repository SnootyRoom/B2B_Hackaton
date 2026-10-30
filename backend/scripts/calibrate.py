"""Калибровка скоринга: прогон tests/dataset/scenarios.yaml через парсер, движок и эмбеддинги.

Без базы и очереди: близость по смыслу считается в Python тем же способом, что и в pgvector.
Правила профилей берутся из текста через LLM один раз и кэшируются в --rules (JSON), чтобы
повторные прогоны были быстрыми и воспроизводимыми. Без ключа LLM нужен готовый --rules.

Запуск из папки backend:
    .venv/Scripts/python scripts/calibrate.py            # правила из scripts/calibrate_rules.json
    .venv/Scripts/python scripts/calibrate.py --c0 0.85 --c1 0.9 -q   # попробовать другие пороги
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.embeddings import service as embeddings
from app.llm.client import LLMClient
from app.llm.parse_profile import parse_text
from app.parsers.registry import ParseError, parse_file
from app.schemas.customer import CustomerData, CustomerStatus
from app.schemas.scoring import ScoringProfileData
from app.scoring import extract_fields, score
from app.scoring.engine import semantic_thresholds
from app.scoring.operators import SemanticThresholds

REPO = Path(__file__).resolve().parents[2]
DATASET = REPO / "tests" / "dataset"

# формат офлайн-файлов роли 5: {"egrul_status": "БАНКРОТ", "unreliable_flags": false, ...}
_RU_STATUS = {
    "ДЕЙСТВУЮЩАЯ": CustomerStatus.active,
    "АКТИВНАЯ": CustomerStatus.active,
    "БАНКРОТ": CustomerStatus.bankrupt,
    "БАНКРОТСТВО": CustomerStatus.bankrupt,
    "ЛИКВИДИРУЕТСЯ": CustomerStatus.liquidating,
    "ЛИКВИДИРОВАНА": CustomerStatus.liquidated,
    "РЕОРГАНИЗАЦИЯ": CustomerStatus.reorganizing,
}


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def load_customer(inn: str | None) -> CustomerData | None:
    if not inn:
        return None
    path = DATASET / "customers" / f"{inn}.json"
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    status = _RU_STATUS.get(str(raw.get("egrul_status", "")).upper(), CustomerStatus.unknown)
    flags = raw.get("unreliable_flags")
    return CustomerData(
        inn=inn,
        name=raw.get("name") or inn,
        status=status,
        unreliable_flags=["есть отметка"] if flags is True else list(flags or []),
    )


def profile_rules(profiles: dict[str, str], cache_path: Path) -> dict[str, ScoringProfileData]:
    cached: dict[str, dict[str, object]] = (
        json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    )
    client = LLMClient.from_env()
    out: dict[str, ScoringProfileData] = {}
    for name, text in profiles.items():
        if name not in cached or cached[name].get("text") != text:
            if not client.enabled:
                raise SystemExit(f"Нет правил для {name} в {cache_path} и не настроен LLM")
            parsed = parse_text(text, client)
            cached[name] = {"text": text, "rules": parsed.model_dump(mode="json")["rules"]}
        out[name] = ScoringProfileData.model_validate({"rules": cached[name]["rules"]})
    cache_path.write_text(json.dumps(cached, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def similarity(passage: str, query: str) -> float | None:
    p = embeddings.embed_passage(passage)
    q = embeddings.query_vector(query)
    if p is None or q is None:
        return None
    return sum(a * b for a, b in zip(p, q, strict=True))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", type=Path, default=Path(__file__).with_name("calibrate_rules.json"))
    ap.add_argument("--now", default="2026-10-31T00:00:00+00:00", help="момент расчёта")
    ap.add_argument("-v", "--verbose", action="store_true", help="правила по каждой закупке")
    ap.add_argument(
        "--c0", type=float, help="порог semantic_match: 0 баллов (по умолчанию из настроек)"
    )
    ap.add_argument("--c1", type=float, help="порог semantic_match: полный балл")
    ap.add_argument("-q", "--quiet", action="store_true", help="только итог")
    ap.add_argument(
        "--weights", help="веса групп закупка,соответствие,заказчик, например 0.3,0.5,0.2"
    )
    args = ap.parse_args()
    load_env(REPO / ".env")

    spec = yaml.safe_load((DATASET / "scenarios.yaml").read_text(encoding="utf-8"))
    profiles = profile_rules({k: v["text"] for k, v in spec["profiles"].items()}, args.rules)
    now = datetime.fromisoformat(args.now).astimezone(UTC)
    if args.weights:
        w = dict(
            zip(
                ("procurement", "fit", "customer"), map(float, args.weights.split(",")), strict=True
            )
        )
        for prof in profiles.values():
            prof.group_weights = prof.group_weights.model_copy(update=w)
    print(f"Веса групп: {next(iter(profiles.values())).group_weights.model_dump()}")
    base = semantic_thresholds()
    semantic = SemanticThresholds(args.c0 or base.c0, args.c1 or base.c1)
    print(f"Пороги semantic_match: c0={semantic.c0}, c1={semantic.c1}")

    rec_ok = range_ok = total = 0
    times: list[float] = []
    for sc in spec["scenarios"]:
        exp_rec, (lo, hi) = sc["expected_recommendation"], sc["expected_score"]
        path = REPO / sc["file"]
        try:
            lots = parse_file(path.read_bytes(), path.name)
        except ParseError as e:
            if not args.quiet:
                print(f"{sc['id']:5} {path.stem[:22]:22} пропуск: {e.code}")
            continue
        lot = lots[0] if sc.get("lot") is None else lots[int(sc["lot"]) - 1]
        t0 = time.perf_counter()
        r = score(
            profiles[sc["profile"]],
            extract_fields(lot, load_customer(lot.customer_inn), now),
            similarity,
            semantic,
        )
        times.append(time.perf_counter() - t0)
        total += 1
        hit_rec = r.recommendation == exp_rec
        hit_range = lo <= r.total <= hi
        rec_ok += hit_rec
        range_ok += hit_range
        mark = "✓" if hit_rec else "✗"
        if args.quiet:
            continue
        print(
            f"{sc['id']:5} {path.stem[:22]:22} {sc['profile'][8:22]:14} "
            f"{r.total:3}% {r.recommendation.value:11} ожид. {exp_rec:11} [{lo:>2}–{hi:>3}] {mark}"
        )
        if args.verbose or not hit_rec:
            for x in r.rules:
                if x.status == "applied" and x.kind == "weighted":
                    print(f"        {x.label[:50]:50} s={x.partial_score:.2f}")
                elif x.triggered:
                    print(f"        СТОП: {x.label}")

    if not total:
        print("Нет ни одного разобранного сценария")
        return 1
    print(
        f"\nСценариев оценено: {total} из {len(spec['scenarios'])}\n"
        f"Точность рекомендации: {rec_ok}/{total} = {rec_ok / total:.0%} (цель ≥ 80%)\n"
        f"Попадание в диапазон:  {range_ok}/{total} = {range_ok / total:.0%} (цель ≥ 70%)\n"
        f"Время оценки: макс {max(times) * 1000:.0f} мс"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
