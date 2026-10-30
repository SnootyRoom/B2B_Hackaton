# Что фронтенд ждёт от API — для тимлида (роль 1)

Адреса — из `CLAUDE.md`, поля — из `docs/analytics.md`. Типы целиком: `src/api/types.ts`.
Когда схемы и OpenAPI будут в `main`, роль 4 сверяет `types.ts` с ними и правит в том же PR.

## Совпадает с CLAUDE.md

| Экран | Запрос | Что ждём в ответ |
| --- | --- | --- |
| Вход | `POST /auth/login`, `POST /auth/register` `{email, password}` | `User` + httpOnly-cookie |
| Шапка | `GET /auth/me` (401 → экран входа), `POST /auth/logout` | `User` |
| Параметры | `GET /scoring-profiles/active` (**404, если профиля ещё нет** → первый вход ведёт на «Параметры») | `ScoringProfile` |
| Параметры | `PUT /scoring-profiles/active` | `ScoringProfile` |
| Параметры | `POST /scoring-profiles/parse` `{text}` | `{rules, company_description, unparsed}` |
| «Сохранить и пересчитать» | `POST /score` `{}` | `{task_id}` |
| Загрузка | `POST /procurements/upload`, multipart, поле `files` (много) | `{task_id}` |
| Прогресс | `GET /tasks/{id}`, опрос раз в 1,5 с | `Task` (ниже) |
| Результаты | `GET /results?recommendation=&region=&nmck_min=&nmck_max=&law=&hide_expired=true` | `ResultRow[]` или `{items: ResultRow[]}` |
| Экспорт | `GET /results/export?format=csv\|json&…те же фильтры` + `deadline_from`, `deadline_to` (ГГГГ-ММ-ДД, окончание подачи с/по — на экране этот фильтр работает в браузере, в выгрузке его желательно учесть) | файл (ставим ссылку, браузер скачивает с cookie) |
| Карточка | `GET /procurements/{id}` | `{procurement, customer, customer_error, score}` |

Ошибки — `{"error": {"code", "message", "details"}}`. `message` показываем пользователю как есть,
если его нет — берём текст по `code` из таблицы аналитики (`src/lib/catalog.ts`, `ERROR_TEXT`).

## Нужно согласовать (в CLAUDE.md этого нет)

1. **Признак LLM.** Без ключа кнопка «Разобрать» должна скрываться. Предлагаю `GET /auth/me` →
   `{"id", "email", "features": {"llm": false}}`. Нет поля — считаем, что LLM есть.
2. **«Загрузить пример» (P1):** `POST /procurements/upload-demo` → `{task_id}`, берёт файлы из `data/demo/`.
3. **Ручной ИНН (P1):** `PUT /procurements/{id}/customer-inn` `{inn}` → `{task_id}` (ЕГРЮЛ + пересчёт одной закупки).
4. **Поле `enabled` у правила** — переключатель «включено» из аналитики. Выключенное правило хранится, но не считается.
6. **Короткая причина в строке результатов:** `ResultRow.reason` — одна фраза («Цена выше лимита 15 млн»),
   показывается на билете закупки. Нет поля — билет просто без причины. Проще всего взять главный минус
   из обоснования (роль 3).
5. **Правила заказчика по умолчанию** приходят от бэкенда (в ответе `parse` и в новом профиле). Фронт их сам не придумывает
   (CLAUDE.md: правила только в `defaults.py`).
7. **История загрузок (вкладка «История»):** `GET /tasks?kind=upload` → список задач загрузки, новые сверху.
   У задачи нужны `created_at` (когда загружено) и желательно `summary: {participate, consider, skip}` —
   сколько закупок из загрузки в каждой рекомендации. Нет `summary` — карточка просто без полоски.
8. **Закупки одной загрузки:** `GET /results?task_id=<id>` — фильтр результатов по загрузке (кнопка «Открыть закупки» в истории).

## Форматы, которые важны фронту

- `Task.files[]`: `{name, status: pending|ok|error, error: {code, message}|null, warnings: [{code, message}], procurement_ids: number[]}`.
  `CUSTOMER_NOT_FOUND` и `EGRUL_UNAVAILABLE` — это `warnings` при `status: ok`. По `procurement_ids` из файла делаем ссылку «Открыть».
- `ScoreResult.rules[]`: `{rule_id, group, kind, label, field_value_text, partial_score, contribution, max_contribution, no_data, triggered}`.
  `field_value_text` — значение уже человеческим текстом («4 200 000 ₽», «Томская область»): так фронту не нужно знать каждое поле.
  `contribution` — Δr из аналитики, `max_contribution` — сколько правило могло дать при s = 1.
- `ScoreResult.groups[]`: `{group, score|null, weight, low_data}` — `weight` после перераспределения (0–1), `score: null` — группа исключена.
- `justification.text` — ссылки на правила в квадратных скобках `[rule_id]`; фронт превращает их в номера и подсвечивает правило.
- Деньги (`nmck`, `bid_security`, `price`) — строкой Decimal, например `"4200000.00"`. Даты — ISO 8601 в UTC.

## docker-compose

```yaml
  frontend:
    build: ./frontend
    ports:
      - "3000:80"
    depends_on:
      - backend
```

nginx в контейнере пересылает `/api/` на `http://backend:8000` (имя сервиса `backend`, как в CLAUDE.md).
Фронт и API на одном адресе — cookie входа работает без настройки CORS.
