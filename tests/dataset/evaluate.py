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


# # # для реальной модели
# # import json
# # from pathlib import Path
# # from decimal import Decimal, InvalidOperation

# # try:
# #     import yaml
# # except ImportError:
# #     print("[ERROR] Не установлена библиотека PyYAML.")
# #     print("Выполни: pip install pyyaml")
# #     raise SystemExit(1)


# # # --------------------------------------------------
# # # PATHS AND SETTINGS
# # # --------------------------------------------------

# # BASE_DIR = Path(__file__).resolve().parent

# # SCENARIOS_FILE = BASE_DIR / "scenarios.yaml"
# # EXPECTED_FILE = BASE_DIR / "expected_fields.json"
# # ACTUAL_FILE = BASE_DIR / "actual_results.json"

# # REQUIRED_RECOMMENDATIONS = {
# #     "participate",
# #     "consider",
# #     "skip",
# # }

# # EXPECTED_FIELD_NAMES = [
# #     "regNumber",
# #     "nmcc",
# #     "object",
# #     "customer_name",
# #     "customer_inn",
# #     "region_code",
# #     "region_name",
# #     "lots_count",
# #     "law",
# # ]


# # # --------------------------------------------------
# # # LOAD DATA
# # # --------------------------------------------------

# # def load_json(path):
# #     with open(path, "r", encoding="utf-8") as file:
# #         return json.load(file)


# # def load_yaml(path):
# #     with open(path, "r", encoding="utf-8") as file:
# #         return yaml.safe_load(file)


# # def normalize_decimal(value):
# #     try:
# #         return Decimal(str(value))
# #     except (InvalidOperation, TypeError, ValueError):
# #         return None


# # def normalize_value(value):
# #     if value is None:
# #         return None

# #     return str(value).strip()


# # def load_actual_results(data):
# #     """
# #     Поддерживает два формата:
# #     1. {"results": [...]}
# #     2. [...]
# #     """

# #     if isinstance(data, dict):
# #         results = data.get("results", [])
# #     elif isinstance(data, list):
# #         results = data
# #     else:
# #         raise ValueError(
# #             "actual_results.json должен содержать список "
# #             "или объект с полем results."
# #         )

# #     if not isinstance(results, list):
# #         raise ValueError("Поле results должно быть списком.")

# #     return results


# # def load_runs(result):
# #     """
# #     Если есть runs — используем все запуски.
# #     Если runs нет — считаем сам объект одним запуском.
# #     """

# #     runs = result.get("runs")

# #     if isinstance(runs, list):
# #         return [
# #             run for run in runs
# #             if isinstance(run, dict)
# #         ]

# #     return [result]


# # # --------------------------------------------------
# # # EXPECTED DATA
# # # --------------------------------------------------

# # def find_expected(expected_data, file_name):
# #     stem = Path(file_name).stem

# #     if isinstance(expected_data, dict):
# #         if stem in expected_data:
# #             return expected_data[stem]

# #         for value in expected_data.values():
# #             if isinstance(value, dict):
# #                 if value.get("file") == file_name:
# #                     return value

# #     return None


# # def expected_fields_for_record(expected):
# #     """
# #     Сравниваем только поля, для которых есть
# #     непустое эталонное значение.
# #     """

# #     return {
# #         field: value
# #         for field, value in expected.items()
# #         if field in EXPECTED_FIELD_NAMES and value is not None
# #     }


# # # --------------------------------------------------
# # # METRIC 1: RECOMMENDATION ACCURACY
# # # --------------------------------------------------

# # def evaluate_recommendation(expected, actual):
# #     expected_value = expected.get("expected_recommendation")
# #     actual_value = actual.get("recommendation")

# #     if actual_value not in REQUIRED_RECOMMENDATIONS:
# #         return False

# #     return actual_value == expected_value


# # # --------------------------------------------------
# # # METRIC 2: SCORE RANGE HIT
# # # --------------------------------------------------

# # def evaluate_score_range(expected, actual):
# #     expected_range = expected.get("expected_score")
# #     actual_score = normalize_decimal(actual.get("score"))

# #     if not isinstance(expected_range, (list, tuple)):
# #         return None

# #     if len(expected_range) != 2 or actual_score is None:
# #         return False

# #     low = normalize_decimal(expected_range[0])
# #     high = normalize_decimal(expected_range[1])

# #     if low is None or high is None:
# #         return None

# #     return low <= actual_score <= high


# # # --------------------------------------------------
# # # METRIC 3: PARSING COMPLETENESS AND FIELD ACCURACY
# # # --------------------------------------------------

# # def evaluate_parsing(expected, actual):
# #     expected_fields = expected_fields_for_record(expected)
# #     extracted_fields = actual.get("extracted_fields", {})

# #     if not isinstance(extracted_fields, dict):
# #         extracted_fields = {}

# #     if not expected_fields:
# #         return None, None, 0, 0

# #     extracted_count = 0
# #     correct_count = 0

# #     for field, expected_value in expected_fields.items():
# #         actual_value = extracted_fields.get(field)

