"""Получение извещений из ЕИС по реестровому номеру (задача B, модуль — роль 2).

Контракт для `app/eis/fetch.py` (пишет роль 2; пока модуля нет — номер берётся из
`data/samples/<номер>.xml`, см. `app/tasks/notice_source.py`):

    def fetch_notice(reg_number: str) -> bytes:
        '''XML печатной формы извещения. Внешние вызовы — httpx с таймаутом, паузой между
        запросами и повтором с нарастающей задержкой. Капчу и блокировки не обходим.'''

Ошибки — только EisError:
- ErrorCode.EIS_NOT_FOUND — закупки с таким номером нет;
- ErrorCode.EIS_UNAVAILABLE — ЕИС не ответила, вернула HTML / капчу вместо XML, блокировка.
"""

from app.schemas.common import ErrorCode


class EisError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
