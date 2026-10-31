from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.score import Recommendation, RuleStatus
from app.schemas.scoring import (
    FIELD_CATALOG,
    GroupWeights,
    Operator,
    RuleKind,
    ScoringProfileData,
    ScoringRule,
)
from app.schemas.scoring import RuleGroup as Group
from app.scoring import default_profile, extract_fields, score, with_defaults
from app.scoring.operators import SemanticThresholds, numeric_score, semantic_score

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)


def rule(
    id: str, field: str, op: Operator, value: object, weight: int = 3, **kw: object
) -> ScoringRule:
    return ScoringRule(
        id=id,
        group=FIELD_CATALOG[field].group,
        kind=kw.pop("kind", RuleKind.weighted),  # type: ignore[arg-type]
        field=field,
        operator=op,
        value=value,  # type: ignore[arg-type]
        weight=weight,
        label=id,
        **kw,  # type: ignore[arg-type]
    )


def procurement(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "reg_number": "0365000000000000001",
        "subject": "Сопровождение программного обеспечения",
        "nmck": Decimal(4200000),
        "method": "auction",
        "region": "Томская область",
        "application_deadline": NOW + timedelta(days=10),
        "contract_security": Decimal(210000),
        "okpd2_codes": ["62.01.11.000"],
    }
    base.update(over)
    return base


GOOD_CUSTOMER = {
    "inn": "7017000000",
    "status": "active",
    "registration_date": "2010-01-01",
    "unreliable_flags": [],
    "region": "Томская область",
}


# --- частичные баллы -------------------------------------------------------


def test_gte_soft_margin() -> None:
    # возраст ≥ 3, допуск 0,67: 1 год → 0, 2 года → ≈ 0,5, 3 → 1
    assert numeric_score(Operator.gte, 3, 3, 0.67) == 1
    assert numeric_score(Operator.gte, 1, 3, 0.67) == pytest.approx(0, abs=0.01)
    assert numeric_score(Operator.gte, 2, 3, 0.67) == pytest.approx(0.5, abs=0.01)


def test_lte_and_between() -> None:
    assert numeric_score(Operator.lte, 12, 10, 0.2) == pytest.approx(0.0)
    assert numeric_score(Operator.lte, 11, 10, 0.2) == pytest.approx(0.5)
    assert numeric_score(Operator.lte, 11, 10, 0.0) == 0
    assert numeric_score(Operator.between, 5, [1, 10], 0.2) == 1
    assert numeric_score(Operator.between, 0.9, [1, 10], 0.2) == pytest.approx(0.5)
    assert numeric_score(Operator.between, 11, [1, 10], 0.2) == pytest.approx(0.5)


def test_semantic_linear() -> None:
    t = SemanticThresholds()
    assert semantic_score(0.5, t) == 0
    assert semantic_score(0.675, t) == pytest.approx(0.5)
    assert semantic_score(0.9, t) == 1


# --- итог и группы ---------------------------------------------------------


def test_analytics_example_78() -> None:
    # закупка 80, соответствие 60, заказчик 100 при 0,40 / 0,35 / 0,25 → 78 → «Участвовать»
    fields = {
        "nmck": 5.0,
        "region": "A",
        "okpd2_codes": ["62.01"],
        "subject": "x",
        "customer.status": "active",
    }
    prof = ScoringProfileData(
        rules=[
            rule("p1", "nmck", Operator.gte, 1, weight=3),  # 1
            rule("p2", "nmck", Operator.gte, 1, weight=1),  # 1
            rule("p3", "region", Operator.in_, ["B"], weight=1),  # 0  → 4/5 = 80
            rule("f1", "okpd2_codes", Operator.prefix_in, ["62"], weight=3),  # 1
            rule("f2", "subject", Operator.contains_any, ["нет"], weight=2),  # 0 → 3/5 = 60
            rule("c1", "customer.status", Operator.in_, ["active"]),  # 100
        ]
    )
    r = score(prof, fields)
    assert [g.score for g in r.groups] == [80, 60, 100]
    assert r.total == 78
    assert r.recommendation == Recommendation.participate
    assert sum(x.contribution or 0 for x in r.rules) == pytest.approx(78, abs=0.01)


def test_okpd2_weighted_rule_is_share_of_codes() -> None:
    # одна случайно совпавшая позиция из четырёх — не профильная закупка
    prof = ScoringProfileData(
        rules=[rule("f1", "okpd2_codes", Operator.prefix_in, ["20.59"], weight=3)]
    )
    codes = ["22.29.25.000", "17.23.13.199", "32.99.12.110", "20.59.59.900"]
    r = score(prof, {"okpd2_codes": codes})
    assert r.rules[0].partial_score == pytest.approx(0.25)
    assert "частично" in r.rules[0].text


