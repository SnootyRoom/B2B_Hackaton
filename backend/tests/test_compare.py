"""Задача A: сравнение двух профилей, объяснение разницы, шаблоны."""

import json
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from app.schemas.score import Recommendation, RuleOutcome, RuleStatus, ScoreResultData
from app.schemas.scoring import Operator, RuleGroup, RuleKind, ScoringProfileData, Thresholds
from app.scoring.defaults import STOP_REORGANIZING, default_profile, template_profile
from app.scoring.difference import explain_difference
from tests.conftest import make_client

P = "/api/scoring-profiles"
NMCK_RULE = {
    "id": "nmck_range",
    "group": "procurement",
    "kind": "weighted",
    "field": "nmck",
    "operator": "between",
    "value": [1_000_000, 3_000_000],
    "weight": 3,
    "label": "НМЦК в диапазоне",
}


def _notice(n: int) -> bytes:
    return json.dumps(
        {
            "reg_number": f"03650000000000000{n:02d}",
            "law": "44",
            "subject": "Сопровождение программного обеспечения",
            "nmck": 1_000_000 * n,
            "method": "auction",
            "customer_inn": "7017000019",
            "region": "Томская область",
        }
    ).encode()


def _setup(client: TestClient) -> tuple[str, str]:
    """Активный «Мой профиль» с диапазоном 1–3 млн и «Агрессивный» из шаблона."""
    files = [("files", (f"{i}.json", _notice(i), "application/json")) for i in range(1, 10)]
    assert client.post("/api/procurements/upload", files=files).status_code == 202
    active = client.get(f"{P}/active").json()
    body = {**active, "rules": [*active["rules"], NMCK_RULE], "rescore": True}
    assert client.put(f"{P}/active", json=body).status_code == 200
    aggressive = client.post(P, json={"name": "Агрессивный", "template": "aggressive"}).json()
    return active["id"], aggressive["id"]


def _compare(client: TestClient, a: str, b: str) -> dict[str, Any]:
    r = client.get("/api/results/compare", params={"a": a, "b": b})
    assert r.status_code == 200, r.text
    return r.json()


def test_compare_flow(client: TestClient) -> None:
    a, b = _setup(client)

    before = _compare(client, a, b)
    assert before["missing"] == 9  # у «Агрессивного» оценок ещё нет
    assert before["summary"]["unknown"] == 9
    assert all(r["b"]["total"] is None and r["b"]["stale"] for r in before["rows"])

    client.post("/api/score", json={"profile_id": b, "only_stale": True})
    after = _compare(client, a, b)
    assert after["missing"] == 0
    s = after["summary"]
    assert s["better"] + s["worse"] + s["same"] == 9
    assert s["better"] >= 1
    assert s["unknown"] == 0

    # Сначала изменившиеся, у них есть объяснение со ссылкой на правило
    first = after["rows"][0]
    assert first["change"] == "better"
    assert first["delta"] == first["b"]["total"] - first["a"]["total"]
    assert "«Агрессивный»" in first["explanation"]
    assert "[" in first["explanation"]
    changed = [r["change"] for r in after["rows"]]
    assert changed == sorted(changed, key=lambda c: c == "same")

    assert _compare(client, a, b) == after  # детерминизм


def test_compare_same_profile(client: TestClient) -> None:
    a, _ = _setup(client)
    res = _compare(client, a, a)
    assert res["summary"]["same"] == 9
    assert all(r["explanation"] == "" and r["delta"] == 0 for r in res["rows"])


def test_compare_edit_makes_unknown(client: TestClient) -> None:
    a, b = _setup(client)
    client.post("/api/score", json={"profile_id": b, "only_stale": True})
    full = client.get(f"{P}/{b}").json()
    client.put(f"{P}/{b}", json={**full, "thresholds": {"participate": 95, "consider": 5}})
    res = _compare(client, a, b)
    assert res["missing"] == 9
    assert res["summary"]["unknown"] == 9


def test_compare_foreign_profile_404(client: TestClient) -> None:
    other = make_client("other@example.com")
    foreign = other.get(f"{P}/active").json()["id"]
    mine = client.get(f"{P}/active").json()["id"]
    r = client.get("/api/results/compare", params={"a": mine, "b": foreign})
    assert r.status_code == 404


# ---------- шаблоны


def _base_with_nmck() -> ScoringProfileData:
    base = default_profile()
    data = base.model_dump(mode="json")
    data["rules"].append(NMCK_RULE)
    return ScoringProfileData.model_validate(data)


def test_template_cautious() -> None:
    t = template_profile("cautious", _base_with_nmck())
    ids = {r.id for r in t.rules}
    assert STOP_REORGANIZING.id in ids
    nmck = next(r for r in t.rules if r.id == "nmck_range")
    assert nmck.soft_margin is None
    assert t.thresholds.participate > Thresholds().participate


def test_template_aggressive() -> None:
    base = template_profile("cautious", _base_with_nmck())
    t = template_profile("aggressive", base)
    rules = {r.id: r for r in t.rules}
    assert STOP_REORGANIZING.id not in rules
    assert rules["nmck_range"].value == [Decimal("500000.0"), Decimal("6000000")]
    active = rules["customer_active"].value
    assert isinstance(active, list) and "reorganizing" in active
    assert t.thresholds.participate < Thresholds().participate
    assert base.rules != t.rules  # исходный профиль не изменён


