from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ORMModel

# bcrypt учитывает только первые 72 байта пароля (≈ 36 русских букв)
PASSWORD_MAX_BYTES = 72


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def _fits_bcrypt(cls, v: str) -> str:
        if len(v.encode()) > PASSWORD_MAX_BYTES:
            raise ValueError(
                "Пароль слишком длинный: не больше 72 латинских символов или 36 русских букв"
            )
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORMModel):
    id: UUID
    email: str
    created_at: datetime
