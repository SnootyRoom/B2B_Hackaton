// Имитация бэкенда для работы без сервера (VITE_USE_MOCK=true).
// Здесь есть маленький «движок» по формулам аналитики — ТОЛЬКО чтобы демо было живым
// (поменял правила → оценки поменялись). Настоящую оценку считает бэкенд роли 3.

import type { Api } from './index';
import { lawOfNumber } from '../lib/regNumbers';
import { ApiError } from './client';
import {
  AGGRESSIVE_PROFILE,
  CAUTIOUS_PROFILE,
  DEFAULT_RULES,
  DEMO_PROFILE,
  MOCK_CUSTOMERS,
  MOCK_PROCUREMENTS,
  MOCK_SIMILARITY,
  PARSED_RULES,
  type MockProcurement,
} from './mockData';
import type {
  Change,
  CompareRow,
  CreateProfileInput,
  CustomerProfile,
  Group,
  GroupResult,
  ProcurementDetail,
  ProfileSummary,
  ResultRow,
  RuleResult,
  ScoreResult,
  ScoringProfile,
  ScoringProfileInput,
  ScoringRule,
  Task,
  TaskFile,
  User,
} from './types';
import { CUSTOMER_STATUS_LABEL, METHOD_LABEL, RECOMMENDATION, RESTRICTION_LABEL } from '../lib/catalog';
import { formatMoney, formatNumber, toNumber, yearsSince } from '../lib/format';
import { MAX_PROFILE_NAME, MAX_PROFILES, MAX_REG_NUMBERS } from '../lib/catalog';

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const DEMO_EMAIL = 'demo@example.com';
const EMPTY_EMAIL = 'new@example.com';
interface State {
  user: User | null;
  /** Все профили; ровно у одного is_active */
  profiles: ScoringProfile[];
  procurementIds: number[];
  manualInn: Record<number, string>;
  tasks: Record<string, { task: Task; startedAt: number }>;
}

const state: State = { user: null, profiles: [], procurementIds: [], manualInn: {}, tasks: {} };

/** Все закупки «сервера»: демо-набор + полученные по номерам */
const procs: MockProcurement[] = [...MOCK_PROCUREMENTS];
/** Закупка, «скачанная» по номеру, берёт смысловую близость у закупки-образца */
const similarityFrom: Record<number, number> = {};
const similarityOf = (p: MockProcurement) => MOCK_SIMILARITY[similarityFrom[p.id] ?? p.id] ?? 0;
const findProc = (id: number) => procs.find((x) => x.id === id);

const activeProfile = (): ScoringProfile | null => state.profiles.find((p) => p.is_active) ?? null;
let profileSeq = 1;
/** Версия профиля: растёт при сохранении правил, весов, порогов (имя не входит) */
const version: Record<string, number> = {};
/** По какой версии профиля посчитана оценка: scored[профиль][закупка] = версия */
const scored: Record<string, Record<number, number>> = {};
const hasScore = (profileId: string, procId: number) => scored[profileId]?.[procId] !== undefined;
const isFresh = (profileId: string, procId: number) =>
  scored[profileId]?.[procId] === (version[profileId] ?? 0);
const staleIds = (profileId: string) => state.procurementIds.filter((id) => !isFresh(profileId, id));
const markScored = (profileId: string, procId: number) => {
  (scored[profileId] ??= {})[procId] = version[profileId] ?? 0;
};
/** Пересчёт, который уже идёт по профилю: повторный activate вернёт тот же task_id */
const runningRescore: Record<string, string> = {};

