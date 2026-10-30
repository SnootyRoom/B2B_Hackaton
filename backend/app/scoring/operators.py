"""Частичные баллы правил s ∈ [0; 1] (аналитика, «Частичный балл правила»)."""

from dataclasses import dataclass

from app.schemas.scoring import Operator, RuleValue
from app.scoring.fields import FieldValue

NUMERIC_OPERATORS = frozenset({Operator.gte, Operator.lte, Operator.between})


@dataclass(frozen=True)
class SemanticThresholds:
    """Пороги semantic_match: s = 0 при c ≤ c0, 1 при c ≥ c1. Значения — из настроек."""

    c0: float = 0.55
    c1: float = 0.80


def _norm(x: str) -> str:
    return " ".join(x.casefold().replace("ё", "е").split())


def _gte(x: float, v: float, m: float) -> float:
    if x >= v:
        return 1.0
    lo = v * (1 - m)
    if m <= 0 or x <= lo or v == lo:
        return 0.0
    return (x - lo) / (v - lo)


def _lte(x: float, v: float, m: float) -> float:
    if x <= v:
        return 1.0
    hi = v * (1 + m)
    if m <= 0 or x >= hi or hi == v:
        return 0.0
    return (hi - x) / (hi - v)


def as_number(value: RuleValue) -> float:
    if isinstance(value, list | str | bool) or value is None:
        raise ValueError("Ожидалось число")
    return float(value)


def as_pair(value: RuleValue) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("Ожидался диапазон из двух чисел")
    return float(value[0]), float(value[1])


def numeric_score(op: Operator, x: float, value: RuleValue, margin: float) -> float:
    if op == Operator.gte:
        return _gte(x, as_number(value), margin)
    if op == Operator.lte:
        return _lte(x, as_number(value), margin)
    a, b = as_pair(value)
    if x < a:
        return _gte(x, a, margin)
    if x > b:
        return _lte(x, b, margin)
    return 1.0


def semantic_score(similarity: float, t: SemanticThresholds) -> float:
    return min(1.0, max(0.0, (similarity - t.c0) / (t.c1 - t.c0)))


def boolean_holds(op: Operator, x: FieldValue, value: RuleValue) -> bool:
    """Условие выполнено? Для операторов «да/нет»."""
    vals = [_norm(str(v)) for v in value] if isinstance(value, list) else []
    if op == Operator.is_false:
        return x is False
    if op in (Operator.in_, Operator.not_in):
        hit = isinstance(x, str) and _norm(x) in vals
        return hit if op == Operator.in_ else not hit
    if op in (Operator.any_in, Operator.none_in):
        items = {_norm(i) for i in x} if isinstance(x, list) else set()
        hit = bool(items & set(vals))
        return hit if op == Operator.any_in else not hit
    if op == Operator.prefix_in:
        codes = x if isinstance(x, list) else []
        return any(c.strip().startswith(p) for c in codes for p in vals)
    if op == Operator.contains_any:
        text = _norm(x) if isinstance(x, str) else ""
        return any(v and v in text for v in vals)
    raise ValueError(f"Оператор {op} не логический")
