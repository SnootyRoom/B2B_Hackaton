"""Текст параметров → черновик правил (POST /scoring-profiles/parse).

LLM только предлагает правила; каждое проверяется теми же валидаторами, что и при сохранении.
При ошибке — один повтор с текстом ошибки, затем LLMError с понятным сообщением.
"""

import json

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
from app.parsers.regions import REGIONS
from app.schemas.common import ErrorCode
from app.schemas.scoring import FIELD_CATALOG, ParseProfileResult, ScoringRule
from app.scoring.defaults import with_defaults
from app.scoring.templates import ENUM_LABELS

STOP_FIELDS = frozenset({"law", "method", "region"})

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
    "required": ["rules", "company_description", "unparsed"],
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
    return "\n".join(lines)


def _to_result(data: JsonObject) -> tuple[ParseProfileResult | None, list[str]]:
    """Ответ модели → правила. Возвращает результат (или None) и список ошибок."""
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list):
        return None, ["Поле rules должно быть списком"]

    rules: list[ScoringRule] = []
    errors: list[str] = []
    for i, raw in enumerate(raw_rules, start=1):
        if not isinstance(raw, dict):
            errors.append(f"Правило {i}: не объект")
            continue
        spec = FIELD_CATALOG.get(str(raw.get("field")))
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
    retry: list[dict[str, str]] | None = None,
) -> tuple[ParseProfileResult | None, list[str], JsonObject | None]:
    try:
        data = client.complete_json(prompt, user_message, RESPONSE_SCHEMA, extra_messages=retry)
    except LLMBadAnswer:
        return None, ["Ответ должен быть JSON-объектом по схеме"], None
    result, errors = _to_result(data)
    return result, errors, data


def parse_text(text: str, client: LLMClient) -> ParseProfileResult:
    if not text.strip():
        raise LLMError(ErrorCode.LLM_PARSE_FAILED, "Опишите, какие закупки вам интересны")
    prompt = load_prompt("parse_profile")
    user_message = f"{catalog_description()}\n\nТекст пользователя:\n{text.strip()}"

    try:
        result, errors, data = _ask(client, prompt, user_message)
        if errors or result is None:
            retry = [
                {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)},
                {
                    "role": "user",
                    "content": "Исправь ошибки и верни JSON целиком заново:\n" + "\n".join(errors),
                },
            ]
            result, errors, _ = _ask(client, prompt, user_message, retry)
    except LLMUnavailable as e:
        raise LLMError(ErrorCode.LLM_UNAVAILABLE, UNAVAILABLE_MESSAGE) from e

    if result is None:
        raise LLMError(ErrorCode.LLM_PARSE_FAILED, PARSE_ERROR_MESSAGE)
    # правила, которые и после повтора не прошли проверку, отдаём пользователю как неразобранные
    result.unparsed.extend(errors)
    return result
