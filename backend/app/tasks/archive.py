"""Распаковка zip-архивов загрузки в воркере.

Каждый .xml / .json внутри архива становится отдельной строкой задачи со своим
статусом — как если бы пользователь загрузил эти файлы по одному. Остальное
(подписи .sig, служебные файлы macOS, вложенные папки как таковые) пропускается.
"""

import shutil
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Task, TaskFile
from app.parsers.errors import ParseError
from app.schemas.common import ErrorCode

ARCHIVE_EXTENSION = ".zip"
NOTICE_EXTENSIONS = {".xml", ".json"}
_CHUNK = 1024 * 1024
_UTF8_FLAG = 0x800
_ENCRYPTED_FLAG = 0x1


def is_archive(filename: str) -> bool:
    return Path(filename).suffix.lower() == ARCHIVE_EXTENSION


def too_large(filename: str) -> ParseError:
    mb = get_settings().upload_max_file_mb
    return ParseError(
        ErrorCode.FILE_TOO_LARGE, f"Файл {filename} больше {mb} МБ", {"filename": filename}
    )


def _bad_archive(message: str) -> ParseError:
    return ParseError(ErrorCode.UNSUPPORTED_FORMAT, message)


def _member_name(info: zipfile.ZipInfo) -> str:
    """Имя файла внутри архива. Архиваторы Windows пишут кириллицу в cp866 без флага UTF-8,
    а zipfile читает такие имена как cp437 — перекодируем обратно."""
    if info.flag_bits & _UTF8_FLAG:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp866")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def _notice_members(zf: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, str]]:
    members = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = _member_name(info)
        parts = PurePosixPath(name.replace("\\", "/")).parts
        if not parts or parts[0] == "__MACOSX" or parts[-1].startswith("."):
            continue
        if PurePosixPath(parts[-1]).suffix.lower() in NOTICE_EXTENSIONS:
            members.append((info, "/".join(parts)))
    return members


@dataclass
class _Extracted:
    display_name: str
    stored_path: str  # "" — файл больше лимита и на диск не записан


def _extract(
    path: Path, archive_name: str, dest: Path, file_limit: int, room: int
) -> list[_Extracted]:
    """Распаковать извещения из архива в dest. room — сколько файлов ещё влезает в пакет."""
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        raise _bad_archive("Архив повреждён или это не zip") from None
    with zf:
        members = _notice_members(zf)
        if not members:
            raise _bad_archive("В архиве нет файлов .xml или .json")
        if any(info.flag_bits & _ENCRYPTED_FLAG for info, _ in members):
            raise _bad_archive("Архив защищён паролем — распакуйте его и загрузите файлы")
        if len(members) > room:
            limit = get_settings().upload_max_files
            raise ParseError(
                ErrorCode.TOO_MANY_FILES,
                f"В архиве {len(members)} файлов, а за один раз можно загрузить "
                f"не больше {limit} вместе с остальными файлами. Разбейте архив на части",
                {"count": len(members), "limit": limit},
            )
        dest.mkdir(parents=True, exist_ok=True)
        out: list[_Extracted] = []
        try:
            for info, inner in members:
                display = f"{archive_name}/{inner}"
                target = dest / f"{uuid.uuid4().hex}{PurePosixPath(inner).suffix.lower()}"
                # Размер из заголовка не проверяем: ему нельзя верить, считаем по факту
                if info.file_size > file_limit or not _copy_limited(zf, info, target, file_limit):
                    out.append(_Extracted(display, ""))
                else:
                    out.append(_Extracted(display, str(target)))
        except (zipfile.BadZipFile, OSError, EOFError, RuntimeError):
            shutil.rmtree(dest, ignore_errors=True)
            raise _bad_archive("Архив повреждён: не удалось распаковать файлы") from None
    return out


def _copy_limited(zf: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path, limit: int) -> bool:
    size = 0
    with zf.open(info) as src, target.open("wb") as dst:
        while chunk := src.read(_CHUNK):
            size += len(chunk)
            if size > limit:
                break
            dst.write(chunk)
    if size > limit:
        target.unlink(missing_ok=True)
        return False
    return True


def expand_archives(db: Session, task: Task) -> dict[uuid.UUID, ParseError]:
    """Заменить строки-архивы задачи строками по файлам внутри, позиции — по порядку.

    Архив, который не удалось разобрать, остаётся строкой задачи; его ошибка возвращается
    в словаре по id строки. При повторной доставке задачи распакованные строки уже на месте,
    а неразобранный архив разбирается снова и даёт ту же ошибку.
    """
    s = get_settings()
    rows = list(task.files)
    if not any(is_archive(f.filename) for f in rows):
        return {}
    errors: dict[uuid.UUID, ParseError] = {}
    room = s.upload_max_files - sum(1 for f in rows if not is_archive(f.filename))
    result: list[TaskFile] = []
    unpacked: list[Path] = []
    for f in rows:
        if not is_archive(f.filename):
            result.append(f)
            continue
        archive = Path(f.stored_path)
        try:
            extracted = _extract(
                archive,
                f.filename,
                archive.parent / archive.stem,
                s.upload_max_file_mb * 1024 * 1024,
                room,
            )
        except ParseError as e:
            errors[f.id] = e
            result.append(f)
            continue
        room -= len(extracted)
        for item in extracted:
            result.append(
                TaskFile(task_id=task.id, filename=item.display_name, stored_path=item.stored_path)
            )
        task.files.remove(f)
        unpacked.append(archive)
    for pos, f in enumerate(result):
        f.position = pos
        if f not in task.files:
            task.files.append(f)
    task.files.sort(key=lambda f: f.position)
    task.total = len(task.files)
    db.commit()
    # Архив больше не нужен: его файлы распакованы и записаны строками задачи
    for archive in unpacked:
        archive.unlink(missing_ok=True)
    return errors
