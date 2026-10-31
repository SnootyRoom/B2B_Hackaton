import json

import httpx
import pytest

from app.llm import parse_profile
from app.llm.client import LLMClient, LLMError, LLMUnavailable, load_prompt
from app.llm.parse_profile import SALVAGED_NOTE, invented_money, parse_text, salvage, text_numbers
from app.parsers.regions import REGIONS
from app.schemas.common import ErrorCode
from app.scoring.defaults import DEFAULT_RULE_IDS

GOOD_ANSWER = {
    "rules": [
        {
            "field": "nmck",
            "operator": "between",
            "value": [500000, 15000000],
            "weight": 3,
            "soft_margin": 0.2,
            "label": "НМЦК от 500 тыс. до 15 млн ₽",
        },
        {
            "field": "method",
            "operator": "in",
            "value": ["auction", "quotation"],
            "weight": 3,
            "soft_margin": 0,
            "label": "Аукционы и запросы котировок",
        },
        {
            "field": "subject",
            "operator": "semantic_match",
            "value": "разработка и сопровождение программного обеспечения",
            "weight": 3,
            "soft_margin": 0,
            "label": "Предмет — разработка ПО",
        },
    ],
    "company_description": "IT-компания из Томска, разработка и сопровождение ПО.",
    "unparsed": ["надёжные заказчики"],
}

# суммы из GOOD_ANSWER и BAD_RULE должны быть в тексте пользователя
TEXT = "IT-компания из Томска, интересны закупки от 500 тыс. до 15 млн руб."

BAD_RULE = {
    "field": "nmck",
    "operator": "between",
    "value": [15000000, 500000],
    "weight": 3,
    "soft_margin": 0.2,
    "label": "Перепутанный диапазон",
}


