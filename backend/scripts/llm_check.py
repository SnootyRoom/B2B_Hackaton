"""Проверка LLM на настоящем провайдере: текст параметров → правила.

Запуск из папки backend:
    uv run --no-project --python 3.12 --with pydantic --with httpx python scripts/llm_check.py
Настройки берутся из ../.env (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_FOLDER_ID).
"""

import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm.client import LLMClient
from app.llm.parse_profile import ProfileParseError, parse_profile_text
from app.scoring.defaults import DEFAULT_RULE_IDS

EXAMPLE = (
    "Мы IT-компания из Томска, разрабатываем и сопровождаем ПО. Интересны аукционы и запросы котировок "
    "в Томской и Новосибирской областях от 500 тыс. до 15 млн, обеспечение контракта не больше 10%, "
    "не меньше 5 дней на подачу заявки. Хотим крупные и надёжные закупки."
)


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_env(Path(__file__).resolve().parents[2] / ".env")

    client = LLMClient.from_env()
    if not client.enabled:
        print("LLM не настроена: заполните LLM_BASE_URL, LLM_API_KEY и LLM_MODEL в .env")
        return 1
    print(f"Адрес: {client.base_url}\nМодель: {client.model}\n")  # ключ не печатаем

    text = " ".join(sys.argv[1:]) or EXAMPLE
    print(f"Текст: {text}\n")
    started = time.perf_counter()
    try:
        profile = parse_profile_text(text, client)
    except ProfileParseError as e:
        print(f"Ошибка: {e.message} (подробности в логе выше)")
        return 1

    print(f"Готово за {time.perf_counter() - started:.1f} с\n")
    print(f"О компании: {profile.company_description}\n")
    print("Правила от ИИ:")
    for r in profile.rules:
        if r.id not in DEFAULT_RULE_IDS:
            print(f"  [{r.id}] {r.label}: {r.field} {r.operator} {r.value} (важность {r.weight})")
    if profile.unparsed:
        print("\nНе удалось разобрать:")
        for u in profile.unparsed:
            print(f"  - {u}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
