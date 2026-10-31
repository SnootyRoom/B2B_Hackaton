# Поля извещений ЕИС: пути тегов

Заполняется ролью 2 по мере сбора образцов. Пути — по локальным именам тегов (без namespace).
Одна таблица на тип документа; новый тип = новая таблица + адаптер + образец + тест.

В коде (`backend/app/parsers/`) имена тегов приводятся к нижнему регистру, пути записаны
так же: `commoninfo/purchasenumber`. Ниже — в исходном регистре, как в XML. `//` — поиск
на любой глубине. Если путей несколько, берётся первый, по которому нашлось значение.

Пути проверены на 25 реальных извещениях из `data/samples/` (печатная форма XML с
zakupki.gov.ru). Эталоны — `backend/tests/parsers/test_samples.py`; там же проверка, что у
каждого образца есть НМЦК, способ, регион, срок подачи и ИНН заказчика с верной контрольной
суммой. Исключения — чего нет в самом извещении: срока подачи у электронного магазина
`0319200064426000189`, цены у запроса цен `32616510892`.

| Тип | Корневой элемент | Образцы | Адаптер |
| --- | --- | --- | --- |
| 44-ФЗ, аукцион | `epNotificationEF2020` | `0338200009826000713`, `0820500000826000733`, `…0841`, `…4584`, `…4788`, `…5020`, `…5362`, `…5437` | `eis44` |
| 44-ФЗ, конкурс | `epNotificationEOK2020` | `0102200001626002273` | `eis44` |
| 44-ФЗ, запрос котировок | `epNotificationEZK2020` | `0122200002526003798`, `0320300090626000468` | `eis44` |
| 44-ФЗ, электронный магазин (ч. 12 ст. 93) | `epNotificationEZT2020` | `0319200064426000189` | `eis44` |
| 44-ФЗ, прежний формат | `fcsNotificationEF` | `0820500000821002973` | `eis44` |
| 223-ФЗ | `purchaseNotice` | `32211747866` (4 лота), `32312753145`, `32616481510`, `32616510892`, `32616514797`, `32616531638`, `32616534862` | `eis223` |
| 223-ФЗ, аукцион среди МСП | `purchaseNoticeAESMBO` | `31807366283`, `32616365512`, `32616529772` | `eis223` |
| ПП 615 | `pprf615NotificationEF` | `203950000012401084`, `209150000012300421` | универсальный |

`31807366283` — тестовая запись самого заказчика в ЕИС (предмет `xxxxxxxxxx`, НМЦК
66 трлн ₽). Оставлена как пример «мусорных» данных: файл разбирается, обработка не падает.

## Нормализация (общая для всех адаптеров, `normalize.py`)

| Поле | Правило |
| --- | --- |
| reg_number | только цифры; лот многолотового извещения → `<номер>-<лот>` |
| nmck, суммы | `Decimal`; пробелы и запятая допускаются: `3 000 000,00` |
| даты | в UTC с учётом смещения из документа (в ЕИС бывает от +03:00 до +12:00); без смещения — время в поясе из `tz_offset` адаптера (сдвиг от МСК в часах), если его нет — московское |
| method | по тексту способа: «аукцион» → `auction`, «конкурс» → `contest`, «котиров» → `quotation`, «предложени» → `proposals`, «единствен» → `single`, иначе `other` (например, «электронный магазин», «многолотовое ПДО») |
| customer_inn | 10 или 12 цифр с верной контрольной суммой, иначе пусто |
| region | к справочнику `regions.py`: отдельное поле региона (если есть) → место поставки → адрес заказчика; в адресе берётся самое раннее совпадение |
| delivery_days | «N календарных дней» → N; «N рабочих дней» → ⌈N·7/5⌉; «по / до / не позднее ДД.ММ.ГГГГ» → дней от даты размещения |
| okpd2_codes | коды позиций и лота; код КТРУ `21.20.10.132-00005` → `21.20.10.132`; без дублей |
| обеспечения | процент главнее суммы: сумма пересчитывается от НМЦК (в совместных закупках сумма в документе — доля одного заказчика); нет процента → процент считается по сумме; «5% от начальной цены» → 5 |
| restrictions | по текстам преимуществ и запретов, в т. ч. по ссылкам на статьи 44-ФЗ: ч. 3 ст. 30, СМП, СОНКО → `smp_only`; ст. 28, УИС → `prefs_uis`; ст. 29, инвалиды → `prefs_disabled`; ст. 14, иностранные товары → `national_regime`; прочее → `other` |
| law | по адаптеру; в универсальном — `615` по имени корня, 19 цифр → `44`, 11 цифр → `223`, иначе `other` |

