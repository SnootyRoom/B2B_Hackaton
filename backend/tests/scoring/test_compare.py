from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.schemas.score import Recommendation
from app.schemas.scoring import (
    FIELD_CATALOG,
    Operator,
    RuleKind,
    ScoringProfileData,
    ScoringRule,
    Thresholds,
)
from app.scoring import extract_fields, score
from app.scoring.compare import explain_difference, profile_version
from app.scoring.defaults import (
    STRATEGY_RULE_IDS,
    TEMPLATES,
    apply_strategy,
    template_profile,
    with_defaults,
)

NOW = datetime(2026, 11, 11, 12, tzinfo=UTC)


def nmck_rule(hi: int) -> ScoringRule:
    return ScoringRule(
        id="r_sum",
        group=FIELD_CATALOG["nmck"].group,
        kind=RuleKind.weighted,
        field="nmck",
        operator=Operator.lte,
        value=Decimal(hi),
        weight=3,
        label=f"НМЦК до {hi // 1_000_000} млн ₽",
    )


METHOD_RULE = ScoringRule(
    id="r_method",
    group=FIELD_CATALOG["method"].group,
    kind=RuleKind.weighted,
    field="method",
    operator=Operator.in_,
    value=["auction"],
    weight=3,
    label="Аукционы",
)


def with_sum(profile: ScoringProfileData, hi: int) -> ScoringProfileData:
    return profile.model_copy(update={"rules": [nmck_rule(hi), METHOD_RULE, *profile.rules]})


def fields(
    status: str = "active", nmck: int = 4_000_000, flags: list[str] | None = None
) -> dict[str, object]:
    lot = {
        "reg_number": "0365000000000000001",
        "subject": "Поставка канцелярских товаров",
        "nmck": Decimal(nmck),
        "method": "auction",
        "application_deadline": NOW + timedelta(days=10),
    }
    customer = {
        "inn": "7017000000",
        "name": "Заказчик",
        "status": status,
        "registration_date": "2010-01-01",
        "unreliable_flags": flags or [],
    }
    return extract_fields(lot, customer, NOW)  # type: ignore[return-value]


CAUTIOUS = template_profile("cautious")
AGGRESSIVE = template_profile("aggressive")


def test_templates_are_valid_and_differ() -> None:
    assert set(TEMPLATES) == {"cautious", "aggressive"}
    assert CAUTIOUS.name == "Осторожный" and AGGRESSIVE.name == "Агрессивный"
    assert CAUTIOUS.thresholds.participate > AGGRESSIVE.thresholds.participate
    # шаблон меняет свою копию правил, а не общие правила по умолчанию
    stop = next(r for r in with_defaults([]) if r.id == "stop_customer_status")
    assert "reorganizing" not in stop.value  # type: ignore[operator]
    with pytest.raises(KeyError):
        template_profile("unknown")


def test_reorganizing_customer_is_stop_only_in_cautious() -> None:
    f = fields(status="reorganizing")
    a, b = score(CAUTIOUS, f), score(AGGRESSIVE, f)  # type: ignore[arg-type]
    assert a.recommendation == Recommendation.skip and a.stop_factors
    assert b.recommendation != Recommendation.skip


def test_version_ignores_name_but_not_rules() -> None:
    v = profile_version(CAUTIOUS)
    assert v == profile_version(template_profile("cautious"))
    assert v == profile_version(CAUTIOUS.model_copy(update={"name": "Другое имя"}))
    assert v != profile_version(with_sum(CAUTIOUS, 5_000_000))
    other = CAUTIOUS.model_copy(update={"thresholds": Thresholds(participate=80, consider=50)})
    assert v != profile_version(other)


def test_version_changes_with_engine_calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config

    v = profile_version(CAUTIOUS)
    s = config.get_settings()
    monkeypatch.setattr(s, "semantic_c0", s.semantic_c0 - 0.01)
    assert profile_version(CAUTIOUS) != v


def test_same_result_gives_empty_explanation() -> None:
    r = score(CAUTIOUS, fields())  # type: ignore[arg-type]
    assert explain_difference(r, r, CAUTIOUS, CAUTIOUS) == ""


def test_stop_factor_is_first_reason() -> None:
    f = fields(status="reorganizing")
    a, b = score(CAUTIOUS, f), score(AGGRESSIVE, f)  # type: ignore[arg-type]
    text = explain_difference(a, b, CAUTIOUS, AGGRESSIVE)
    assert text.startswith("«Осторожный»: Пропустить, 0%; «Агрессивный»:")
    assert "В профиле «Осторожный» сработал стоп-фактор" in text
    assert "[stop_customer_status]" in text
    assert "в профиле «Агрессивный» условие другое и не сработало" in text


def test_different_sum_ranges_name_both_conditions() -> None:
    pa, pb = with_sum(CAUTIOUS, 5_000_000), with_sum(AGGRESSIVE, 30_000_000)
    f = fields(nmck=12_000_000)
    a, b = score(pa, f), score(pb, f)  # type: ignore[arg-type]
    text = explain_difference(a, b, pa, pb)
    assert (
        "Условие «НМЦК до 5 млн ₽» не выполнено в профиле «Осторожный» [r_sum], "
        "а «НМЦК до 30 млн ₽» выполнено в профиле «Агрессивный» [r_sum] (НМЦК: 12 млн ₽)."
    ) in text


