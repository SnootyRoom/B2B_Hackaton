"""Подбор кодов ОКПД2 профиля по полному справочнику: кандидаты по смыслу → выбор LLM."""

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from app.core.config import get_settings
from app.embeddings import service as embeddings
from app.llm import okpd2_search
from app.llm import parse_profile as pp
from app.llm.client import load_prompt
from app.llm.parse_profile import parse_text, without_nested

from .test_parse_profile import GOOD_ANSWER, TEXT, fake_llm

CATALOG = [
    ("62", "Продукты программные и услуги по разработке программного обеспечения"),
    ("62.01", "Продукты программные и услуги по разработке программного обеспечения"),
    ("62.01.1", "Услуги по проектированию и разработке информационных технологий"),
    ("62.02", "Услуги консультативные в области компьютерных технологий"),
    ("95.11", "Услуги по ремонту компьютеров и периферийного оборудования"),
]
# направление вектора на код: «разработка ПО» ближе всего к 62.01, затем 62.01.1, 62.02
VECTORS = np.array(
    [[1, 0, 0], [1, 0, 0], [0.9, 0.1, 0], [0.6, 0.7, 0.3], [0, 0, 1]], dtype=np.float32
)


@pytest.fixture
def catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Справочник из пяти кодов с готовым индексом; запрос «разработка ПО» → (1, 0, 0)."""
    csv = tmp_path / "okpd2.csv"
    csv.write_text("code;name\n" + "".join(f"{c};{n}\n" for c, n in CATALOG), encoding="utf-8")
    np.save(okpd2_search.index_path(csv), VECTORS.astype(np.float16))
    monkeypatch.setattr(get_settings(), "okpd2_csv", csv)
    monkeypatch.setattr(embeddings, "query_vector", lambda text: [1.0, 0.0, 0.0])
    okpd2_search._index.cache_clear()
    yield
    okpd2_search._index.cache_clear()


def test_candidates_are_nearest_without_class_level(catalog: None) -> None:
    found = okpd2_search.okpd2_candidates(["разработка ПО"], k=3)
    assert found is not None
    # класс «62» в кандидаты не попадает: для prefix_in он слишком широк
    assert [code for code, _ in found] == ["62.01", "62.01.1", "62.02"]


def test_candidates_of_several_activities_without_repeats(
    catalog: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    vecs = {"разработка ПО": [1.0, 0.0, 0.0], "ремонт компьютеров": [0.0, 0.0, 1.0]}
    monkeypatch.setattr(embeddings, "query_vector", lambda text: vecs[text])
    found = okpd2_search.okpd2_candidates(["разработка ПО", "ремонт компьютеров"], k=2)
    assert found is not None
    assert [code for code, _ in found] == ["62.01", "62.01.1", "95.11", "62.02"]


def test_index_is_rebuilt_in_memory_when_file_does_not_match(
    catalog: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    np.save(okpd2_search.index_path(get_settings().okpd2_csv), VECTORS[:2])
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: VECTORS)
    okpd2_search._index.cache_clear()
    found = okpd2_search.okpd2_candidates(["разработка ПО"], k=1)
    assert found == [("62.01", CATALOG[1][1])]


def test_no_catalog_or_model_means_none(monkeypatch: pytest.MonkeyPatch) -> None:
    okpd2_search._index.cache_clear()
    assert okpd2_search.okpd2_candidates(["что угодно"], k=5) is None  # справочника нет
    okpd2_search._index.cache_clear()


def test_llm_picks_codes_from_candidates(catalog: None) -> None:
    client, reqs = fake_llm([GOOD_ANSWER, {"codes": ["62.01", "62.01.1"]}])
    rules = parse_text(TEXT, client).rules
    okpd = next(r for r in rules if r.field == "okpd2_codes")
    # 62.01.1 уже покрыт 62.01
    assert okpd.id == "r_okpd" and okpd.value == ["62.01"] and okpd.weight == 3
    assert okpd.operator == "prefix_in" and okpd.label.startswith(
        "Коды ОКПД2: Продукты программные"
    )
    pick = reqs[1]
    assert pick["temperature"] == 0
    enum = pick["response_format"]["json_schema"]["schema"]["properties"]["codes"]["items"]["enum"]  # type: ignore[index]
    assert enum == ["62.01", "62.01.1", "62.02", "95.11"]
    assert "разработка и сопровождение программного обеспечения" in pick["messages"][-1]["content"]  # type: ignore[index]


def test_code_outside_candidates_is_dropped(catalog: None) -> None:
    client, _ = fake_llm([GOOD_ANSWER, {"codes": ["99.99", "62.02"]}])
    okpd = next(r for r in parse_text(TEXT, client).rules if r.field == "okpd2_codes")
    assert okpd.value == ["62.02"]


def test_empty_pick_means_no_okpd2_rule(catalog: None) -> None:
    client, _ = fake_llm([GOOD_ANSWER, {"codes": []}])
    assert not any(r.field == "okpd2_codes" for r in parse_text(TEXT, client).rules)


def test_picked_codes_merged_with_categories(catalog: None) -> None:
    answer = {**GOOD_ANSWER, "okpd2_categories": ["юридические и бухгалтерские услуги, аудит"]}
    client, _ = fake_llm([answer, {"codes": ["62.01.1"]}])
    okpd = next(r for r in parse_text(TEXT, client).rules if r.field == "okpd2_codes")
    assert okpd.value == ["69", "62.01"]  # вид 62.01.1 поднят до группы


def test_categories_not_merged_when_switched_off(
    catalog: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "okpd2_with_categories", False)
    answer = {**GOOD_ANSWER, "okpd2_categories": ["юридические и бухгалтерские услуги, аудит"]}
    client, _ = fake_llm([answer, {"codes": ["62.02"]}])
    okpd = next(r for r in parse_text(TEXT, client).rules if r.field == "okpd2_codes")
    assert okpd.value == ["62.02"]


def test_pick_failure_is_retried_then_profile_has_no_codes(catalog: None) -> None:
    client, reqs = fake_llm([GOOD_ANSWER, "не json", "и это не json"])
    result = parse_text(TEXT, client)
    assert len(reqs) == 3
    assert not any(r.field == "okpd2_codes" for r in result.rules)
    assert any(r.field == "subject" for r in result.rules)  # разбор профиля не упал


def test_pick_retry_succeeds(catalog: None) -> None:
    client, _ = fake_llm([GOOD_ANSWER, "не json", {"codes": ["62.02"]}])
    okpd = next(r for r in parse_text(TEXT, client).rules if r.field == "okpd2_codes")
    assert okpd.value == ["62.02"]


def test_without_catalog_categories_are_used() -> None:
    okpd2_search._index.cache_clear()
    answer = {**GOOD_ANSWER, "okpd2_categories": ["юридические и бухгалтерские услуги, аудит"]}
    client, reqs = fake_llm([answer])
    okpd = next(r for r in parse_text(TEXT, client).rules if r.field == "okpd2_codes")
    assert okpd.value == ["69"] and len(reqs) == 1  # шаг 2 не вызывался


def test_user_codes_merged_with_picked(catalog: None) -> None:
    own = {"field": "okpd2_codes", "operator": "prefix_in", "value": ["58.29"], "weight": 3,
           "soft_margin": 0, "label": "Свои коды"}  # fmt: skip
    answer = {**GOOD_ANSWER, "rules": [*GOOD_ANSWER["rules"], own]}  # type: ignore[list-item]
    client, _ = fake_llm([answer, {"codes": ["62.01"]}])
    rules = [r for r in parse_text(TEXT, client).rules if r.field == "okpd2_codes"]
    assert len(rules) == 1 and rules[0].value == ["58.29", "62.01"]


def test_activity_falls_back_to_company_description(catalog: None) -> None:
    rules = [r for r in GOOD_ANSWER["rules"] if r["field"] != "subject"]  # type: ignore[union-attr]
    client, reqs = fake_llm([{**GOOD_ANSWER, "rules": rules}, {"codes": ["62.01"]}])
    parse_text(TEXT, client)
    assert "IT-компания из Томска" in reqs[1]["messages"][-1]["content"]  # type: ignore[index]


def test_without_nested() -> None:
    assert without_nested(["28.93", "28.93.15", "28.9", "10.71"]) == ["28.9", "10.71"]


def test_pick_prompt_has_version() -> None:
    assert load_prompt("okpd2_pick").version == "3"
    assert pp.okpd2_candidates is okpd2_search.okpd2_candidates
