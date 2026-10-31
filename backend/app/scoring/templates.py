"""Шаблонные фразы обоснования по каждому оператору и форматирование значений."""

from app.schemas.score import RuleOutcome, RuleStatus
from app.schemas.scoring import (
    FIELD_CATALOG,
    FieldType,
    Operator,
    RuleKind,
    RuleValue,
    ScoringRule,
)
from app.scoring.fields import FieldValue
from app.scoring.operators import as_pair

ENUM_LABELS: dict[str, dict[str, str]] = {
    "method": {
        "auction": "аукцион",
        "contest": "конкурс",
        "quotation": "запрос котировок",
        "proposals": "запрос предложений",
        "single": "закупка у единственного поставщика",
        "other": "иной способ",
    },
    "law": {
        "44": "44-ФЗ",
        "223": "223-ФЗ",
        "615": "ПП РФ № 615",
        "94": "94-ФЗ",
        "other": "иной порядок",
    },
    "customer.status": {
        "active": "действующая",
        "reorganizing": "в процессе реорганизации",
        "liquidating": "ликвидируется",
        "liquidated": "ликвидирована",
        "bankrupt": "банкротство",
        "unknown": "статус не определён",
    },
    "restrictions": {
        "smp_only": "только для малого бизнеса",
        "national_regime": "национальный режим",
        "prefs_uis": "преимущества учреждениям УИС",
        "prefs_disabled": "преимущества организациям инвалидов",
        "other": "иные ограничения",
    },
}


def _plural(n: float, one: str, few: str, many: str) -> str:
    k = abs(int(n))
    if k % 10 == 1 and k % 100 != 11:
        return one
    if 2 <= k % 10 <= 4 and not 12 <= k % 100 <= 14:
        return few
    return many


def _num(x: float, digits: int = 1) -> str:
    s = f"{x:,.{digits}f}".replace(",", " ").replace(".", ",")
    return s.rstrip("0").rstrip(",") if "," in s else s


def fmt_money(x: float) -> str:
    """Короткий формат, как в таблице: «4,2 млн ₽»."""
    a = abs(x)
    if a >= 1e9:
        return f"{_num(x / 1e9)} млрд ₽"
    if a >= 1e6:
        return f"{_num(x / 1e6)} млн ₽"
    if a >= 1e3:
        return f"{_num(x / 1e3)} тыс. ₽"
    return f"{_num(x, 2)} ₽"


def _fmt_number(unit: str | None, v: float) -> str:
    if unit == "% НМЦК":
        return f"{_num(v)}%"
    if unit == "дн.":
        n = int(v)
        return f"{n} {_plural(n, 'день', 'дня', 'дней')}"
    if unit == "лет":
        word = _plural(v, "год", "года", "лет") if v == int(v) else "года"
        return f"{_num(v)} {word}"
    return _num(v, 2)


def fmt_value(field: str, x: object) -> str:
    spec = FIELD_CATALOG[field]
    if isinstance(x, list):
        return ", ".join(fmt_value(field, i) for i in x)
    if x is None:
        return "нет данных"
    if spec.type == FieldType.bool:
        return "есть" if x else "нет"
    if not isinstance(x, str):
        try:
            v = float(x)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return str(x)
        return fmt_money(v) if spec.type == FieldType.money else _fmt_number(spec.unit, v)
    return ENUM_LABELS.get(field, {}).get(x, x)


def _range(field: str, value: RuleValue) -> str:
    a, b = as_pair(value)
    return f"от {fmt_value(field, a)} до {fmt_value(field, b)}"


def _weighted_text(rule: ScoringRule, x: FieldValue, s: float) -> str:
    f = rule.field
    name = FIELD_CATALOG[f].label
    xv = fmt_value(f, x)
    v = rule.value
    ok = s >= 1.0
    part = "" if ok or s <= 0 else " (частично)"
    match rule.operator:
        case Operator.between:
            if ok:
                return f"{name} {xv} — в вашем диапазоне {_range(f, v)}"
            side = "ниже" if isinstance(x, int | float) and x < as_pair(v)[0] else "выше"
            return f"{name} {xv} — {side} вашего диапазона {_range(f, v)}{part}"
        case Operator.gte:
            return (
                f"{name} {xv} — не меньше {fmt_value(f, v)}"
                if ok
                else f"{name} {xv} — меньше {fmt_value(f, v)}{part}"
            )
        case Operator.lte:
            return (
                f"{name} {xv} — не больше {fmt_value(f, v)}"
                if ok
                else f"{name} {xv} — выше вашего лимита {fmt_value(f, v)}{part}"
            )
        case Operator.in_:
            vals = fmt_value(f, v)
            return (
                f"{name}: {xv} — входит в выбранные ({vals})"
                if ok
                else f"{name}: {xv} — не входит в выбранные ({vals})"
            )
        case Operator.not_in:
            return (
                f"{name}: {xv} — не из исключённых"
                if ok
                else f"{name}: {xv} — в списке исключённых"
            )
        case Operator.any_in:
            return (
                f"{name}: есть {fmt_value(f, v)}"
                if ok
                else f"{name}: нет ни одного из выбранных ({fmt_value(f, v)})"
            )
        case Operator.none_in:
            return (
                f"{name}: нет нежелательных ({fmt_value(f, v)})"
                if ok
                else f"{name}: есть нежелательные — {xv}"
            )
        case Operator.prefix_in:
            if ok:
                return f"Коды ОКПД2 {xv} совпадают с вашими ({fmt_value(f, v)})"
            if s > 0:
                return f"Коды ОКПД2 {xv} совпадают с вашими ({fmt_value(f, v)}) частично"
            return f"Коды ОКПД2 {xv} не совпадают с вашими ({fmt_value(f, v)})"
        case Operator.contains_any:
            return (
                f"Предмет закупки содержит ключевые слова ({fmt_value(f, v)})"
                if ok
                else f"Предмет закупки не содержит ключевых слов ({fmt_value(f, v)})"
            )
        case Operator.is_false:
            return f"{name}: нет" if ok else f"{name}: есть"
        case Operator.semantic_match:
            if ok:
                return f"Предмет закупки соответствует вашему профилю «{v}»"
            if s > 0:
                return f"Предмет закупки частично соответствует вашему профилю «{v}»"
            return f"Предмет закупки не соответствует вашему профилю «{v}»"
    return rule.label


def rule_text(rule: ScoringRule, res: RuleOutcome, x: FieldValue) -> str:
    if res.status == RuleStatus.disabled:
        return f"{rule.label} — правило отключено"
    if res.status == RuleStatus.no_data:
        return f"{FIELD_CATALOG[rule.field].label}: нет данных"
    if rule.kind == RuleKind.stop:
        if not res.triggered:
            return f"{rule.label} — не выявлено"
        if FIELD_CATALOG[rule.field].type == FieldType.enum:
            return f"{rule.label}: {fmt_value(rule.field, x)}"
        return rule.label
    return _weighted_text(rule, x, res.partial_score or 0.0)
