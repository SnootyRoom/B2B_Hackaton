"""Ограничение частоты неудачных попыток входа (счётчики в Redis).

Считаются только неудачные попытки: по e-mail (подбор пароля к одному аккаунту) и по IP
(перебор аккаунтов). Успешный вход сбрасывает счётчик e-mail. Redis недоступен — вход
не блокируется: защита от перебора не должна ломать вход.
"""

import hashlib
import logging
from functools import lru_cache
from typing import cast

import redis

from app.core.config import get_settings

log = logging.getLogger(__name__)

_PREFIX = "login_fail:"


@lru_cache
def _client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, socket_timeout=0.5)


def _keys(email: str, ip: str | None) -> list[tuple[str, int]]:
    s = get_settings()
    # e-mail в ключе — хэшем, чтобы не хранить адреса в Redis открытым текстом
    digest = hashlib.sha256(email.lower().encode()).hexdigest()[:32]
    keys = [(f"{_PREFIX}email:{digest}", s.login_max_failures)]
    if ip:
        keys.append((f"{_PREFIX}ip:{ip}", s.login_max_failures_ip))
    return keys


def retry_after(email: str, ip: str | None) -> int | None:
    """Через сколько секунд можно снова пробовать; None — вход разрешён."""
    try:
        r = _client()
        for key, limit in _keys(email, ip):
            count = cast("bytes | None", r.get(key))  # синхронный клиент
            if count is not None and int(count) >= limit:
                return max(cast(int, r.ttl(key)), 1)
    except redis.RedisError as e:
        log.warning("login limit: Redis недоступен (%s)", type(e).__name__)
    return None


def register_failure(email: str, ip: str | None) -> None:
    window = get_settings().login_window_s
    try:
        pipe = _client().pipeline()
        for key, _ in _keys(email, ip):
            pipe.incr(key)
            pipe.expire(key, window, nx=True)
        pipe.execute()
    except redis.RedisError as e:
        log.warning("login limit: Redis недоступен (%s)", type(e).__name__)


def reset(email: str) -> None:
    try:
        _client().delete(_keys(email, None)[0][0])
    except redis.RedisError as e:
        log.warning("login limit: Redis недоступен (%s)", type(e).__name__)


def reset_all() -> None:
    """Для тестов: сбросить все счётчики."""
    r = _client()
    keys = list(r.scan_iter(f"{_PREFIX}*"))
    if keys:
        r.delete(*keys)
