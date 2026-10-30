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


def test_prefixes_and_similarity(fake: FakeEncoder) -> None:
    vec = service.embed_passage("Ремонт   кровли школы")
    assert fake.calls[0] == "passage: Ремонт кровли школы"
    close = service.similarity(vec, "строительство и кровельные работы")
    far = service.similarity(vec, "разработка программного обеспечения")
    assert fake.calls[1].startswith("query: ")
    assert close is not None and far is not None and close > far


def test_query_vectors_are_cached(fake: FakeEncoder) -> None:
    vec = service.embed_passage("кровля")
    service.similarity(vec, "кровельные работы")
    service.similarity(vec, "кровельные работы")
    assert len(fake.calls) == 2


def test_no_model_or_vector_gives_none(fake: FakeEncoder, monkeypatch: pytest.MonkeyPatch) -> None:
    assert service.similarity(None, "что угодно") is None
    assert service.embed_passage("   ") is None
    monkeypatch.setattr(service, "_model", lambda: None)
    service._query_vec.cache_clear()
    assert service.embed_passage("кровля") is None
    assert service.similarity([1.0, 0.0, 0.0], "кровля") is None
