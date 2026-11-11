// Все обращения к API — только через этот объект.
// Адреса и ответы — по контракту бэкенда (docs/openapi.json).
// VITE_USE_MOCK=true — работаем на демо-данных без бэкенда (по умолчанию в `npm run dev`).
// В Docker собирается с VITE_USE_MOCK=false.

import { ApiError, request } from './client';
import { mockApi } from './mock';
import type {
  CompareOut,
  CreateProfileInput,
  FieldCatalog,
  ParseResult,
  ProcurementDetail,
  ProfileSummary,
  ProfileTaskResponse,
  ResultRow,
  SaveProfileResponse,
  ScoringProfile,
  ScoringProfileInput,
  Task,
  TaskCreated,
  User,
} from './types';

export const USE_MOCK = (import.meta.env.VITE_USE_MOCK ?? 'true') !== 'false';

export interface Api {
  me(): Promise<User>;
  login(email: string, password: string): Promise<User>;
  register(email: string, password: string): Promise<User>;
  logout(): Promise<void>;

  /** 404 → профиля ещё нет (первый вход) */
  getActiveProfile(): Promise<ScoringProfile>;
  /** rescore=true — сразу пересчитать все закупки, в ответе task_id */
  saveActiveProfile(p: ScoringProfileInput, rescore: boolean): Promise<SaveProfileResponse>;
  /** Краткий список, активный первым */
  listProfiles(): Promise<ProfileSummary[]>;
  /** Профиль целиком (для редактора) */
  getProfile(id: string): Promise<ScoringProfile>;
  /** Пустой (правила по умолчанию), из шаблона или с готовыми правилами. Новый — не активный */
  createProfile(input: CreateProfileInput): Promise<ScoringProfile>;
  /** Копия «<имя> (копия)», не активная, оценки не копируются */
  duplicateProfile(id: string): Promise<ScoringProfile>;
  /** Только имя, без пересчёта */
  renameProfile(id: string, name: string): Promise<ProfileSummary>;
  /** rescore имеет смысл только у активного; у неактивного оценки становятся устаревшими */
  saveProfile(id: string, p: ScoringProfileInput, rescore: boolean): Promise<SaveProfileResponse>;
  /** Последний — 400 LAST_PROFILE. Удалили активный → task_id пересчёта нового активного */
  deleteProfile(id: string): Promise<ProfileTaskResponse>;
  /** Сделать активным; task_id = null — все оценки уже актуальны */
  activateProfile(id: string): Promise<ProfileTaskResponse>;
  /** Досчитать недостающие и устаревшие оценки по профилю (POST /score {profile_id, only_stale}) */
  scoreStale(profileId: string): Promise<TaskCreated>;
  /** Сравнение двух профилей; только чтение. missing > 0 — сначала scoreStale для обоих */
  compareProfiles(a: string, b: string): Promise<CompareOut>;
  getCatalog(): Promise<FieldCatalog>;
  parseProfileText(text: string): Promise<ParseResult>;

  upload(files: File[]): Promise<TaskCreated>;
  /** Загрузка по реестровым номерам → задача kind=fetch, одна строка files на номер */
  fetchByNumbers(numbers: string[]): Promise<TaskCreated>;
  /** P1, на бэкенде пока нет: только в демо-режиме */
  uploadDemo(): Promise<TaskCreated>;
  /** P1, на бэкенде пока нет: только в демо-режиме */
  setCustomerInn(procurementId: string, inn: string): Promise<TaskCreated>;
  getTask(id: string): Promise<Task>;
  /** История загрузок (файлами и по номерам), новые сверху */
  listUploads(): Promise<Task[]>;

  /** Без profileId — по активному профилю */
  getResults(profileId?: string): Promise<ResultRow[]>;
  getProcurement(id: string): Promise<ProcurementDetail>;
}

const PARSE_POLL_MS = 1000;
const PARSE_TIMEOUT_MS = 60_000;