/** Две прошлые загрузки, чтобы в «Истории» было что показать */
function seedHistory() {
  const hoursAgo = (h: number) => new Date(Date.now() - h * 3600 * 1000).toISOString();
  const done = (id: string, created_at: string, ids: number[], extra: TaskFile[] = []): void => {
    const files: TaskFile[] = [
      ...ids.map((pid) => {
        const p = findProc(pid)!;
        return { ...fileFor(`${p.reg_number}.xml`, pid), status: 'ok' as const };
      }),
      ...extra,
    ];
    const errors = files.filter((f) => f.status === 'error').length;
    state.tasks[id] = {
      task: {
        id,
        kind: 'upload',
        status: errors ? 'partial' : 'done',
        total: files.length,
        processed: files.length,
        files,
        result: null,
        error: null,
        created_at,
        finished_at: created_at,
      },
      startedAt: Date.parse(created_at),
    };
  };
  done(
    'h1',
    hoursAgo(74),
    [1, 2, 3, 4, 5, 6, 7],
    [
      {
        ...fileFor('protocol_0365100002326000147.xml', null, {
          code: 'NOT_A_NOTICE',
          message: 'Это не извещение о закупке',
        }),
        status: 'error',
      },
    ],
  );
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
  state.user = { id: '1', email, created_at: new Date().toISOString() };
  writeSession(email);
  // Для наглядности любой вход сразу получает готовый профиль и набор закупок с разными оценками.
  // Чтобы проверить путь «с нуля» (пустой аккаунт), войдите как new@example.com.
  if (state.profiles.length > 0) return;
  if (email !== EMPTY_EMAIL) {
    state.profiles = [
      mockProfile(DEMO_PROFILE, true),
      mockProfile(CAUTIOUS_PROFILE),
      mockProfile(AGGRESSIVE_PROFILE),
    ];
    state.procurementIds = MOCK_PROCUREMENTS.map((p) => p.id);
    // Оценки есть только по активному профилю — по остальным досчитаются при переключении или сравнении
    state.procurementIds.forEach((id) => markScored(state.profiles[0]!.id, id));
    seedHistory();
  } else {
    // Как на бэкенде: новому пользователю профиль создаётся сам, только с правилами заказчика
    state.profiles = [mockProfile({ ...EMPTY_PROFILE, rules: structuredClone(DEFAULT_RULES) }, true)];
  }
}

const EMPTY_PROFILE: ScoringProfileInput = {
  name: 'Мой профиль',
  company_description: '',
  source_text: '',
  group_weights: { procurement: 0.4, fit: 0.35, customer: 0.25 },
  thresholds: { participate: 70, consider: 40 },
  rules: [],
};

function mockProfile(p: ScoringProfileInput, active = false): ScoringProfile {
  return {
    id: 'pr' + profileSeq++,
    is_active: active,
    updated_at: new Date().toISOString(),
    ...structuredClone(p),
  };
}

function profileById(id: string): ScoringProfile {
  const p = state.profiles.find((x) => x.id === id);
  if (!p) throw new ApiError(404, { code: 'NOT_FOUND', message: 'Профиль не найден' });
  return p;
}

function checkName(name: string, exceptId?: string): string {
  const n = name.trim();
  if (!n || n.length > MAX_PROFILE_NAME)
    throw new ApiError(422, {
      code: 'VALIDATION_ERROR',
      message: `Название — от 1 до ${MAX_PROFILE_NAME} символов`,
    });
  if (state.profiles.some((p) => p.id !== exceptId && p.name.toLowerCase() === n.toLowerCase()))
    throw new ApiError(409, { code: 'PROFILE_NAME_TAKEN', message: 'Профиль с таким названием уже есть' });
  return n;
}

function checkLimit() {
  if (state.profiles.length >= MAX_PROFILES)
    throw new ApiError(400, {
      code: 'TOO_MANY_PROFILES',
      message: `Можно завести не больше ${MAX_PROFILES} профилей`,
    });
}

const summaryOf = (p: ScoringProfile): ProfileSummary => ({
  id: p.id,
  name: p.name,
  is_active: p.is_active,
  rules_count: p.rules.length,
  updated_at: p.updated_at,
});

/** «Осторожный (копия)», «Осторожный (копия 2)» — как на бэкенде */
function copyName(base: string): string {
  const taken = new Set(state.profiles.map((p) => p.name.toLowerCase()));
  const first = `${base} (копия)`;
  if (!taken.has(first.toLowerCase())) return first;
  for (let i = 2; ; i++) if (!taken.has(`${base} (копия ${i})`.toLowerCase())) return `${base} (копия ${i})`;
}

/** Досчёт оценок по профилю без повторной загрузки: по одной закупке за тик */
function startRescore(profileId: string, ids: number[] = staleIds(profileId)): string {
  const running = runningRescore[profileId];
  const st = running ? state.tasks[running]?.task.status : undefined;
  if (running && (st === 'queued' || st === 'processing')) return running;
  const id = startTask(
    'rescore',
    ids.map((pid) => fileFor(findProc(pid)!.reg_number, pid)),
    {
      tickMs: 300,
      onFile: (f) => f.procurement_ids.forEach((pid) => markScored(profileId, Number(pid))),
      onDone: () => delete runningRescore[profileId],
    },
  );
  runningRescore[profileId] = id;
  return id;
}

