import json

import httpx
import pytest

from app.llm.client import LLMClient, LLMError, LLMUnavailable, load_prompt
from app.llm.parse_profile import parse_text
from app.schemas.common import ErrorCode
from app.schemas.scoring import Operator, RuleKind
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

BAD_RULE = {
    "field": "nmck",
    "operator": "between",
    "value": [15000000, 500000],
    "weight": 3,
    "soft_margin": 0.2,
    "label": "Перепутанный диапазон",
}


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
    p = parse_text("Мы IT-компания из Томска…", client)
    ids = {r.id for r in p.rules}
    assert {"r1", "r2", "r3"} <= ids
    assert ids >= DEFAULT_RULE_IDS
    assert p.unparsed == ["надёжные заказчики"]
    assert reqs[0]["temperature"] == 0
    assert p.rules[0].group == "procurement" and p.rules[2].group == "fit"


def test_same_text_is_cached() -> None:
    client, reqs = fake_llm([GOOD_ANSWER])
    a = parse_text("текст", client)
    b = parse_text("текст", client)
    assert a == b and len(reqs) == 1


def test_retry_with_error_text() -> None:
    bad = {**GOOD_ANSWER, "rules": [BAD_RULE]}
    client, reqs = fake_llm([bad, GOOD_ANSWER])
    p = parse_text("текст", client)
    assert len(reqs) == 2
    retry_msg = reqs[1]["messages"][-1]["content"]  # type: ignore[index]
    assert "Левая граница" in retry_msg
    assert p.rules[0].field == "nmck"


def test_still_invalid_after_retry_goes_to_unparsed() -> None:
    bad = {**GOOD_ANSWER, "rules": [GOOD_ANSWER["rules"][0], BAD_RULE]}  # type: ignore[index]
    client, _ = fake_llm([bad, bad])
    p = parse_text("текст", client)
    assert any("Перепутанный диапазон" in u for u in p.unparsed)
    assert "r1" in {r.id for r in p.rules}


def test_garbage_answer_gives_user_message() -> None:
    client, _ = fake_llm(["это не json", "и это не json"])
    with pytest.raises(LLMError, match="задайте правила вручную") as e:
        parse_text("текст", client)
    assert e.value.code == ErrorCode.LLM_PARSE_FAILED


def test_provider_error_gives_user_message() -> None:
    client, _ = fake_llm([httpx.Response(500)])
    with pytest.raises(LLMError) as e:
        parse_text("текст", client)
    assert e.value.code == ErrorCode.LLM_UNAVAILABLE


def test_answer_in_code_fence_is_accepted() -> None:
    client, _ = fake_llm(["```json\n" + json.dumps(GOOD_ANSWER, ensure_ascii=False) + "\n```"])
    assert parse_text("текст", client).company_description


def test_no_key_means_disabled() -> None:
    client = LLMClient(None, None, None)
    assert not client.enabled
    with pytest.raises(LLMUnavailable):
        client.complete_json(load_prompt("parse_profile"), "x", {})


def test_prompt_has_version() -> None:
    assert load_prompt("parse_profile").version == "5"


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
    parse_text("текст", client)
    assert seen[0].headers["OpenAI-Project"] == "b1gfolder"
    assert json.loads(seen[0].content)["model"] == "gpt://b1gfolder/yandexgpt-lite/latest"


def test_falls_back_to_json_object_when_schema_rejected() -> None:
    client, reqs = fake_llm([httpx.Response(400, json={"error": "json_schema"}), GOOD_ANSWER])
    p = parse_text("текст", client)
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
    parse_text("текст", client)
    assert "справочнике" in reqs[1]["messages"][-1]["content"]  # type: ignore[index]


def _answer_with(rule: dict[str, object]) -> dict[str, object]:
    return {**GOOD_ANSWER, "rules": [*GOOD_ANSWER["rules"], rule]}  # type: ignore[list-item]


def test_okpd2_catalog_in_prompt_and_unknown_class_retried() -> None:
    bad = {"field": "okpd2_codes", "operator": "prefix_in", "value": ["04"], "weight": 3,
           "soft_margin": 0, "label": "ОКПД2"}  # fmt: skip
    good = {**bad, "value": ["32.50", "21"]}
    client, reqs = fake_llm([_answer_with(bad), _answer_with(good)])
    p = parse_text("Поставляем медицинские изделия", client)
    first_user = reqs[0]["messages"][-1]["content"]  # type: ignore[index]
    assert "Классы ОКПД2" in first_user and "32.50" in first_user
    assert "Наборы кодов ОКПД2" in first_user
    assert "классов ОКПД2: 04" in reqs[1]["messages"][-1]["content"]  # type: ignore[index]
    okpd = next(r for r in p.rules if r.field == "okpd2_codes")
    assert okpd.value == ["32.50", "21"]


def test_home_region_gets_its_pair() -> None:
    rule = {"field": "region", "operator": "in", "value": ["Московская область"], "weight": 3,
            "soft_margin": 0, "label": "Свой регион"}  # fmt: skip
    client, _ = fake_llm([_answer_with(rule)])
    region = next(r for r in parse_text("Мы из Подмосковья", client).rules if r.field == "region")
    assert region.value == ["Московская область", "Москва"]


def test_strict_law_becomes_stop_factor() -> None:
    rule = {"field": "law", "operator": "in", "value": ["44"], "weight": 3, "soft_margin": 0,
            "label": "Только 44-ФЗ", "strict": True}  # fmt: skip
    client, _ = fake_llm([_answer_with(rule)])
    law = next(r for r in parse_text("Работаем только по 44-ФЗ", client).rules if r.field == "law")
    assert law.kind == RuleKind.stop and law.weight is None
    # у закона нет not_in — стоп-фактор срабатывает на остальных законах
    assert law.operator == Operator.in_ and "44" not in law.value  # type: ignore[operator]
    assert law.label == "Нарушено условие «Только 44-ФЗ»"


def test_strict_region_becomes_not_in_stop_and_soft_stays_weighted() -> None:
    strict = {"field": "region", "operator": "in", "value": ["Томская область"], "weight": 3,
              "soft_margin": 0, "label": "Только Томская область", "strict": True}  # fmt: skip
    soft = {"field": "method", "operator": "in", "value": ["auction"], "weight": 3,
            "soft_margin": 0, "label": "Аукционы", "strict": False}  # fmt: skip
    answer = {**GOOD_ANSWER, "rules": [strict, soft]}
    client, _ = fake_llm([answer])
    rules = {r.field: r for r in parse_text("Только Томская область, аукционы", client).rules}
    assert rules["region"].kind == RuleKind.stop
    assert rules["region"].operator == Operator.not_in
    assert rules["region"].value == ["Томская область"]
    assert rules["method"].kind == RuleKind.weighted