def test_okpd2_share_by_cost_when_items_priced() -> None:
    # капремонт на 41 млн ₽ и светильники на 2 млн ₽: профильная закупка, хотя код у 1 из 2 позиций
    prof = ScoringProfileData(
        rules=[rule("f1", "okpd2_codes", Operator.prefix_in, ["41.20"], weight=3)]
    )
    procurement = {
        "subject": "Капитальный ремонт здания",
        "nmck": 43_000_000,
        "okpd2_codes": ["41.20.40.000", "27.40.25.123"],
        "items": [
            {"name": "Капремонт", "okpd2": "41.20.40.000", "price": 41_000_000, "quantity": 1},
            {"name": "Светильник", "okpd2": "27.40.25.123", "price": 1000, "quantity": 2000},
        ],
    }
    r = score(prof, extract_fields(procurement, None, NOW))
    assert r.rules[0].partial_score == pytest.approx(41 / 43)
    # цена известна у одной позиции из трёх → доля кодов закупки (1 из 2)
    procurement["items"][1]["price"] = None  # type: ignore[index]
    procurement["items"].append(  # type: ignore[attr-defined]
        {"name": "Огнетушитель", "okpd2": "28.29.22.110", "price": None, "quantity": 1}
    )
    r = score(prof, extract_fields(procurement, None, NOW))
    assert r.rules[0].partial_score == pytest.approx(0.5)


def _limit_profile(region_weight: int) -> ScoringProfileData:
    return ScoringProfileData(
        rules=[
            rule("p1", "nmck", Operator.gte, 1, weight=3),
            rule("p2", "region", Operator.in_, ["Томская область"], weight=region_weight),
            rule("f1", "okpd2_codes", Operator.prefix_in, ["62"], weight=3),
            rule("c1", "customer.status", Operator.in_, ["active"]),
        ]
    )


def test_subject_mismatch_caps_to_skip() -> None:
    # сумма, регион и заказчик подходят (без ограничения было бы 65), но предмет чужой
    fields = {"nmck": 5.0, "region": "Томская область", "okpd2_codes": ["10.51"],
              "customer.status": "active"}  # fmt: skip
    r = score(_limit_profile(3), fields)
    assert r.total == 39
    assert r.recommendation == Recommendation.skip
    assert "Оценка ограничена: предмет закупки не соответствует профилю" in r.justification


def test_semantic_only_mismatch_does_not_cap() -> None:
    # без кодов ОКПД2 и ключевых слов предмет не отсекаем: близость e5 одна ненадёжна
    prof = ScoringProfileData(
        rules=[
            rule("p1", "nmck", Operator.gte, 1, weight=3),
            rule("f1", "subject", Operator.semantic_match, "разработка ПО", weight=3),
            rule("c1", "customer.status", Operator.in_, ["active"]),
        ]
    )
    fields = {"nmck": 5.0, "subject": "Поставка молока", "customer.status": "active"}
    r = score(prof, fields, similarity=lambda _t, _q: 0.0)
    assert r.total == 65
    assert "Оценка ограничена" not in r.justification


def test_failed_important_condition_caps_to_consider() -> None:
    fields = {"nmck": 5.0, "region": "Москва", "okpd2_codes": ["62.01"],
              "customer.status": "active"}  # fmt: skip
    r = score(_limit_profile(3), fields)
    assert r.total == 69
    assert r.recommendation == Recommendation.consider
    assert "не выполнено важное условие" in r.justification and "[p2]" in r.justification
    # то же условие средней важности оценку не ограничивает
    r2 = score(_limit_profile(2), fields)
    assert r2.recommendation == Recommendation.participate and r2.total > 69


def test_stop_factor_zeroes_total() -> None:
    p = procurement(application_deadline=NOW - timedelta(hours=1))
    r = score(default_profile(), extract_fields(p, GOOD_CUSTOMER, NOW))
    assert r.total == 0
    assert r.recommendation == Recommendation.skip
    assert r.stop_factors == ["stop_deadline"]
    assert r.justification.startswith("Рекомендация: Пропустить")
    assert "[stop_deadline]" in r.justification


def test_liquidating_customer_is_stop() -> None:
    c = {**GOOD_CUSTOMER, "status": "liquidating"}
    r = score(default_profile(), extract_fields(procurement(), c, NOW))
    assert r.stop_factors == ["stop_customer_status"]
    assert r.total == 0


def test_missing_field_skipped_and_group_excluded() -> None:
    prof = ScoringProfileData(
        group_weights=GroupWeights(procurement=0.4, fit=0.35, customer=0.25),
        rules=with_defaults([rule("p1", "nmck", Operator.between, [1_000_000, 10_000_000])]),
    )
    # заказчик неизвестен → группа «Заказчик» исключена, вес переходит «Закупке»
    r = score(prof, extract_fields(procurement(), None, NOW))
    cust = next(g for g in r.groups if g.group == Group.customer)
    assert cust.score is None and cust.low_data
    assert r.total == 100
    assert r.incomplete
    assert all(x.status == RuleStatus.no_data for x in r.rules if x.group == Group.customer)


