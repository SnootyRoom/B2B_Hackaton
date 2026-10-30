# #!/usr/bin/env python3
# """Проверка тестовых данных для скоринга закупок (Роль 5)."""

# import json
# import xml.etree.ElementTree as ET
# from decimal import Decimal, InvalidOperation
# from pathlib import Path

# DATASET_DIR = Path(__file__).resolve().parent
# XML_DIR = DATASET_DIR / "procurements"
# SCENARIOS_PATH = DATASET_DIR / "scenarios.yaml"
# EXPECTED_PATH = DATASET_DIR / "expected_fields.json"

# REQUIRED_SCENARIO_FIELDS = [
#     "id", "file", "profile", "expected_recommendation", "rationale"
# ]


# SCORE_THRESHOLD = 70
# CONSIDER_THRESHOLD = 40
# VALID_RECOMMENDATIONS = {"participate", "consider", "skip"}



# def validate_score_threshold(scenario):
#     """Проверяет соответствие ожидаемой рекомендации диапазону баллов
#     и наличию стоп-факторов.
#     """
#     errors = []

#     recommendation = scenario.get("expected_recommendation")
#     expected_score = scenario.get("expected_score")
#     raw_stop_factors = scenario.get("expected_stop_factor")

#     # Приводим стоп-факторы к единому формату: список строк
#     if raw_stop_factors is None or raw_stop_factors == "":
#         stop_factors = []
#     elif isinstance(raw_stop_factors, str):
#         stop_factors = [
#             factor.strip()
#             for factor in raw_stop_factors.split(",")
#             if factor.strip()
#         ]
#     elif isinstance(raw_stop_factors, list):
#         stop_factors = [
#             str(factor).strip()
#             for factor in raw_stop_factors
#             if str(factor).strip()
#         ]
#     else:
#         errors.append(
#             f"Некорректный формат expected_stop_factor: "
#             f"{raw_stop_factors!r}"
#         )
#         stop_factors = []

#     # Проверяем наличие и формат диапазона баллов
#     if (
#         not isinstance(expected_score, list)
#         or len(expected_score) != 2
#     ):
#         errors.append(
#             f"Некорректный expected_score: {expected_score!r}. "
#             "Ожидается список из двух чисел."
#         )
#         return errors

#     low, high = expected_score

#     if (
#         not isinstance(low, (int, float))
#         or isinstance(low, bool)
#         or not isinstance(high, (int, float))
#         or isinstance(high, bool)
#     ):
#         errors.append("Границы expected_score должны быть числами.")
#         return errors

#     if not (0 <= low <= high <= 100):
#         errors.append(
#             f"Некорректный диапазон баллов: {expected_score}"
#         )
#         return errors

#     # Проверяем рекомендацию
#     if recommendation not in {"participate", "consider", "skip"}:
#         errors.append(
#             f"Неизвестная рекомендация: {recommendation!r}"
#         )
#         return errors

#     # Если есть стоп-факторы, рекомендация должна быть skip
#     if stop_factors:
#         if recommendation != "skip":
#             errors.append(
#                 "При наличии стоп-факторов рекомендация должна быть skip."
#             )

#         if [low, high] != [0, 0]:
#             errors.append(
#                 "При наличии стоп-факторов ожидаемый балл должен быть [0, 0]."
#             )

#     else:
#         if recommendation == "participate" and low < 70:
#             errors.append(
#                 "Для participate нижняя граница балла должна быть >= 70."
#             )

#         elif recommendation == "consider":
#             if low < 40 or high >= 70:
#                 errors.append(
#                     "Для consider диапазон должен находиться "
#                     "в пределах 40–69."
#                 )

#         elif recommendation == "skip" and high >= 40:
#             errors.append(
#                 "Для skip без стоп-факторов верхняя граница "
#                 "балла должна быть < 40."
#             )

#     return errors



# def load_json(path):
#     try:
#         with path.open(encoding="utf-8") as f:
#             return json.load(f)
#     except (OSError, json.JSONDecodeError) as exc:
#         print(f"[FAIL] Не удалось прочитать {path.name}: {exc}")
#         return None