# ---------- объяснение


def _outcome(rule_id: str, **kw: Any) -> RuleOutcome:
    base: dict[str, Any] = {
        "rule_id": rule_id,
        "label": kw.pop("label", rule_id),
        "group": RuleGroup.procurement,
        "kind": RuleKind.weighted,
        "field": "nmck",
        "operator": Operator.between,
        "field_value": 12_000_000,
        "status": RuleStatus.applied,
        "text": "НМЦК 12 млн ₽",
    }
    return RuleOutcome(**{**base, **kw})


def _result(
    total: int, rec: Recommendation, rules: list[RuleOutcome], stops: list[str] | None = None
) -> ScoreResultData:
    return ScoreResultData(
        total=total,
        recommendation=rec,
        incomplete=False,
        stop_factors=stops or [],
        groups=[],
        rules=rules,
        justification="",
    )


def _profiles() -> tuple[ScoringProfileData, ScoringProfileData]:
    return ScoringProfileData(name="Осторожный"), ScoringProfileData(name="Агрессивный")


def test_explain_same_is_empty() -> None:
    pa, pb = _profiles()
    r = _result(50, Recommendation.consider, [])
    assert explain_difference(r, r, pa, pb) == ""


def test_explain_stop_first() -> None:
    pa, pb = _profiles()
    stop = _outcome(
        "stop_customer_reorganizing",
        kind=RuleKind.stop,
        triggered=True,
        text="Заказчик в процессе реорганизации: реорганизуется",
    )
    rule_a = _outcome(
        "r2",
        partial_score=0.0,
        contribution=0.0,
        lost=30.0,
        text="НМЦК 12 млн ₽ — выше вашего диапазона",
    )
    rule_b = _outcome(
        "r2",
        partial_score=1.0,
        contribution=30.0,
        lost=0.0,
        text="НМЦК 12 млн ₽ — в вашем диапазоне",
    )
    a = _result(0, Recommendation.skip, [stop, rule_a], ["stop_customer_reorganizing"])
    b = _result(75, Recommendation.participate, [rule_b])
    text = explain_difference(a, b, pa, pb)
    assert text.startswith("В «Осторожный» стоп: заказчик в процессе реорганизации")
    assert "[stop_customer_reorganizing]" in text
    assert "[r2]" in text
    assert text.count(". ") <= 2  # не больше трёх фраз


def test_explain_rule_only_in_one_profile() -> None:
    pa, pb = _profiles()
    region = _outcome(
        "region",
        label="Регион поставки",
        partial_score=0.0,
        contribution=0.0,
        lost=20.0,
        text="Регион: Москва — не входит в выбранные",
    )
    a = _result(40, Recommendation.consider, [region])
    b = _result(70, Recommendation.participate, [])
    text = explain_difference(a, b, pa, pb)
    assert "В «Агрессивный» нет условия «регион поставки»" in text
    assert "[region]" in text


def test_explain_thresholds() -> None:
    pa = ScoringProfileData(name="А", thresholds=Thresholds(participate=75, consider=45))
    pb = ScoringProfileData(name="Б", thresholds=Thresholds(participate=60, consider=30))
    a = _result(65, Recommendation.consider, [])
    b = _result(65, Recommendation.participate, [])
    assert "Разные пороги" in explain_difference(a, b, pa, pb)


def test_explain_same_outcome_only_weight_differs() -> None:
    base = default_profile()
    pa = base.model_copy(update={"name": "А"})
    rules_b = [
        r.model_copy(update={"weight": 1}) if r.id == "customer_age" else r for r in base.rules
    ]
    pb = base.model_copy(update={"name": "Б", "rules": rules_b})
    age_a = _outcome(
        "customer_age",
        label="Заказчик работает не меньше 3 лет",
        partial_score=1.0,
        contribution=20.0,
        lost=0.0,
        text="Возраст 10 лет",
    )
    age_b = _outcome(
        "customer_age",
        label="Заказчик работает не меньше 3 лет",
        partial_score=1.0,
        contribution=10.0,
        lost=0.0,
        text="Возраст 10 лет",
    )
    a = _result(60, Recommendation.consider, [age_a])
    b = _result(50, Recommendation.consider, [age_b])
    text = explain_difference(a, b, pa, pb)
    assert text == "Условие «заказчик работает не меньше 3 лет» важнее в «А» [customer_age]."


def test_explain_same_outcome_same_weight_is_silent() -> None:
    pa, pb = _profiles()
    x = _outcome("customer_age", partial_score=1.0, contribution=20.0, lost=0.0, text="≥ 3 лет")
    y = _outcome("customer_age", partial_score=1.0, contribution=20.0, lost=0.0, text="≥ 1 год")
    a = _result(60, Recommendation.consider, [x])
    b = _result(61, Recommendation.consider, [y])
    assert explain_difference(a, b, pa, pb) == ""