Не извещения (корень содержит `protocol`, `contract`, `plan`, `cancel`, `clarification`,
`explanation`, `complaint`) → `NOT_A_NOTICE`. Не найдено ни одного обязательного поля →
`NOT_A_NOTICE`, часть → `MISSING_REQUIRED_FIELD`. НМЦК 0 в документе — значение, а не
пропуск. Если адаптер не нашёл обязательные поля, документ пробует универсальный адаптер.

## 44-ФЗ: `epNotification*2020` и `fcsNotification*`

Адаптер `adapters/eis44.py`, `parsed_by = adapter:eis44`. В формате 2020 почти всё лежит в
`notificationInfo/customerRequirementsInfo/customerRequirementInfo` (ниже — `CRI`); в
прежнем — в `lot/customerRequirements/customerRequirement`.

| Поле `Procurement` | Путь в XML | Примечание |
| --- | --- | --- |
| reg_number | `commonInfo/purchaseNumber`; прежний — `purchaseNumber` | |
| subject | `commonInfo/purchaseObjectInfo`; электронный магазин — `//purchaseObjectsInfo//purchaseObject/name` первой позиции | в `epNotificationEZT2020` нет `purchaseObjectInfo`, на сайте ЕИС предмет пустой |
| nmck | `notificationInfo/contractConditionsInfo/maxPriceInfo/maxPrice`; прежний — `lot/maxPrice` | в совместной закупке у каждого `CRI` своя доля — не используется |
| currency | `//maxPriceInfo/currency/code` | |
| method / method_raw | `commonInfo/placingWay/name` | |
| customer_inn | 1) `CRI/customer/INN`, если есть; 2) ИКЗ: `CRI//IKZInfo/customerCode`, цифры 2–11; 3) `purchaseResponsibleInfo/responsibleOrgInfo/INN` при `responsibleRole = CU` | `customerCode` = уровень бюджета (1) + ИНН (10) + КПП (9). Если размещает уполномоченный орган (`RA`, `AI`, `OAI`), у заказчика тега ИНН нет, а ИНН организатора брать нельзя |
| customer_name | `CRI/customer/fullName` | в совместной закупке — первый заказчик |
| delivery_place | `CRI//deliveryPlacesInfo/byGARInfo/GARInfo/GARAddress`, `…/byGARInfo/deliveryPlace`; прежний — `kladrPlaces/kladrPlace/deliveryPlace` | ГАР пишет регион наоборот: «край Приморский» |
| region | по `delivery_place`, затем по `responsibleOrgInfo/factAddress` | |
| published_at | `commonInfo/publishDTInEIS`; прежний — `docPublishDate` | |
| application_deadline | `notificationInfo/procedureInfo/collectingInfo/endDT`; прежний — `procedureInfo/collecting/endDate` | у электронного магазина в извещении нет |
| delivery_term_text | прежний — `customerRequirement/deliveryTerm`; 2020 — текста нет, собирается из `CRI//contractExecutionTermsInfo/notRelativeTermsInfo/startDate`, `endDate`: «с 01.01.2027 по 31.12.2027» | это срок исполнения контракта; дата берётся из текста без перевода в UTC |
| okpd2_codes | из позиций | |
| items | `//purchaseObject` (`name`, `OKPD2/OKPDCode` или `KTRU/code`, `quantity/value`, `OKEI/name`, `price`); лекарства — `//drugPurchaseObjectInfo` (`name`, `.//OKPD2/OKPDCode`, `.//drugQuantity`) | |
| bid_security | `CRI/applicationGuarantee/part` (%), `amount` | в совместной закупке без `part` — сумма по всем `CRI` |
| contract_security | `CRI/contractGuarantee/part` (%), `amount` | так же |
| restrictions | `notificationInfo/preferensesInfo/preferenseInfo/preferenseRequirementInfo/name`, `//restrictionInfo//name` | `requirementsInfo` (единые требования ст. 31) — не ограничения, не берутся |
| source_url | `commonInfo/href`; прежний — `href` | |
| лоты | `//lots/lot`, номер `lotNumber` | в образцах лот всегда один |

Совместные закупки (несколько `CRI`, организатор — уполномоченный орган): `…4584` (14
заказчиков), `…5020` (19), `…5437` (27).

## 223-ФЗ: `purchaseNotice*`

Адаптер `adapters/eis223.py`, `parsed_by = adapter:eis223`. Общие сведения — в
`body/item/purchaseNotice*Data` (`purchaseNoticeData`, `purchaseNoticeAESMBOData`, …), НМЦК и
позиции — в `lots/lot/lotData`.