# def load_yaml(path):
#     try:
#         import yaml
#         with path.open(encoding="utf-8") as f:
#             return yaml.safe_load(f)
#     except ImportError:
#         print("[FAIL] Не установлен PyYAML. Установи: py -m pip install pyyaml")
#     except (OSError, ValueError) as exc:
#         print(f"[FAIL] Не удалось прочитать {path.name}: {exc}")
#     return None


# def local_name(tag):
#     return tag.rsplit("}", 1)[-1]


# def read_xml(path):
#     root = ET.parse(path).getroot()
#     fields = {}

#     for element in root.iter():
#         name = local_name(element.tag)
#         value = (element.text or "").strip()
#         if value and name not in fields:
#             fields[name] = value

#     return fields


# def find_expected(file_name, expected):
#     stem = Path(file_name).stem

#     if stem in expected:
#         return expected[stem]

#     # Для специальных XML-файлов имя файла содержит ИНН заказчика.
#     inn = stem.split("_")[0]
#     matches = [
#         item for item in expected.values()
#         if str(item.get("customer_inn", "")) == inn
#     ]

#     return matches[0] if len(matches) == 1 else None


# def compare_value(field, expected_value, actual_value):
#     if field == "nmcc":
#         expected_missing = expected_value is None or expected_value == ""
#         actual_missing = actual_value is None or actual_value == ""

#         # Если цена отсутствует и в эталоне, и в XML,
#         # отсутствие данных считается совпадением.
#         if expected_missing and actual_missing:
#             return True

#         # Если цена есть только с одной стороны,
#         # данные не совпадают.
#         if expected_missing or actual_missing:
#             return False

#         try:
#             return Decimal(str(expected_value)) == Decimal(str(actual_value))
#         except (InvalidOperation, ValueError):
#             return False

#     if expected_value is None or actual_value is None:
#         return False

#     return str(expected_value) == str(actual_value)



# def main():
#     print("=== ПРОВЕРКА ТЕСТОВЫХ ДАННЫХ: РОЛЬ 5 ===\n")

#     scenarios_data = load_yaml(SCENARIOS_PATH)
#     expected = load_json(EXPECTED_PATH)

#     if scenarios_data is None or expected is None:
#         print("\nИТОГ: не удалось загрузить тестовые данные.")
#         return 1

#     scenarios = scenarios_data.get("scenarios", [])
#     failures = 0
#     checks = 0

#     print(f"[OK] Сценариев загружено: {len(scenarios)}")
#     print(f"[OK] Эталонов загружено: {len(expected)}")

#     if len(scenarios) < 20:
#         print(
#             f"[FAIL] Ожидалось не менее 20 сценариев, "
#             f"найдено {len(scenarios)}"
#         )
#         failures += 1
#     else:
#         print(
#             f"[PASS] Количество сценариев ({len(scenarios)}) "
#             "соответствует плану (≥20)"
#         )

#     seen_ids = set()
#     print("\n--- Проверка сценариев и XML ---")

#     for scenario in scenarios:
#         threshold_error = validate_score_threshold(scenario)
#         if threshold_error:
#             print(f"[FAIL] {threshold_error}")
#             failures += 1
#         scenario_id = scenario.get("id", "UNKNOWN")
#         missing = [
#             field for field in REQUIRED_SCENARIO_FIELDS
#             if field not in scenario
#         ]

#         if missing:
#             print(f"[FAIL] {scenario_id}: нет полей {missing}")
#             failures += 1
#             continue

#         if scenario_id in seen_ids:
#             print(f"[FAIL] Повторяется ID сценария: {scenario_id}")
#             failures += 1
#         seen_ids.add(scenario_id)

#         file_name = scenario["file"]
#         xml_path = XML_DIR / Path(file_name).name

#         if not xml_path.is_file():
#             print(f"[FAIL] {scenario_id}: XML не найден: {file_name}")
#             failures += 1
#             continue

#         record = find_expected(file_name, expected)

#         if record is None:
#             print(f"[FAIL] {scenario_id}: эталон не найден для {file_name}")
#             failures += 1
#             continue

