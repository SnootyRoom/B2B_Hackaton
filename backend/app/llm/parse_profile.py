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
from app.llm.okpd2 import OKPD2_BUNDLES, OKPD2_CLASSES, OKPD2_GROUPS, OKPD2_REMOTE
from app.parsers.regions import REGIONS
from app.schemas.common import ErrorCode
from app.schemas.scoring import (
    FIELD_CATALOG,
    FieldSpec,
    Operator,
    ParseProfileResult,
    RuleKind,
    ScoringRule,
)
from app.scoring.defaults import with_defaults
from app.scoring.templates import ENUM_LABELS

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
                    "field",
                    "operator",
                    "value",
                    "weight",
                    "soft_margin",
                    "label",
                    "strict",
                    "home_region",
                ],
                "properties": {
                    "field": {"type": "string", "enum": sorted(FIELD_CATALOG)},
                    "operator": {"type": "string"},
                    "value": _VALUE_SCHEMA,
                    "weight": {"type": "integer", "enum": [1, 2, 3]},
                    "soft_margin": {"type": "number"},
                    "label": {"type": "string"},
                    "strict": {"type": "boolean"},
                    "home_region": {"type": "boolean"},
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
    lines.append("\nКлассы ОКПД2 (для okpd2_codes):")
    lines.extend(f"- {code} {name}" for code, name in OKPD2_CLASSES.items())
    lines.append("\nЧастые группы ОКПД2 (уточнение класса):")
    lines.extend(f"- {code} {name}" for code, name in OKPD2_GROUPS.items())
    lines.append("\nНаборы кодов ОКПД2 для частых видов деятельности (бери набор целиком):")
    lines.extend(f"- {name}: {codes}" for name, codes in OKPD2_BUNDLES.items())
    return "\n".join(lines)


# Субъекты, которые для поставщика — один рынок: компания из Подмосковья работает и в Москве
_REGION_PAIRS = [
    ("Москва", "Московская область"),
    ("Санкт-Петербург", "Ленинградская область"),
    ("Севастополь", "Республика Крым"),
]


def _with_pairs(regions: list[str]) -> list[str]:
    out = list(regions)
    for a, b in _REGION_PAIRS:
        for x, y in ((a, b), (b, a)):
            if x in out and y not in out:
                out.append(y)
    return out


# Поля, по которым условие «только …» становится стоп-фактором
_STRICT_FIELDS = ("law", "method", "region")


def _strict_stop(raw: JsonObject, spec: FieldSpec) -> JsonObject | None:
    """«Работаем только по 44-ФЗ» → стоп-фактор «закупка не по 44-ФЗ»; None — не превращается.

    Взвешенное правило снимает за чужой закон 10–12 баллов, а поставщик в такой закупке
    участвовать не будет.
    """
    value = raw.get("value")
    if (
        raw.get("strict") is not True
        or spec.field not in _STRICT_FIELDS
        or raw.get("operator") != Operator.in_.value
        or not isinstance(value, list)
    ):
        return None
    if Operator.not_in in spec.operators:
        op, other = Operator.not_in, list(value)
    else:
        op, other = Operator.in_, [o for o in spec.options or [] if o not in value]
    if not other:
        return None
    return {
        **raw,
        "kind": RuleKind.stop.value,
        "operator": op.value,
        "value": other,
        "weight": None,
        "soft_margin": None,
        "label": f"Нарушено условие «{raw.get('label', '')}»",
    }


def _without_remote_home_region(rules: list[ScoringRule], home: set[str]) -> list[ScoringRule]:
    """Свой регион убирается, если все коды ОКПД2 профиля — удалённые услуги (ПО, консалтинг)."""
    codes = [
        str(c)
        for r in rules
        if r.field == "okpd2_codes" and isinstance(r.value, list)
        for c in r.value
    ]
    if not home or not codes or not all(c.startswith(OKPD2_REMOTE) for c in codes):
        return rules
    return [r for r in rules if r.id not in home]


def _to_result(data: JsonObject) -> tuple[ParseProfileResult | None, list[str]]:
    """Ответ модели → правила. Возвращает результат (или None) и список ошибок."""
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list):
        return None, ["Поле rules должно быть списком"]

    rules: list[ScoringRule] = []
    home: set[str] = set()  # id правил «Свой регион», выведенных из местонахождения компании
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
            if isinstance(value, list):
                raw = {**raw, "value": _with_pairs([str(r) for r in value])}
        if spec and spec.field == "okpd2_codes":
            value = raw.get("value")
            bad = (
                [c for c in value if str(c)[:2] not in OKPD2_CLASSES]
                if isinstance(value, list)
                else []
            )
            if bad:
                errors.append(
                    f"Правило {i}: кодов нет среди классов ОКПД2: {', '.join(map(str, bad))}"
                )
                continue
        rule = {**raw, "kind": RuleKind.weighted.value}
        is_home = (
            rule.pop("home_region", None) is True and spec is not None and spec.field == "region"
        )
        if is_home:
            # свой регион — мягкое, но важное условие: чужой регион → не выше «Рассмотреть»;
            # жёстким (стоп-фактором) он не бывает
            rule["weight"] = 3
        elif spec:
            rule = _strict_stop(rule, spec) or rule
        rule.pop("strict", None)
        try:
            rules.append(
                ScoringRule.model_validate(
                    {**rule, "id": f"r{i}", "group": spec.group if spec else "procurement"}
                )
            )
            if is_home:
                home.add(f"r{i}")
        except ValidationError as e:
            msgs = "; ".join(str(err["msg"]) for err in e.errors())
            errors.append(f"Правило {i} ({raw.get('label', '')}): {msgs}")

    unparsed = data.get("unparsed")
    result = ParseProfileResult(
        rules=with_defaults(_without_remote_home_region(rules, home)),
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
