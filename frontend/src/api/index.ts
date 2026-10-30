// Все обращения к API — только через этот объект.
// Адреса — из CLAUDE.md (раздел «API»). Пометка «согласовать» — адреса, которых пока нет в CLAUDE.md.
//
// VITE_USE_MOCK=true — работаем на демо-данных без бэкенда (по умолчанию в `npm run dev`,
// пока контракты не в main). В Docker собирается с VITE_USE_MOCK=false.

import { buildUrl, request } from './client';
import { mockApi } from './mock';
import type {
  ParseResult,
  ProcurementDetail,
  ResultRow,
  ResultsFilters,
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
  saveActiveProfile(p: ScoringProfileInput): Promise<ScoringProfile>;
  parseProfileText(text: string): Promise<ParseResult>;
  /** Пересчитать все закупки по активному профилю */
  rescore(): Promise<TaskCreated>;

  upload(files: File[]): Promise<TaskCreated>;
  /** P1, согласовать: загрузить демо-набор из data/demo */
  uploadDemo(): Promise<TaskCreated>;
  /** P1, согласовать: ручной ИНН заказчика для закупки → пересчёт */
  setCustomerInn(procurementId: number, inn: string): Promise<TaskCreated>;
  getTask(id: string): Promise<Task>;
  /** Согласовать: история загрузок пользователя, новые сверху (GET /tasks?kind=upload) */
  listUploads(): Promise<Task[]>;

  getResults(filters: ResultsFilters): Promise<ResultRow[]>;
  exportUrl(format: 'csv' | 'json', filters: ResultsFilters): string;
  getProcurement(id: number): Promise<ProcurementDetail>;
}

const filtersQuery = (f: ResultsFilters) => ({
  recommendation: f.recommendation,
  region: f.region,
  nmck_min: f.nmck_min,
  nmck_max: f.nmck_max,
  law: f.law,
  hide_expired: f.hide_expired,
  deadline_from: f.deadline_from,
  deadline_to: f.deadline_to,
  task_id: f.upload_id,
});

const realApi: Api = {
  me: () => request<User>('/auth/me'),
  login: (email, password) => request<User>('/auth/login', { method: 'POST', json: { email, password } }),
  register: (email, password) => request<User>('/auth/register', { method: 'POST', json: { email, password } }),
  logout: () => request<void>('/auth/logout', { method: 'POST' }),

  getActiveProfile: () => request<ScoringProfile>('/scoring-profiles/active'),
  saveActiveProfile: (p) => request<ScoringProfile>('/scoring-profiles/active', { method: 'PUT', json: p }),
  parseProfileText: (text) => request<ParseResult>('/scoring-profiles/parse', { method: 'POST', json: { text } }),
  rescore: () => request<TaskCreated>('/score', { method: 'POST', json: {} }),

  upload: (files) => {
    const form = new FormData();
    files.forEach((f) => form.append('files', f));
    return request<TaskCreated>('/procurements/upload', { method: 'POST', form });
  },
  uploadDemo: () => request<TaskCreated>('/procurements/upload-demo', { method: 'POST' }),
  setCustomerInn: (id, inn) =>
    request<TaskCreated>(`/procurements/${id}/customer-inn`, { method: 'PUT', json: { inn } }),
  getTask: (id) => request<Task>(`/tasks/${id}`),
  listUploads: async () => {
    const r = await request<Task[] | { items: Task[] }>('/tasks', { query: { kind: 'upload' } });
    return Array.isArray(r) ? r : r.items;
  },

  getResults: async (f) => {
    // Принимаем и массив, и {items: [...]} — что решит тимлид
    const r = await request<ResultRow[] | { items: ResultRow[] }>('/results', { query: filtersQuery(f) });
    return Array.isArray(r) ? r : r.items;
  },
  exportUrl: (format, f) => buildUrl('/results/export', { format, ...filtersQuery(f) }),
  getProcurement: (id) => request<ProcurementDetail>(`/procurements/${id}`),
};

export const api: Api = USE_MOCK ? mockApi : realApi;