/** Объяснение разницы двух оценок — как explain_difference у роли 3: по шаблонам, до 3 фраз */
function explainDifference(pa: ScoringProfile, pb: ScoringProfile, ra: ScoreResult, rb: ScoreResult): string {
  const out: { w: number; t: string }[] = [];
  const stops = (r: ScoreResult) => r.rules.filter((x) => x.kind === 'stop' && x.triggered);
  const sa = stops(ra);
  const sb = stops(rb);
  sa.filter((x) => !sb.some((y) => y.field === x.field)).forEach((x) =>
    out.push({
      w: 100,
      t: `В «${pa.name}» стоп: ${x.label.charAt(0).toLowerCase() + x.label.slice(1)} [${x.rule_id}].`,
    }),
  );
  sb.filter((x) => !sa.some((y) => y.field === x.field)).forEach((x) =>
    out.push({
      w: 100,
      t: `В «${pb.name}» стоп: ${x.label.charAt(0).toLowerCase() + x.label.slice(1)} [${x.rule_id}].`,
    }),
  );
  const weighted = (r: ScoreResult) => r.rules.filter((x) => x.kind === 'weighted');
  const wa = weighted(ra);
  const wb = weighted(rb);
  for (const x of wa) {
    const y = wb.find((z) => z.field === x.field);
    if (!y) {
      out.push({ w: x.contribution ?? 0, t: `В «${pb.name}» нет условия «${x.label}» [${x.rule_id}].` });
    } else if (Math.abs((x.partial_score ?? 0) - (y.partial_score ?? 0)) > 0.05) {
      const better =
        (y.partial_score ?? 0) > (x.partial_score ?? 0)
          ? ([pb, y, pa, x] as const)
          : ([pa, x, pb, y] as const);
      out.push({
        w: Math.abs((x.contribution ?? 0) - (y.contribution ?? 0)),
        t: `Условие «${better[3].label}» [${better[3].rule_id}] в «${better[2].name}» выполнено хуже, чем «${better[1].label}» [${better[1].rule_id}] в «${better[0].name}».`,
      });
    }
  }
  wb.filter((y) => !wa.some((x) => x.field === y.field)).forEach((y) =>
    out.push({ w: y.contribution ?? 0, t: `В «${pa.name}» нет условия «${y.label}» [${y.rule_id}].` }),
  );
  const ta = pa.thresholds;
  const tb = pb.thresholds;
  if (ta.participate !== tb.participate || ta.consider !== tb.consider)
    out.push({
      w: 0.5,
      t: `Пороги «Участвовать / Рассмотреть»: в «${pa.name}» ${ta.participate}/${ta.consider}, в «${pb.name}» ${tb.participate}/${tb.consider}.`,
    });
  return out
    .sort((a, b) => b.w - a.w)
    .slice(0, 3)
    .map((x) => x.t)
    .join(' ');
}

const RANK: Record<string, number> = { skip: 0, consider: 1, participate: 2 };

const restored = readSession();
if (restored) signIn(restored);

function requireUser() {
  if (!state.user) throw new ApiError(401, { code: 'UNAUTHORIZED', message: 'Войдите, чтобы продолжить' });
}
function customerOf(p: MockProcurement): CustomerProfile | null {
  const inn = state.manualInn[p.id] ?? p.customer_inn;
  return inn ? (MOCK_CUSTOMERS[inn] ?? null) : null;
}

type FieldValue = number | string | boolean | string[] | null;

