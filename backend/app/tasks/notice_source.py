"""Откуда взять XML извещения по реестровому номеру (задача B).

1. Модуль ЕИС роли 2 (`app.eis.fetch.fetch_notice`), если он есть.
2. Не нашёлся модуль или ЕИС недоступна (EIS_UNAVAILABLE) — `data/samples/<номер>.xml`
   (запасной путь для демо без интернета); источник виден пользователю предупреждением
   EIS_FALLBACK_SAMPLE. Если ЕИС ответила EIS_NOT_FOUND — это ответ, образец не подставляется.
3. Иначе — понятная ошибка с советом загрузить файл вручную.
"""

import importlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.core.config import get_settings
from app.eis import EisError
from app.schemas.common import ErrorCode
from app.schemas.procurement import REG_NUMBER_PATTERN

log = logging.getLogger(__name__)

MANUAL_HINT = "Скачайте извещение на zakupki.gov.ru и загрузите файл вручную"
MESSAGES = {
    ErrorCode.INVALID_REG_NUMBER: "Это не похоже на реестровый номер закупки "
    "(нужно 11, 18 или 19 цифр)",
    ErrorCode.EIS_NOT_FOUND: "Закупка с таким номером не найдена в ЕИС. Проверьте номер",
    ErrorCode.EIS_UNAVAILABLE: f"Портал закупок сейчас недоступен. {MANUAL_HINT}",
}
FALLBACK_MESSAGE = "ЕИС недоступна — документ взят из сохранённых образцов"


@dataclass(frozen=True)
class Notice:
    content: bytes
    source: Literal["eis", "sample"]


class NoticeError(Exception):
    def __init__(self, code: ErrorCode, message: str | None = None) -> None:
        self.code = code
        self.message = message or MESSAGES.get(code, MANUAL_HINT)
        super().__init__(self.message)


def is_valid(number: str) -> bool:
    return re.fullmatch(REG_NUMBER_PATTERN, number) is not None


def _eis_fetch() -> Callable[[str], bytes] | None:
    try:
        module = importlib.import_module("app.eis.fetch")
    except ModuleNotFoundError:
        return None
    fn = getattr(module, "fetch_notice", None)
    return fn if callable(fn) else None


def _sample(number: str) -> bytes | None:
    path = get_settings().samples_dir / f"{number}.xml"
    return path.read_bytes() if path.is_file() else None


def get_notice(number: str) -> Notice:
    if not is_valid(number):
        raise NoticeError(ErrorCode.INVALID_REG_NUMBER)
    fetch = _eis_fetch()
    error = NoticeError(ErrorCode.EIS_UNAVAILABLE)
    if fetch is not None:
        try:
            return Notice(fetch(number), "eis")
        except EisError as e:
            log.info("ЕИС %s: %s", number, e.code)
            if e.code != ErrorCode.EIS_UNAVAILABLE:
                # ЕИС ответила, что номера нет — старый образец вместо ответа не подставляем
                raise NoticeError(e.code) from e
            error = NoticeError(e.code)
    sample = _sample(number)
    if sample is not None:
        return Notice(sample, "sample")
    raise error