def test_sum_far_outside_range_is_named_as_cap() -> None:
    pa, pb = with_sum(CAUTIOUS, 5_000_000), with_sum(AGGRESSIVE, 30_000_000)
    f = fields(nmck=25_000_000)
    a, b = score(pa, f), score(pb, f)  # type: ignore[arg-type]
    assert a.recommendation == Recommendation.skip
    text = explain_difference(a, b, pa, pb)
    assert "В профиле «Осторожный» сумма далеко за пределами условия «НМЦК до 5 млн ₽»" in text


def test_rule_only_in_one_profile() -> None:
    pa = with_sum(CAUTIOUS, 5_000_000)
    f = fields(nmck=12_000_000)
    a, b = score(pa, f), score(CAUTIOUS, f)  # type: ignore[arg-type]
    text = explain_difference(a, b, pa, CAUTIOUS.model_copy(update={"name": "Без суммы"}))
    assert (
        "есть условие «НМЦК до 5 млн ₽» [r_sum] и оно не выполнено (НМЦК: 12 млн ₽), "
        "в профиле «Без суммы» такого условия нет"
    ) in text


def test_thresholds_named_when_they_change_recommendation() -> None:
    strict = Thresholds(participate=75, consider=60)
    pa = AGGRESSIVE.model_copy(update={"name": "Строгий", "thresholds": strict})
    f = fields(flags=["недостоверный адрес"])  # оценка между порогами двух профилей
    a, b = score(pa, f), score(AGGRESSIVE, f)  # type: ignore[arg-type]
    assert a.total == b.total and a.recommendation != b.recommendation
    text = explain_difference(a, b, pa, AGGRESSIVE)
    assert (
        "Пороги разные: «Участвовать» от 75 в профиле «Строгий» и от 60 в профиле "
        "«Агрессивный», «Рассмотреть» от 60 и от 30" in text
    )


def test_reasons_sorted_by_impact_and_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.scoring import compare

    pa, pb = with_sum(CAUTIOUS, 5_000_000), with_sum(AGGRESSIVE, 30_000_000)
    f = fields(status="reorganizing", nmck=12_000_000)
    a, b = score(pa, f), score(pb, f)  # type: ignore[arg-type]
    full = explain_difference(a, b, pa, pb)
    assert full == explain_difference(a, b, pa, pb)  # детерминизм
    assert full.index("стоп-фактор") < full.index("(НМЦК: 12 млн ₽)")
    monkeypatch.setattr(compare, "MAX_REASONS", 1)
    short = explain_difference(a, b, pa, pb)
    assert "стоп-фактор" in short and "(НМЦК: 12 млн ₽)" not in short


def own_profile() -> ScoringProfileData:
    """Профиль компании: свои условия о сумме и способе + правила по умолчанию."""
    p = with_sum(ScoringProfileData(rules=with_defaults([])), 5_000_000)
    return p.model_copy(update={"name": "Мой профиль", "company_description": "Канцтовары"})


def test_strategy_keeps_company_conditions() -> None:
    mine = own_profile()
    bold = apply_strategy(mine, "aggressive")
    assert bold.name == "Мой профиль" and bold.company_description == "Канцтовары"
    assert bold.group_weights == mine.group_weights
    assert bold.thresholds == AGGRESSIVE.thresholds
    rules = {r.id: r for r in bold.rules}
    assert rules["r_sum"] == nmck_rule(5_000_000) and rules["r_method"] == METHOD_RULE
    strategy = {r.id: r for r in AGGRESSIVE.rules}
    for rule_id in STRATEGY_RULE_IDS:
        assert rules[rule_id] == strategy[rule_id]
    assert [r.id for r in bold.rules] == [r.id for r in mine.rules]  # порядок прежний


def test_strategy_does_not_change_source_profile() -> None:
    mine = own_profile()
    before = mine.model_dump()
    apply_strategy(mine, "cautious")
    assert mine.model_dump() == before


def test_strategy_keeps_disabled_rule_disabled_and_adds_missing() -> None:
    mine = own_profile()
    rules = [
        r.model_copy(update={"enabled": False}) if r.id == "customer_age" else r
        for r in mine.rules
        if r.id != "customer_reliable"
    ]
    careful = apply_strategy(mine.model_copy(update={"rules": rules}), "cautious")
    by_id = {r.id: r for r in careful.rules}
    assert by_id["customer_age"].enabled is False and by_id["customer_age"].weight == 3
    assert "customer_reliable" in by_id


def test_strategy_changes_recommendation_for_reorganizing_customer() -> None:
    mine = own_profile()
    f = fields(status="reorganizing")
    careful, bold = apply_strategy(mine, "cautious"), apply_strategy(mine, "aggressive")
    a, b = score(careful, f), score(bold, f)  # type: ignore[arg-type]
    assert a.recommendation == Recommendation.skip
    assert b.recommendation == Recommendation.participate
    assert profile_version(careful) != profile_version(bold)


def test_unknown_strategy() -> None:
    with pytest.raises(KeyError):
        apply_strategy(own_profile(), "unknown")
