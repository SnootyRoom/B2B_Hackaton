from fastapi import APIRouter, Response
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, get_active_profile
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, UserOut
from app.schemas.common import ErrorCode

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookie(response: Response, user: User) -> None:
    s = get_settings()
    response.set_cookie(
        s.cookie_name,
        create_access_token(user.id),
        max_age=s.jwt_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=s.cookie_secure,
        path="/",
    )


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterRequest, db: DB, response: Response) -> User:
    email = body.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise AppError(ErrorCode.EMAIL_TAKEN, "Пользователь с таким e-mail уже есть", 409)
    user = User(email=email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    get_active_profile(db, user.id)
    _set_cookie(response, user)
    return user


@router.post("/login", response_model=UserOut)
def login(body: LoginRequest, db: DB, response: Response) -> User:
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise AppError(ErrorCode.INVALID_CREDENTIALS, "Неверный e-mail или пароль", 401)
    _set_cookie(response, user)
    return user


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    response.delete_cookie(get_settings().cookie_name, path="/")


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user