# #         if actual_value is not None and str(actual_value).strip() != "":
# #             extracted_count += 1

# #             if normalize_value(actual_value) == normalize_value(expected_value):
# #                 correct_count += 1

# #     total = len(expected_fields)

# #     completeness = extracted_count / total
# #     accuracy = correct_count / total

# #     return completeness, accuracy, extracted_count, total


# # # --------------------------------------------------
# # # METRIC 4: EXECUTION TIME
# # # --------------------------------------------------

# # def get_execution_time(actual):
# #     value = normalize_decimal(actual.get("execution_time_ms"))

# #     if value is None or value < 0:
# #         return None

# #     return float(value)


# # # --------------------------------------------------
# # # METRIC 5: REPRODUCIBILITY
# # # --------------------------------------------------

# # def result_signature(run):
# #     """
# #     Сравниваем ключевые результаты повторных запусков.
# #     Время выполнения не учитываем.
# #     """

# #     return {
# #         "recommendation": run.get("recommendation"),
# #         "score": normalize_value(run.get("score")),
# #         "extracted_fields": run.get("extracted_fields", {}),
# #         "stop_factors": sorted(
# #             run.get("stop_factors", [])
# #             if isinstance(run.get("stop_factors", []), list)
# #             else []
# #         ),
# #     }


# # def evaluate_reproducibility(runs):
# #     if len(runs) < 2:
# #         return None

# #     first_signature = result_signature(runs[0])

# #     return all(
# #         result_signature(run) == first_signature
# #         for run in runs[1:]
# #     )


# # # --------------------------------------------------
# # # MAIN EVALUATION
# # # --------------------------------------------------

# # def main():
# #     print("================================================")
# #     print(" AI PROCUREMENT COPILOT — EVALUATION")
# #     print("================================================")

# #     for path in [SCENARIOS_FILE, EXPECTED_FILE]:
# #         if not path.exists():
# #             print(f"[ERROR] Не найден файл: {path}")
# #             return

# #     try:
# #         scenarios_data = load_yaml(SCENARIOS_FILE)
# #         expected_data = load_json(EXPECTED_FILE)
# #     except Exception as error:
# #         print(f"[ERROR] Ошибка загрузки эталонных данных: {error}")
# #         return

# #     scenarios = scenarios_data.get("scenarios", [])

# #     if not isinstance(scenarios, list):
# #         print("[ERROR] В scenarios.yaml поле scenarios должно быть списком.")
# #         return

# #     print(f"\nСценариев в датасете: {len(scenarios)}")

# #     # Без фактических результатов нельзя оценить Copilot.
# #     if not ACTUAL_FILE.exists():
# #         print("\n[WAITING] Файл actual_results.json пока отсутствует.")
# #         print("Проверка датасета возможна, но оценка AI не запускалась.")
# #         print("Добавь фактические результаты Copilot и запусти файл снова.")
# #         return

# #     try:
# #         actual_data = load_json(ACTUAL_FILE)
# #         actual_results = load_actual_results(actual_data)
# #     except Exception as error:
# #         print(f"[ERROR] Ошибка загрузки фактических результатов: {error}")
# #         return

# #     actual_by_id = {}

# #     for result in actual_results:
# #         if not isinstance(result, dict):
# #             continue

# #         scenario_id = result.get("scenario_id")

# #         if not scenario_id:
# #             print("[WARN] Найден результат без scenario_id.")
# #             continue

# #         if scenario_id in actual_by_id:
# #             print(f"[WARN] Повторная запись scenario_id: {scenario_id}")

# #         actual_by_id[scenario_id] = result

# #     # Counters
# #     total_scenarios = 0
# #     total_runs = 0

# #     recommendation_pass = 0
# #     recommendation_total = 0

# #     score_pass = 0
# #     score_total = 0

# #     parsing_completeness_sum = 0.0
# #     parsing_accuracy_sum = 0.0
# #     parsing_total = 0

# #     execution_times = []

# #     reproducibility_pass = 0
# #     reproducibility_total = 0

# #     missing_results = 0

# #     print("\n---------------- SCENARIO RESULTS ----------------")

# #     for scenario in scenarios:
# #         scenario_id = scenario.get("id")
# #         file_name = scenario.get("file")

# #         if not scenario_id:
# #             continue

# #         total_scenarios += 1

# #         actual_record = actual_by_id.get(scenario_id)

# #         if actual_record is None:
# #             print(f"\n[NO RESULT] {scenario_id}: нет фактического результата.")
# #             missing_results += 1
# #             continue

# #         expected = find_expected(expected_data, file_name)

# #         if expected is None:
# #             print(f"\n[NO GOLD DATA] {scenario_id}: эталон не найден.")
# #             continue

# #         runs = load_runs(actual_record)

# #         if not runs:
# #             print(f"\n[NO RUNS] {scenario_id}: нет запусков.")
# #             continue

# #         print(f"\nСценарий: {scenario_id}")
# #         print(f"Количество запусков: {len(runs)}")

# #         for run_number, run in enumerate(runs, start=1):
# #             total_runs += 1

