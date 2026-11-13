"""Исправления по ревью: оценка пишется одним запросом, отклонённая загрузка не оставляет файлов."""

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Procurement, ScoreResult, ScoringProfile
from app.schemas.scoring import ScoringProfileData
from app.tasks.pipeline import score_procurement


def _notice(n: int) -> bytes:
    return json.dumps(
        {
            "reg_number": f"03650000000000000{n:02d}",
            "law": "44",
            "subject": "Сопровождение программного обеспечения",
            "nmck": 1_000_000,
            "method": "auction",
            "region": "Томская область",
        }
    ).encode()


def test_score_upsert_survives_concurrent_writer(client: TestClient) -> None:
    """Вторая сессия пишет ту же пару «закупка + профиль», пока первая не закоммитила:
    раньше это давало IntegrityError, теперь — обновление."""
    r = client.post(
        "/api/procurements/upload", files=[("files", ("a.json", _notice(1), "application/json"))]
    )
    assert r.status_code == 202
    with SessionLocal() as db:
        db.execute(delete(ScoreResult))  # как будто оценки ещё нет
        db.commit()
    first_written = threading.Event()
    errors: list[BaseException] = []

    def worker(first: bool) -> None:
        try:
            with SessionLocal() as db:
                p = db.scalars(select(Procurement)).one()
                prof = db.scalars(select(ScoringProfile)).one()
                data = ScoringProfileData.model_validate(prof, from_attributes=True)
                if not first:
                    first_written.wait(5)
                score_procurement(db, p, prof, data)
                if first:
                    first_written.set()  # строка вставлена, но ещё не закоммичена
                    time.sleep(0.5)
                db.commit()
        except BaseException as e:  # noqa: BLE001 — ошибку проверяем в основном потоке
            errors.append(e)
            first_written.set()

    threads = [threading.Thread(target=worker, args=(f,)) for f in (True, False)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
    assert errors == []
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ScoreResult)) == 1


def test_rejected_upload_leaves_no_files(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(get_settings(), "upload_dir", tmp_path)
    monkeypatch.setattr(get_settings(), "upload_max_file_mb", 0)  # любой файл «слишком большой»
    r = client.post(
        "/api/procurements/upload",
        files=[
            ("files", ("a.json", _notice(1), "application/json")),
            ("files", ("b.json", _notice(2), "application/json")),
        ],
    )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert list(tmp_path.iterdir()) == []
    assert client.get("/api/tasks").json() == []


def test_accepted_upload_keeps_files(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(get_settings(), "upload_dir", tmp_path)
    r = client.post(
        "/api/procurements/upload", files=[("files", ("a.json", _notice(1), "application/json"))]
    )
    assert r.status_code == 202
    assert len(list(tmp_path.iterdir())) == 1
