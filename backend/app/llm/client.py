"""Единственная точка доступа к LLM (роль 3), OpenAI-совместимый протокол (YandexGPT).

Контракт для конвейера:
- `parse_profile_text(db, text) -> ParseProfileResult`; ошибки — `LLMError` с кодом
  LLM_UNAVAILABLE (нет ключа / провайдер не ответил) или LLM_PARSE_FAILED.

Нет ключа → client.enabled = False, система работает без LLM.
YandexGPT: LLM_BASE_URL=https://ai.api.cloud.yandex.net/v1, LLM_FOLDER_ID=<каталог>,
LLM_MODEL=yandexgpt/latest — превращается в gpt://<каталог>/yandexgpt/latest.
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import LLMCache as LLMCacheRow
from app.schemas.common import ErrorCode
from app.schemas.scoring import ParseProfileResult

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"
DEFAULT_TIMEOUT_S = 20.0

JsonObject = dict[str, object]


class LLMError(Exception):
    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class LLMUnavailable(Exception):
    """Нет ключа или провайдер не ответил."""


class LLMBadAnswer(Exception):
    """Провайдер ответил, но не JSON-объектом."""


class LLMCache(Protocol):
    def get(self, key: str) -> JsonObject | None: ...
    def set(self, key: str, value: JsonObject) -> None: ...


class MemoryCache:
    """Кэш в памяти процесса — для скриптов и тестов."""

    def __init__(self) -> None:
        self._data: dict[str, JsonObject] = {}

    def get(self, key: str) -> JsonObject | None:
        return self._data.get(key)

    def set(self, key: str, value: JsonObject) -> None:
        self._data[key] = value


class DbCache:
    """Кэш в таблице llm_cache. Коммит делает вызывающий код."""

    def __init__(self, db: Session, model: str) -> None:
        self._db = db
        self._model = model

    def get(self, key: str) -> JsonObject | None:
        row = self._db.get(LLMCacheRow, key)
        return row.response if row is not None and isinstance(row.response, dict) else None

    def set(self, key: str, value: JsonObject) -> None:
        self._db.merge(LLMCacheRow(key=key, model=self._model, response=value))
        self._db.flush()


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str


def load_prompt(name: str) -> Prompt:
    """Файл prompts/<name>.md, первая строка — `version: N`."""
    raw = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    first, _, body = raw.partition("\n")
    if not first.startswith("version:"):
        raise ValueError(f"В промпте {name} нет строки version")
    return Prompt(name=name, version=first.split(":", 1)[1].strip(), text=body.strip())


def _extract_json(text: str) -> JsonObject:
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s.removeprefix("json").strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end < start:
        raise ValueError("В ответе нет JSON-объекта")
    data = json.loads(s[start : end + 1])
    if not isinstance(data, dict):
        raise TypeError("Ответ не JSON-объект")
    return data


class LLMClient:
    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        model: str | None,
        *,
        folder_id: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        cache: LLMCache | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self._api_key = api_key or ""
        self._folder_id = folder_id or ""
        model = model or ""
        if self._folder_id and model and "://" not in model:
            model = f"gpt://{self._folder_id}/{model}"
        self.model = model
        self._timeout = timeout
        self._cache: LLMCache = cache if cache is not None else MemoryCache()
        self._transport = transport

    @classmethod
    def from_env(cls, cache: LLMCache | None = None) -> "LLMClient":
        """Из переменных окружения — для скриптов вне приложения."""
        return cls(
            os.environ.get("LLM_BASE_URL"),
            os.environ.get("LLM_API_KEY"),
            os.environ.get("LLM_MODEL"),
            folder_id=os.environ.get("LLM_FOLDER_ID"),
            cache=cache,
        )

    @classmethod
    def from_settings(cls, db: Session | None = None) -> "LLMClient":
        s = get_settings()
        client = cls(s.llm_base_url, s.llm_api_key, s.llm_model, folder_id=s.llm_folder_id)
        if db is not None:
            client._cache = DbCache(db, client.model)
        return client

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self._api_key and self.model)

    def cache_key(self, prompt: Prompt, messages: list[dict[str, str]]) -> str:
        payload = json.dumps(
            [self.model, prompt.name, prompt.version, messages], ensure_ascii=False, sort_keys=True
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def complete_json(
        self,
        prompt: Prompt,
        user_message: str,
        schema: JsonObject,
        *,
        extra_messages: list[dict[str, str]] | None = None,
    ) -> JsonObject:
        """Ответ модели как JSON-объект. temperature 0, структурированный вывод по схеме."""
        if not self.enabled:
            raise LLMUnavailable("LLM не настроена")

        messages = [
            {"role": "system", "content": prompt.text},
            {"role": "user", "content": user_message},
            *(extra_messages or []),
        ]
        key = self.cache_key(prompt, messages)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self._folder_id:
            headers["OpenAI-Project"] = self._folder_id
        body: JsonObject = {
            "model": self.model,
            "temperature": 0,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": prompt.name, "strict": True, "schema": schema},
            },
        }
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as http:
                url = f"{self.base_url}/chat/completions"
                resp = http.post(url, headers=headers, json=body)
                if resp.status_code == 400:
                    # провайдер не принял JSON-схему → просим просто JSON, схему кладём в инструкцию
                    log.info("LLM %s: json_schema не поддержан, повтор с json_object", self.model)
                    body["response_format"] = {"type": "json_object"}
                    hint = "\n\nОтвет — JSON по схеме:\n" + json.dumps(schema, ensure_ascii=False)
                    body["messages"] = [
                        {**messages[0], "content": messages[0]["content"] + hint},
                        *messages[1:],
                    ]
                    resp = http.post(url, headers=headers, json=body)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            # ключ в лог не попадает: логируем только тип ошибки, модель и ответ провайдера
            log.warning("LLM %s: %s", self.model, type(e).__name__)
            if isinstance(e, httpx.HTTPStatusError):
                log.warning("LLM ответ %s: %s", e.response.status_code, e.response.text[:500])
            raise LLMUnavailable(type(e).__name__) from e
        try:
            content = resp.json()["choices"][0]["message"]["content"]
            data = _extract_json(str(content))
        except (KeyError, IndexError, TypeError, ValueError) as e:
            log.warning("LLM %s: ответ не JSON (%s)", self.model, type(e).__name__)
            raise LLMBadAnswer(type(e).__name__) from e

        self._cache.set(key, data)
        return data


def parse_profile_text(db: Session, text: str) -> ParseProfileResult:
    """Текст параметров → черновик правил. Вызывается из фоновой задачи."""
    from app.llm.parse_profile import parse_text

    client = LLMClient.from_settings(db)
    if not client.enabled:
        raise LLMError(ErrorCode.LLM_UNAVAILABLE, "Разбор текста недоступен")
    return parse_text(text, client)
