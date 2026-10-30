// Типы данных API. Написаны по docs/analytics.md и CLAUDE.md.
// Когда тимлид выложит OpenAPI в main — сверить с ним (или сгенерировать: npx openapi-typescript).

export type Law = '44' | '223' | '615' | '94' | 'other';
export type Method = 'auction' | 'contest' | 'quotation' | 'proposals' | 'single' | 'other';
export type Restriction = 'smp_only' | 'national_regime' | 'prefs_uis' | 'prefs_disabled' | 'other';
export type CustomerStatus = 'active' | 'reorganizing' | 'liquidating' | 'liquidated' | 'bankrupt' | 'unknown';
export type CustomerSource = 'dadata' | 'cache' | 'stale_cache' | 'offline';
export type Recommendation = 'participate' | 'consider' | 'skip';
export type Group = 'procurement' | 'fit' | 'customer';
export type RuleKind = 'stop' | 'weighted';
export type Weight = 1 | 2 | 3;

export type Operator =
  | 'between'
  | 'gte'
  | 'lte'
  | 'in'
  | 'not_in'
  | 'any_in'
  | 'none_in'
  | 'prefix_in'
  | 'is_false'
  | 'semantic_match'
  | 'contains_any';

/** Деньги приходят строкой (Decimal на бэкенде), но принимаем и число. */
export type Money = string | number;

// ---------- Пользователь ----------
export interface User {
  id: number;
  email: string;
  /** Предложение для тимлида: признаки включённых функций. Если поля нет — считаем, что LLM есть. */
  features?: { llm: boolean };
}

// ---------- Закупка ----------
export interface ProcurementItem {
  name: string;
  quantity: Money | null;
  unit: string | null;
  price: Money | null;
}

export interface Procurement {
  id: number;
  reg_number: string;
  law: Law | null;
  subject: string;
  nmck: Money;
  currency: string | null;
  method: Method | null;
  method_raw: string | null;
  customer_inn: string | null;
  customer_name: string | null;
  region: string | null;
  delivery_place: string | null;
  published_at: string | null;
  application_deadline: string | null;
  delivery_term_text: string | null;
  delivery_days: number | null;
  okpd2_codes: string[];
  items: ProcurementItem[];
  bid_security: Money | null;
  contract_security: Money | null;
  restrictions: Restriction[];
  source_url: string | null;
  parsed_by: string;
}

// ---------- Заказчик (ЕГРЮЛ) ----------
export interface CustomerProfile {
  inn: string;
  ogrn: string | null;
  name: string | null;
  org_type: 'legal' | 'individual' | null;
  status: CustomerStatus;
  registration_date: string | null;
  liquidation_date: string | null;
  okved_main: string | null;
  address: string | null;
  region: string | null;
  unreliable_flags: string[];
  fetched_at: string | null;
  source: CustomerSource;
}

// ---------- Профиль скоринга ----------
export type RuleValue = number | string | boolean | string[] | [number, number] | null;

export interface ScoringRule {
  id: string;
  group: Group;
  kind: RuleKind;
  field: string;
  operator: Operator;
  value: RuleValue;
  /** У стоп-факторов не задаётся */
  weight: Weight | null;
  soft_margin: number | null;
  label: string;
  /** Выключенное правило хранится, но не считается */
  enabled: boolean;
}

export interface GroupWeights {
  procurement: number;
  fit: number;
  customer: number;
}

export interface Thresholds {
  participate: number;
  consider: number;
}

export interface ScoringProfile {
  id: number;
  name: string;
  company_description: string;
  source_text: string;
  group_weights: GroupWeights;
  thresholds: Thresholds;
  rules: ScoringRule[];
}

export type ScoringProfileInput = Omit<ScoringProfile, 'id'>;

export interface ParseResult {
  rules: ScoringRule[];
  company_description: string;
  unparsed: string[];
}

