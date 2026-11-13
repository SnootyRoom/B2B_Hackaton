"""Демо-набор задачи A: ожидаемые оценки по базовому профилю и двум стратегиям.

Считает оценки тем же движком и той же моделью эмбеддингов, что и сервис, без сети и БД: закупки из
`data/demo/procurements`, заказчики из `data/customers`, базовый профиль из
`data/demo/profile.json`; «Осторожный» и «Агрессивный» строятся из него шаблонами.

    python tests/demo_check.py                    # сверить с data/demo/expected.json
    python tests/demo_check.py --write            # записать ожидаемые результаты заново
    python tests/demo_check.py --date 2026-11-20  # оценки на день показа

Оценка зависит от даты: закупка с истёкшим сроком подачи получает стоп-фактор в любом
профиле. Перед показом запустите с датой показа — истёкшие закупки будут перечислены.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "data" / "demo"
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.egrul import offline  # noqa: E402
from app.embeddings import service as embeddings  # noqa: E402
from app.parsers.registry import parse_file  # noqa: E402
from app.schemas.scoring import ScoringProfileData  # noqa: E402
from app.scoring.defaults import template_profile, with_defaults  # noqa: E402
from app.scoring.engine import score  # noqa: E402
from app.scoring.fields import extract_fields  # noqa: E402

PROFILES = ("base", "cautious", "aggressive")
LABELS = {"participate": "Участвовать", "consider": "Рассмотреть", "skip": "Пропустить"}


def profiles() -> dict[str, ScoringProfileData]:
    base = ScoringProfileData.model_validate_json((DEMO / "profile.json").read_text("utf-8"))
    base.rules = with_defaults(base.rules)
    return {
        "base": base,
        "cautious": template_profile("cautious", base),
        "aggressive": template_profile("aggressive", base),
    }


def similarity(text: str, _field_text: str, query: str) -> float | None:
    """Близость по смыслу — как в сервисе: e5, текст закупки = предмет + названия позиций."""
    a, b = embeddings.embed_passage(text), embeddings.query_vector(query)
    if a is None or b is None:
        return None
    return float(sum(x * y for x, y in zip(a, b, strict=True)))


def evaluate(now: datetime) -> dict[str, Any]:
    get_settings().customers_dir = ROOT / "data" / "customers"
    profs = profiles()
    out: dict[str, Any] = {}
    for path in sorted((DEMO / "procurements").glob("*.xml")):
        for lot in parse_file(path.read_bytes(), path.name):
            found = offline.load(lot.customer_inn) if lot.customer_inn else None
            customer = found[0] if found else None
            fields = extract_fields(lot, customer, now)
            text = " ".join([lot.subject, *(i.name for i in lot.items)])
            row: dict[str, Any] = {
                "subject": (lot.subject or "")[:80],
                "nmck": str(lot.nmck),
                "deadline": lot.application_deadline.date().isoformat()
                if lot.application_deadline
                else None,
                "customer_inn": lot.customer_inn,
                "customer_status": customer.status.value if customer else None,
                "customer_registered": customer.registration_date.isoformat()
                if customer and customer.registration_date
                else None,
            }
            for name, profile in profs.items():
                result = score(profile, fields, partial(similarity, text))
                row[name] = {
                    "total": result.total,
                    "recommendation": result.recommendation.value,
                    "stop_factors": result.stop_factors,
                }
            out[lot.reg_number] = row
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true", help="записать expected.json")
    parser.add_argument("--date", help="день показа, ГГГГ-ММ-ДД (по умолчанию сегодня)")
    args = parser.parse_args()
    now = (
        datetime.fromisoformat(args.date).replace(hour=6, tzinfo=UTC)
        if args.date
        else datetime.now(UTC)
    )
    actual = evaluate(now)

    differ = 0
    for number, row in actual.items():
        recs = [LABELS[row[p]["recommendation"]] for p in PROFILES]
        mark = "≠" if recs[1] != recs[2] else " "
        differ += recs[1] != recs[2]
        totals = " / ".join(
            f"{row[p]['total']:>3} {r:<11}" for p, r in zip(PROFILES, recs, strict=True)
        )
        expired = "  срок подачи истёк" if "stop_deadline" in row["base"]["stop_factors"] else ""
        print(f"{mark} {number:<22} {totals}{expired}")
    print(f"\nЗакупок: {len(actual)}; «Осторожный» и «Агрессивный» расходятся: {differ}")
    print("Столбцы: базовый / осторожный / агрессивный. Дата оценки:", now.date().isoformat())

    expected_path = DEMO / "expected.json"
    if args.write:
        payload = {"scored_on": now.date().isoformat(), "procurements": actual}
        expected_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print("Записано:", expected_path.relative_to(ROOT))
        return 0
    expected = json.loads(expected_path.read_text("utf-8"))["procurements"]
    changed = [
        n
        for n in sorted(set(expected) | set(actual))
        if any(
            (expected.get(n) or {}).get(p, {}).get("recommendation")
            != (actual.get(n) or {}).get(p, {}).get("recommendation")
            for p in PROFILES
        )
    ]
    if changed:
        print("\nРекомендация отличается от записанной:", ", ".join(changed))
        return 1
    print("Рекомендации совпадают с expected.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
