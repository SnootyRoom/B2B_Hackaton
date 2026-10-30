// Справочники интерфейса: каталог полей для правил, подписи значений, тексты ошибок.
// Источник — docs/analytics.md (разделы «Профиль скоринга», «ЕГРЮЛ», «Загрузка»).
// Новое поле в каталоге роли 3 = одна запись в FIELDS, больше ничего менять не нужно.

import type {
  CustomerSource,
  CustomerStatus,
  ErrorCode,
  Group,
  Law,
  Method,
  Operator,
  Recommendation,
  Restriction,
} from '../api/types';

export const GROUPS: { key: Group; label: string; hint: string }[] = [
  { key: 'procurement', label: 'Закупка', hint: 'Цена, способ, регион, сроки, обеспечение' },
  { key: 'fit', label: 'Соответствие', hint: 'Насколько предмет закупки подходит вашей компании' },
  { key: 'customer', label: 'Заказчик', hint: 'Надёжность заказчика по данным ЕГРЮЛ' },
];

export const GROUP_LABEL: Record<Group, string> = {
  procurement: 'Закупка',
  fit: 'Соответствие',
  customer: 'Заказчик',
};

export const RECOMMENDATION: Record<Recommendation, { label: string; tone: 'good' | 'mid' | 'bad' }> = {
  participate: { label: 'Участвовать', tone: 'good' },
  consider: { label: 'Рассмотреть', tone: 'mid' },
  skip: { label: 'Пропустить', tone: 'bad' },
};

export const METHOD_LABEL: Record<Method, string> = {
  auction: 'Электронный аукцион',
  contest: 'Конкурс',
  quotation: 'Запрос котировок',
  proposals: 'Запрос предложений',
  single: 'Единственный поставщик',
  other: 'Другой способ',
};

export const LAW_LABEL: Record<Law, string> = {
  '44': '44-ФЗ',
  '223': '223-ФЗ',
  '615': 'ПП РФ № 615',
  '94': '94-ФЗ (архив)',
  other: 'Другое',
};

export const RESTRICTION_LABEL: Record<Restriction, string> = {
  smp_only: 'Только для малого бизнеса (СМП)',
  national_regime: 'Национальный режим',
  prefs_uis: 'Преимущества УИС',
  prefs_disabled: 'Преимущества организациям инвалидов',
  other: 'Другие ограничения',
};

export const CUSTOMER_STATUS_LABEL: Record<CustomerStatus, string> = {
  active: 'Действующая',
  reorganizing: 'В процессе реорганизации',
  liquidating: 'Ликвидируется',
  liquidated: 'Ликвидирована',
  bankrupt: 'Банкротство',
  unknown: 'Статус не определён',
};

export const CUSTOMER_SOURCE_LABEL: Record<CustomerSource, string> = {
  dadata: 'ЕГРЮЛ, получено сейчас',
  cache: 'ЕГРЮЛ, из сохранённых данных',
  stale_cache: 'ЕГРЮЛ, сохранённые данные могли устареть',
  offline: 'ЕГРЮЛ, заранее сохранённая выписка',
};

export const OPERATOR_LABEL: Record<Operator, string> = {
  between: 'от … до',
  gte: 'не меньше',
  lte: 'не больше',
  in: 'один из',
  not_in: 'любой, кроме',
  any_in: 'есть хотя бы одно из',
  none_in: 'нет ни одного из',
  prefix_in: 'коды начинаются с',
  is_false: 'нет',
  semantic_match: 'по смыслу похоже на',
  contains_any: 'содержит любое из слов',
};

/** Как редактировать значение правила */
export type ValueType =
  | 'money' // число, ₽
  | 'number' // число с единицей
  | 'enum' // мультивыбор из списка
  | 'codes' // список кодов ОКПД2 через запятую
  | 'words' // список слов через запятую
  | 'text' // свободный текст (описание для смыслового сравнения)
  | 'none'; // значение не нужно (is_false)

export interface FieldDef {
  key: string;
  label: string;
  group: Group;
  operators: Operator[];
  valueType: ValueType;
  unit?: string;
  /** Единица после числа в родительном падеже: «не меньше 1 дня / 5 дней» */
  unitForms?: [string, string, string];
  options?: { value: string; label: string }[];
  /** Как звучит правило «нет …» (оператор is_false) */
  falseLabel?: string;
  /** Названия вариантов — имена собственные, их не пишем со строчной буквы */
  properNames?: boolean;
}

const toOptions = (rec: Record<string, string>) =>
  Object.entries(rec).map(([value, label]) => ({ value, label }));

