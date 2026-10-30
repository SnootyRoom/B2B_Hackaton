// Имитация бэкенда для работы без сервера (VITE_USE_MOCK=true).
// Здесь есть маленький «движок» по формулам аналитики — ТОЛЬКО чтобы демо было живым
// (поменял правила → оценки поменялись). Настоящую оценку считает бэкенд роли 3.

import type { Api } from './index';
import { ApiError } from './client';
import {
  DEFAULT_RULES,
  DEMO_PROFILE,
  MOCK_CUSTOMERS,
  MOCK_PROCUREMENTS,
  MOCK_SIMILARITY,
  PARSED_RULES,
} from './mockData';
import type {
  CustomerProfile,
  Group,
  GroupResult,
  Procurement,
  ProcurementDetail,
  ResultRow,
  RuleResult,
  ScoreResult,
  ScoringProfile,
  ScoringRule,
  Task,
  TaskFile,
} from './types';
import { CUSTOMER_STATUS_LABEL, METHOD_LABEL, RECOMMENDATION, RESTRICTION_LABEL } from '../lib/catalog';
import { formatMoney, formatNumber, isPast, toNumber, yearsSince } from '../lib/format';

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const DEMO_EMAIL = 'demo@example.com';
const EMPTY_EMAIL = 'new@example.com';

// ---------- Состояние «сервера» в памяти ----------
interface State {
  user: { id: number; email: string } | null;
  profile: ScoringProfile | null;
  procurementIds: number[];
  manualInn: Record<number, string>;
  tasks: Record<string, { task: Task; startedAt: number }>;
}

const state: State = { user: null, profile: null, procurementIds: [], manualInn: {}, tasks: {} };

/** Две прошлые загрузки, чтобы в «Истории» было что показать */
function seedHistory() {
  const hoursAgo = (h: number) => new Date(Date.now() - h * 3600 * 1000).toISOString();
  const done = (id: string, created_at: string, ids: number[], extra: TaskFile[] = []): void => {
    const files: TaskFile[] = [
      ...ids.map((pid) => {
        const p = MOCK_PROCUREMENTS.find((x) => x.id === pid)!;
        return { ...fileFor(`${p.reg_number}.xml`, pid), status: 'ok' as const };
      }),
      ...extra,
    ];
    const errors = files.filter((f) => f.status === 'error').length;
    state.tasks[id] = {
      task: { id, kind: 'upload', status: errors ? 'partial' : 'done', total: files.length, processed: files.length, files, created_at },
      startedAt: Date.parse(created_at),
    };
  };
  done('h1', hoursAgo(74), [1, 2, 3, 4, 5, 6, 7], [
    { ...fileFor('protocol_0365100002326000147.xml', null, { code: 'NOT_A_NOTICE', message: 'Это не извещение о закупке' }), status: 'error' },
  ]);
  done('h2', hoursAgo(20), [8, 9, 10, 11]);
}

function readSession(): string | null {
  try {
    return sessionStorage.getItem('mock-user');
  } catch {
    return null;
  }
}
function writeSession(email: string | null) {
  try {
    if (email) sessionStorage.setItem('mock-user', email);
    else sessionStorage.removeItem('mock-user');
  } catch {
    /* хранилище недоступно — живём в памяти */
  }
}

function signIn(email: string) {
  state.user = { id: 1, email };
  writeSession(email);
  // Для наглядности любой вход сразу получает готовый профиль и набор закупок с разными оценками.
  // Чтобы проверить путь «с нуля» (пустой аккаунт), войдите как new@example.com.
  if (email !== EMPTY_EMAIL && !state.profile) {
    state.profile = { id: 1, ...structuredClone(DEMO_PROFILE) };
    state.procurementIds = MOCK_PROCUREMENTS.map((p) => p.id);
    seedHistory();
  }
}

const restored = readSession();
if (restored) signIn(restored);

function requireUser() {
  if (!state.user) throw new ApiError(401, { code: 'UNAUTHORIZED', message: 'Войдите, чтобы продолжить' });
}

