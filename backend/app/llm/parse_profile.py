"""Текст параметров → черновик правил (POST /scoring-profiles/parse).

LLM только предлагает правила; каждое проверяется теми же валидаторами, что и при сохранении.
При ошибке — один повтор с текстом ошибки, затем ProfileParseError с понятным сообщением.
"""

import json

from pydantic import BaseModel, Field, ValidationError

from app.llm.client import JsonObject, LLMClient, LLMUnavailable, load_prompt
from app.scoring.catalog import CATALOG_VERSION, FIELD_CATALOG
from app.scoring.defaults import with_defaults
from app.scoring.templates import ENUM_LABELS
from app.scoring.types import ScoringRule

PARSE_ERROR_MESSAGE = "Не удалось разобрать текст, задайте правила вручную"

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
                "required": ["field", "operator", "value", "weight", "soft_margin", "label"],
                "properties": {
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


class ProfileParseError(Exception):
    def __init__(self, message: str = PARSE_ERROR_MESSAGE) -> None:
        super().__init__(message)
        self.message = message


class ParsedProfile(BaseModel):
    rules: list[ScoringRule]
    company_description: str = ""
    unparsed: list[str] = Field(default_factory=list)


def catalog_description() -> str:
    """Каталог полей и допустимые значения для промпта."""
    lines = [f"Каталог полей (версия {CATALOG_VERSION}):"]
    for spec in FIELD_CATALOG.values():
        ops = ", ".join(sorted(spec.operators))
        line = f"- {spec.name} ({spec.label}; тип {spec.type}; группа {spec.group}): операторы {ops}"
        if spec.name in ENUM_LABELS:
            vals = ", ".join(f"{k} = {v}" for k, v in ENUM_LABELS[spec.name].items())
            line += f"; значения: {vals}"
        lines.append(line)
    return "\n".join(lines)


def _to_profile(data: JsonObject) -> tuple[ParsedProfile | None, list[str]]:
    """Ответ модели → правила. Возвращает профиль (или None) и список ошибок."""
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
        try:
            rules.append(
                ScoringRule.model_validate(
                    {
                        **raw,
                        "id": f"r{i}",
                        "group": spec.group if spec else "procurement",
                        "kind": "weighted",
                    }
                )
            )
        except ValidationError as e:
            msgs = "; ".join(str(err["msg"]) for err in e.errors())
            errors.append(f"Правило {i} ({raw.get('label', '')}): {msgs}")

    unparsed = data.get("unparsed")
    profile = ParsedProfile(
        rules=with_defaults(rules),
        company_description=str(data.get("company_description") or ""),
        unparsed=[str(x) for x in unparsed] if isinstance(unparsed, list) else [],
    )
    return profile, errors


def parse_profile_text(text: str, client: LLMClient) -> ParsedProfile:
    if not text.strip():
        raise ProfileParseError("Опишите, какие закупки вам интересны")
    prompt = load_prompt("parse_profile")
    user_message = f"{catalog_description()}\n\nТекст пользователя:\n{text.strip()}"

    try:
        data = client.complete_json(prompt, user_message, RESPONSE_SCHEMA)
        profile, errors = _to_profile(data)
        if errors or profile is None:
            retry = [
                {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)},
                {
                    "role": "user",
                    "content": "Исправь ошибки и верни JSON целиком заново:\n" + "\n".join(errors),
                },
            ]
            data = client.complete_json(prompt, user_message, RESPONSE_SCHEMA, extra_messages=retry)
            profile, errors = _to_profile(data)
    except LLMUnavailable as e:
        raise ProfileParseError() from e

    if profile is None:
        raise ProfileParseError()
    # правила, которые и после повтора не прошли проверку, отдаём пользователю как неразобранные
    profile.unparsed.extend(errors)
    return profile
