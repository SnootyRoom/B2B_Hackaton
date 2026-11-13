import io
import json
import os
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from tests.test_pipeline import _notice, _upload


class _Cp866Info(zipfile.ZipInfo):
    """Так пишет имена архиватор Windows: cp866 без флага UTF-8."""

    __slots__ = ()

    def _encodeFilenameFlags(self) -> tuple[bytes, int]:
        return self.filename.encode("cp866"), self.flag_bits


def _zip(*members: tuple[str, bytes], cp866: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in members:
            info = _Cp866Info(name) if cp866 else zipfile.ZipInfo(name)
            zf.writestr(info, content, zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def _json(reg: str, **extra: object) -> bytes:
    return json.dumps(_notice(reg, **extra)).encode()


def test_zip_members_become_task_files(client: TestClient) -> None:
    archive = _zip(
        ("a.json", _json("1")),
        ("папка/b.json", _json("2")),
        ("broken.json", b"{bad"),
        ("a.json.sig", b"signature"),
        ("__MACOSX/._a.json", b"junk"),
        (".DS_Store", b"junk"),
    )
    task = _upload(client, ("пакет.zip", archive), ("c.json", _json("3")))
    assert task["status"] == "partial"
    assert task["total"] == task["processed"] == 4
    names = [f["filename"] for f in task["files"]]
    assert names == [
        "пакет.zip/a.json",
        "пакет.zip/папка/b.json",
        "пакет.zip/broken.json",
        "c.json",
    ]
    assert [f["status"] for f in task["files"]] == ["ok", "ok", "error", "ok"]
    assert task["files"][2]["error"]["code"] == "UNSUPPORTED_FORMAT"
    assert len(client.get("/api/procurements").json()) == 3
    # архив распакован и удалён, файлы лежат отдельно
    task_dir = get_settings().upload_dir / task["id"]
    assert not list(task_dir.glob("*.zip"))


def test_cp866_names_decoded(client: TestClient) -> None:
    task = _upload(client, ("a.zip", _zip(("извещение.json", _json("1")), cp866=True)))
    assert task["files"][0]["filename"] == "a.zip/извещение.json"
    assert task["status"] == "done"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"not a zip at all", "Архив повреждён или это не zip"),
        (_zip(("readme.txt", b"hi")), "В архиве нет файлов .xml или .json"),
    ],
)
def test_bad_archive_is_one_error_row(client: TestClient, content: bytes, message: str) -> None:
    task = _upload(client, ("bad.zip", content), ("ok.json", _json("1")))
    assert task["status"] == "partial"
    bad = task["files"][0]
    assert bad["filename"] == "bad.zip"
    assert bad["error"] == {"code": "UNSUPPORTED_FORMAT", "message": message, "details": {}}
    assert task["files"][1]["status"] == "ok"


def test_member_over_file_limit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "upload_max_file_mb", 1)
    big = b" " * (1024 * 1024 + 1)  # сжимается почти в ноль — проверяем по распакованному
    task = _upload(client, ("a.zip", _zip(("big.xml", big), ("ok.json", _json("1")))))
    assert [f["status"] for f in task["files"]] == ["error", "ok"]
    assert task["files"][0]["error"]["code"] == "FILE_TOO_LARGE"


def test_archive_over_files_limit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "upload_max_files", 2)
    archive = _zip(*((f"{i}.json", _json(str(i))) for i in range(3)))
    task = _upload(client, ("a.zip", archive))
    assert task["status"] == "failed"
    assert task["files"][0]["error"]["code"] == "TOO_MANY_FILES"


def test_redelivery_after_expand(client: TestClient) -> None:
    from app.tasks.jobs import run_task

    task = _upload(client, ("a.zip", _zip(("a.json", _json("1")), ("b.json", _json("2")))))
    run_task(task["id"])
    again = client.get(f"/api/tasks/{task['id']}").json()
    assert again["status"] == "done"
    assert again["total"] == again["processed"] == 2


def test_archive_size_limit_on_upload(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "upload_max_file_mb", 1)
    monkeypatch.setattr(s, "upload_max_archive_mb", 2)
    # случайные байты не сжимаются: архив ~1,5 МБ
    ok = _zip(("a.json", _json("1")), ("pad.bin", os.urandom(1_500_000)))
    # архив больше лимита файла, но меньше лимита архива — принимается
    r = client.post("/api/procurements/upload", files=[("files", ("a.zip", ok, "x"))])
    assert r.status_code == 202, r.text
    r = client.post(
        "/api/procurements/upload", files=[("files", ("a.zip", b"0" * (3 * 1024 * 1024), "x"))]
    )
    assert r.status_code == 413