# #             # Recommendation accuracy
# #             recommendation_total += 1
# #             recommendation_ok = evaluate_recommendation(
# #                 scenario,
# #                 run
# #             )

# #             if recommendation_ok:
# #                 recommendation_pass += 1

# #             print(
# #                 f"  Запуск {run_number} — рекомендация: "
# #                 f"{'PASS' if recommendation_ok else 'FAIL'}"
# #             )

# #             # Score range hit
# #             score_result = evaluate_score_range(scenario, run)

# #             if score_result is not None:
# #                 score_total += 1

# #                 if score_result:
# #                     score_pass += 1

# #             print(
# #                 f"  Запуск {run_number} — диапазон баллов: "
# #                 f"{'PASS' if score_result else 'FAIL'}"
# #             )

# #             # Parsing completeness and accuracy
# #             completeness, accuracy, extracted, fields_total = (
# #                 evaluate_parsing(expected, run)
# #             )

# #             if completeness is not None:
# #                 parsing_completeness_sum += completeness
# #                 parsing_accuracy_sum += accuracy
# #                 parsing_total += 1

# #                 print(
# #                     f"  Запуск {run_number} — парсинг: "
# #                     f"{extracted}/{fields_total} полей, "
# #                     f"полнота {completeness * 100:.1f}%, "
# #                     f"точность {accuracy * 100:.1f}%"
# #                 )
# #             else:
# #                 print(
# #                     f"  Запуск {run_number} — парсинг: "
# #                     "нет доступных эталонных полей"
# #                 )

# #             # Execution time
# #             execution_time = get_execution_time(run)

# #             if execution_time is not None:
# #                 execution_times.append(execution_time)

# #                 print(
# #                     f"  Запуск {run_number} — время: "
# #                     f"{execution_time:.2f} ms"
# #                 )
# #             else:
# #                 print(
# #                     f"  Запуск {run_number} — время: "
# #                     "не указано"
# #                 )

# #         # Reproducibility
# #         reproducibility = evaluate_reproducibility(runs)

# #         if reproducibility is not None:
# #             reproducibility_total += 1

# #             if reproducibility:
# #                 reproducibility_pass += 1

# #             print(
# #                 "  Воспроизводимость: "
# #                 f"{'PASS' if reproducibility else 'FAIL'}"
# #             )
# #         else:
# #             print(
# #                 "  Воспроизводимость: недостаточно запусков "
# #                 "(нужно минимум 2)"
# #             )

# #     # --------------------------------------------------
# #     # FINAL REPORT
# #     # --------------------------------------------------

# #     print("\n================================================")
# #     print(" FINAL EVALUATION REPORT")
# #     print("================================================")

# #     print(f"Сценариев в датасете: {total_scenarios}")
# #     print(f"Фактических запусков: {total_runs}")
# #     print(f"Сценариев без результатов: {missing_results}")

# #     print("\n1. RECOMMENDATION ACCURACY")

# #     if recommendation_total:
# #         value = recommendation_pass / recommendation_total * 100
# #         print(
# #             f"{recommendation_pass}/{recommendation_total} "
# #             f"({value:.2f}%)"
# #         )
# #     else:
# #         print("Нет данных.")

# #     print("\n2. SCORE RANGE HIT")

# #     if score_total:
# #         value = score_pass / score_total * 100
# #         print(f"{score_pass}/{score_total} ({value:.2f}%)")
# #     else:
# #         print("Нет данных.")

# #     print("\n3. PARSING COMPLETENESS")

# #     if parsing_total:
# #         completeness = (
# #             parsing_completeness_sum / parsing_total * 100
# #         )
# #         accuracy = (
# #             parsing_accuracy_sum / parsing_total * 100
# #         )

# #         print(f"Средняя полнота: {completeness:.2f}%")
# #         print(f"Средняя точность полей: {accuracy:.2f}%")
# #     else:
# #         print("Нет данных.")

# #     print("\n4. EXECUTION TIME")

# #     if execution_times:
# #         average_time = sum(execution_times) / len(execution_times)

# #         print(f"Среднее время: {average_time:.2f} ms")
# #         print(f"Минимальное время: {min(execution_times):.2f} ms")
# #         print(f"Максимальное время: {max(execution_times):.2f} ms")
# #         print(f"Измерений: {len(execution_times)}")
# #     else:
# #         print("Нет данных.")

# #     print("\n5. REPRODUCIBILITY")

# #     if reproducibility_total:
# #         value = (
# #             reproducibility_pass /
# #             reproducibility_total * 100
# #         )

# #         print(
# #             f"{reproducibility_pass}/{reproducibility_total} "
# #             f"({value:.2f}%)"
# #         )
# #     else:
# #         print("Недостаточно повторных запусков.")

# #     print("\n================================================")
# #     print(" EVALUATION FINISHED")
# #     print("================================================")

# #     if missing_results:
# #         print(
# #             "[INFO] Часть сценариев не имеет фактических результатов. "
# #             "Общая оценка пока неполная."
# #         )
# #     else:
# #         print("[INFO] Все сценарии имеют фактические результаты.")


# # if __name__ == "__main__":
# #     main()