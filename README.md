# Скоринг закупок (AI Procurement Copilot, задача 4)

Веб-сервис для поставщика: загружаете извещения ЕИС (`.xml` / `.json`), система извлекает
параметры закупки, подтягивает данные заказчика из ЕГРЮЛ по ИНН и выдаёт оценку 0–100%,
рекомендацию «Участвовать / Рассмотреть / Пропустить» и обоснование.

## Запуск

```bash
cp .env.example .env      # ключи необязательны: без них система работает
docker-compose up --build
```

- Интерфейс: http://localhost:3000
- API и Swagger: http://localhost:8000/docs (контракт также в `docs/openapi.json`)
- Демо-вход: `demo@example.com` / `demo12345` (меняется в `.env`)

При старте бэкенд сам применяет миграции и создаёт демо-пользователя.

| Сервис | Что делает |
| --- | --- |
| `frontend` | nginx: статика React + прокси `/api` → `backend` (одно происхождение, cookie работают) |
| `backend` | FastAPI; синхронные ответы < 2 с, всё тяжёлое ставится в очередь |
| `worker` | Celery: парсинг → ЕГРЮЛ → эмбеддинг → оценка, по файлу за раз с прогрессом |
| `db` | PostgreSQL 16 + pgvector: данные и векторный поиск смыслового сравнения |
| `redis` | брокер очереди |

Модель эмбеддингов `intfloat/multilingual-e5-small` скачивается при сборке образа.

## Переменные окружения

См. `.env.example`. Комментарии в `.env` — только отдельной строкой: docker-compose считает
текст после `=` значением.

- `JWT_SECRET` — свой длинный случайный ключ для подписи входа.
- `LLM_API_KEY` и `LLM_FOLDER_ID` — доступ к YandexGPT. Пусто → правила задаются вручную,
  обоснование по шаблону.
- `DADATA_API_KEY` — ЕГРЮЛ. Пусто → только кэш и офлайн-профили `data/customers/<ИНН>.json`.

**Модель LLM:** YandexGPT Pro через Yandex AI Studio, `LLM_MODEL=yandexgpt/latest`
(URI `gpt://<каталог>/yandexgpt/latest`). Окончательная версия фиксируется после проверки
на тестовых сценариях.

**Справочник ОКПД2:** `data/okpd2.csv` (`code;name`, ОК 034-2014 от класса до вида `XX.XX.XX`,
5654 кода, по дереву classifikators.ru) и индекс векторов `data/okpd2.npy` рядом. Коды профиля
подбираются по нему: кандидаты по смыслу (e5) → выбор LLM (`backend/app/llm/okpd2_search.py`,
промпт `okpd2_pick.md`). Индекс пересобирается после замены CSV:
`docker-compose run --rm -v ./data:/out -e OKPD2_CSV=/out/okpd2.csv backend python scripts/build_okpd2_index.py`.
Без справочника или модели коды берутся из ручных категорий `backend/app/llm/okpd2.py`.

## Как устроена обработка

1. `POST /api/procurements/upload` сохраняет файлы и сразу отвечает `202 {"task_id"}` —
   поэтому большие пакеты не дают 504.
2. Воркер обрабатывает файлы по одному; ошибка в файле не останавливает пакет.
3. Фронт опрашивает `GET /api/tasks/{id}` раз в 1–2 с: `processed` из `total`, статусы файлов.
4. Итог задачи: `done` / `partial` / `failed`.

Ошибки API всегда в формате `{"error": {"code", "message", "details"}}`.
Чужие записи → 404. Суммы в JSON — числа (внутри `Decimal`), даты — ISO 8601 в UTC.

## Примеры запросов

```bash
# вход (cookie сохраняется в jar)
curl -c jar -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"demo12345"}' localhost:8000/api/auth/login
curl -b jar localhost:8000/api/auth/me
curl -c jar -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"password123"}' localhost:8000/api/auth/register
curl -b jar -X POST localhost:8000/api/auth/logout

# загрузка и прогресс
curl -b jar -F files=@tests/dataset/procurements/0102200001626002273.xml -F files=@notice.json \
  localhost:8000/api/procurements/upload            # → {"task_id": "..."}
curl -b jar localhost:8000/api/tasks/<task_id>
curl -b jar "localhost:8000/api/tasks?kind=upload"  # история загрузок

# закупки и результаты
curl -b jar localhost:8000/api/procurements
curl -b jar localhost:8000/api/procurements/<id>    # карточка: данные, заказчик, оценка
curl -b jar localhost:8000/api/results              # таблица, по убыванию оценки

# профиль скоринга
curl -b jar localhost:8000/api/scoring-profiles/catalog   # поля для правил, регионы, llm_enabled
curl -b jar localhost:8000/api/scoring-profiles/active
curl -b jar -X PUT -H 'Content-Type: application/json' \
  -d @profile.json localhost:8000/api/scoring-profiles/active   # "rescore": true → task_id
curl -b jar -H 'Content-Type: application/json' \
  -d '{"text":"Интересны аукционы в Томской области до 10 млн"}' \
  localhost:8000/api/scoring-profiles/parse         # → task_id, правила в TaskOut.result

# пересчёт и заказчик
curl -b jar -H 'Content-Type: application/json' -d '{}' localhost:8000/api/score
curl -b jar localhost:8000/api/organizations/7017000019   # 200 из кэша, иначе 202 + task_id
```

Формат JSON-файла закупки — схема `ProcurementData` (объект или список лотов):

```json
{"reg_number": "0365000000000000001", "subject": "Сопровождение ПО",
 "nmck": 4200000, "method": "auction", "customer_inn": "7017000019",
 "region": "Томская область", "application_deadline": "2026-11-20T10:00:00Z"}
```

## Разработка

```bash
docker-compose exec backend pytest
docker-compose exec backend sh -c "ruff check . && ruff format --check . && mypy app"
docker-compose exec backend python /repo/tests/dataset/evaluate.py   # проверка тестовых данных
docker-compose exec backend alembic revision --autogenerate -m "..."  # после изменения моделей
```

Правила команды, роли и архитектура — в `CLAUDE.md`; ТЗ и аналитика — в `docs/`.

### Контракты между модулями

| Модуль (роль) | Функция, которую вызывает конвейер |
| --- | --- |
| `parsers/registry.py` (2) | `parse_file(content, filename) -> list[ProcurementData]`, ошибки — `ParseError` |
| `egrul/service.py` (2) | `lookup(db, inn) -> CustomerLookup` (воркер), `get_cached(db, inn)` (API, без сети) |
| `scoring/engine.py` (3) | `score(profile, fields, similarity) -> ScoreResultData`, поля — `extract_fields(procurement, customer, now)` |
| `embeddings/service.py` (3) | `embed_passage(text)`, `similarity_in_db(db, procurement_id, query)` (pgvector) |
| `llm/client.py` (3) | `parse_profile_text(db, text) -> ParseProfileResult`, ошибки — `LLMError` |

Схемы — `backend/app/schemas/`. Меняете схему → обновите `docs/openapi.json`, фронт и тесты в том же PR.
