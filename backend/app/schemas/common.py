from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

# Деньги и числовые значения правил: внутри Decimal, в JSON — число.
Money = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class ErrorCode(StrEnum):
    # Обработка файлов (аналитика, «Загрузка и фоновая обработка»)
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    NOT_A_NOTICE = "NOT_A_NOTICE"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    CUSTOMER_NOT_FOUND = "CUSTOMER_NOT_FOUND"
    EGRUL_UNAVAILABLE = "EGRUL_UNAVAILABLE"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    # API
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    TOO_MANY_FILES = "TOO_MANY_FILES"
    NO_FILES = "NO_FILES"
    NO_ACTIVE_PROFILE = "NO_ACTIVE_PROFILE"
    INVALID_PROFILE = "INVALID_PROFILE"
    LLM_PARSE_FAILED = "LLM_PARSE_FAILED"
    # Несколько профилей (задача A)
    PROFILE_NAME_TAKEN = "PROFILE_NAME_TAKEN"
    LAST_PROFILE = "LAST_PROFILE"
    TOO_MANY_PROFILES = "TOO_MANY_PROFILES"
    # Загрузка по реестровому номеру (задача B)
    INVALID_REG_NUMBER = "INVALID_REG_NUMBER"
    TOO_MANY_NUMBERS = "TOO_MANY_NUMBERS"
    EIS_NOT_FOUND = "EIS_NOT_FOUND"
    EIS_UNAVAILABLE = "EIS_UNAVAILABLE"
    EIS_FALLBACK_SAMPLE = "EIS_FALLBACK_SAMPLE"  # предупреждение: XML взят из data/samples
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"  # временно, пока эндпоинт в разработке
    EMAIL_TAKEN = "EMAIL_TAKEN"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    TOO_MANY_ATTEMPTS = "TOO_MANY_ATTEMPTS"
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    HTTP_ERROR = "HTTP_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorInfo(BaseModel):
    code: ErrorCode
    message: str = Field(description="Текст для пользователя, на русском")
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorInfo


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
