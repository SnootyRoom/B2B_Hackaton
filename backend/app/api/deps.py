import uuid
from typing import Annotated

from fastapi import Cookie, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import Base, get_db
from app.core.errors import AppError, not_found
from app.core.security import decode_access_token
from app.models import ScoringProfile, User
from app.schemas.common import ErrorCode
from app.schemas.scoring import ScoringProfileData
from app.scoring.defaults import default_profile

DB = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DB,
    access_token: Annotated[str | None, Cookie(alias=get_settings().cookie_name)] = None,
) -> User:
    user_id = decode_access_token(access_token) if access_token else None
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise AppError(ErrorCode.NOT_AUTHENTICATED, "Войдите в систему", 401)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_owned[M: Base](db: Session, model: type[M], obj_id: uuid.UUID, user: User) -> M:
    """Запись пользователя по id. Чужая или несуществующая → 404."""
    obj = db.get(model, obj_id)
    if obj is None or getattr(obj, "owner_id", None) != user.id:
        raise not_found()
    return obj


def get_active_profile(db: Session, user_id: uuid.UUID) -> ScoringProfile:
    """Активный профиль; если его нет — создаётся профиль по умолчанию."""
    profile = db.scalars(
        select(ScoringProfile)
        .where(ScoringProfile.owner_id == user_id, ScoringProfile.is_active.is_(True))
        .order_by(ScoringProfile.updated_at.desc())
    ).first()
    if profile is None:
        # Профиль по умолчанию от движка → в формат контракта (лишние поля отбрасываются)
        data = ScoringProfileData.model_validate(
            default_profile().model_dump(mode="json", exclude_none=True)
        )
        profile = ScoringProfile(
            owner_id=user_id,
            is_active=True,
            **data.model_dump(mode="json"),
        )
        db.add(profile)
        db.commit()
    return profile
