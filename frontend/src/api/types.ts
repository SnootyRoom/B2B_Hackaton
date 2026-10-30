// Типы данных API. Источник правды — схемы бэкенда (backend/app/schemas, docs/openapi.json).

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

/** Деньги в JSON — число (внутри бэкенда Decimal). */
export type Money = number;

// ---------- Пользователь ----------
export interface User {
  id: string;
  email: string;
  created_at: string;
}

// ---------- Закупка ----------
export interface ProcurementItem {
  name: string;
  quantity: Money | null;
  unit: string | null;
  price: Money | null;
  okpd2?: string | null;
}

export interface Procurement {
  reg_number: string;
  lot_number?: number | null;
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
  bid_security_pct?: number | null;
  contract_security: Money | null;
  contract_security_pct?: number | null;
  restrictions: Restriction[];
  source_url: string | null;
  parsed_by: string;
}

// ---------- Заказчик (ЕГРЮЛ) ----------
export interface CustomerProfile {
  inn: string;
  ogrn: string | null;
  name: string;
  org_type: 'legal' | 'individual' | null;
  status: CustomerStatus;
  registration_date: string | null;
  liquidation_date: string | null;
  okved_main: string | null;
  okved_main_name?: string | null;
  address: string | null;
  region: string | null;
  unreliable_flags: string[];
  fetched_at: string;
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
  id: string;
  is_active: boolean;
  updated_at: string;
  name: string;
  company_description: string;
  source_text: string;
  group_weights: GroupWeights;
  thresholds: Thresholds;
  rules: ScoringRule[];
}

export type ScoringProfileInput = Omit<ScoringProfile, 'id' | 'is_active' | 'updated_at'>;

export interface SaveProfileResponse {
  profile: ScoringProfile;
  /** Задача пересчёта, если сохраняли с rescore */
  task_id: string | null;
}

/** GET /scoring-profiles/catalog; фронту нужен признак LLM */
export interface FieldCatalog {
  regions: string[];
  llm_enabled: boolean;
}

export interface ParseResult {
  rules: ScoringRule[];
  company_description: string;
  unparsed: string[];
}

// ---------- Оценка ----------
export type RuleStatus = 'applied' | 'no_data' | 'disabled';

export interface RuleResult {
  rule_id: string;
  label: string;
  group: Group;
  kind: RuleKind;
  field: string;
  operator: Operator;
  /** Значение поля как есть; для показа — готовая фраза `text` */
  field_value: unknown;
  status: RuleStatus;
  /** Для стоп-факторов: сработал ли */
  triggered: boolean;
  /** Частичный балл 0–1 */
  partial_score: number | null;
  /** Вклад в итог в баллах */
  contribution: number | null;
  /** Сколько баллов недобрано относительно максимума */
  lost: number | null;
  /** Фраза обоснования по правилу */
  text: string;
}

export interface GroupResult {
  group: Group;
  /** 0–100; null — группа исключена (нет применимых правил) */
  score: number | null;
  /** Вес из профиля */
  weight: number;
  /** Вес после перераспределения, сумма по группам = 1 */
  effective_weight: number;
  low_data: boolean;
}

export interface ScoreResult {
  id: string;
  procurement_id: string;
  profile_id: string;
  total: number;
  recommendation: Recommendation;
  incomplete: boolean;
  groups: GroupResult[];
  /** rule_id сработавших стоп-факторов */
  stop_factors: string[];
  rules: RuleResult[];
  justification: string;
  justification_source: 'template' | 'llm';
  computed_at: string;
}

/** Строка таблицы результатов (GET /results). Закупки без оценки слой API отбрасывает. */
export interface ResultRow {
  procurement_id: string;
  reg_number: string;
  subject: string;
  customer_name: string | null;
  nmck: Money;
  currency: string;
  region: string | null;
  law: Law | null;
  application_deadline: string | null;
  total: number;
  recommendation: Recommendation;
  incomplete: boolean;
  has_stop_factor: boolean;
}

/** Карточка закупки (GET /procurements/{id}) */
export interface ProcurementDetail {
  id: string;
  data: Procurement;
  customer: CustomerProfile | null;
  /** Почему нет данных о заказчике: CUSTOMER_NOT_FOUND / EGRUL_UNAVAILABLE */
  customer_error: ErrorCode | null;
  score: ScoreResult | null;
  created_at: string;
  updated_at: string;
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
  id: string;
  filename: string;
  status: 'pending' | 'ok' | 'error';
  error: ApiErrorBody | null;
  /** Предупреждения при статусе ok: CUSTOMER_NOT_FOUND, EGRUL_UNAVAILABLE */
  warnings: ApiErrorBody[];
  /** Закупки (лоты), созданные из файла */
  procurement_ids: string[];
}

export interface Task {
  id: string;
  kind: 'upload' | 'rescore' | 'parse_profile' | 'egrul_lookup';
  status: TaskStatus;
  total: number;
  processed: number;
  files: TaskFile[];
  /** parse_profile → ParseResult */
  result: unknown;
  error: ApiErrorBody | null;
  created_at: string;
  finished_at: string | null;
}

export interface TaskCreated {
  task_id: string;
}

/** Фильтры таблицы результатов; применяются в браузере */
export interface ResultsFilters {
  region?: string;
  nmck_min?: number;
  nmck_max?: number;
  law?: Law;
  hide_expired?: boolean;
}
