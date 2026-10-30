Офлайн-профили ЕГРЮЛ: `<ИНН>.json`. Используются, когда DaData недоступна или ключа нет.

Два формата (модуль `backend/app/egrul/offline.py`):

1. Сохранённый ответ DaData `findById/party` — целиком `{"suggestions": [...]}` или одна подсказка.
2. Готовый профиль по схеме `CustomerData` (`backend/app/schemas/customer.py`) — для заказчиков,
   заданных вручную (тестовые сценарии, ликвидированные организации):

```json
{
  "inn": "5410787285",
  "name": "ООО \"НЕОН\"",
  "org_type": "legal",
  "status": "liquidated",
  "registration_date": "2015-03-01",
  "liquidation_date": "2022-04-15",
  "okved_main": "49.41",
  "address": "...",
  "region": "Новосибирская область",
  "unreliable_flags": ["Недостоверные сведения об организации"]
}
```

Обязательны `inn` и `name`. `status`: `active`, `reorganizing`, `liquidating`, `liquidated`,
`bankrupt`, `unknown`. `region` — как в справочнике субъектов (`backend/app/parsers/regions.py`).
`unreliable_flags` — список отметок о недостоверности, пустой список = отметок нет. Даты — `ГГГГ-ММ-ДД`.
Незнакомые поля (например, `egrul_status`) — ошибка: файл не читается, в логе предупреждение.
