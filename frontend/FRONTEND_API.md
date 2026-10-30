# Как фронтенд работает с API

Источник правды — бэкенд: схемы `backend/app/schemas/`, выгрузка `docs/openapi.json`.
`src/api/types.ts` повторяет их. Меняется схема — меняем типы в том же PR.

## Что важно помнить

- `id` всех записей — UUID-строка. Деньги — число. Даты — ISO 8601 в UTC.
- Ошибки — `{"error": {"code", "message", "details"}}`, `message` показываем как есть.
- Всё тяжёлое идёт через задачу: ответ `202 {task_id}`, дальше опрос `GET /tasks/{id}`.
- Разбор текста (`POST /scoring-profiles/parse`) тоже задача: правила лежат в `Task.result`.
  Ожидание спрятано в `api.parseProfileText`.
- Сохранение профиля (`PUT /scoring-profiles/active`) возвращает `{profile, task_id}`;
  с `rescore: true` оно же запускает пересчёт.
- Признак LLM — `llm_enabled` в `GET /scoring-profiles/catalog`: `false` → кнопку «Составить правила» не показываем.
- Новому пользователю профиль создаётся сам, `404` на него не бывает. Шаг 1 на стартовой странице
  считается пройденным, когда в профиле есть критерии не только о заказчике.

## Оценка закупки

- `rules[].status`: `applied` / `no_data` / `disabled`. Выключенные правила в разборе не показываем.
- `rules[].text` — готовая фраза для показа, `field_value` — сырое значение.
- Максимум правила = `contribution + lost` (`maxContribution` в `lib/rules.ts`).
- `groups[].effective_weight` — вес после перераспределения, `weight` — из профиля.
- `stop_factors` — список `rule_id`; сами причины — в `rules[]` с `triggered: true`.
- `justification` — строка со ссылками `[rule_id]`, источник — `justification_source`.

## Что считается в браузере

Фильтры, поиск и сортировка результатов, а также экспорт CSV/JSON (`lib/export.ts`): `GET /results`
отдаёт полный список. Закупки одной загрузки берутся из `procurement_ids` её файлов.

## Пока только в демо-режиме (P1)

На бэкенде нет: загрузки `.zip`, `POST /procurements/upload-demo` («Попробовать на примере»),
`PUT /procurements/{id}/customer-inn` (ручной ИНН). Кнопки показываются при `VITE_USE_MOCK=true`.