#         try:
#             actual = read_xml(xml_path)
#         except (ET.ParseError, OSError) as exc:
#             print(f"[FAIL] {scenario_id}: XML не читается: {exc}")
#             failures += 1
#             continue

#         fields_to_check = [
#             ("regNumber", record.get("regNumber"), actual.get("regNumber")),
#             ("nmcc", record.get("nmcc"), actual.get("initialPrice")),
#             ("customer_inn", record.get("customer_inn"), actual.get("inn")),
#             ("law", record.get("law"), actual.get("law")),
#         ]

#         scenario_failed = False

#         for field, expected_value, actual_value in fields_to_check:
#             checks += 1
#             if compare_value(field, expected_value, actual_value):
#                 continue

#             print(
#                 f"[FAIL] {scenario_id} / {field}: "
#                 f"XML={actual_value!r}, эталон={expected_value!r}"
#             )
#             failures += 1
#             scenario_failed = True

#         if not scenario_failed:
#             print(f"[PASS] {scenario_id}: XML и эталон совпадают")

#     print("\n--- Итог ---")
#     print(f"Проверок полей: {checks}")
#     print(f"Ошибок: {failures}")

#     if failures:
#         print("РЕЗУЛЬТАТ: найдены проблемы в тестовых данных.")
#         return 1

#     print("РЕЗУЛЬТАТ: тестовые данные прошли проверки.")
#     print("Примечание: качество реальных рекомендаций скоринга здесь не оценивается.")
#     return 0


# if __name__ == "__main__":
#     raise SystemExit(main())




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
    "id",
    "file",
    "profile",
    "expected_recommendation",
    "expected_score",
    "rationale",
]

SCORE_THRESHOLD = 70
CONSIDER_THRESHOLD = 40

VALID_RECOMMENDATIONS = {
    "participate",
    "consider",
    "skip",
}


def normalize_stop_factors(value):
    """Преобразует стоп-факторы в список строк."""

    if value is None or value == "":
        return []

    if isinstance(value, str):
        return [
            item.strip()
            for item in value.split(",")
            if item.strip()
        ]

    if isinstance(value, list):
        return [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]

    return None


def validate_score_threshold(scenario):
    """Проверяет рекомендацию, баллы и стоп-факторы."""

    errors = []

    recommendation = scenario.get("expected_recommendation")
    expected_score = scenario.get("expected_score")
    stop_factors = normalize_stop_factors(
        scenario.get("expected_stop_factor")
    )

    if stop_factors is None:
        errors.append(
            "Некорректный формат expected_stop_factor."
        )
        stop_factors = []

    if (
        not isinstance(expected_score, list)
        or len(expected_score) != 2
    ):
        errors.append(
            f"Некорректный expected_score: {expected_score!r}"
        )
        return errors

    low, high = expected_score

    if (
        not isinstance(low, (int, float))
        or isinstance(low, bool)
        or not isinstance(high, (int, float))
        or isinstance(high, bool)
    ):
        errors.append("Границы expected_score должны быть числами.")
        return errors

    if not (0 <= low <= high <= 100):
        errors.append(
            f"Некорректный диапазон баллов: {expected_score}"
        )
        return errors

    if recommendation not in VALID_RECOMMENDATIONS:
        errors.append(
            f"Неизвестная рекомендация: {recommendation!r}"
        )
        return errors

    if stop_factors:
        if recommendation != "skip":
            errors.append(
                "При наличии стоп-факторов рекомендация должна быть skip."
            )

        if [low, high] != [0, 0]:
            errors.append(
                "При наличии стоп-факторов балл должен быть [0, 0]."
            )

    else:
        if recommendation == "participate" and low < SCORE_THRESHOLD:
            errors.append(
                f"Для participate нижняя граница должна быть >= {SCORE_THRESHOLD}."
            )

        elif recommendation == "consider":
            if low < CONSIDER_THRESHOLD or high >= SCORE_THRESHOLD:
                errors.append(
                    "Для consider диапазон должен быть 40–69."
                )

        elif recommendation == "skip" and high >= CONSIDER_THRESHOLD:
            errors.append(
                "Для skip без стоп-факторов верхняя граница должна быть < 40."
            )

    return errors