// ---------- Оценка ----------
export interface RuleResult {
  rule_id: string;
  group: Group;
  kind: RuleKind;
  label: string;
  /** Значение поля закупки/заказчика, уже готовое для показа («4 200 000 ₽», «Томская область») */
  field_value_text: string | null;
  /** Частичный балл 0–1; null — «нет данных» */
  partial_score: number | null;
  /** Вклад в итог в баллах (может быть отрицательным = потеря относительно максимума); null — нет данных */
  contribution: number | null;
  /** Сколько баллов правило могло дать максимум */
  max_contribution: number | null;
  no_data: boolean;
  /** Для стоп-факторов: сработал ли */
  triggered: boolean;
}

export interface GroupResult {
  group: Group;
  /** 0–100; null — группа исключена (нет применимых правил) */
  score: number | null;
  /** Вес группы после перераспределения, 0–1 */
  weight: number;
  low_data: boolean;
}

export interface StopFactor {
  rule_id: string;
  label: string;
  message: string;
}

export interface ScoreResult {
  total: number;
  recommendation: Recommendation;
  incomplete: boolean;
  groups: GroupResult[];
  stop_factors: StopFactor[];
  rules: RuleResult[];
  justification: { text: string; source: 'template' | 'llm' };
  calculated_at: string;
}

/** Строка таблицы результатов (GET /results) */
export interface ResultRow {
  procurement_id: number;
  reg_number: string;
  subject: string;
  customer_name: string | null;
  nmck: Money;
  region: string | null;
  law: Law | null;
  application_deadline: string | null;
  total: number;
  recommendation: Recommendation;
  incomplete: boolean;
  has_stop_factor: boolean;
  /** Согласовать с ролью 3: главная причина оценки одной фразой («Цена выше лимита 15 млн») для билета */
  reason?: string | null;
}

/** Карточка закупки (GET /procurements/{id}) */
export interface ProcurementDetail {
  procurement: Procurement;
  customer: CustomerProfile | null;
  /** Почему нет данных о заказчике: CUSTOMER_NOT_FOUND / EGRUL_UNAVAILABLE */
  customer_error: ErrorCode | null;
  score: ScoreResult | null;
}

// ---------- Фоновые задачи ----------
export type TaskStatus = 'queued' | 'processing' | 'done' | 'partial' | 'failed';

export type ErrorCode =
  | 'UNSUPPORTED_FORMAT'
  | 'NOT_A_NOTICE'
  | 'MISSING_REQUIRED_FIELD'
  | 'CUSTOMER_NOT_FOUND'
  | 'EGRUL_UNAVAILABLE'
  | 'LLM_UNAVAILABLE'
  | 'FILE_TOO_LARGE'
  | 'TOO_MANY_FILES'
  | 'VALIDATION_ERROR'
  | 'NOT_FOUND'
  | 'UNAUTHORIZED'
  | (string & {});

export interface ApiErrorBody {
  code: ErrorCode;
  message: string;
  details?: Record<string, unknown>;
}

export interface TaskFile {
  name: string;
  status: 'pending' | 'ok' | 'error';
  error: ApiErrorBody | null;
  /** Предупреждения при статусе ok: CUSTOMER_NOT_FOUND, EGRUL_UNAVAILABLE */
  warnings: ApiErrorBody[];
  /** Закупки (лоты), созданные из файла */
  procurement_ids: number[];
}

export interface Task {
  id: string;
  kind: 'upload' | 'score';
  status: TaskStatus;
  total: number;
  processed: number;
  files: TaskFile[];
  /** Когда создана задача (ISO, UTC) — для истории загрузок */
  created_at: string;
  /** Согласовать: сколько закупок из загрузки в каждой рекомендации (для истории) */
  summary?: { participate: number; consider: number; skip: number };
}

export interface TaskCreated {
  task_id: string;
}

export interface ResultsFilters {
  recommendation?: Recommendation;
  region?: string;
  nmck_min?: number;
  nmck_max?: number;
  law?: Law;
  hide_expired?: boolean;
  /** Окончание подачи заявок с/по, ГГГГ-ММ-ДД (на экране фильтруется в браузере, серверу передаётся только для выгрузки) */
  deadline_from?: string;
  deadline_to?: string;
  /** Показать только закупки из одной загрузки (история) */
  upload_id?: string;
}
