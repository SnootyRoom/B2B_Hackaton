"""Единственная точка доступа к LLM (роль 3). SDK провайдеров импортируются только здесь.

Контракт для конвейера:
- `parse_profile_text(db, text) -> ParseProfileResult`; ошибки — `LLMError` с кодом
  LLM_UNAVAILABLE (нет ключа / провайдер не ответил) или LLM_PARSE_FAILED.
"""

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.schemas.common import ErrorCode
from app.schemas.scoring import ParseProfileResult


class LLMError(Exception):
    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def parse_profile_text(db: Session, text: str) -> ParseProfileResult:
    if not get_settings().llm_enabled:
        raise LLMError(ErrorCode.LLM_UNAVAILABLE, "Разбор текста недоступен")
    # TODO(роль 3): ProxyAPI, temperature 0, JSON-схема, повтор, кэш в llm_cache.
    raise LLMError(
        ErrorCode.LLM_PARSE_FAILED, "Не удалось разобрать текст, задайте правила вручную"
    )