def load_json(path):
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[FAIL] Не удалось прочитать {path.name}: {exc}")
        return None


def load_yaml(path):
    try:
        import yaml

        with path.open(encoding="utf-8") as file:
            return yaml.safe_load(file)

    except ImportError:
        print("[FAIL] Установи PyYAML: py -m pip install pyyaml")
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

    inn = stem.split("_")[0]

    matches = [
        item for item in expected.values()
        if str(item.get("customer_inn", "")) == inn
    ]

    return matches[0] if len(matches) == 1 else None


def compare_value(field, expected_value, actual_value):
    if field == "nmcc":
        expected_missing = expected_value is None or expected_value == ""
        actual_missing = actual_value is None or actual_value == ""

        if expected_missing and actual_missing:
            return None

        if expected_missing or actual_missing:
            return False

        try:
            return Decimal(str(expected_value)) == Decimal(str(actual_value))
        except (InvalidOperation, ValueError):
            return False

    if expected_value is None or actual_value is None:
        return False

    return str(expected_value) == str(actual_value)


def validate_scenario_ids(scenarios):
    errors = []
    seen_ids = set()

    for scenario in scenarios:
        scenario_id = scenario.get("id")

        if not scenario_id:
            errors.append("Обнаружен сценарий без ID.")
        elif scenario_id in seen_ids:
            errors.append(f"Повторяется ID сценария: {scenario_id}")

        seen_ids.add(scenario_id)

    return errors

def validate_profiles(scenarios_data, scenarios):
    print("\n--- ПРОВЕРКА ПРОФИЛЕЙ ПОСТАВЩИКОВ ---")

    profiles = scenarios_data.get("profiles")

    if isinstance(profiles, dict):
        profile_ids = list(profiles.keys())

    elif isinstance(profiles, list):
        profile_ids = [
            profile.get("id")
            for profile in profiles
            if isinstance(profile, dict) and profile.get("id")
        ]

    else:
        print("[FAIL] Раздел profiles отсутствует или имеет неверный формат.")
        return 1

    profile_ids = [str(profile_id) for profile_id in profile_ids]

    if not 3 <= len(profile_ids) <= 4:
        print(
            f"[FAIL] Найдено профилей: {len(profile_ids)}. "
            "По требованиям должно быть от 3 до 4."
        )
        errors = 1
    else:
        print(f"[PASS] Количество профилей соответствует плану: {len(profile_ids)}.")
        errors = 0

    counts = {profile_id: 0 for profile_id in profile_ids}

    for scenario in scenarios:
        scenario_id = scenario.get("id", "без ID")
        profile_id = scenario.get("profile")

        if profile_id is None:
            print(f"[FAIL] {scenario_id}: не указан профиль.")
            errors += 1
            continue

        profile_id = str(profile_id)

        if profile_id not in counts:
            print(
                f"[FAIL] {scenario_id}: профиль "
                f"'{profile_id}' отсутствует в profiles."
            )
            errors += 1
        else:
            counts[profile_id] += 1

    print("\nИспользование профилей:")

    for profile_id, count in counts.items():
        if count == 0:
            print(f"[WARN] {profile_id}: не используется ни в одном сценарии.")
        else:
            print(f"[PASS] {profile_id}: {count} сценариев.")

    print(f"\nОшибок проверки профилей: {errors}")

    return errors


def validate_stop_factors(scenarios):
    """Показывает все стоп-факторы и проверяет их согласованность."""

    print("\n--- ПРОВЕРКА СТОП-ФАКТОРОВ ---")

    with_factors = 0
    without_factors = 0
    all_factor_types = set()
    errors = 0

    for scenario in scenarios:
        scenario_id = scenario.get("id", "UNKNOWN")
        raw_value = scenario.get("expected_stop_factor")
        factors = normalize_stop_factors(raw_value)

        if factors is None:
            print(
                f"[FAIL] {scenario_id}: некорректный формат стоп-факторов"
            )
            errors += 1
            continue

        if factors:
            with_factors += 1
            all_factor_types.update(factors)

            print(
                f"[PASS] {scenario_id}: {', '.join(factors)}"
            )
        else:
            without_factors += 1

    print(f"\nСценариев со стоп-факторами: {with_factors}")
    print(f"Сценариев без стоп-факторов: {without_factors}")
    print(f"Уникальных типов стоп-факторов: {len(all_factor_types)}")

    if all_factor_types:
        print("Все типы стоп-факторов:")
        for factor in sorted(all_factor_types):
            print(f"  - {factor}")
    else:
        print("[FAIL] В датасете не найдено ни одного стоп-фактора.")
        errors += 1

    print(f"Ошибок проверки стоп-факторов: {errors}")

    return errors


