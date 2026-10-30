"""Единственная точка доступа к LLM по OpenAI-совместимому протоколу (YandexGPT, ProxyAPI).

Нет LLM_API_KEY → client.enabled = False, вызывающий код работает без LLM.
Любая ошибка провайдера → LLMUnavailable, обработку она не роняет.

YandexGPT: LLM_BASE_URL=https://ai.api.cloud.yandex.net/v1, LLM_FOLDER_ID=<каталог>,
LLM_MODEL=yandexgpt-lite/latest — превращается в gpt://<каталог>/yandexgpt-lite/latest.
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"
DEFAULT_TIMEOUT_S = 20.0

JsonObject = dict[str, object]


class LLMUnavailable(Exception):
    """Нет ключа, провайдер не ответил или ответ не JSON."""


class LLMCache(Protocol):
    def get(self, key: str) -> JsonObject | None: ...
    def set(self, key: str, value: JsonObject) -> None: ...


class MemoryCache:
    """Кэш в памяти процесса. Роль 1 подменит его кэшем в Postgres."""

    def __init__(self) -> None:
        self._data: dict[str, JsonObject] = {}

    def get(self, key: str) -> JsonObject | None:
        return self._data.get(key)

    def set(self, key: str, value: JsonObject) -> None:
        self._data[key] = value


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
        return cls(
            os.environ.get("LLM_BASE_URL"),
            os.environ.get("LLM_API_KEY"),
            os.environ.get("LLM_MODEL"),
            folder_id=os.environ.get("LLM_FOLDER_ID"),
            cache=cache,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self._api_key and self.model)

    def cache_key(self, prompt: Prompt, messages: list[dict[str, str]]) -> str:
        payload = json.dumps([self.model, prompt.name, prompt.version, messages], ensure_ascii=False, sort_keys=True)
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
                    schema_hint = "\n\nОтвет — JSON по схеме:\n" + json.dumps(schema, ensure_ascii=False)
                    body["messages"] = [{**messages[0], "content": messages[0]["content"] + schema_hint}, *messages[1:]]
                    resp = http.post(url, headers=headers, json=body)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            data = _extract_json(str(content))
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as e:
            # ключ в лог не попадает: логируем только тип ошибки и модель
            log.warning("LLM %s: %s", self.model, type(e).__name__)
            if isinstance(e, httpx.HTTPStatusError):
                log.warning("LLM ответ %s: %s", e.response.status_code, e.response.text[:500])
            raise LLMUnavailable(str(type(e).__name__)) from e

        self._cache.set(key, data)
        return data
