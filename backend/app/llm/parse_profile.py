"""Текст параметров → черновик правил (POST /scoring-profiles/parse).

LLM только предлагает правила; каждое проверяется теми же валидаторами, что и при сохранении.
При ошибке — один повтор с текстом ошибки, затем LLMError с понятным сообщением.
"""

import json
import re

from pydantic import ValidationError

from app.llm.client import (
    JsonObject,
    LLMBadAnswer,
    LLMClient,
    LLMError,
    LLMUnavailable,
    Prompt,
    load_prompt,
)
from app.llm.okpd2 import OKPD2_CATEGORIES, codes_for
from app.parsers.regions import REGIONS
from app.schemas.common import ErrorCode
from app.schemas.scoring import FIELD_CATALOG, FieldType, ParseProfileResult, ScoringRule
from app.scoring.defaults import with_defaults
from app.scoring.templates import ENUM_LABELS

STOP_FIELDS = frozenset({"law", "method", "region"})

# Город федерального значения и область вокруг него — для поставщика один регион
PAIRED_REGIONS = {
    "Москва": "Московская область",
    "Московская область": "Москва",
    "Санкт-Петербург": "Ленинградская область",
    "Ленинградская область": "Санкт-Петербург",
}


def with_paired_regions(rules: list[ScoringRule]) -> None:
    """Дополняет правила о регионе парным регионом: «Московская область» → + «Москва»."""
    for rule in rules:
        if rule.field == "region" and rule.kind == "weighted" and isinstance(rule.value, list):
            values = [str(v) for v in rule.value]
            extra = [PAIRED_REGIONS[v] for v in values if v in PAIRED_REGIONS]
            rule.value = list(dict.fromkeys([*values, *extra]))


# Число в тексте: «30», «1,5», «1 000 000» (группы разрядов через пробел)
_NUMBER = re.compile(r"\d+(?:\s\d{3})*(?:[.,]\d+)?")
# Сумма в рублях может быть записана в рублях, тысячах или миллионах: «1 до 30 млн» → 1 000 000
_MONEY_SCALES = (1, 1_000, 1_000_000, 1_000_000_000)


def text_numbers(text: str) -> set[float]:
    found = set()
    for m in _NUMBER.finditer(text):
        raw = re.sub(r"\s", "", m.group()).replace(",", ".")
        found.add(float(raw))
    # суммы словами: «от миллиона», «до полмиллиона»
    low = text.casefold()
    if re.search(r"(?<!пол)(миллион|тысяч)", low):
        found.add(1.0)
    if "полмиллион" in low:
        found.add(0.5)
    return found


def invented_money(value: object, numbers: set[float]) -> list[float]:
    """Суммы правила, которых нет в тексте пользователя ни в рублях, ни в тысячах, ни в миллионах:
    модель их придумала или ошиблась в разрядах (написала 10 млн вместо 1 млн)."""
    values = value if isinstance(value, list) else [value]
    bad = []
    for v in values:
        if not isinstance(v, int | float) or isinstance(v, bool):
            continue
        if not any(abs(v / k - n) < 1e-6 for k in _MONEY_SCALES for n in numbers):
            bad.append(float(v))
    return bad


PARSE_ERROR_MESSAGE = "Не удалось разобрать текст, задайте правила вручную"
UNAVAILABLE_MESSAGE = "Разбор текста временно недоступен, задайте правила вручную"

_VALUE_SCHEMA: JsonObject = {
    "anyOf": [
        {"type": "number"},
        {"type": "string"},
        {"type": "array", "items": {"type": "number"}},
        {"type": "array", "items": {"type": "string"}},
        {"type": "null"},
    ]
}

RESPONSE_SCHEMA: JsonObject = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rules", "okpd2_categories", "company_description", "unparsed"],
    "properties": {
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "kind",
                    "field",
                    "operator",
                    "value",
                    "weight",
                    "soft_margin",
                    "label",
                ],
                "properties": {
                    "kind": {"type": "string", "enum": ["weighted", "stop"]},
                    "field": {"type": "string", "enum": sorted(FIELD_CATALOG)},
                    "operator": {"type": "string"},
                    "value": _VALUE_SCHEMA,
                    "weight": {"type": "integer", "enum": [1, 2, 3]},
                    "soft_margin": {"type": "number"},
                    "label": {"type": "string"},
                },
            },
        },
        "okpd2_categories": {
            "type": "array",
            "items": {"type": "string", "enum": list(OKPD2_CATEGORIES)},
        },
        "company_description": {"type": "string"},
        "unparsed": {"type": "array", "items": {"type": "string"}},
    },
}


def catalog_description() -> str:
    """Каталог полей и допустимые значения для промпта."""
    lines = ["Каталог полей:"]
    for spec in FIELD_CATALOG.values():
        ops = ", ".join(sorted(spec.operators))
        line = f"- {spec.field} ({spec.label}; тип {spec.type}; группа {spec.group})"
        if spec.unit:
            line += f", единица {spec.unit}"
        line += f": операторы {ops}"
        if spec.options:
            labels = ENUM_LABELS.get(spec.field, {})
            vals = ", ".join(f"{o} = {labels.get(o, o)}" for o in spec.options)
            line += f"; значения: {vals}"
        lines.append(line)
    lines.append("\nДопустимые регионы (для region и customer.region): " + "; ".join(REGIONS))
    lines.append("\nКатегории ОКПД2 (для okpd2_categories):")
    lines.extend(f"- {name}" for name in OKPD2_CATEGORIES)
    return "\n".join(lines)