// ---------- Мини-движок по формулам аналитики ----------
function customerOf(p: Procurement): CustomerProfile | null {
  const inn = state.manualInn[p.id] ?? p.customer_inn;
  return inn ? (MOCK_CUSTOMERS[inn] ?? null) : null;
}

type FieldValue = number | string | boolean | string[] | null;

function fieldValue(p: Procurement, c: CustomerProfile | null, field: string): FieldValue {
  const nmck = toNumber(p.nmck) ?? 0;
  switch (field) {
    case 'nmck':
      return nmck;
    case 'method':
      return p.method;
    case 'law':
      return p.law;
    case 'region':
      return p.region;
    case 'days_to_deadline':
      return p.application_deadline
        ? Math.floor((new Date(p.application_deadline).getTime() - Date.now()) / 86400000)
        : null;
    case 'delivery_days':
      return p.delivery_days;
    case 'bid_security_pct': {
      const v = toNumber(p.bid_security);
      return v === null ? null : (v / nmck) * 100;
    }
    case 'contract_security_pct': {
      const v = toNumber(p.contract_security);
      return v === null ? null : (v / nmck) * 100;
    }
    case 'restrictions':
      return p.restrictions;
    case 'okpd2_codes':
      return p.okpd2_codes.length ? p.okpd2_codes : null;
    case 'subject':
      return p.subject;
    case 'customer.status':
      return c ? c.status : null;
    case 'customer.age_years':
      return c ? yearsSince(c.registration_date) : null;
    case 'customer.has_unreliable_flags':
      return c ? c.unreliable_flags.length > 0 : null;
    case 'customer.region':
      return c?.region ?? null;
    default:
      return null;
  }
}

function valueText(field: string, v: FieldValue, p: Procurement): string | null {
  if (v === null) return null;
  switch (field) {
    case 'nmck':
      return formatMoney(v as number);
    case 'method':
      return p.method_raw ?? METHOD_LABEL[v as keyof typeof METHOD_LABEL];
    case 'days_to_deadline':
      return (v as number) <= 0 ? 'приём заявок завершён' : `${v} дн.`;
    case 'delivery_days':
      return `${v} дн.`;
    case 'bid_security_pct':
    case 'contract_security_pct':
      return formatNumber(v as number, 1) + ' %';
    case 'restrictions':
      return (v as string[]).map((r) => RESTRICTION_LABEL[r as keyof typeof RESTRICTION_LABEL] ?? r).join(', ') || 'нет';
    case 'okpd2_codes':
      return (v as string[]).join(', ');
    case 'subject':
      return `близость ${Math.round((MOCK_SIMILARITY[p.id] ?? 0) * 100)} %`;
    case 'customer.status':
      return CUSTOMER_STATUS_LABEL[v as keyof typeof CUSTOMER_STATUS_LABEL];
    case 'customer.age_years':
      return `${v} лет`;
    case 'customer.has_unreliable_flags':
      return v ? 'есть отметки' : 'отметок нет';
    default:
      return String(v);
  }
}

const gteScore = (x: number, v: number, m: number) => (x >= v ? 1 : m > 0 ? Math.max(0, (x - v * (1 - m)) / (v * m)) : 0);
const lteScore = (x: number, v: number, m: number) => (x <= v ? 1 : m > 0 ? Math.max(0, 1 - (x - v) / (v * m)) : 0);