def test_low_data_flag_threshold() -> None:
    prof = ScoringProfileData(
        rules=[
            rule("a", "nmck", Operator.gte, 1, weight=1),
            rule("b", "delivery_days", Operator.lte, 30, weight=2),
        ]
    )
    r = score(prof, {"nmck": 10.0, "delivery_days": None})
    g = next(g for g in r.groups if g.group == Group.procurement)
    assert g.low_data and g.score == 100


def test_disabled_rule_ignored() -> None:
    prof = ScoringProfileData(
        rules=[
            rule("a", "nmck", Operator.gte, 1),
            rule("b", "region", Operator.in_, ["X"], enabled=False),
        ]
    )
    r = score(prof, {"nmck": 10.0, "region": "Y"})
    assert r.total == 100
    assert r.rules[1].status == RuleStatus.disabled


def test_semantic_uses_similarity_and_missing_provider_is_no_data() -> None:
    prof = ScoringProfileData(
        rules=[rule("s", "subject", Operator.semantic_match, "разработка ПО")]
    )
    r = score(
        prof,
        {"subject": "сопровождение ПО"},
        similarity=lambda a, b: 0.675,
        semantic=SemanticThresholds(0.55, 0.80),
    )
    assert r.total == 50
    r2 = score(prof, {"subject": "сопровождение ПО"})
    assert r2.rules[0].status == RuleStatus.no_data


def test_no_data_at_all_means_consider_incomplete() -> None:
    # профиль по умолчанию, а данных о заказчике нет: ни одно правило не проверено
    r = score(default_profile(), extract_fields(procurement(), None, NOW))
    assert r.recommendation == Recommendation.consider
    assert r.incomplete and r.total == 0
    assert all(g.score is None for g in r.groups)
    assert "проверьте закупку вручную" in r.justification
    assert "оценка 0%" not in r.justification


def test_stop_factor_wins_over_no_data() -> None:
    p = procurement(application_deadline=NOW - timedelta(days=1))
    r = score(default_profile(), extract_fields(p, None, NOW))
    assert r.recommendation == Recommendation.skip
    assert r.stop_factors == ["stop_deadline"]


def test_digit_codes_stay_strings() -> None:
    r = ScoringRule.model_validate(
        {"id": "o", "group": "fit", "kind": "weighted", "field": "okpd2_codes",
         "operator": "prefix_in", "value": ["62", "63.11"], "weight": 2, "label": "ОКПД2"}
    )  # fmt: skip
    assert r.value == ["62", "63.11"]
    res = score(ScoringProfileData(rules=[r]), {"okpd2_codes": ["62.01.11.000"]})
    assert res.rules[0].partial_score == 1


def test_given_security_pct_is_preferred() -> None:
    f = extract_fields(procurement(contract_security_pct=Decimal(7)), None, NOW)
    assert f["contract_security_pct"] == 7


def test_deterministic() -> None:
    f = extract_fields(procurement(), GOOD_CUSTOMER, NOW)
    assert score(default_profile(), f) == score(default_profile(), f)


def test_derived_fields() -> None:
    f = extract_fields(procurement(), GOOD_CUSTOMER, NOW)
    assert f["contract_security_pct"] == pytest.approx(5.0)
    assert f["days_to_deadline"] == pytest.approx(10.0)
    assert f["customer.has_unreliable_flags"] is False
    assert f["customer.age_years"] == pytest.approx(16.8, abs=0.1)


def test_justification_mentions_values_and_rules() -> None:
    prof = ScoringProfileData(
        rules=with_defaults(
            [
                rule("nmck", "nmck", Operator.between, [1_000_000, 10_000_000]),
                rule("sec", "contract_security_pct", Operator.lte, 3, weight=2),
            ]
        )
    )
    r = score(prof, extract_fields(procurement(), GOOD_CUSTOMER, NOW))
    assert "4,2 млн ₽" in r.justification
    assert "НМЦК 4,2 млн ₽" in r.justification  # аббревиатура не портится
    assert "[nmck]" in r.justification and "[sec]" in r.justification


# --- валидация профиля -----------------------------------------------------


@pytest.mark.parametrize(
    ("field", "op", "value"),
    [
        ("unknown", Operator.gte, 1),
        ("nmck", Operator.in_, ["1"]),  # оператор недопустим
        ("nmck", Operator.between, [10, 1]),  # левая > правой
        ("nmck", Operator.gte, "много"),  # тип значения
        ("region", Operator.in_, []),
    ],
)
def test_invalid_rule(field: str, op: Operator, value: object) -> None:
    with pytest.raises(ValidationError):
        ScoringRule(
            id="x",
            group=Group.procurement,
            kind=RuleKind.weighted,
            field=field,
            operator=op,
            value=value,
            weight=1,
            label="x",
        )  # type: ignore[arg-type]


def test_zero_group_weights_invalid() -> None:
    with pytest.raises(ValidationError):
        GroupWeights(procurement=0, fit=0, customer=0)
