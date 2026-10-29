# Поля извещений ЕИС: пути тегов

Заполняется ролью 2 по мере сбора образцов. Пути — по локальным именам тегов (без namespace).
Одна таблица на тип документа; новый тип = новая таблица + адаптер + образец + тест.

## <Тип документа, корневой элемент>

Образцы: `data/samples/...`

| Поле `Procurement` | Путь в XML | Примечание |
| --- | --- | --- |
| reg_number | | |
| subject | | |
| nmck | | |
| currency | | |
| method / method_raw | | |
| customer_inn / customer_name | | |
| region / delivery_place | | |
| published_at | | |
| application_deadline | | |
| delivery_term_text | | |
| okpd2_codes | | |
| items | | |
| bid_security | | |
| contract_security | | |
| restrictions | | |
| лоты | | как перечислены лоты, если их несколько |

## Словарь синонимов для универсального адаптера

| Поле | Синонимы тегов (из образцов) |
| --- | --- |
| reg_number | |
| nmck | |
| subject | |
| customer_inn | |