// Субъекты РФ — названия как в справочнике роли 2 (уточнить, если у неё другие)
export const REGIONS = [
  'Республика Адыгея', 'Республика Алтай', 'Республика Башкортостан', 'Республика Бурятия',
  'Республика Дагестан', 'Республика Ингушетия', 'Кабардино-Балкарская Республика', 'Республика Калмыкия',
  'Карачаево-Черкесская Республика', 'Республика Карелия', 'Республика Коми', 'Республика Крым',
  'Республика Марий Эл', 'Республика Мордовия', 'Республика Саха (Якутия)',
  'Республика Северная Осетия — Алания', 'Республика Татарстан', 'Республика Тыва',
  'Удмуртская Республика', 'Республика Хакасия', 'Чеченская Республика', 'Чувашская Республика',
  'Донецкая Народная Республика', 'Луганская Народная Республика',
  'Алтайский край', 'Забайкальский край', 'Камчатский край', 'Краснодарский край', 'Красноярский край',
  'Пермский край', 'Приморский край', 'Ставропольский край', 'Хабаровский край',
  'Амурская область', 'Архангельская область', 'Астраханская область', 'Белгородская область',
  'Брянская область', 'Владимирская область', 'Волгоградская область', 'Вологодская область',
  'Воронежская область', 'Запорожская область', 'Ивановская область', 'Иркутская область',
  'Калининградская область', 'Калужская область', 'Кемеровская область', 'Кировская область',
  'Костромская область', 'Курганская область', 'Курская область', 'Ленинградская область',
  'Липецкая область', 'Магаданская область', 'Московская область', 'Мурманская область',
  'Нижегородская область', 'Новгородская область', 'Новосибирская область', 'Омская область',
  'Оренбургская область', 'Орловская область', 'Пензенская область', 'Псковская область',
  'Ростовская область', 'Рязанская область', 'Самарская область', 'Саратовская область',
  'Сахалинская область', 'Свердловская область', 'Смоленская область', 'Тамбовская область',
  'Тверская область', 'Томская область', 'Тульская область', 'Тюменская область',
  'Ульяновская область', 'Херсонская область', 'Челябинская область', 'Ярославская область',
  'Москва', 'Санкт-Петербург', 'Севастополь', 'Еврейская автономная область', 'Ненецкий автономный округ',
  'Ханты-Мансийский автономный округ — Югра', 'Чукотский автономный округ', 'Ямало-Ненецкий автономный округ',
];

const REGION_OPTIONS = REGIONS.map((r) => ({ value: r, label: r }));

export const FIELDS: FieldDef[] = [
  { key: 'nmck', label: 'Начальная цена (НМЦК)', group: 'procurement', operators: ['between', 'gte', 'lte'], valueType: 'money', unit: '₽' },
  { key: 'method', label: 'Способ закупки', group: 'procurement', operators: ['in', 'not_in'], valueType: 'enum', options: toOptions(METHOD_LABEL) },
  { key: 'law', label: 'Закон', group: 'procurement', operators: ['in'], valueType: 'enum', options: toOptions(LAW_LABEL) },
  { key: 'region', label: 'Регион поставки', group: 'procurement', operators: ['in', 'not_in'], valueType: 'enum', options: REGION_OPTIONS, properNames: true },
  { key: 'days_to_deadline', label: 'Срок на подачу заявки', group: 'procurement', operators: ['gte', 'lte', 'between'], valueType: 'number', unit: 'дн.', unitForms: ['дня', 'дней', 'дней'] },
  { key: 'delivery_days', label: 'Срок поставки', group: 'procurement', operators: ['gte', 'lte', 'between'], valueType: 'number', unit: 'дн.', unitForms: ['дня', 'дней', 'дней'] },
  { key: 'bid_security_pct', label: 'Обеспечение заявки', group: 'procurement', operators: ['lte'], valueType: 'number', unit: '% от НМЦК' },
  { key: 'contract_security_pct', label: 'Обеспечение контракта', group: 'procurement', operators: ['lte'], valueType: 'number', unit: '% от НМЦК' },
  { key: 'restrictions', label: 'Ограничения и преимущества', group: 'procurement', operators: ['any_in', 'none_in'], valueType: 'enum', options: toOptions(RESTRICTION_LABEL) },
  { key: 'subject', label: 'Предмет закупки', group: 'fit', operators: ['semantic_match', 'contains_any'], valueType: 'text' },
  { key: 'okpd2_codes', label: 'Коды ОКПД2', group: 'fit', operators: ['prefix_in'], valueType: 'codes' },
  { key: 'customer.status', label: 'Статус заказчика', group: 'customer', operators: ['in', 'not_in'], valueType: 'enum', options: toOptions(CUSTOMER_STATUS_LABEL) },
  { key: 'customer.age_years', label: 'Возраст заказчика', group: 'customer', operators: ['gte', 'between'], valueType: 'number', unit: 'лет', unitForms: ['года', 'лет', 'лет'] },
  { key: 'customer.has_unreliable_flags', label: 'Отметки о недостоверности сведений о заказчике', group: 'customer', operators: ['is_false'], valueType: 'none', falseLabel: 'Нет отметок о недостоверности сведений о заказчике' },
  { key: 'customer.region', label: 'Регион заказчика', group: 'customer', operators: ['in'], valueType: 'enum', options: REGION_OPTIONS, properNames: true },
];

export const FIELD_BY_KEY: Record<string, FieldDef> = Object.fromEntries(FIELDS.map((f) => [f.key, f]));

/** Тексты ошибок из таблицы «Коды ошибок» аналитики. message от сервера главнее. */
export const ERROR_TEXT: Record<string, string> = {
  UNSUPPORTED_FORMAT: 'Файл не похож на выгрузку из ЕИС',
  NOT_A_NOTICE: 'Это не извещение о закупке',
  MISSING_REQUIRED_FIELD: 'В файле не найдены обязательные данные',
  CUSTOMER_NOT_FOUND: 'Заказчик не найден в ЕГРЮЛ',
  EGRUL_UNAVAILABLE: 'Данные о заказчике временно недоступны',
  FILE_TOO_LARGE: 'Файл слишком большой',
  TOO_MANY_FILES: 'Слишком много файлов за раз',
  NOT_FOUND: 'Не найдено',
  UNAUTHORIZED: 'Войдите, чтобы продолжить',
};

export function errorText(code: ErrorCode, message?: string | null): string {
  return message || ERROR_TEXT[code] || 'Что-то пошло не так. Попробуйте ещё раз.';
}

/** Лимиты загрузки (NFR-4, .env.example) */
export const UPLOAD_LIMITS = { fileMb: 20, archiveMb: 100, maxFiles: 500 };
export const ACCEPTED_EXT = ['.xml', '.json', '.zip'];
