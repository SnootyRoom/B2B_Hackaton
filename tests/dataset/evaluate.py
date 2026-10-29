
#!/usr/bin/env python3
"""Проверка тестовых данных для скоринга закупок (Роль 5)."""

import json
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent
XML_DIR = DATASET_DIR / "procurements"
SCENARIOS_PATH = DATASET_DIR / "scenarios.yaml"
EXPECTED_PATH = DATASET_DIR / "expected_fields.json"

REQUIRED_SCENARIO_FIELDS = [
    "id", "file", "profile", "expected_recommendation", "rationale"
]


SCORE_THRESHOLD = 80
CONSIDER_THRESHOLD = 40
VALID_RECOMMENDATIONS = {"participate", "consider", "skip"}


def validate_score_threshold(scenario):
    """Проверяет ожидаемые баллы, рекомендацию и стоп-факторы."""
    scenario_id = scenario.get("id", "UNKNOWN")
    recommendation = scenario.get("expected_recommendation")
    score_range = scenario.get("expected_score")
    stop_factors = scenario.get("stop_factors", [])

    if recommendation not in VALID_RECOMMENDATIONS:
        return f"{scenario_id}: неизвестная рекомендация {recommendation!r}"

    if (
        not isinstance(score_range, list)
        or len(score_range) != 2
    ):
        return f"{scenario_id}: expected_score должен быть [min, max]"

    low, high = score_range

    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        for value in (low, high)
    ):
        return f"{scenario_id}: границы expected_score должны быть числами"

    if not (0 <= low <= high <= 100):
        return f"{scenario_id}: некорректный диапазон {score_range}"

    if not isinstance(stop_factors, list):
        return f"{scenario_id}: stop_factors должен быть списком"

    # Стоп-факторы имеют приоритет над баллами.
    if stop_factors:
        if recommendation != "skip":
            return (
                f"{scenario_id}: при стоп-факторах {stop_factors} "
                "ожидается рекомендация skip"
            )
        if score_range != [0, 0]:
            return (
                f"{scenario_id}: для сценария со стоп-факторами "
                "ожидаемый диапазон должен быть [0, 0]"
            )
        return None

    # Без стоп-факторов рекомендация должна соответствовать баллам.
    if recommendation == "participate" and low < SCORE_THRESHOLD:
        return (
            f"{scenario_id}: participate требует диапазон "
            f"не ниже {SCORE_THRESHOLD}, получено {score_range}"
        )

    if recommendation == "consider" and (
        low < CONSIDER_THRESHOLD or high >= SCORE_THRESHOLD
    ):
        return (
            f"{scenario_id}: consider требует диапазон "
            f"[{CONSIDER_THRESHOLD}, {SCORE_THRESHOLD - 1}], "
            f"получено {score_range}"
        )

    if recommendation == "skip" and high >= CONSIDER_THRESHOLD:
        return (
            f"{scenario_id}: без стоп-факторов skip требует "
            f"баллы ниже {CONSIDER_THRESHOLD}, получено {score_range}"
        )

    return None


def load_json(path):
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[FAIL] Не удалось прочитать {path.name}: {exc}")
        return None


def load_yaml(path):
    try:
        import yaml
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        print("[FAIL] Не установлен PyYAML. Установи: py -m pip install pyyaml")
    except (OSError, ValueError) as exc:
        print(f"[FAIL] Не удалось прочитать {path.name}: {exc}")
    return None


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def read_xml(path):
    root = ET.parse(path).getroot()
    fields = {}

    for element in root.iter():
        name = local_name(element.tag)
        value = (element.text or "").strip()
        if value and name not in fields:
            fields[name] = value

    return fields


def find_expected(file_name, expected):
    stem = Path(file_name).stem

    if stem in expected:
        return expected[stem]

    # Для специальных XML-файлов имя файла содержит ИНН заказчика.
    inn = stem.split("_")[0]
    matches = [
        item for item in expected.values()
        if str(item.get("customer_inn", "")) == inn
    ]

    return matches[0] if len(matches) == 1 else None


def compare_value(field, expected_value, actual_value):
    if expected_value is None or actual_value is None:
        return False

    if field == "nmcc":
        try:
            return Decimal(str(expected_value)) == Decimal(str(actual_value))
        except InvalidOperation:
            return False

    return str(expected_value) == str(actual_value)


def main():
    print("=== ПРОВЕРКА ТЕСТОВЫХ ДАННЫХ: РОЛЬ 5 ===\n")

    scenarios_data = load_yaml(SCENARIOS_PATH)
    expected = load_json(EXPECTED_PATH)

    if scenarios_data is None or expected is None:
        print("\nИТОГ: не удалось загрузить тестовые данные.")
        return 1

    scenarios = scenarios_data.get("scenarios", [])
    failures = 0
    checks = 0

    print(f"[OK] Сценариев загружено: {len(scenarios)}")
    print(f"[OK] Эталонов загружено: {len(expected)}")

    if len(scenarios) != 8:
        print(f"[FAIL] Ожидалось 8 сценариев, найдено {len(scenarios)}")
        failures += 1

    seen_ids = set()
    print("\n--- Проверка сценариев и XML ---")

    for scenario in scenarios:
        threshold_error = validate_score_threshold(scenario)
        if threshold_error:
            print(f"[FAIL] {threshold_error}")
            failures += 1
        scenario_id = scenario.get("id", "UNKNOWN")
        missing = [
            field for field in REQUIRED_SCENARIO_FIELDS
            if field not in scenario
        ]

        if missing:
            print(f"[FAIL] {scenario_id}: нет полей {missing}")
            failures += 1
            continue

        if scenario_id in seen_ids:
            print(f"[FAIL] Повторяется ID сценария: {scenario_id}")
            failures += 1
        seen_ids.add(scenario_id)

        file_name = scenario["file"]
        xml_path = XML_DIR / Path(file_name).name

        if not xml_path.is_file():
            print(f"[FAIL] {scenario_id}: XML не найден: {file_name}")
            failures += 1
            continue

        record = find_expected(file_name, expected)

        if record is None:
            print(f"[FAIL] {scenario_id}: эталон не найден для {file_name}")
            failures += 1
            continue

        try:
            actual = read_xml(xml_path)
        except (ET.ParseError, OSError) as exc:
            print(f"[FAIL] {scenario_id}: XML не читается: {exc}")
            failures += 1
            continue

        fields_to_check = [
            ("regNumber", record.get("regNumber"), actual.get("regNumber")),
            ("nmcc", record.get("nmcc"), actual.get("initialPrice")),
            ("customer_inn", record.get("customer_inn"), actual.get("inn")),
            ("law", record.get("law"), actual.get("law")),
        ]

        scenario_failed = False

        for field, expected_value, actual_value in fields_to_check:
            checks += 1
            if compare_value(field, expected_value, actual_value):
                continue

            print(
                f"[FAIL] {scenario_id} / {field}: "
                f"XML={actual_value!r}, эталон={expected_value!r}"
            )
            failures += 1
            scenario_failed = True

        if not scenario_failed:
            print(f"[PASS] {scenario_id}: XML и эталон совпадают")

    print("\n--- Итог ---")
    print(f"Проверок полей: {checks}")
    print(f"Ошибок: {failures}")

    if failures:
        print("РЕЗУЛЬТАТ: найдены проблемы в тестовых данных.")
        return 1

    print("РЕЗУЛЬТАТ: тестовые данные прошли проверки.")
    print("Примечание: качество реальных рекомендаций скоринга здесь не оценивается.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