/** Разбор текста идёт в очереди: ставим задачу и ждём результат в Task.result */
async function parseViaTask(text: string): Promise<ParseResult> {
  const { task_id } = await request<TaskCreated>('/scoring-profiles/parse', {
    method: 'POST',
    json: { text },
  });
  const deadline = Date.now() + PARSE_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const t = await realApi.getTask(task_id);
    if (t.status === 'done') return t.result as ParseResult;
    if (t.status === 'failed' || t.status === 'partial') {
      throw new ApiError(200, t.error ?? { code: 'LLM_PARSE_FAILED', message: '' });
    }
    await new Promise((r) => setTimeout(r, PARSE_POLL_MS));
  }
  throw new ApiError(200, { code: 'LLM_PARSE_FAILED', message: '' });
}

const realApi: Api = {
  me: () => request<User>('/auth/me'),
  login: (email, password) => request<User>('/auth/login', { method: 'POST', json: { email, password } }),
  register: (email, password) =>
    request<User>('/auth/register', { method: 'POST', json: { email, password } }),
  logout: () => request<void>('/auth/logout', { method: 'POST' }),

  getActiveProfile: () => request<ScoringProfile>('/scoring-profiles/active'),
  saveActiveProfile: (p, rescore) =>
    request<SaveProfileResponse>('/scoring-profiles/active', { method: 'PUT', json: { ...p, rescore } }),
  getCatalog: () => request<FieldCatalog>('/scoring-profiles/catalog'),

  listProfiles: () => request<ProfileSummary[]>('/scoring-profiles'),
  getProfile: (id) => request<ScoringProfile>(`/scoring-profiles/${id}`),
  createProfile: (input) => request<ScoringProfile>('/scoring-profiles', { method: 'POST', json: input }),
  duplicateProfile: (id) => request<ScoringProfile>(`/scoring-profiles/${id}/duplicate`, { method: 'POST' }),
  renameProfile: (id, name) =>
    request<ProfileSummary>(`/scoring-profiles/${id}`, { method: 'PATCH', json: { name } }),
  saveProfile: (id, p, rescore) =>
    request<SaveProfileResponse>(`/scoring-profiles/${id}`, { method: 'PUT', json: { ...p, rescore } }),
  deleteProfile: (id) => request<ProfileTaskResponse>(`/scoring-profiles/${id}`, { method: 'DELETE' }),
  activateProfile: (id) =>
    request<ProfileTaskResponse>(`/scoring-profiles/${id}/activate`, { method: 'POST' }),
  scoreStale: (id) =>
    request<TaskCreated>('/score', { method: 'POST', json: { profile_id: id, only_stale: true } }),
  compareProfiles: (a, b) => request<CompareOut>('/results/compare', { query: { a, b } }),
  parseProfileText: parseViaTask,

  upload: (files) => {
    const form = new FormData();
    files.forEach((f) => form.append('files', f));
    return request<TaskCreated>('/procurements/upload', { method: 'POST', form });
  },
  fetchByNumbers: (numbers) =>
    request<TaskCreated>('/procurements/fetch', { method: 'POST', json: { numbers } }),
  uploadDemo: () => request<TaskCreated>('/procurements/upload-demo', { method: 'POST' }),
  setCustomerInn: (id, inn) =>
    request<TaskCreated>(`/procurements/${id}/customer-inn`, { method: 'PUT', json: { inn } }),
  getTask: (id) => request<Task>(`/tasks/${id}`),
  listUploads: async () => {
    const [files, numbers] = await Promise.all([
      request<Task[]>('/tasks', { query: { kind: 'upload' } }),
      request<Task[]>('/tasks', { query: { kind: 'fetch' } }),
    ]);
    return [...files, ...numbers].sort((x, y) => y.created_at.localeCompare(x.created_at));
  },

  getResults: async (profileId) => {
    const rows = await request<ResultRow[]>('/results', { query: { profile_id: profileId } });
    // Строки без оценки приходят с total = null — показываем их как «пересчитывается»
    return rows.map((r) => ({ ...r, stale: r.stale || r.total === null }));
  },
  getProcurement: (id) => request<ProcurementDetail>(`/procurements/${id}`),
};

export const api: Api = USE_MOCK ? mockApi : realApi;
