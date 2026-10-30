"""Близость по смыслу считает PostgreSQL (pgvector), а не Python."""

import math
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.embeddings import service
from app.models import EMBEDDING_DIM, Procurement, User


def _unit(*head: float) -> list[float]:
    v = [*head, *([0.0] * (EMBEDDING_DIM - len(head)))]
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def _procurement(owner_id: uuid.UUID, reg: str, vec: list[float] | None) -> Procurement:
    return Procurement(
        owner_id=owner_id,
        reg_number=reg,
        subject="x",
        nmck=Decimal(1),
        parsed_by="json",
        data={},
        embedding=vec,
    )


def test_similarity_is_computed_by_pgvector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "query_vector", lambda q: _unit(1.0, 1.0))
    with SessionLocal() as db:
        user = User(email="v@example.com", password_hash="x")
        db.add(user)
        db.flush()
        same = _procurement(user.id, "1", _unit(1.0, 1.0))
        orth = _procurement(user.id, "2", _unit(1.0, -1.0))
        empty = _procurement(user.id, "3", None)
        db.add_all([same, orth, empty])
        db.flush()

        assert service.similarity_in_db(db, same.id, "q") == pytest.approx(1.0)
        assert service.similarity_in_db(db, orth.id, "q") == pytest.approx(0.0, abs=1e-6)
        assert service.similarity_in_db(db, empty.id, "q") is None

        # тот же оператор <=> упорядочивает закупки по близости — векторный поиск в базе
        nearest = db.scalars(
            select(Procurement.reg_number)
            .where(Procurement.embedding.is_not(None))
            .order_by(Procurement.embedding.cosine_distance(_unit(1.0, 1.0)))
        ).all()
        assert nearest == ["1", "2"]