function fieldValue(p: MockProcurement, c: CustomerProfile | null, field: string): FieldValue {
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

function valueText(field: string, v: FieldValue, p: MockProcurement): string | null {
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
      return (
        (v as string[]).map((r) => RESTRICTION_LABEL[r as keyof typeof RESTRICTION_LABEL] ?? r).join(', ') ||
        'нет'
      );
    case 'okpd2_codes':
      return (v as string[]).join(', ');
    case 'subject':
      return `близость ${Math.round(similarityOf(p) * 100)} %`;
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

const gteScore = (x: number, v: number, m: number) =>
  x >= v ? 1 : m > 0 ? Math.max(0, (x - v * (1 - m)) / (v * m)) : 0;
const lteScore = (x: number, v: number, m: number) =>
  x <= v ? 1 : m > 0 ? Math.max(0, 1 - (x - v) / (v * m)) : 0;

/** Частичный балл 0–1 или null, если данных нет */
function partial(rule: ScoringRule, x: FieldValue, p: MockProcurement): number | null {
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
      const c = similarityOf(p);
      return Math.min(1, Math.max(0, (c - 0.55) / (0.8 - 0.55)));
    }
  }
}

function score(p: MockProcurement, profile: ScoringProfile): ScoreResult {
  const c = customerOf(p);
  const rules = profile.rules.filter((r) => r.enabled);
  const results: RuleResult[] = [];
  const stopFactors: string[] = [];
  const base = (r: ScoringRule, x: FieldValue) => ({
    rule_id: r.id,
    label: r.label,
    group: r.group,
    kind: r.kind,
    field: r.field,
    operator: r.operator,
    field_value: x,
    text: valueText(r.field, x, p) ?? '',
  });

  for (const r of rules.filter((r) => r.kind === 'stop')) {
    const x = fieldValue(p, c, r.field);
    const triggered = partial(r, x, p) === 1;
    if (triggered) stopFactors.push(r.id);
    results.push({
      ...base(r, x),
      status: x === null ? 'no_data' : 'applied',
      triggered,
      partial_score: null,
      contribution: null,
      lost: null,
    });
  }

  const groups: Group[] = ['procurement', 'fit', 'customer'];
  const raw: {
    g: Group;
    score: number | null;
    sumW: number;
    lowData: boolean;
    items: { r: ScoringRule; s: number | null; x: FieldValue }[];
  }[] = groups.map((g) => {
    const items = rules
      .filter((r) => r.kind === 'weighted' && r.group === g)
      .map((r) => {
        const x = fieldValue(p, c, r.field);
        return { r, x, s: partial(r, x, p) };
      });
    const applied = items.filter((i) => i.s !== null);
    const sumW = applied.reduce((a, i) => a + (i.r.weight ?? 1), 0);
    const totalW = items.reduce((a, i) => a + (i.r.weight ?? 1), 0);
    const score =
      sumW > 0 ? (100 * applied.reduce((a, i) => a + (i.r.weight ?? 1) * (i.s ?? 0), 0)) / sumW : null;
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
      const max = s === null || x.sumW === 0 ? null : (W * w * 100) / x.sumW;
      results.push({
        ...base(r, val),
        status: s === null ? 'no_data' : 'applied',
        triggered: false,
        partial_score: s,
        contribution: max === null ? null : max * (s ?? 0),
        lost: max === null ? null : max * (1 - (s ?? 0)),
      });
    });
    return {
      group: x.g,
      score: x.score === null ? null : Math.round(x.score),
      weight: profile.group_weights[x.g],
      effective_weight: W,
      low_data: x.lowData,
    };
  });

  total = stopFactors.length ? 0 : Math.round(total);
  const t = profile.thresholds;
  const recommendation =
    stopFactors.length || total < t.consider ? 'skip' : total >= t.participate ? 'participate' : 'consider';
  const incomplete = groupResults.some((g) => g.low_data || g.score === null);

  // Шаблонное обоснование: вывод → стоп → плюсы → минусы → нет данных
  const ref = (r: RuleResult) => `[${r.rule_id}]`;
  const weighted = results.filter((r) => r.kind === 'weighted' && r.status === 'applied');
  const pros = [...weighted]
    .filter((r) => (r.partial_score ?? 0) > 0.5)
    .sort((a, b) => (b.contribution ?? 0) - (a.contribution ?? 0))
    .slice(0, 3);
  const cons = [...weighted]
    .filter((r) => (r.partial_score ?? 0) < 1)
    .sort((a, b) => (b.lost ?? 0) - (a.lost ?? 0))
    .slice(0, 2);
  const missing = results.filter((r) => r.status === 'no_data' && r.kind === 'weighted');
  const parts = [
    `Рекомендация: ${RECOMMENDATION[recommendation].label.toLowerCase()}, оценка ${total} из 100.`,
  ];
  const firstStop = results.find((r) => r.triggered);
  if (firstStop) parts.push(`Сработал стоп-фактор: ${firstStop.label}: ${firstStop.text}.`);
  if (pros.length)
    parts.push('Плюсы: ' + pros.map((r) => `${r.label} — ${r.text} ${ref(r)}`).join('; ') + '.');
  if (cons.length)
    parts.push('Минусы: ' + cons.map((r) => `${r.label} — ${r.text} ${ref(r)}`).join('; ') + '.');
  if (missing.length)
    parts.push('Нет данных: ' + missing.map((r) => `${r.label} ${ref(r)}`).join('; ') + '.');

  return {
    id: String(p.id),
    procurement_id: String(p.id),
    profile_id: profile.id,
    total,
    recommendation,
    incomplete,
    groups: groupResults,
    stop_factors: stopFactors,
    rules: results,
    justification: parts.join(' '),
    justification_source: 'template',
    computed_at: new Date().toISOString(),
  };
}

