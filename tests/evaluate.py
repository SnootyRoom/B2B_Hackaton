"""
Проверка реального парсера и скорингового движка B2B_Hackaton.
Python 3.12+
"""

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


# --------------------------------------------------
# Пути проекта
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
DATASET_DIR = PROJECT_ROOT / "tests" / "dataset"
PROCUREMENTS_DIR = DATASET_DIR / "procurements"
SCENARIOS_FILE = DATASET_DIR / "scenarios.yaml"

sys.path.insert(0, str(BACKEND_DIR))


# --------------------------------------------------
# Импорты проекта
# --------------------------------------------------

try:
    from app.parsers.registry import parse_file
    from app.scoring.defaults import default_profile
    from app.scoring.engine import score
    from app.scoring.fields import extract_fields

except Exception as exc:
    print("Ошибка импорта backend:", repr(exc))
    traceback.print_exc()
    sys.exit(1)


# --------------------------------------------------
# Загрузка сценариев
# --------------------------------------------------

def load_scenarios() -> list[dict[str, Any]]:
    if not SCENARIOS_FILE.exists():
        raise FileNotFoundError(
            "Не найден файл: {}".format(SCENARIOS_FILE)
        )

    with SCENARIOS_FILE.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if isinstance(data, list):
        return data

    if isinstance(data, dict) and isinstance(data.get("scenarios"), list):
        return data["scenarios"]

    raise ValueError(
        "В scenarios.yaml не найден список scenarios."
    )


# --------------------------------------------------
# Поиск XML-файла
# --------------------------------------------------

def find_xml_file(scenario: dict, dataset_dir: Path) -> Path | None:
    """Находит XML по пути, указанному в scenarios.yaml."""
    project_root = Path(__file__).resolve().parents[1]

    # В scenarios.yaml путь к XML хранится в поле file
    file_value = scenario.get("file")

    if file_value:
        source_path = Path(file_value)

        candidates = [
            source_path,
            project_root / source_path,
            dataset_dir / source_path,
            dataset_dir / "procurements" / source_path.name,
        ]

        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()

    # Резервный поиск по другим возможным именам
    for key in ("filename", "xml_file", "procurement_file", "source_file"):
        value = scenario.get(key)
        if value:
            candidate = Path(value)
            if not candidate.is_absolute():
                candidate = project_root / candidate
            if candidate.is_file():
                return candidate.resolve()

    return None


# --------------------------------------------------
# Парсинг XML
# --------------------------------------------------

def parse_procurement(xml_path: Path, scenario: dict[str, Any]):
    content = xml_path.read_bytes()

    parsed = parse_file(content, xml_path.name)

    if not parsed:
        raise ValueError("Парсер не вернул данные закупки.")

    lot_index = scenario.get(
        "lot_index",
        scenario.get("lot", scenario.get("lot_number")),
    )

    if lot_index is not None:
        index = int(lot_index)

        if 1 <= index <= len(parsed):
            return parsed[index - 1]

        if index == 0:
            return parsed[0]

    return parsed[0]


# --------------------------------------------------
# Выполнение скоринга
# --------------------------------------------------

def evaluate_scenario(
    scenario: dict[str, Any],
    profile: Any,
) -> dict[str, Any]:

    scenario_id = scenario.get(
        "id",
        scenario.get("scenario_id", "unknown"),
    )

    xml_path = find_xml_file(scenario, DATASET_DIR)
    procurement = parse_procurement(xml_path, scenario)

    # На этом этапе данные ЕГРЮЛ не подключаются.
    customer = None

    fields = extract_fields(
        procurement,
        customer,
        datetime.now(timezone.utc),
    )

    result = score(
        profile,
        fields,
        similarity=None,
    )

    return {
        "id": scenario_id,
        "file": xml_path.name,
        "total": result.total,
        "recommendation": result.recommendation,
        "incomplete": result.incomplete,
        "stop_factors": result.stop_factors,
        "groups": result.groups,
        "rules": result.rules,
        "justification": result.justification,
    }


# --------------------------------------------------
# Подготовка результата к JSON
# --------------------------------------------------

def to_plain(value: Any) -> Any:

    if hasattr(value, "model_dump"):
        return to_plain(value.model_dump())

    if hasattr(value, "dict") and callable(value.dict):
        return to_plain(value.dict())

    if isinstance(value, dict):
        return {
            str(key): to_plain(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [to_plain(item) for item in value]

    if hasattr(value, "value"):
        return value.value

    return value


# --------------------------------------------------
# Главная функция
# --------------------------------------------------

def main() -> int:

    print("=" * 60)
    print("ПРОВЕРКА СКОРИНГОВОГО ДВИЖКА")
    print("=" * 60)

    print("Python:", sys.version.split()[0])
    print("Проект:", PROJECT_ROOT)

    if not PROCUREMENTS_DIR.exists():
        print("Не найдена папка:", PROCUREMENTS_DIR)
        return 1

    scenarios = load_scenarios()
    profile = default_profile()

    print("Загружено сценариев:", len(scenarios))
    print("-" * 60)

    passed = 0
    failed = 0
    results = []

    for scenario in scenarios:
        scenario_id = scenario.get(
            "id",
            scenario.get("scenario_id", "unknown"),
        )

        try:
            result = evaluate_scenario(scenario, profile)
            results.append(to_plain(result))
            passed += 1

            print(
                f"[OK] {scenario_id} | "
                f"score={result['total']} | "
                f"recommendation={result['recommendation']}"
            )

            if result["stop_factors"]:
                print("     Стоп-факторы:", result["stop_factors"])

            if result["incomplete"]:
                print("     Есть неполные данные.")

        except Exception as exc:
            failed += 1
            print(f"[ОШИБКА] {scenario_id}: {exc}")

    print("-" * 60)
    print("ИТОГИ")
    print("Всего сценариев:", len(scenarios))
    print("Успешно обработано:", passed)
    print("Ошибок:", failed)

    output_file = DATASET_DIR / "evaluation_results.json"

    with output_file.open("w", encoding="utf-8") as file:
        json.dump(
            results,
            file,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    print("Результаты сохранены:", output_file)

    if failed == 0:
        print("РЕЗУЛЬТАТ: все сценарии обработаны.")
        return 0

    print("РЕЗУЛЬТАТ: есть ошибки.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