/** Частичный балл 0–1 или null, если данных нет */
function partial(rule: ScoringRule, x: FieldValue, p: Procurement): number | null {
  if (x === null) return null;
  const m = rule.soft_margin ?? 0;
  const v = rule.value;
  const list = Array.isArray(v) ? (v as (string | number)[]).map(String) : [];
  switch (rule.operator) {
    case 'gte':
      return gteScore(x as number, v as number, m);
    case 'lte':
      return lteScore(x as number, v as number, m);
    case 'between': {
      const [a, b] = v as [number, number];
      const n = x as number;
      return n < a ? gteScore(n, a, m) : n > b ? lteScore(n, b, m) : 1;
    }
    case 'in':
      return list.includes(String(x)) ? 1 : 0;
    case 'not_in':
      return list.includes(String(x)) ? 0 : 1;
    case 'any_in':
      return (x as string[]).some((r) => list.includes(r)) ? 1 : 0;
    case 'none_in':
      return (x as string[]).some((r) => list.includes(r)) ? 0 : 1;
    case 'prefix_in':
      return (x as string[]).some((code) => list.some((pre) => code.startsWith(pre))) ? 1 : 0;
    case 'is_false':
      return x === false ? 1 : 0;
    case 'contains_any':
      return list.some((w) => String(x).toLowerCase().includes(w.toLowerCase())) ? 1 : 0;
    case 'semantic_match': {
      const c = MOCK_SIMILARITY[p.id] ?? 0;
      return Math.min(1, Math.max(0, (c - 0.55) / (0.8 - 0.55)));
    }
  }
}

function score(p: Procurement, profile: ScoringProfile): ScoreResult {
  const c = customerOf(p);
  const rules = profile.rules.filter((r) => r.enabled);
  const results: RuleResult[] = [];
  const stopFactors: ScoreResult['stop_factors'] = [];

  for (const r of rules.filter((r) => r.kind === 'stop')) {
    const x = fieldValue(p, c, r.field);
    const triggered = partial(r, x, p) === 1;
    if (triggered) stopFactors.push({ rule_id: r.id, label: r.label, message: `${r.label}: ${valueText(r.field, x, p)}` });
    results.push({ rule_id: r.id, group: r.group, kind: 'stop', label: r.label, field_value_text: valueText(r.field, x, p), partial_score: null, contribution: null, max_contribution: null, no_data: x === null, triggered });
  }

  const groups: Group[] = ['procurement', 'fit', 'customer'];
  const raw: { g: Group; score: number | null; sumW: number; lowData: boolean; items: { r: ScoringRule; s: number | null; x: FieldValue }[] }[] =
    groups.map((g) => {
      const items = rules
        .filter((r) => r.kind === 'weighted' && r.group === g)
        .map((r) => {
          const x = fieldValue(p, c, r.field);
          return { r, x, s: partial(r, x, p) };
        });
      const applied = items.filter((i) => i.s !== null);
      const sumW = applied.reduce((a, i) => a + (i.r.weight ?? 1), 0);
      const totalW = items.reduce((a, i) => a + (i.r.weight ?? 1), 0);
      const score = sumW > 0 ? (100 * applied.reduce((a, i) => a + (i.r.weight ?? 1) * (i.s ?? 0), 0)) / sumW : null;
      return { g, score, sumW, items, lowData: totalW > 0 && totalW - sumW > totalW / 2 };
    });

  const included = raw.filter((x) => x.score !== null && profile.group_weights[x.g] > 0);
  const sumGW = included.reduce((a, x) => a + profile.group_weights[x.g], 0) || 1;
  let total = 0;
  const groupResults: GroupResult[] = raw.map((x) => {
    const W = x.score !== null && included.includes(x) ? profile.group_weights[x.g] / sumGW : 0;
    total += W * (x.score ?? 0);
    x.items.forEach(({ r, s, x: val }) => {
      const w = r.weight ?? 1;
      results.push({
        rule_id: r.id, group: r.group, kind: 'weighted', label: r.label,
        field_value_text: valueText(r.field, val, p),
        partial_score: s,
        contribution: s === null || x.sumW === 0 ? null : (W * w * s * 100) / x.sumW,
        max_contribution: s === null || x.sumW === 0 ? null : (W * w * 100) / x.sumW,
        no_data: s === null, triggered: false,
      });
    });
    return { group: x.g, score: x.score === null ? null : Math.round(x.score), weight: W, low_data: x.lowData };
  });

  total = stopFactors.length ? 0 : Math.round(total);
  const t = profile.thresholds;
  const recommendation = stopFactors.length || total < t.consider ? 'skip' : total >= t.participate ? 'participate' : 'consider';
  const incomplete = groupResults.some((g) => g.low_data || g.score === null);

  // Шаблонное обоснование: вывод → стоп → плюсы → минусы → нет данных
  const ref = (r: RuleResult) => `[${r.rule_id}]`;
  const weighted = results.filter((r) => r.kind === 'weighted' && !r.no_data);
  const pros = [...weighted].filter((r) => (r.partial_score ?? 0) > 0.5).sort((a, b) => (b.contribution ?? 0) - (a.contribution ?? 0)).slice(0, 3);
  const cons = [...weighted].filter((r) => (r.partial_score ?? 0) < 1).sort((a, b) => ((b.max_contribution ?? 0) - (b.contribution ?? 0)) - ((a.max_contribution ?? 0) - (a.contribution ?? 0))).slice(0, 2);
  const missing = results.filter((r) => r.no_data && r.kind === 'weighted');
  const parts = [`Рекомендация: ${RECOMMENDATION[recommendation].label.toLowerCase()}, оценка ${total} из 100.`];
  const firstStop = stopFactors[0];
  if (firstStop) parts.push(`Сработал стоп-фактор: ${firstStop.message}.`);
  if (pros.length) parts.push('Плюсы: ' + pros.map((r) => `${r.label} — ${r.field_value_text} ${ref(r)}`).join('; ') + '.');
  if (cons.length) parts.push('Минусы: ' + cons.map((r) => `${r.label} — ${r.field_value_text} ${ref(r)}`).join('; ') + '.');
  if (missing.length) parts.push('Нет данных: ' + missing.map((r) => `${r.label} ${ref(r)}`).join('; ') + '.');

  return { total, recommendation, incomplete, groups: groupResults, stop_factors: stopFactors, rules: results, justification: { text: parts.join(' '), source: 'template' }, calculated_at: new Date().toISOString() };
}