@pytest.fixture(autouse=True)
def no_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Модель эмбеддингов в тестах не грузим: категории ОКПД2 по смыслу не проверяются."""
    monkeypatch.setattr(parse_profile, "_closeness", lambda a, b: None)


def fake_llm(answers: list[object]) -> tuple[LLMClient, list[dict[str, object]]]:
    """Клиент, который вместо сети отдаёт заранее заданные ответы по очереди."""
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        answer = answers[len(requests) - 1]
        if isinstance(answer, httpx.Response):
            return answer
        content = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    client = LLMClient(
        "https://proxy.test/v1", "test-key", "test-model", transport=httpx.MockTransport(handler)
    )
    return client, requests


def test_parses_rules_and_adds_defaults() -> None:
    client, reqs = fake_llm([GOOD_ANSWER])
    p = parse_text(TEXT, client)
    ids = {r.id for r in p.rules}
    assert {"r1", "r2", "r3"} <= ids
    assert ids >= DEFAULT_RULE_IDS
    assert p.unparsed == ["надёжные заказчики"]
    assert reqs[0]["temperature"] == 0
    assert p.rules[0].group == "procurement" and p.rules[2].group == "fit"


def test_same_text_is_cached() -> None:
    client, reqs = fake_llm([GOOD_ANSWER])
    a = parse_text(TEXT, client)
    b = parse_text(TEXT, client)
    assert a == b and len(reqs) == 1


def test_retry_with_error_text() -> None:
    bad = {**GOOD_ANSWER, "rules": [BAD_RULE]}
    client, reqs = fake_llm([bad, GOOD_ANSWER])
    p = parse_text(TEXT, client)
    assert len(reqs) == 2
    retry_msg = reqs[1]["messages"][-1]["content"]  # type: ignore[index]
    assert "Левая граница" in retry_msg
    assert p.rules[0].field == "nmck"


def test_still_invalid_after_retry_goes_to_unparsed() -> None:
    bad = {**GOOD_ANSWER, "rules": [GOOD_ANSWER["rules"][0], BAD_RULE]}  # type: ignore[index]
    client, _ = fake_llm([bad, bad])
    p = parse_text(TEXT, client)
    assert any("Перепутанный диапазон" in u for u in p.unparsed)
    assert "r1" in {r.id for r in p.rules}


def test_garbage_answer_gives_user_message() -> None:
    client, _ = fake_llm(["это не json", "и это не json"])
    with pytest.raises(LLMError, match="задайте правила вручную") as e:
        parse_text(TEXT, client)
    assert e.value.code == ErrorCode.LLM_PARSE_FAILED


def test_provider_error_gives_user_message() -> None:
    client, _ = fake_llm([httpx.Response(500)])
    with pytest.raises(LLMError) as e:
        parse_text(TEXT, client)
    assert e.value.code == ErrorCode.LLM_UNAVAILABLE


def test_answer_in_code_fence_is_accepted() -> None:
    client, _ = fake_llm(["```json\n" + json.dumps(GOOD_ANSWER, ensure_ascii=False) + "\n```"])
    assert parse_text(TEXT, client).company_description


def test_no_key_means_disabled() -> None:
    client = LLMClient(None, None, None)
    assert not client.enabled
    with pytest.raises(LLMUnavailable):
        client.complete_json(load_prompt("parse_profile"), "x", {})


def test_prompt_has_version() -> None:
    assert load_prompt("parse_profile").version == "10"


def test_yandex_folder_builds_model_uri_and_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        content = json.dumps(GOOD_ANSWER, ensure_ascii=False)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    client = LLMClient(
        "https://ai.api.cloud.yandex.net/v1",
        "key",
        "yandexgpt-lite/latest",
        folder_id="b1gfolder",
        transport=httpx.MockTransport(handler),
    )
    assert client.model == "gpt://b1gfolder/yandexgpt-lite/latest"
    parse_text(TEXT, client)
    assert seen[0].headers["OpenAI-Project"] == "b1gfolder"
    assert json.loads(seen[0].content)["model"] == "gpt://b1gfolder/yandexgpt-lite/latest"


def test_falls_back_to_json_object_when_schema_rejected() -> None:
    client, reqs = fake_llm([httpx.Response(400, json={"error": "json_schema"}), GOOD_ANSWER])
    p = parse_text(TEXT, client)
    assert reqs[1]["response_format"] == {"type": "json_object"}
    assert "схеме" in reqs[1]["messages"][0]["content"]  # type: ignore[index]
    assert p.rules[0].field == "nmck"


def test_unknown_region_is_retried() -> None:
    bad_region = {
        "field": "region",
        "operator": "in",
        "value": ["Томск"],
        "weight": 3,
        "soft_margin": 0,
        "label": "Томск",
    }
    client, reqs = fake_llm([{**GOOD_ANSWER, "rules": [bad_region]}, GOOD_ANSWER])
    parse_text(TEXT, client)
    assert "справочнике" in reqs[1]["messages"][-1]["content"]  # type: ignore[index]


def test_only_44fz_becomes_stop_factor() -> None:
    stop = {
        "kind": "stop",
        "field": "law",
        "operator": "in",
        "value": ["223", "615", "94", "other"],
        "weight": 3,
        "soft_margin": 0,
        "label": "Не 44-ФЗ",
    }
    client, _ = fake_llm([{**GOOD_ANSWER, "rules": [stop]}])
    rule = parse_text("Работаем только по 44-ФЗ", client).rules[0]
    assert rule.kind == "stop" and rule.weight is None


def test_stop_only_for_hard_conditions() -> None:
    # стоп по сумме или предмету модель предлагать не должна — превращаем в обычное правило
    rule = {**GOOD_ANSWER["rules"][0], "kind": "stop"}  # type: ignore[index, dict-item]
    client, _ = fake_llm([{**GOOD_ANSWER, "rules": [rule]}])
    assert parse_text(TEXT, client).rules[0].kind == "weighted"


def test_okpd2_categories_expand_to_all_codes() -> None:
    answer = {**GOOD_ANSWER, "okpd2_categories": ["мебель, в том числе медицинская и лабораторная"]}
    client, reqs = fake_llm([answer])
    rules = parse_text(TEXT, client).rules
    okpd = next(r for r in rules if r.field == "okpd2_codes")
    assert okpd.value == ["31", "32.50.30"] and okpd.weight == 3
    assert "Категории ОКПД2" in reqs[0]["messages"][1]["content"]  # type: ignore[index]


def test_user_codes_are_merged_with_categories() -> None:
    own = {
        "kind": "weighted",
        "field": "okpd2_codes",
        "operator": "prefix_in",
        "value": ["62.01"],
        "weight": 3,
        "soft_margin": 0,
        "label": "ОКПД2 62.01",
    }
    answer = {**GOOD_ANSWER, "rules": [own], "okpd2_categories": ["оборудование видеонаблюдения"]}
    client, _ = fake_llm([answer])
    rules = [r for r in parse_text(TEXT, client).rules if r.field == "okpd2_codes"]
    assert len(rules) == 1 and rules[0].value == ["62.01", "26.40", "26.70"]


def test_unknown_category_is_ignored() -> None:
    client, _ = fake_llm([{**GOOD_ANSWER, "okpd2_categories": ["космос"]}])
    assert not any(r.field == "okpd2_codes" for r in parse_text(TEXT, client).rules)


def test_paired_regions_are_added() -> None:
    region = {
        "kind": "weighted",
        "field": "region",
        "operator": "in",
        "value": ["Московская область"],
        "weight": 2,
        "soft_margin": 0,
        "label": "Свой регион",
    }
    client, _ = fake_llm([{**GOOD_ANSWER, "rules": [region]}])
    rule = next(r for r in parse_text(TEXT, client).rules if r.field == "region")
    assert rule.value == ["Московская область", "Москва"]


def test_text_numbers() -> None:
    assert text_numbers("от 1,5 до 30 млн, НМЦК не выше 2 500 000 ₽") == {1.5, 30.0, 2_500_000.0}
    assert text_numbers("от полмиллиона до миллиона") == {0.5, 1.0}


@pytest.mark.parametrize(
    ("value", "bad"),
    [
        ([1_000_000, 30_000_000], []),  # «от 1 до 30 млн»
        ([10_000_000, 30_000_000], [10_000_000.0]),  # модель ошиблась в разрядах
        (500_000, []),  # «500 тыс.»
    ],
)
def test_invented_money(value: object, bad: list[float]) -> None:
    assert invented_money(value, text_numbers("от 1 до 30 млн, можно от 500 тыс.")) == bad


def test_invented_sum_is_retried_then_unparsed() -> None:
    wrong = {**GOOD_ANSWER["rules"][0], "value": [5_000_000, 15_000_000]}  # type: ignore[dict-item]
    answer = {**GOOD_ANSWER, "rules": [wrong]}
    client, reqs = fake_llm([answer, answer])
    p = parse_text(TEXT, client)
    assert "нет в тексте пользователя" in reqs[1]["messages"][-1]["content"]  # type: ignore[index]
    assert not any(r.field == "nmck" for r in p.rules)
    assert any("5000000" in u for u in p.unparsed)


def _region_rule(values: list[str], weight: int) -> dict[str, object]:
    return {
        "kind": "weighted",
        "field": "region",
        "operator": "in",
        "value": values,
        "weight": weight,
        "soft_margin": 0,
        "label": "Регион",
    }


NATIONWIDE_TEXT = TEXT + " Работаем с заказчиками по всей России."


@pytest.mark.parametrize(
    "region",
    [
        _region_rule(["Новосибирская область"], 2),  # «Свой регион» при работе по всей России
        _region_rule(list(REGIONS), 1),  # перечислены все регионы
    ],
)
def test_nationwide_company_gets_no_region_rule(region: dict[str, object]) -> None:
    client, _ = fake_llm([{**GOOD_ANSWER, "rules": [region]}])
    assert not any(r.field == "region" for r in parse_text(NATIONWIDE_TEXT, client).rules)


def test_explicit_regions_kept_for_nationwide_company() -> None:
    region = _region_rule(["Новосибирская область"], 3)  # «интересны закупки в …»
    client, _ = fake_llm([{**GOOD_ANSWER, "rules": [region]}])
    assert any(r.field == "region" for r in parse_text(NATIONWIDE_TEXT, client).rules)


def test_home_region_kept_without_nationwide() -> None:
    client, _ = fake_llm([{**GOOD_ANSWER, "rules": [_region_rule(["Томская область"], 2)]}])
    assert any(r.field == "region" for r in parse_text(TEXT, client).rules)


def _only(field: str, values: list[str]) -> dict[str, object]:
    return {
        "kind": "only",
        "field": field,
        "operator": "in",
        "value": values,
        "weight": 3,
        "soft_margin": 0,
        "label": "Только",
    }


def test_only_law_becomes_stop_on_other_laws() -> None:
    # модель называет только разрешённое — «все кроме» достраивает программа
    client, _ = fake_llm([{**GOOD_ANSWER, "rules": [_only("law", ["44"])]}])
    rule = parse_text("Работаем только по 44-ФЗ", client).rules[0]
    assert rule.kind == "stop" and rule.operator == "in"
    assert rule.value == ["223", "615", "94", "other"]


def test_only_method_and_region_use_not_in() -> None:
    answer = {**GOOD_ANSWER, "rules": [_only("method", ["auction"]), _only("region", ["Москва"])]}
    client, _ = fake_llm([answer])
    rules = parse_text(TEXT, client).rules
    assert [(r.kind, r.operator, r.value) for r in rules[:2]] == [
        ("stop", "not_in", ["auction"]),
        ("stop", "not_in", ["Москва"]),
    ]


def test_only_on_other_field_is_ordinary_rule() -> None:
    rule = {**GOOD_ANSWER["rules"][0], "kind": "only"}  # type: ignore[dict-item]
    client, _ = fake_llm([{**GOOD_ANSWER, "rules": [rule]}])
    assert parse_text(TEXT, client).rules[0].kind == "weighted"


def test_category_far_from_activity_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    near = "программное обеспечение и IT-услуги"
    far = "оборудование видеонаблюдения"
    monkeypatch.setattr(parse_profile, "_closeness", lambda a, b: 0.92 if a == near else 0.80)
    client, _ = fake_llm([{**GOOD_ANSWER, "okpd2_categories": [near, far]}])
    okpd = next(r for r in parse_text(TEXT, client).rules if r.field == "okpd2_codes")
    assert far not in okpd.label and near in okpd.label


def test_broken_answer_is_asked_again_without_showing_it() -> None:
    client, reqs = fake_llm(["это не json", GOOD_ANSWER])
    assert parse_text(TEXT, client).rules[0].field == "nmck"
    messages = reqs[1]["messages"]
    assert [m["role"] for m in messages] == ["system", "user"]  # type: ignore[index,union-attr]
    assert "коротким JSON" in messages[1]["content"]  # type: ignore[index]


def test_cut_answer_keeps_whole_rules() -> None:
    rule = json.dumps(GOOD_ANSWER["rules"][0], ensure_ascii=False)  # type: ignore[index]
    cut = '{"rules": [' + rule + ", " + rule + ', {"field": "method", "lab'
    client, _ = fake_llm([cut, cut])
    p = parse_text(TEXT, client)
    assert [r.id for r in p.rules if r.field == "nmck"] == ["r1"]  # повтор убран
    assert SALVAGED_NOTE in p.unparsed


def test_salvage_without_whole_rules_gives_none() -> None:
    assert salvage('{"rules": [{"field": "nm') is None
    assert salvage("не json") is None
