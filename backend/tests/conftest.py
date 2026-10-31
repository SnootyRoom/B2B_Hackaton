import os
import tempfile
from collections.abc import Iterator

# Настройки читаются при импорте app — задаём окружение тестов заранее.
_base_url = os.environ.get("DATABASE_URL", "postgresql+psycopg://app:app@db:5432/app")
_TEST_DB = "app_test"
os.environ["DATABASE_URL"] = _base_url.rsplit("/", 1)[0] + f"/{_TEST_DB}"
os.environ["CELERY_EAGER"] = "true"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="uploads-")
os.environ["LLM_API_KEY"] = ""
os.environ["DADATA_API_KEY"] = ""
# Подбор ОКПД2 по полному справочнику включают только его тесты: остальным хватает категорий
os.environ["OKPD2_CSV"] = "/nonexistent/okpd2.csv"

import psycopg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402


def _create_test_db() -> None:
    admin = _base_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(admin, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (_TEST_DB,)
        ).fetchone()
        if not exists:
            conn.execute(f"CREATE DATABASE {_TEST_DB}")


_create_test_db()

import app.models  # noqa: E402, F401
from app.core.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    yield
    with engine.begin() as conn:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        conn.execute(text(f"TRUNCATE {tables} CASCADE"))


def make_client(email: str = "user@example.com", password: str = "password123") -> TestClient:
    client = TestClient(app)
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return client


@pytest.fixture
def client() -> TestClient:
    return make_client()
