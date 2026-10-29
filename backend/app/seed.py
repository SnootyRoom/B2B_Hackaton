"""Создание демо-пользователя при старте (логин и пароль из .env)."""

import logging

from sqlalchemy import select

from app.api.deps import get_active_profile
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.logging import setup_logging
from app.core.security import hash_password
from app.models import User

log = logging.getLogger(__name__)


def seed_demo_user() -> None:
    s = get_settings()
    email = s.demo_user_email.lower()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, password_hash=hash_password(s.demo_user_password))
            db.add(user)
            db.commit()
            log.info("Создан демо-пользователь %s", email)
        get_active_profile(db, user.id)


if __name__ == "__main__":
    setup_logging()
    seed_demo_user()
