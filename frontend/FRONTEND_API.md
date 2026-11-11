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

## Несколько профилей и сравнение (задача A)

Схемы — `backend/app/schemas/scoring.py` (`ProfileSummary`, `CreateProfileRequest`,
`RenameProfileRequest`, `ProfileTaskResponse`) и `procurement.py` (`CompareOut`).
Отмеченные «501» пока отвечают `NOT_IMPLEMENTED` — работаем на моках.

| Запрос | Ответ | Готово |
| --- | --- | --- |
| `GET /scoring-profiles` | `ProfileSummary[]`, активный первым | ✅ |
| `GET /scoring-profiles/{id}` | `ScoringProfileOut` | ✅ |
| `POST /scoring-profiles` `{name, template?, rules?, ...}` | `201 ScoringProfileOut` | 501 |
| `PUT /scoring-profiles/{id}` (тело как у `/active`) | `SaveProfileResponse` | 501 |
| `PATCH /scoring-profiles/{id}` `{name}` | `ProfileSummary` | 501 |
| `POST /scoring-profiles/{id}/duplicate` | `201 ScoringProfileOut` | 501 |
| `DELETE /scoring-profiles/{id}` | `{task_id: uuid \| null}` | 501 |
| `POST /scoring-profiles/{id}/activate` | `{task_id: uuid \| null}` | 501 |
| `GET /results?profile_id=` | `ResultRow[]`, у строк `stale` | ✅ |
| `POST /score` `{profile_id?, only_stale?}` | `202 {task_id}` | ✅ |
| `GET /results/compare?a=&b=` | `CompareOut` | 501 |

- `GET/PUT /scoring-profiles/active` остаются как были.
- `task_id: null` у activate/DELETE — пересчитывать нечего, ждать не нужно.
  Повторный activate во время пересчёта вернёт тот же `task_id`.
- `ResultRow.stale: true` — оценки нет или она устарела → в таблице «пересчитывается».
- Сравнение только читает. `CompareOut.missing > 0` → запустить
  `POST /score {profile_id: a, only_stale: true}` и то же для `b`, показать прогресс задач,
  затем перезапросить сравнение.
- `CompareRow.change`: `better` / `worse` / `same` / `unknown` (нет одной из оценок) —
  изменение рекомендации от A к B; `delta = b.total − a.total`; `explanation` — готовый текст
  со ссылками `[rule_id]`.
- Ошибки: `PROFILE_NAME_TAKEN` (409), `LAST_PROFILE` (400), `TOO_MANY_PROFILES` (400, лимит 20).

## Загрузка по реестровому номеру (задача B)

- `POST /procurements/fetch` `{numbers: string[]}` → `202 {task_id}` (пока 501).
  Можно слать строки как есть из поля: сервер сам делит по пробелам, переносам, `,` и `;`
  и убирает повторы. Формат номера — `REG_NUMBER_PATTERN`: 11, 18 или 19 цифр.
- Неверные номера не срывают пакет: они попадают в задачу строками со статусом `error`
  и кодом `INVALID_REG_NUMBER`. Все неверные → `400 INVALID_REG_NUMBER`
  (`details.invalid`). Больше 200 номеров → `400 TOO_MANY_NUMBERS`.
- Задача `kind=fetch` — та же `TaskOut`: `files[].filename` — номер, статусы
  `pending` / `ok` / `error`. «Загружаем» — строка `pending` с позицией `== processed`.
  `ok` → `procurement_ids` ведут на карточки.
- Коды ошибок по номеру: `EIS_NOT_FOUND`, `EIS_UNAVAILABLE`, `INVALID_REG_NUMBER`;
  предупреждение `EIS_FALLBACK_SAMPLE` — документ взят из локальных образцов.
- История — `GET /tasks?kind=fetch`. Повторный номер обновляет закупку, дублей нет.