/** Главная причина одной фразой (в реальной системе её должен присылать бэкенд — поле reason) */
function shortReason(s: ScoreResult): string {
  const stop = s.stop_factors[0];
  if (stop) return stop.label;
  const weighted = s.rules.filter((r) => r.kind === 'weighted' && !r.no_data && r.max_contribution);
  const worst = [...weighted].sort(
    (a, b) => (b.max_contribution! - (b.contribution ?? 0)) - (a.max_contribution! - (a.contribution ?? 0)),
  )[0];
  if (worst && (worst.max_contribution ?? 0) - (worst.contribution ?? 0) > 3)
    return `Не совпало — ${worst.label}`;
  if (s.incomplete) return 'Не хватает данных о заказчике';
  return 'Совпали все ваши условия';
}

function procurementById(id: number) {
  const p = MOCK_PROCUREMENTS.find((x) => x.id === id);
  if (!p || !state.procurementIds.includes(id)) throw new ApiError(404, { code: 'NOT_FOUND', message: 'Закупка не найдена' });
  return p;
}

// ---------- Фоновые задачи: «обрабатываем» по файлу в 0,7 с ----------
function startTask(kind: Task['kind'], files: TaskFile[], onDone: () => void): string {
  const id = 't' + Date.now();
  state.tasks[id] = {
    task: { id, kind, status: 'queued', total: files.length, processed: 0, files, created_at: new Date().toISOString() },
    startedAt: Date.now(),
  };
  const tick = setInterval(() => {
    const entry = state.tasks[id];
    if (!entry) return clearInterval(tick);
    const t = entry.task;
    t.status = 'processing';
    const f = t.files[t.processed];
    if (f && f.status === 'pending') f.status = f.error ? 'error' : 'ok';
    t.processed = Math.min(t.total, t.processed + 1);
    if (f?.status === 'ok') f.procurement_ids.forEach((pid) => state.procurementIds.includes(pid) || state.procurementIds.push(pid));
    if (t.processed >= t.total) {
      clearInterval(tick);
      const errors = t.files.filter((x) => x.status === 'error').length;
      t.status = errors === 0 ? 'done' : errors === t.total ? 'failed' : 'partial';
      onDone();
    }
  }, 700);
  return id;
}

