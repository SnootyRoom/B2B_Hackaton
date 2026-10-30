import math
from collections.abc import Iterator

import pytest

from app.embeddings import service


class FakeEncoder:
    """Вектор по ключевым словам: «по» и «стро» — две оси смысла."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def encode(
        self, sentences: list[str], *, normalize_embeddings: bool, convert_to_numpy: bool
    ) -> list[list[float]]:
        self.calls.append(sentences[0])
        text = sentences[0].lower()
        v = [1.0 if "по" in text.split() or "программ" in text else 0.0,
             1.0 if "стро" in text or "кровл" in text else 0.0, 0.1]  # fmt: skip
        n = math.sqrt(sum(x * x for x in v))
        return [[x / n for x in v]]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeEncoder]:
    enc = FakeEncoder()
    monkeypatch.setattr(service, "_model", lambda: enc)
    service._query_vec.cache_clear()
    yield enc
    service._query_vec.cache_clear()


def test_passage_and_query_prefixes(fake: FakeEncoder) -> None:
    service.embed_passage("Ремонт   кровли школы")
    service.query_vector("строительство и кровельные работы")
    assert fake.calls == [
        "passage: Ремонт кровли школы",
        "query: строительство и кровельные работы",
    ]


def test_query_vectors_are_cached(fake: FakeEncoder) -> None:
    service.query_vector("кровельные работы")
    service.query_vector("кровельные работы")
    assert len(fake.calls) == 1


def test_no_model_gives_none(fake: FakeEncoder, monkeypatch: pytest.MonkeyPatch) -> None:
    assert service.embed_passage("   ") is None
    assert service.query_vector("  ") is None
    monkeypatch.setattr(service, "_model", lambda: None)
    service._query_vec.cache_clear()
    assert service.embed_passage("кровля") is None
    assert service.query_vector("кровля") is None
