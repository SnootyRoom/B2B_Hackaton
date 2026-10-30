# Поля извещений ЕИС: пути тегов

Заполняется ролью 2 по мере сбора образцов. Пути — по локальным именам тегов (без namespace).
Одна таблица на тип документа; новый тип = новая таблица + адаптер + образец + тест.

В коде (`backend/app/parsers/`) имена тегов приводятся к нижнему регистру, пути записаны
так же: `commoninfo/purchasenumber`. Ниже — в исходном регистре, как в XML. `//` — поиск
на любой глубине. Если путей несколько, берётся первый, по которому нашлось значение.

> **Статус.** Пути составлены по схемам ЕИС и проверены на тестовых XML
> (`backend/tests/parsers/fixtures/`) той же структуры. Реальных образцов в `data/samples/`
> пока нет: zakupki.gov.ru использует сертификат НУЦ Минцифры, без него сайт не открывается.
> После сбора образцов пути сверяются, расхождения правятся здесь и в адаптерах.

## Нормализация (общая для всех адаптеров, `normalize.py`)

| Поле | Правило |
| --- | --- |
| reg_number | только цифры; лот многолотового извещения → `<номер>-<лот>` |
| nmck, суммы | `Decimal`; пробелы и запятая допускаются: `3 000 000,00` |
| даты | в UTC; без смещения считаются московским временем; `2026-11-15` и `2026-11-15+03:00` → полночь этого дня |
| method | по тексту способа: «аукцион» → `auction`, «конкурс» → `contest`, «котиров» → `quotation`, «предложени» → `proposals`, «единствен» → `single`, иначе `other` |
| customer_inn | 10 или 12 цифр с верной контрольной суммой, иначе пусто |
| region | к справочнику `regions.py` по месту поставки, затем по адресу заказчика; берётся самое раннее совпадение в адресе |
| delivery_days | «N календарных дней» → N; «N рабочих дней» → ⌈N·7/5⌉; «до ДД.ММ.ГГГГ» → дней от даты размещения |
| okpd2_codes | коды позиций и лота; код КТРУ `62.01.11.000-00000002` → `62.01.11.000`; без дублей |
| обеспечения | процент → рубли от НМЦК и наоборот, процент сохраняется в `*_pct` |
| restrictions | по текстам преимуществ и запретов: СМП/СОНКО → `smp_only`, УИС → `prefs_uis`, инвалиды → `prefs_disabled`, иностранные товары / нацрежим → `national_regime`, прочее → `other` |
| law | по адаптеру; в универсальном — `615` по имени корня, 19 цифр → `44`, 11 цифр → `223`, иначе `other` |

Не извещения (корень содержит `protocol`, `contract`, `plan`, `cancel`, `clarification`,
`explanation`, `complaint`) → `NOT_A_NOTICE`. Не найдено ни одного обязательного поля →
`NOT_A_NOTICE`, часть → `MISSING_REQUIRED_FIELD`. Если адаптер не нашёл обязательные поля,
документ пробует универсальный адаптер.

## 44-ФЗ: `epNotification*2020` (формат с 2020 г.) и `fcsNotification*` (прежний)

Адаптер `adapters/eis44.py`, `parsed_by = adapter:eis44`.
Образцы: `backend/tests/parsers/fixtures/notice44_ef2020.xml` (тестовый), `data/samples/` — нет.

| Поле `Procurement` | Путь в XML | Примечание |
| --- | --- | --- |
| reg_number | `commonInfo/purchaseNumber` | |
| subject | `commonInfo/purchaseObjectInfo` | |
| nmck | `//maxPriceInfo/maxPrice`, `//lot/maxPrice` | старый формат — в `lot` |
| currency | `//maxPriceInfo/currency/code` | |
| method / method_raw | `commonInfo/placingWay/name` | |
| customer_inn | `//customerRequirementInfo/customer/INN`; иначе `responsibleOrgInfo/INN` | ИНН размещающей организации берётся, только если `responsibleRole = CU` или её наименование совпадает с заказчиком: ИНН уполномоченного органа не подставляем |
| customer_name | `//customerRequirementInfo/customer/fullName`, `//responsibleOrgInfo/fullName` | |
| region / delivery_place | `//deliveryPlaceInfo/GARInfo/GARAddress`, `//deliveryPlaceInfo/deliveryPlace`, `//deliveryPlace`; запасной — `responsibleOrgInfo/factAddress`, `postAddress` | |
| published_at | `commonInfo/publishDTInEIS`, `//docPublishDate` | |
| application_deadline | `//collectingInfo/endDT`, `//collecting/endDate` | |
| delivery_term_text | `//deliveryTerm`, `//deliveryTermsInfo` | проверить по образцам |
| okpd2_codes | `purchaseObject/OKPD2/OKPDCode`, `OKPD2/code`, `KTRU/code` | |
| items | `//purchaseObject`: `name`, `quantity/value`, `OKEI/name`, `price` | |
| bid_security | `//applicationGuarantee/amount`, `part` (%) | |
| contract_security | `//contractGuarantee/amount`, `part` (%) | |
| restrictions | `//preferenseInfo//name`, `//restrictionInfo//name`, `//requirementInfo//name` со словом «малого» | |
| source_url | `commonInfo/href` | иначе ссылка на поиск ЕИС по номеру |
| лоты | `//lots/lot`, номер `lotNumber` | в формате 2020 лот один |

