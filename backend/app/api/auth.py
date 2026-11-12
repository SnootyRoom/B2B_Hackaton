from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, get_active_profile
from app.core import login_limit
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, UserOut
from app.schemas.common import ErrorCode, ErrorResponse

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


def _client_ip(request: Request) -> str | None:
    """Адрес пользователя: nginx фронта передаёт его в X-Real-IP."""
    return request.headers.get("x-real-ip") or (request.client.host if request.client else None)


@router.post(
    "/login",
    response_model=UserOut,
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
def login(body: LoginRequest, db: DB, request: Request, response: Response) -> User:
    email, ip = body.email.lower(), _client_ip(request)
    wait = login_limit.retry_after(email, ip)
    if wait is not None:
        minutes = max(1, -(-wait // 60))
        raise AppError(
            ErrorCode.TOO_MANY_ATTEMPTS,
            f"Слишком много неудачных попыток входа. Попробуйте через {minutes} мин.",
            429,
            {"retry_after": wait},
        )
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not verify_password(body.password, user.password_hash):
        login_limit.register_failure(email, ip)
        raise AppError(ErrorCode.INVALID_CREDENTIALS, "Неверный e-mail или пароль", 401)
    login_limit.reset(email)
    _set_cookie(response, user)
    return user


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    response.delete_cookie(get_settings().cookie_name, path="/")


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user
