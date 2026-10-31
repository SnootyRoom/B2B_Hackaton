"""Текст параметров → черновик правил (POST /scoring-profiles/parse).

LLM только предлагает правила; каждое проверяется теми же валидаторами, что и при сохранении.
При ошибке — один повтор с текстом ошибки, затем LLMError с понятным сообщением.
"""

import json
import re

from pydantic import ValidationError

from app.core.config import get_settings
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
from app.llm.okpd2_search import group_code, okpd2_candidates, okpd2_name
from app.parsers.regions import REGIONS
from app.schemas.common import ErrorCode
from app.schemas.scoring import (
    FIELD_CATALOG,
    FieldSpec,
    FieldType,
    Operator,
    ParseProfileResult,
    ScoringRule,
)
from app.scoring.defaults import DEFAULT_RULE_IDS, with_defaults
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


# «Работаем по всей России» — регион компании не важен
_NATIONWIDE = re.compile(r"по всей (росси|стран)|в любом регионе|в любых регионах|во всех регионах")


def without_needless_regions(rules: list[ScoringRule], text: str) -> list[ScoringRule]:
    """Убирает правила о регионе, которые ничего не проверяют: список из всех регионов и,
    если компания работает по всей России, правило «Свой регион». Явное «интересны закупки в …»
    (важность 3) остаётся. Так ответ не зависит от того, как модель поняла «по всей России»."""
    nationwide = bool(_NATIONWIDE.search(text.casefold()))

    def needless(r: ScoringRule) -> bool:
        if r.field != "region" or r.kind != "weighted" or not isinstance(r.value, list):
            return False
        return len(set(r.value)) >= len(REGIONS) or (nationwide and (r.weight or 0) < 3)

    return [r for r in rules if not needless(r)]


def only_to_stop(raw: JsonObject, spec: FieldSpec) -> JsonObject:
    """«Только 44-ФЗ»: модель называет допустимые значения, программа строит стоп-фактор на все
    остальные. Перечислять «все кроме» модель не просим: на длинных списках она зацикливается."""
    value = raw.get("value")
    allowed = [str(v) for v in value] if isinstance(value, list) else [str(value)]
    if Operator.not_in in spec.operators:
        return {**raw, "operator": Operator.not_in, "value": allowed}
    others = [o for o in spec.options or [] if o not in allowed]
    return {**raw, "operator": Operator.in_, "value": others}


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
                    "kind": {"type": "string", "enum": ["weighted", "only"]},
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


def okpd2_rule(codes: list[str], names: list[str], rules: list[ScoringRule]) -> ScoringRule | None:
    """Правило «коды ОКПД2 профиля»; коды, названные пользователем, уже стоят в его правиле —
    добавляем к нему. Код точнее смысла, поэтому важность 3."""
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
        kind = "weighted"
        if raw.get("kind") in ("only", "stop") and spec and field in STOP_FIELDS:
            kind = "stop"
            if raw.get("kind") == "only":
                raw = only_to_stop(raw, spec)
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

    rules = without_needless_regions(rules, text)
    with_paired_regions(rules)

    unparsed = data.get("unparsed")
    result = ParseProfileResult(
        rules=with_defaults(rules),
        company_description=str(data.get("company_description") or ""),
        unparsed=[str(x) for x in unparsed] if isinstance(unparsed, list) else [],
    )
    return result, errors


def activities(result: ParseProfileResult) -> list[str]:
    """Описания деятельности для поиска кодов: значения правил «предмет по смыслу», иначе
    описание компании."""
    found = [
        r.value.strip()
        for r in result.rules
        if r.field == "subject"
        and r.operator == Operator.semantic_match
        and isinstance(r.value, str)
        and r.value.strip()
    ]
    if found:
        return list(dict.fromkeys(found))
    return [result.company_description.strip()] if result.company_description.strip() else []