## 223-ФЗ: `purchaseNotice*` (`purchaseNoticeAE`, `purchaseNoticeOK`, `purchaseNoticeZK`, …)

Адаптер `adapters/eis223.py`, `parsed_by = adapter:eis223`. Общие сведения — в
`body/item/purchaseNotice*Data`, НМЦК и позиции — в лотах.
Образцы: `backend/tests/parsers/fixtures/notice223_multilot.xml` (тестовый), `data/samples/` — нет.

| Поле `Procurement` | Путь в XML (от `purchaseNotice*Data` / от лота) | Примечание |
| --- | --- | --- |
| reg_number | `registrationNumber` | 11 цифр |
| subject | лот: `lotData/subject`; извещение: `name` | |
| nmck | лот: `lotData/initialSum` | |
| currency | лот: `lotData/currency/code` | |
| method / method_raw | `purchaseCodeName` | |
| customer_inn / customer_name | `customer/mainInfo/inn`, `customer/mainInfo/fullName` | |
| region / delivery_place | лот: `lotData/deliveryPlace/address`; запасной — `customer/mainInfo/legalAddress` | |
| published_at | `publicationDateTime` | |
| application_deadline | `submissionCloseDateTime` | |
| delivery_term_text | — | в извещении 223-ФЗ обычно нет |
| okpd2_codes | `lotItem/okpd2/code` | |
| items | `//lotItem`: `okpd2/name` или `additionalInfo`, `qty`, `okei/name` | |
| bid_security / contract_security | — | в извещении 223-ФЗ обычно нет |
| restrictions | `lotData/forSmallOrMiddle = true` → `smp_only` | |
| source_url | `urlEIS` | |
| лоты | `lots/lot`, номер `ordinalNumber` | больше одного лота → запись на лот `<номер>-<лот>` |

## Прочие (ПП 615, 94-ФЗ, неизвестные схемы) — универсальный адаптер

`universal.py`, `parsed_by = universal`; документ — один лот. Обёртки `export`, `body`, `item`
с единственным потомком снимаются. Тестовый образец: `notice615_unknown.xml` (`pprf615NotificationEF`,
windows-1251).

## Словарь синонимов для универсального адаптера

Полный список — `backend/app/parsers/synonyms.py`; поиск на любой глубине.

| Поле | Синонимы тегов |
| --- | --- |
| reg_number | `purchaseNumber`, `registrationNumber`, `notificationNumber`, `purchaseNoticeNumber`, `noticeNumber`, `purchaseRegNumber` |
| nmck | `maxPriceInfo/maxPrice`, `maxPrice`, `initialSum`, `contractMaxPrice`, `maxContractPrice`, `startPrice`, `initialPrice`, `nmck` |
| subject | `purchaseObjectInfo`, `lotData/subject`, `lot/subject`, `purchaseName`, `lotName`, `objectName`, `subject`, `name` (только верхний уровень) |
| customer_inn | `INN` внутри `customer`, `customerInfo`, `responsibleOrgInfo`, `responsibleOrg`, `organizer`, `placer`; затем любой `INN` |
| method_raw | `placingWay/name`, `purchaseCodeName`, `purchaseMethodName`, `methodName` |
| application_deadline | `collectingInfo/endDT`, `collecting/endDate`, `submissionCloseDateTime`, `applicationEndDate`, `endDT`, `endDate` |
| published_at | `publishDTInEIS`, `publicationDateTime`, `docPublishDate`, `publishDate`, `createDateTime` |
| delivery_place | `GARAddress`, `deliveryPlace/address`, `deliveryPlace`, `deliveryAddress` |