def okpd2_rule(categories: list[object], rules: list[ScoringRule]) -> ScoringRule | None:
    """Правило «коды ОКПД2 профиля» по выбранным категориям; коды, названные пользователем,
    уже стоят в его правиле — добавляем к нему. Код точнее смысла, поэтому важность 3."""
    names = [str(c) for c in categories if c in OKPD2_CATEGORIES]
    codes = codes_for(names)
    if not codes:
        return None
    own = next((r for r in rules if r.field == "okpd2_codes"), None)
    if own is not None:
        user_codes = [str(c) for c in own.value] if isinstance(own.value, list) else []
        own.value = list(dict.fromkeys([*user_codes, *codes]))
        return None
    return ScoringRule(
        id="r_okpd",
        group=FIELD_CATALOG["okpd2_codes"].group,
        kind="weighted",
        field="okpd2_codes",
        operator="prefix_in",
        value=codes,
        weight=3,
        label="Коды ОКПД2: " + "; ".join(names),
    )


def _to_result(data: JsonObject, text: str) -> tuple[ParseProfileResult | None, list[str]]:
    """Ответ модели → правила. Возвращает результат (или None) и список ошибок."""
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list):
        return None, ["Поле rules должно быть списком"]

    rules: list[ScoringRule] = []
    errors: list[str] = []
    numbers = text_numbers(text)
    for i, raw in enumerate(raw_rules, start=1):
        if not isinstance(raw, dict):
            errors.append(f"Правило {i}: не объект")
            continue
        spec = FIELD_CATALOG.get(str(raw.get("field")))
        if spec and spec.type == FieldType.money:
            bad_sums = invented_money(raw.get("value"), numbers)
            if bad_sums:
                sums = ", ".join(f"{v:.0f}" for v in bad_sums)
                errors.append(
                    f"Правило {i}: суммы {sums} нет в тексте пользователя — "
                    "перепроверь разряды (тысячи, миллионы)"
                )
                continue
        if spec and spec.field in ("region", "customer.region"):
            value = raw.get("value")
            bad = [r for r in value if r not in REGIONS] if isinstance(value, list) else []
            if bad:
                errors.append(
                    f"Правило {i}: регионов нет в справочнике: {', '.join(map(str, bad))}"
                )
                continue
        # стоп-фактор — только жёсткое условие «только …» по закону, способу или региону
        field = spec.field if spec else ""
        kind = "stop" if raw.get("kind") == "stop" and field in STOP_FIELDS else "weighted"
        try:
            rules.append(
                ScoringRule.model_validate(
                    {
                        **raw,
                        "id": f"r{i}",
                        "group": spec.group if spec else "procurement",
                        "kind": kind,
                    }
                )
            )
        except ValidationError as e:
            msgs = "; ".join(str(err["msg"]) for err in e.errors())
            errors.append(f"Правило {i} ({raw.get('label', '')}): {msgs}")

    with_paired_regions(rules)
    categories = data.get("okpd2_categories")
    okpd_rule = okpd2_rule(categories if isinstance(categories, list) else [], rules)
    if okpd_rule is not None:
        rules.append(okpd_rule)

    unparsed = data.get("unparsed")
    result = ParseProfileResult(
        rules=with_defaults(rules),
        company_description=str(data.get("company_description") or ""),
        unparsed=[str(x) for x in unparsed] if isinstance(unparsed, list) else [],
    )
    return result, errors


def _ask(
    client: LLMClient,
    prompt: Prompt,
    user_message: str,
    text: str,
    retry: list[dict[str, str]] | None = None,
) -> tuple[ParseProfileResult | None, list[str], JsonObject | None]:
    try:
        data = client.complete_json(prompt, user_message, RESPONSE_SCHEMA, extra_messages=retry)
    except LLMBadAnswer:
        return None, ["Ответ должен быть JSON-объектом по схеме"], None
    result, errors = _to_result(data, text)
    return result, errors, data


def parse_text(text: str, client: LLMClient) -> ParseProfileResult:
    if not text.strip():
        raise LLMError(ErrorCode.LLM_PARSE_FAILED, "Опишите, какие закупки вам интересны")
    prompt = load_prompt("parse_profile")
    user_message = f"{catalog_description()}\n\nТекст пользователя:\n{text.strip()}"

    try:
        result, errors, data = _ask(client, prompt, user_message, text)
        if errors or result is None:
            retry = [
                {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)},
                {
                    "role": "user",
                    "content": "Исправь ошибки и верни JSON целиком заново:\n" + "\n".join(errors),
                },
            ]
            result, errors, _ = _ask(client, prompt, user_message, text, retry)
    except LLMUnavailable as e:
        raise LLMError(ErrorCode.LLM_UNAVAILABLE, UNAVAILABLE_MESSAGE) from e

    if result is None:
        raise LLMError(ErrorCode.LLM_PARSE_FAILED, PARSE_ERROR_MESSAGE)
    # правила, которые и после повтора не прошли проверку, отдаём пользователю как неразобранные
    result.unparsed.extend(errors)
    return result