def main():
    print("=== ПРОВЕРКА ТЕСТОВЫХ ДАННЫХ: РОЛЬ 5 ===\n")

    scenarios_data = load_yaml(SCENARIOS_PATH)
    expected = load_json(EXPECTED_PATH)

    if scenarios_data is None or expected is None:
        print("\nИТОГ: не удалось загрузить тестовые данные.")
        return 1

    scenarios = scenarios_data.get("scenarios", [])

    if not isinstance(scenarios, list):
        print("[FAIL] Поле scenarios должно быть списком.")
        return 1

    failures = 0
    checks = 0
    skipped_checks = 0

    print(f"[OK] Сценариев загружено: {len(scenarios)}")
    print(f"[OK] Эталонов загружено: {len(expected)}")

    if len(scenarios) < 20:
        print("[FAIL] Должно быть не менее 20 сценариев.")
        failures += 1
    else:
        print("[PASS] Количество сценариев соответствует плану.")

    print("\n--- ПРОВЕРКА ID СЦЕНАРИЕВ ---")

    id_errors = validate_scenario_ids(scenarios)

    if id_errors:
        for error in id_errors:
            print(f"[FAIL] {error}")
        failures += len(id_errors)
    else:
        print(f"[PASS] Все ID уникальны ({len(scenarios)} сценариев).")

    print("\n--- ПРОВЕРКА РЕКОМЕНДАЦИЙ И БАЛЛОВ ---")

    for scenario in scenarios:
        errors = validate_score_threshold(scenario)

        if errors:
            failures += len(errors)
            print(f"[FAIL] {scenario.get('id', 'UNKNOWN')}")

            for error in errors:
                print(f"  {error}")
        else:
            print(
                f"[PASS] {scenario.get('id')}: "
                "рекомендация и диапазон корректны"
            )

    failures += validate_stop_factors(scenarios)
    failures += validate_profiles(scenarios_data, scenarios)

    print("\n--- ПРОВЕРКА XML И ЭТАЛОНОВ ---")

    for scenario in scenarios:
        scenario_id = scenario.get("id", "UNKNOWN")

        missing = [
            field for field in REQUIRED_SCENARIO_FIELDS
            if field not in scenario
        ]

        if missing:
            print(f"[FAIL] {scenario_id}: отсутствуют поля {missing}")
            failures += 1
            continue

        file_name = scenario["file"]
        xml_path = XML_DIR / Path(file_name).name

        if not xml_path.is_file():
            print(f"[FAIL] {scenario_id}: XML не найден: {file_name}")
            failures += 1
            continue

        record = find_expected(file_name, expected)

        if record is None:
            print(f"[FAIL] {scenario_id}: эталон не найден")
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
            result = compare_value(field, expected_value, actual_value)

            if result is None:
                skipped_checks += 1
                continue

            checks += 1

            if not result:
                print(
                    f"[FAIL] {scenario_id} / {field}: "
                    f"XML={actual_value!r}, эталон={expected_value!r}"
                )
                failures += 1
                scenario_failed = True

        if not scenario_failed:
            print(f"[PASS] {scenario_id}: XML и эталон совпадают")

    print("\n--- ИТОГ ---")
    print(f"Проверок полей: {checks}")
    print(f"Пропущено проверок: {skipped_checks}")
    print(f"Ошибок: {failures}")

    if failures:
        print("РЕЗУЛЬТАТ: найдены проблемы в тестовых данных.")
        return 1

    print("РЕЗУЛЬТАТ: тестовые данные прошли проверки.")
    print("Качество фактических рекомендаций Copilot здесь не оценивается.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())