const briefOf = (p: MockProcurement) => ({
  procurement_id: String(p.id),
  reg_number: p.reg_number,
  subject: p.subject,
  customer_name: customerOf(p)?.name ?? p.customer_name,
  nmck: p.nmck,
  currency: p.currency ?? 'RUB',
  region: p.region,
  law: p.law,
  application_deadline: p.application_deadline,
});

/** Неизвестный номер: «скачиваем» — берём за образец одну из демо-закупок */
function fetchNew(num: string, i: number): number {
  const tpl = MOCK_PROCUREMENTS[i % MOCK_PROCUREMENTS.length]!;
  const id = 100 + procs.length;
  const law = lawOfNumber(num);
  procs.push({
    ...structuredClone(tpl),
    id,
    reg_number: num,
    law,
    source_url: `https://zakupki.gov.ru/epz/order/notice/${law === '44' ? 'ea20' : 'notice223'}/view/common-info.html?regNumber=${num}`,
    parsed_by: 'adapter:demo',
  });
  similarityFrom[id] = tpl.id;
  return id;
}

function procurementById(id: number) {
  const p = findProc(id);
  if (!p || !state.procurementIds.includes(id))
    throw new ApiError(404, { code: 'NOT_FOUND', message: 'Закупка не найдена' });
  return p;
}
let taskSeq = 0;
interface TaskOptions {
  onDone?: () => void;
  /** После обработки каждой строки */
  onFile?: (f: TaskFile) => void;
  tickMs?: number;
}

function startTask(
  kind: Task['kind'],
  files: TaskFile[],
  { onDone, onFile, tickMs = 700 }: TaskOptions = {},
): string {
  const id = 't' + Date.now() + '-' + taskSeq++;
  state.tasks[id] = {
    task: {
      id,
      kind,
      status: 'queued',
      total: files.length,
      processed: 0,
      files,
      result: null,
      error: null,
      created_at: new Date().toISOString(),
      finished_at: null,
    },
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
    if (f?.status === 'ok') {
      f.procurement_ids
        .map(Number)
        .forEach((pid) => state.procurementIds.includes(pid) || state.procurementIds.push(pid));
      // Загрузка оценивает закупку по активному профилю, по остальным оценка устаревает
      if (kind === 'upload' || kind === 'fetch') {
        Object.values(scored).forEach((m) => f.procurement_ids.forEach((pid) => delete m[Number(pid)]));
        const active = activeProfile();
        if (active) f.procurement_ids.forEach((pid) => markScored(active.id, Number(pid)));
      }
      onFile?.(f);
    }
    if (t.processed >= t.total) {
      clearInterval(tick);
      const errors = t.files.filter((x) => x.status === 'error').length;
      t.status = errors === 0 ? 'done' : errors === t.total ? 'failed' : 'partial';
      t.finished_at = new Date().toISOString();
      onDone?.();
    }
  }, tickMs);
  return id;
}