function fileFor(name: string, procurementId: number | null, error?: TaskFile['error']): TaskFile {
  const p = procurementId ? MOCK_PROCUREMENTS.find((x) => x.id === procurementId) : undefined;
  const warnings: TaskFile['warnings'] =
    p && !customerOf(p) ? [{ code: 'CUSTOMER_NOT_FOUND', message: 'Заказчик не найден в ЕГРЮЛ' }] : [];
  return { name, status: 'pending', error: error ?? null, warnings, procurement_ids: procurementId ? [procurementId] : [] };
}

// ---------- Реализация API ----------
export const mockApi: Api = {
  async me() {
    await wait(150);
    requireUser();
    return { ...state.user!, features: { llm: true } };
  },
  async login(email, password) {
    await wait(400);
    if (email === DEMO_EMAIL && password !== 'demo12345')
      throw new ApiError(401, { code: 'INVALID_CREDENTIALS', message: 'Неверная почта или пароль' });
    if (password.length < 1) throw new ApiError(400, { code: 'VALIDATION_ERROR', message: 'Введите пароль' });
    signIn(email);
    return { ...state.user!, features: { llm: true } };
  },
  async register(email, password) {
    await wait(400);
    if (password.length < 8)
      throw new ApiError(400, { code: 'VALIDATION_ERROR', message: 'Пароль должен быть не короче 8 символов' });
    signIn(email);
    return { ...state.user!, features: { llm: true } };
  },
  async logout() {
    await wait(100);
    state.user = null;
    writeSession(null);
  },

  async getActiveProfile() {
    await wait(200);
    requireUser();
    if (!state.profile) throw new ApiError(404, { code: 'NOT_FOUND', message: 'Профиль ещё не создан' });
    return structuredClone(state.profile);
  },
  async saveActiveProfile(p) {
    await wait(300);
    requireUser();
    state.profile = { id: 1, ...structuredClone(p) };
    return structuredClone(state.profile);
  },
  async parseProfileText(text) {
    await wait(1200);
    requireUser();
    const unparsed = ['крупные закупки', 'нормальные сроки', 'хорошие заказчики'].filter((ph) =>
      text.toLowerCase().includes(ph.split(' ')[0]!),
    );
    return {
      rules: structuredClone([...PARSED_RULES, ...DEFAULT_RULES]),
      company_description: 'IT-компания: разработка и сопровождение программного обеспечения.',
      unparsed,
    };
  },
  async rescore() {
    await wait(200);
    requireUser();
    const files = state.procurementIds.map((id) => fileFor(MOCK_PROCUREMENTS.find((p) => p.id === id)!.reg_number, id));
    return { task_id: startTask('score', files, () => {}) };
  },

  async upload(files) {
    await wait(500);
    requireUser();
    const list = files.map((f, i) => {
      const ok = /\.(xml|json|zip)$/i.test(f.name);
      if (!ok) return fileFor(f.name, null, { code: 'UNSUPPORTED_FORMAT', message: 'Файл не похож на выгрузку из ЕИС' });
      // Сначала раздаём ещё не загруженные демо-закупки, чтобы новые файлы добавлялись к старым,
      // а не «совпадали» с ними (в настоящей системе закупку определяет реестровый номер из файла)
      const fresh = MOCK_PROCUREMENTS.filter((p) => !state.procurementIds.includes(p.id));
      const pool = fresh.length > 0 ? fresh : MOCK_PROCUREMENTS;
      return fileFor(f.name, pool[i % pool.length]!.id);
    });
    return { task_id: startTask('upload', list, () => {}) };
  },
  async uploadDemo() {
    await wait(300);
    requireUser();
    const list = [
      ...MOCK_PROCUREMENTS.map((p) => fileFor(`${p.reg_number}.xml`, p.id)),
      fileFor('protocol_0365100002326000147.xml', null, { code: 'NOT_A_NOTICE', message: 'Это не извещение о закупке' }),
    ];
    return { task_id: startTask('upload', list, () => {}) };
  },
  async setCustomerInn(procurementId, inn) {
    await wait(300);
    requireUser();
    if (!/^\d{10}$|^\d{12}$/.test(inn))
      throw new ApiError(400, { code: 'VALIDATION_ERROR', message: 'ИНН — это 10 цифр для организации или 12 для ИП' });
    state.manualInn[procurementId] = inn;
    const p = procurementById(procurementId);
    return { task_id: startTask('score', [fileFor(p.reg_number, p.id)], () => {}) };
  },
  async listUploads() {
    await wait(200);
    requireUser();
    const profile = state.profile;
    return Object.values(state.tasks)
      .map((e) => e.task)
      .filter((t) => t.kind === 'upload')
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
      .map((t) => {
        const summary = { participate: 0, consider: 0, skip: 0 };
        if (profile)
          t.files
            .filter((f) => f.status === 'ok')
            .flatMap((f) => f.procurement_ids)
            .forEach((pid) => summary[score(MOCK_PROCUREMENTS.find((p) => p.id === pid)!, profile).recommendation]++);
        return { ...structuredClone(t), summary };
      });
  },
  async getTask(id) {
    await wait(100);
    requireUser();
    const entry = state.tasks[id];
    if (!entry) throw new ApiError(404, { code: 'NOT_FOUND', message: 'Задача не найдена' });
    return structuredClone(entry.task);
  },

  async getResults(f) {
    await wait(250);
    requireUser();
    const profile = state.profile;
    if (!profile) return [];
    return state.procurementIds
      .map((id) => MOCK_PROCUREMENTS.find((p) => p.id === id)!)
      .map((p): ResultRow => {
        const s = score(p, profile);
        return { procurement_id: p.id, reg_number: p.reg_number, subject: p.subject, customer_name: customerOf(p)?.name ?? p.customer_name, nmck: p.nmck, region: p.region, law: p.law, application_deadline: p.application_deadline, total: s.total, recommendation: s.recommendation, incomplete: s.incomplete, has_stop_factor: s.stop_factors.length > 0, reason: shortReason(s) };
      })
      .filter((r) => !f.recommendation || r.recommendation === f.recommendation)
      .filter((r) => !f.region || r.region === f.region)
      .filter((r) => !f.law || r.law === f.law)
      .filter((r) => f.nmck_min === undefined || (toNumber(r.nmck) ?? 0) >= f.nmck_min)
      .filter((r) => f.nmck_max === undefined || (toNumber(r.nmck) ?? 0) <= f.nmck_max)
      .filter((r) => !f.hide_expired || !isPast(r.application_deadline))
      .filter((r) => {
        if (!f.upload_id) return true;
        const t = state.tasks[f.upload_id]?.task;
        return Boolean(t?.files.some((x) => x.status === 'ok' && x.procurement_ids.includes(r.procurement_id)));
      });
  },
  exportUrl: () => '#',
  async getProcurement(id): Promise<ProcurementDetail> {
    await wait(250);
    requireUser();
    const p = procurementById(id);
    const c = customerOf(p);
    return {
      procurement: { ...structuredClone(p), customer_inn: state.manualInn[p.id] ?? p.customer_inn },
      customer: c ? structuredClone(c) : null,
      customer_error: c ? null : 'CUSTOMER_NOT_FOUND',
      score: state.profile ? score(p, state.profile) : null,
    };
  },
};

/** Для экспорта в демо-режиме: собрать файл в браузере */
export async function mockExport(format: 'csv' | 'json', rows: ResultRow[]): Promise<Blob> {
  if (format === 'json') return new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json' });
  const head = ['Реестровый номер', 'Предмет', 'Заказчик', 'НМЦК', 'Регион', 'Окончание подачи', 'Оценка', 'Рекомендация'];
  const lines = rows.map((r) => [r.reg_number, r.subject, r.customer_name ?? '', String(r.nmck), r.region ?? '', r.application_deadline ?? '', String(r.total), RECOMMENDATION[r.recommendation].label]);
  const csv = [head, ...lines].map((l) => l.map((v) => `"${v.replace(/"/g, '""')}"`).join(';')).join('\n');
  return new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' });
}