| Поле `Procurement` | Путь (от `*Data` / от `lot`) | Примечание |
| --- | --- | --- |
| reg_number | `registrationNumber` | 11 цифр |
| subject | лот: `lotData/subject`; извещение: `name` | |
| nmck | лот: `lotData/initialSum` или `lotData/maxContractPrice` больше 0; иначе сумма `jointLotData/lotCustomers/lotCustomer/lotCustomerData/initialSum`; иначе 0 | `maxContractPrice` — в новых схемах (TFF-16), напр. `32616481510`. Централизованная закупка (`lotData/centralized = true`): у лота 0, цены — у заказчиков, напр. `32616514797`. Запрос цен для формирования НМЦК: 0 и на сайте ЕИС, напр. `32616510892` |
| currency | лот: `lotData/currency/code` | |
| method / method_raw | `purchaseCodeName` | |
| customer_inn / customer_name | `customer/mainInfo/inn`, `customer/mainInfo/fullName` | |
| region | лот: `lotData/deliveryPlace/region`; затем по адресу поставки; затем `customer/mainInfo/legalAddress` | |
| delivery_place | лот: `lotData/deliveryPlace/address` | заказчики пишут сюда что угодно: «В соответствии с документацией» или название работ |
| published_at | `publicationDateTime` | без смещения, местное время заказчика |
| application_deadline | `submissionCloseDateTime` | без смещения, местное время заказчика: на сайте «10:00 (МСК+4)» |
| часовой пояс (`tz_offset`) | `customer/mainInfo/timeZone/offset` | сдвиг от МСК в часах: `4` → UTC+7. Проверено по всем образцам: `header/createDateTime` (МСК) + сдвиг = `publicationDateTime` |
| delivery_term_text | — | в извещении 223-ФЗ нет |
| okpd2_codes | `lotItem/okpd2/code` | |
| items | `//lotItem`: `okpd2/name` или `additionalInfo`, `qty`, `okei/name` | |
| bid_security | лот: `lotData/applicationSupplyInfo/sum` | в образцах нет; путь по аналогии |
| contract_security | лот: `lotData/completingSupplyInfo/sum` | текст: «5% от начальной (максимальной) цены Договора» |
| restrictions | `lotData/forSmallOrMiddle = true` → `smp_only` | |
| source_url | `urlEIS` | |
| лоты | `lots/lot`, номер `ordinalNumber` | больше одного → запись на лот `<номер>-<лот>`, напр. `32211747866-1…4` |

## ПП 615 (`pprf615Notification*`), 94-ФЗ и неизвестные схемы — универсальный адаптер

`universal.py`, `parsed_by = universal`; документ — один лот. Обёртки `export`, `body`, `item`
с единственным потомком снимаются.

ПП 615 по образцам: способ — `placingWayInfo/name`, НМЦК — `notificationInfo/contractCondition/maxPriceInfo/maxPrice`,
срок подачи — `notificationInfo/procedureInfo/collectingEndDate`, обеспечения —
`maxPriceInfo/applicationGuarantee/amount`, `contractGuarantee/amount`. ОКПД2 и позиций нет:
предмет — виды работ по капремонту (`servicesWorksKind…`).

## Словарь синонимов для универсального адаптера

Полный список — `backend/app/parsers/synonyms.py`; поиск на любой глубине.

| Поле | Синонимы тегов |
| --- | --- |
| reg_number | `purchaseNumber`, `registrationNumber`, `notificationNumber`, `purchaseNoticeNumber`, `noticeNumber`, `purchaseRegNumber` |
| nmck | `maxPriceInfo/maxPrice`, `maxPrice`, `initialSum`, `contractMaxPrice`, `maxContractPrice`, `startPrice`, `initialPrice`, `nmck` |
| subject | `purchaseObjectInfo`, `lotData/subject`, `lot/subject`, `purchaseName`, `lotName`, `objectName`, `subject`, `name` (только верхний уровень) |
| customer_inn | `INN` внутри `customer`, `customerInfo`, `responsibleOrgInfo`, `responsibleOrg`, `organizer`, `placer`; затем любой `INN` |
| method_raw | `placingWay/name`, `placingWayInfo/name`, `purchaseCodeName`, `purchaseMethodName`, `methodName` |
| application_deadline | `collectingInfo/endDT`, `collecting/endDate`, `submissionCloseDateTime`, `collectingEndDate`, `applicationEndDate`, `endDT`, `endDate` |
| published_at | `publishDTInEIS`, `publicationDateTime`, `docPublishDate`, `publishDate`, `createDateTime` |
| region / delivery_place | `deliveryPlace/region`; `GARAddress`, `deliveryPlace/address`, `deliveryPlace`, `deliveryAddress` |
| items | `purchaseObject`, `drugPurchaseObjectInfo`, `lotItem` |
