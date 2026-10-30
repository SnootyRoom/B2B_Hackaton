// Низкоуровневый запрос к бэкенду.
// Вход — через httpOnly-cookie (её ставит сервер), поэтому токен во фронтенде не хранится:
// достаточно credentials: 'include'.

import type { ApiErrorBody } from './types';
import { errorText } from '../lib/catalog';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody) {
    super(errorText(body.code, body.message));
    this.status = status;
    this.code = body.code;
    this.details = body.details;
  }
}

const BASE = '/api';

/** Вызывается при 401 — App сбрасывает данные пользователя и показывает вход */
let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

function readErrorBody(status: number, text: string): ApiErrorBody {
  try {
    const data: unknown = JSON.parse(text);
    if (data && typeof data === 'object' && 'error' in data) {
      const e = (data as { error: ApiErrorBody }).error;
      if (e && typeof e.code === 'string') return e;
    }
    // На всякий случай — стандартный формат FastAPI {"detail": "..."}
    if (data && typeof data === 'object' && 'detail' in data) {
      const d = (data as { detail: unknown }).detail;
      if (typeof d === 'string') return { code: 'HTTP_' + status, message: d };
    }
  } catch {
    /* не JSON */
  }
  if (status === 404) return { code: 'NOT_FOUND', message: 'Не найдено' };
  if (status === 401) return { code: 'UNAUTHORIZED', message: 'Войдите, чтобы продолжить' };
  if (status === 413) return { code: 'FILE_TOO_LARGE', message: 'Файлы слишком большие для загрузки' };
  if (status >= 500) return { code: 'SERVER_ERROR', message: 'Сервер временно не отвечает. Попробуйте через минуту.' };
  return { code: 'HTTP_' + status, message: '' };
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  json?: unknown;
  form?: FormData;
  query?: Record<string, string | number | boolean | undefined>;
}

export function buildUrl(path: string, query?: RequestOptions['query']): string {
  const params = new URLSearchParams();
  Object.entries(query ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== '' && v !== false) params.set(k, String(v));
  });
  const qs = params.toString();
  return BASE + path + (qs ? '?' + qs : '');
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;
  if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.json);
  } else if (opts.form) {
    body = opts.form;
  }

  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), {
      method: opts.method ?? 'GET',
      headers,
      body,
      credentials: 'include',
    });
  } catch {
    throw new ApiError(0, { code: 'NETWORK', message: 'Нет связи с сервером. Проверьте интернет и попробуйте ещё раз.' });
  }

  const text = await res.text();
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith('/auth/login')) onUnauthorized();
    throw new ApiError(res.status, readErrorBody(res.status, text));
  }
  return (text ? JSON.parse(text) : null) as T;
}
