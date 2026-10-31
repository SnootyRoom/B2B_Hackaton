# -*- coding: utf-8 -*-

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# Настраиваем UTF-8 для консоли Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
DATASET_EVALUATOR = ROOT / "tests" / "dataset" / "evaluate.py"
RESULTS_FILE = ROOT / "tests" / "evaluation_results.json"


def main():
    # Дополнительно включаем UTF-8 для дочерних процессов
    import os
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"

    print("=" * 60)
    print("РОЛЬ 5: ПРОВЕРКА ТЕСТОВОГО НАБОРА")
    print("=" * 60)

    if not DATASET_EVALUATOR.is_file():
        print(f"ОШИБКА: файл не найден: {DATASET_EVALUATOR}")
        return 2

    print(f"Проверяемый файл: {DATASET_EVALUATOR.relative_to(ROOT)}")
    print()

    start = time.perf_counter()

    try:
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(DATASET_EVALUATOR)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=os.environ.copy(),
            check=False,
        )
    except OSError as exc:
        print(f"Не удалось запустить проверку: {exc}")
        return 2

    elapsed = time.perf_counter() - start
    output = result.stdout or ""
    error_output = result.stderr or ""

    if output:
        print(output, end="" if output.endswith("\n") else "\n")

    if error_output:
        print("\n--- СООБЩЕНИЯ ОБ ОШИБКАХ ---")
        print(error_output, end="" if error_output.endswith("\n") else "\n")

    scenario_match = re.search(
        r"Сценариев загружено:\s*(\d+)", output
    )
    error_match = re.search(r"Ошибок:\s*(\d+)", output)

    passed = (
        result.returncode == 0
        and error_match is not None
        and int(error_match.group(1)) == 0
    )

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_validation": {
            "status": "passed" if passed else "failed",
            "scenario_count": (
                int(scenario_match.group(1))
                if scenario_match else None
            ),
            "error_count": (
                int(error_match.group(1))
                if error_match else None
            ),
            "execution_time_seconds": round(elapsed, 4),
        },
        "copilot_metrics": {
            "recommendation_accuracy": None,
            "score_range_hit_rate": None,
            "parsing_completeness": None,
            "processing_time": None,
            "reproducibility": None,
            "status": "not_measured",
            "reason": (
                "Интеграция для запуска Copilot пока не готова."
            ),
        },
    }

    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)

    with RESULTS_FILE.open("w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("ИТОГ ПРОВЕРКИ")
    print("=" * 60)
    print(
        f"Проверка датасета: "
        f"{'ПРОЙДЕНА' if passed else 'ЕСТЬ ОШИБКИ'}"
    )
    print(
        f"Количество сценариев: "
        f"{report['dataset_validation']['scenario_count']}"
    )
    print(f"Время проверки датасета: {elapsed:.4f} сек.")
    print("Точность рекомендаций Copilot: пока не измерена")
    print("Время обработки закупки Copilot: пока не измерено")
    print(f"JSON-отчёт: {RESULTS_FILE.relative_to(ROOT)}")

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())