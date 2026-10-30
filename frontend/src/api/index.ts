// Все обращения к API — только через этот объект.
// Адреса и ответы — по контракту бэкенда (docs/openapi.json).
//
// VITE_USE_MOCK=true — работаем на демо-данных без бэкенда (по умолчанию в `npm run dev`).
// В Docker собирается с VITE_USE_MOCK=false.

import { ApiError, request } from './client';
import { mockApi } from './mock';
import type {
  FieldCatalog,
  ParseResult,
  ProcurementDetail,
  Recommendation,
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
  getCatalog(): Promise<FieldCatalog>;
  parseProfileText(text: string): Promise<ParseResult>;

  upload(files: File[]): Promise<TaskCreated>;
  /** P1, на бэкенде пока нет: только в демо-режиме */
  uploadDemo(): Promise<TaskCreated>;
  /** P1, на бэкенде пока нет: только в демо-режиме */
  setCustomerInn(procurementId: string, inn: string): Promise<TaskCreated>;
  getTask(id: string): Promise<Task>;
  /** История загрузок, новые сверху */
  listUploads(): Promise<Task[]>;

  getResults(): Promise<ResultRow[]>;
  getProcurement(id: string): Promise<ProcurementDetail>;
}

const PARSE_POLL_MS = 1000;
const PARSE_TIMEOUT_MS = 60_000;

/** Разбор текста идёт в очереди: ставим задачу и ждём результат в Task.result */
async function parseViaTask(text: string): Promise<ParseResult> {
  const { task_id } = await request<TaskCreated>('/scoring-profiles/parse', { method: 'POST', json: { text } });
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

type RawResultRow = Omit<ResultRow, 'total' | 'recommendation'> & {
  total: number | null;
  recommendation: Recommendation | null;
};

const realApi: Api = {
  me: () => request<User>('/auth/me'),
  login: (email, password) => request<User>('/auth/login', { method: 'POST', json: { email, password } }),
  register: (email, password) => request<User>('/auth/register', { method: 'POST', json: { email, password } }),
  logout: () => request<void>('/auth/logout', { method: 'POST' }),

  getActiveProfile: () => request<ScoringProfile>('/scoring-profiles/active'),
  saveActiveProfile: (p, rescore) =>
    request<SaveProfileResponse>('/scoring-profiles/active', { method: 'PUT', json: { ...p, rescore } }),
  getCatalog: () => request<FieldCatalog>('/scoring-profiles/catalog'),
  parseProfileText: parseViaTask,

  upload: (files) => {
    const form = new FormData();
    files.forEach((f) => form.append('files', f));
    return request<TaskCreated>('/procurements/upload', { method: 'POST', form });
  },
  uploadDemo: () => request<TaskCreated>('/procurements/upload-demo', { method: 'POST' }),
  setCustomerInn: (id, inn) =>
    request<TaskCreated>(`/procurements/${id}/customer-inn`, { method: 'PUT', json: { inn } }),
  getTask: (id) => request<Task>(`/tasks/${id}`),
  listUploads: () => request<Task[]>('/tasks', { query: { kind: 'upload' } }),

  getResults: async () => {
    const rows = await request<RawResultRow[]>('/results');
    return rows.filter((r): r is ResultRow => r.total !== null && r.recommendation !== null);
  },
  getProcurement: (id) => request<ProcurementDetail>(`/procurements/${id}`),
};

export const api: Api = USE_MOCK ? mockApi : realApi;