def without_nested(codes: list[str]) -> list[str]:
    """Убирает коды, у которых выбран и родитель: «28.9» покрывает «28.93» и «28.93.15» — так же,
    по началу кода, сравнивает и prefix_in."""
    return [c for c in codes if not any(c != p and c.startswith(p) for p in codes)]


def pick_okpd2(
    client: LLMClient, texts: list[str], candidates: list[tuple[str, str]]
) -> list[str] | None:
    """Шаг 2: LLM выбирает подходящие коды из кандидатов (можно ни одного). Код не из списка
    модель вернуть не может — схема перечисляет кандидатов. Сбой — один повтор, затем None."""
    allowed = [code for code, _ in candidates]
    schema: JsonObject = {
        "type": "object",
        "additionalProperties": False,
        "required": ["codes"],
        "properties": {"codes": {"type": "array", "items": {"type": "string", "enum": allowed}}},
    }
    message = (
        "Деятельность компании:\n"
        + "\n".join(f"- {t}" for t in texts)
        + "\n\nКоды-кандидаты:\n"
        + "\n".join(f"{code} — {name}" for code, name in candidates)
    )
    prompt = load_prompt("okpd2_pick")
    for _ in range(2):
        try:
            data = client.complete_json(prompt, message, schema)
        except (LLMBadAnswer, LLMUnavailable):
            continue
        raw = data.get("codes")
        if isinstance(raw, list):
            picked = [c for c in dict.fromkeys(str(x) for x in raw) if c in allowed]
            return without_nested(picked)
    return None


def hybrid_okpd2(client: LLMClient, texts: list[str]) -> tuple[list[str], list[str]] | None:
    """Коды ОКПД2 по полному справочнику: кандидаты по смыслу (шаг 1) → выбор LLM (шаг 2).
    None — справочника или модели эмбеддингов нет, работает запасной путь по категориям.
    Сбой шага 2 даёт пустой список: профиль без кода лучше, чем с неверным кодом."""
    if not texts:
        return None
    candidates = okpd2_candidates(texts, get_settings().okpd2_candidates_k)
    if not candidates:
        return None
    picked = pick_okpd2(client, texts, candidates) or []
    # выбранная подгруппа или вид → группа: точный код пропускает свои закупки соседних видов
    codes = without_nested(list(dict.fromkeys(group_code(c) for c in picked)))
    names = dict(candidates)
    return codes, [okpd2_name(c) or names.get(c, c) for c in codes]


def add_okpd2_rule(result: ParseProfileResult, client: LLMClient, categories: list[str]) -> None:
    """Правило r_okpd: по полному справочнику, а без него — по категориям ручного справочника."""
    picked = hybrid_okpd2(client, activities(result))
    known = [c for c in categories if c in OKPD2_CATEGORIES]
    if picked is None:
        codes, names = codes_for(known), known
    else:
        codes, names = picked
        if get_settings().okpd2_with_categories and known:
            codes = without_nested(list(dict.fromkeys([*codes_for(known), *codes])))
            names = [*known, *names]
    rule = okpd2_rule(codes, names, result.rules)
    if rule is None:
        return
    # перед правилами по умолчанию — там, где оно стояло раньше
    defaults_at = (i for i, r in enumerate(result.rules) if r.id in DEFAULT_RULE_IDS)
    at = next(defaults_at, len(result.rules))
    result.rules.insert(at, rule)


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
            result, errors, data = _ask(client, prompt, user_message, text, retry)
    except LLMUnavailable as e:
        raise LLMError(ErrorCode.LLM_UNAVAILABLE, UNAVAILABLE_MESSAGE) from e

    if result is None:
        raise LLMError(ErrorCode.LLM_PARSE_FAILED, PARSE_ERROR_MESSAGE)
    categories = (data or {}).get("okpd2_categories")
    names = [str(c) for c in categories] if isinstance(categories, list) else []
    add_okpd2_rule(result, client, names)
    # правила, которые и после повтора не прошли проверку, отдаём пользователю как неразобранные
    result.unparsed.extend(errors)
    return result