function fileFor(name: string, procurementId: number | null, error?: TaskFile['error']): TaskFile {
  const p = procurementId ? findProc(procurementId) : undefined;
  const warnings: TaskFile['warnings'] =
    p && !customerOf(p) ? [{ code: 'CUSTOMER_NOT_FOUND', message: 'Заказчик не найден в ЕГРЮЛ' }] : [];
  return {
    id: name,
    filename: name,
    status: 'pending',
    error: error ?? null,
    warnings,
    procurement_ids: procurementId ? [String(procurementId)] : [],
  };
}
export const mockApi: Api = {
  async me() {
    await wait(150);
    requireUser();
    return { ...state.user! };
  },
  async login(email, password) {
    await wait(400);
    if (email === DEMO_EMAIL && password !== 'demo12345')
      throw new ApiError(401, { code: 'INVALID_CREDENTIALS', message: 'Неверная почта или пароль' });
    if (password.length < 1) throw new ApiError(400, { code: 'VALIDATION_ERROR', message: 'Введите пароль' });
    signIn(email);
    return { ...state.user! };
  },
  async register(email, password) {
    await wait(400);
    if (password.length < 8)
      throw new ApiError(400, {
        code: 'VALIDATION_ERROR',
        message: 'Пароль должен быть не короче 8 символов',
      });
    signIn(email);
    return { ...state.user! };
  },
  async logout() {
    await wait(100);
    state.user = null;
    writeSession(null);
  },

  async getActiveProfile() {
    await wait(200);
    requireUser();
    const active = activeProfile();
    if (!active) throw new ApiError(404, { code: 'NOT_FOUND', message: 'Профиль ещё не создан' });
    return structuredClone(active);
  },
  async saveActiveProfile(p, rescore) {
    const active = activeProfile();
    if (!active) throw new ApiError(404, { code: 'NOT_FOUND', message: 'Профиль ещё не создан' });
    return mockApi.saveProfile(active.id, p, rescore);
  },

  async listProfiles() {
    await wait(150);
    requireUser();
    return [...state.profiles]
      .sort((a, b) => Number(b.is_active) - Number(a.is_active) || b.updated_at.localeCompare(a.updated_at))
      .map(summaryOf);
  },
  async getProfile(id) {
    await wait(150);
    requireUser();
    return structuredClone(profileById(id));
  },
  async createProfile(input: CreateProfileInput) {
    await wait(250);
    requireUser();
    checkLimit();
    const name = checkName(input.name);
    if (input.template && input.rules)
      throw new ApiError(422, { code: 'VALIDATION_ERROR', message: 'Укажите либо шаблон, либо правила' });
    const tpl =
      input.template === 'cautious'
        ? CAUTIOUS_PROFILE
        : input.template === 'aggressive'
          ? AGGRESSIVE_PROFILE
          : null;
    const created = mockProfile({
      name,
      company_description: input.company_description || tpl?.company_description || '',
      source_text: input.source_text || tpl?.source_text || '',
      group_weights: input.group_weights ?? tpl?.group_weights ?? EMPTY_PROFILE.group_weights,
      thresholds: input.thresholds ?? tpl?.thresholds ?? EMPTY_PROFILE.thresholds,
      rules: structuredClone(input.rules ?? tpl?.rules ?? DEFAULT_RULES),
    });
    state.profiles.push(created);
    return structuredClone(created);
  },
  async duplicateProfile(id) {
    await wait(250);
    requireUser();
    checkLimit();
    const src = profileById(id);
    const copy = mockProfile({
      name: copyName(src.name),
      company_description: src.company_description,
      source_text: src.source_text,
      group_weights: src.group_weights,
      thresholds: src.thresholds,
      rules: src.rules,
    });
    state.profiles.push(copy);
    return structuredClone(copy);
  },
  async renameProfile(id, name) {
    await wait(200);
    requireUser();
    const p = profileById(id);
    p.name = checkName(name, id);
    return summaryOf(p);
  },
  async saveProfile(id, input, rescore) {
    await wait(300);
    requireUser();
    const p = profileById(id);
    Object.assign(p, structuredClone({ ...input, name: p.name }), { updated_at: new Date().toISOString() });
    version[id] = (version[id] ?? 0) + 1; // все оценки по профилю устарели
    const task_id = rescore && p.is_active ? startRescore(id) : null;
    return { profile: structuredClone(p), task_id };
  },
  async deleteProfile(id) {
    await wait(250);
    requireUser();
    const p = profileById(id);
    if (state.profiles.length === 1)
      throw new ApiError(400, { code: 'LAST_PROFILE', message: 'Нельзя удалить единственный профиль' });
    state.profiles = state.profiles.filter((x) => x.id !== id);
    delete scored[id];
    if (!p.is_active) return { task_id: null };
    // Удалили активный — активным становится недавно изменённый
    const next = [...state.profiles].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]!;
    next.is_active = true;
    return { task_id: staleIds(next.id).length ? startRescore(next.id) : null };
  },
  async activateProfile(id) {
    await wait(250);
    requireUser();
    profileById(id);
    state.profiles.forEach((x) => (x.is_active = x.id === id));
    return { task_id: staleIds(id).length ? startRescore(id) : null };
  },
  async scoreStale(profileId) {
    await wait(150);
    requireUser();
    profileById(profileId);
    return { task_id: startRescore(profileId) };
  },
  async compareProfiles(a, b) {
    await wait(300);
    requireUser();
    const pa = profileById(a);
    const pb = profileById(b);
    const summary: Record<Change, number> = { better: 0, worse: 0, same: 0, unknown: 0 };
    let missing = 0;
    const rows = state.procurementIds.map((id): CompareRow => {
      const p = findProc(id)!;
      const ra = hasScore(a, id) ? score(p, pa) : null;
      const rb = hasScore(b, id) ? score(p, pb) : null;
      missing += Number(!isFresh(a, id)) + Number(!isFresh(b, id));
      const change: Change =
        !ra || !rb
          ? 'unknown'
          : RANK[rb.recommendation]! > RANK[ra.recommendation]!
            ? 'better'
            : RANK[rb.recommendation]! < RANK[ra.recommendation]!
              ? 'worse'
              : 'same';
      summary[change]++;
      return {
        ...briefOf(p),
        a: { total: ra?.total ?? null, recommendation: ra?.recommendation ?? null, stale: !isFresh(a, id) },
        b: { total: rb?.total ?? null, recommendation: rb?.recommendation ?? null, stale: !isFresh(b, id) },
        change,
        delta: ra && rb ? rb.total - ra.total : null,
        explanation:
          ra && rb && (change !== 'same' || ra.total !== rb.total) ? explainDifference(pa, pb, ra, rb) : '',
      };
    });
    const moved = (r: CompareRow) => Number(r.change === 'better' || r.change === 'worse');
    rows.sort((x, y) => moved(y) - moved(x) || Math.abs(y.delta ?? 0) - Math.abs(x.delta ?? 0));
    return { profile_a: a, profile_b: b, rows, summary, missing };
  },
  async getCatalog() {
    await wait(100);
    return { regions: [], llm_enabled: true };
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

  async upload(files) {
    await wait(500);
    requireUser();
    const list = files.map((f, i) => {
      const ok = /\.(xml|json|zip)$/i.test(f.name);
      if (!ok)
        return fileFor(f.name, null, {
          code: 'UNSUPPORTED_FORMAT',
          message: 'Файл не похож на выгрузку из ЕИС',
        });
      // Сначала раздаём ещё не загруженные демо-закупки, чтобы новые файлы добавлялись к старым,
      // а не «совпадали» с ними (в настоящей системе закупку определяет реестровый номер из файла)
      const fresh = MOCK_PROCUREMENTS.filter((p) => !state.procurementIds.includes(p.id));
      const pool = fresh.length > 0 ? fresh : MOCK_PROCUREMENTS;
      return fileFor(f.name, pool[i % pool.length]!.id);
    });
    return { task_id: startTask('upload', list) };
  },
  async fetchByNumbers(input) {
    await wait(400);
    requireUser();
    // Как на сервере: делим строки по пробелам, переносам, «,» и «;», убираем повторы
    const numbers = [...new Set(input.flatMap((x) => x.split(/[\s,;]+/)).filter(Boolean))];
    const invalid = numbers.filter((n) => !/^(\d{11}|\d{18}|\d{19})$/.test(n));
    if (numbers.length === 0 || invalid.length === numbers.length)
      throw new ApiError(400, {
        code: 'INVALID_REG_NUMBER',
        message: 'Ни один номер не подходит',
        details: { invalid },
      });
    if (numbers.length > MAX_REG_NUMBERS)
      throw new ApiError(400, {
        code: 'TOO_MANY_NUMBERS',
        message: `За один раз — не больше ${MAX_REG_NUMBERS} номеров`,
      });
    const list = numbers.map((num, i) => {
      if (invalid.includes(num))
        return fileFor(num, null, {
          code: 'INVALID_REG_NUMBER',
          message: 'Это не похоже на реестровый номер закупки',
        });
      // Демо-правила, чтобы показать все статусы: …0000 — нет в ЕИС, …9999 — портал не ответил,
      // …7777 — ЕИС недоступна, документ взят из data/samples
      if (num.endsWith('0000'))
        return fileFor(num, null, {
          code: 'EIS_NOT_FOUND',
          message: 'Закупка с таким номером не найдена в ЕИС',
        });
      if (num.endsWith('9999'))
        return fileFor(num, null, { code: 'EIS_UNAVAILABLE', message: 'Портал закупок не ответил' });
      const known = procs.find((p) => p.reg_number === num);
      // Повторный номер обновляет ту же закупку — дубля нет
      const id = known?.id ?? fetchNew(num, i);
      const file = fileFor(num, id);
      if (num.endsWith('7777'))
        file.warnings = [
          { code: 'EIS_FALLBACK_SAMPLE', message: 'ЕИС недоступна — документ взят из сохранённых образцов' },
          ...file.warnings,
        ];
      return file;
    });
    return { task_id: startTask('fetch', list) };
  },
  async uploadDemo() {
    await wait(300);
    requireUser();
    const list = [
      ...MOCK_PROCUREMENTS.map((p) => fileFor(`${p.reg_number}.xml`, p.id)),
      fileFor('protocol_0365100002326000147.xml', null, {
        code: 'NOT_A_NOTICE',
        message: 'Это не извещение о закупке',
      }),
    ];
    return { task_id: startTask('upload', list) };
  },
  async setCustomerInn(procurementId, inn) {
    await wait(300);
    requireUser();
    if (!/^\d{10}$|^\d{12}$/.test(inn))
      throw new ApiError(400, {
        code: 'VALIDATION_ERROR',
        message: 'ИНН — это 10 цифр для организации или 12 для ИП',
      });
    state.manualInn[Number(procurementId)] = inn;
    const p = procurementById(Number(procurementId));
    // Заказчик поменялся — оценки по всем профилям устарели, пересчитываем по активному
    Object.values(scored).forEach((m) => delete m[p.id]);
    const active = activeProfile()!;
    return { task_id: startRescore(active.id, [p.id]) };
  },
  async listUploads() {
    await wait(200);
    requireUser();
    return Object.values(state.tasks)
      .map((e) => e.task)
      .filter((t) => t.kind === 'upload' || t.kind === 'fetch')
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
      .map((t) => structuredClone(t));
  },
  async getTask(id) {
    await wait(100);
    requireUser();
    const entry = state.tasks[id];
    if (!entry) throw new ApiError(404, { code: 'NOT_FOUND', message: 'Задача не найдена' });
    return structuredClone(entry.task);
  },

  async getResults(profileId) {
    await wait(250);
    requireUser();
    const profile = profileId ? profileById(profileId) : activeProfile();
    if (!profile) return [];
    return state.procurementIds
      .map((id) => findProc(id)!)
      .map((p): ResultRow => {
        const s = hasScore(profile.id, p.id) ? score(p, profile) : null;
        return {
          ...briefOf(p),
          total: s?.total ?? null,
          recommendation: s?.recommendation ?? null,
          incomplete: s?.incomplete ?? false,
          has_stop_factor: (s?.stop_factors.length ?? 0) > 0,
          stale: !isFresh(profile.id, p.id),
        };
      });
  },
  async getProcurement(id): Promise<ProcurementDetail> {
    await wait(250);
    requireUser();
    const p = procurementById(Number(id));
    const c = customerOf(p);
    const now = new Date().toISOString();
    return {
      id,
      data: { ...structuredClone(p), customer_inn: state.manualInn[p.id] ?? p.customer_inn },
      customer: c ? structuredClone(c) : null,
      customer_error: c ? null : 'CUSTOMER_NOT_FOUND',
      score: activeProfile() && hasScore(activeProfile()!.id, p.id) ? score(p, activeProfile()!) : null,
      created_at: now,
      updated_at: now,
    };
  },
};
