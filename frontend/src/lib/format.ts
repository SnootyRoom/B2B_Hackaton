// Форматы из CLAUDE.md: суммы «4 200 000 ₽», в таблице «4,2 млн ₽», даты ДД.ММ.ГГГГ, местное время.

import type { Money } from '../api/types';

const NBSP = ' ';

export function toNumber(value: Money | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = typeof value === 'number' ? value : Number(String(value).replace(/\s/g, '').replace(',', '.'));
  return Number.isFinite(n) ? n : null;
}

/** Целые разряды через пробел: 4200000 → «4 200 000» */
function groupDigits(n: number, fractionDigits = 0): string {
  const fixed = Math.abs(n).toFixed(fractionDigits);
  const [int = '0', frac] = fixed.split('.');
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  const trimmedFrac = frac?.replace(/0+$/, '');
  return (n < 0 ? '−' : '') + grouped + (trimmedFrac ? ',' + trimmedFrac : '');
}

/** Полная сумма: «4 200 000 ₽», копейки — только если есть */
export function formatMoney(value: Money | null | undefined): string {
  const n = toNumber(value);
  if (n === null) return 'нет данных';
  return groupDigits(n, 2) + NBSP + '₽';
}

/** Короткая сумма для таблицы: «4,2 млн ₽», «680 тыс. ₽», «1,25 млрд ₽» */
export function formatMoneyShort(value: Money | null | undefined): string {
  const n = toNumber(value);
  if (n === null) return '—';
  const abs = Math.abs(n);
  const short = (x: number, unit: string) => {
    const digits = x >= 100 ? 0 : x >= 10 ? 1 : 2;
    return groupDigits(Number(x.toFixed(digits)), digits) + NBSP + unit + NBSP + '₽';
  };
  if (abs >= 1e9) return short(n / 1e9, 'млрд');
  if (abs >= 1e6) return short(n / 1e6, 'млн');
  if (abs >= 1e3) return short(n / 1e3, 'тыс.');
  return groupDigits(n, 2) + NBSP + '₽';
}

export function formatNumber(n: number | null | undefined, fractionDigits = 2): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '—';
  return groupDigits(n, fractionDigits);
}

function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

const pad = (n: number) => String(n).padStart(2, '0');

/** «10.11.2026» в местном времени пользователя */
export function formatDate(value: string | null | undefined): string {
  const d = parseDate(value);
  if (!d) return '—';
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}`;
}

/** «10.11.2026 09:00» */
export function formatDateTime(value: string | null | undefined): string {
  const d = parseDate(value);
  if (!d) return '—';
  return `${formatDate(value)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function isPast(value: string | null | undefined, now: Date = new Date()): boolean {
  const d = parseDate(value);
  return d !== null && d.getTime() < now.getTime();
}

/** «осталось 5 дней» / «последний день» / «приём завершён» + насколько срочно */
export function deadlineInfo(
  value: string | null | undefined,
  now: Date = new Date(),
): { text: string; tone: 'normal' | 'urgent' | 'closed' } {
  const d = parseDate(value);
  if (!d) return { text: 'срок не указан', tone: 'normal' };
  const ms = d.getTime() - now.getTime();
  if (ms <= 0) return { text: 'приём завершён', tone: 'closed' };
  const days = Math.floor(ms / 86400000);
  if (days === 0) return { text: 'последний день', tone: 'urgent' };
  return { text: `осталось ${days} ${plural(days, 'день', 'дня', 'дней')}`, tone: days <= 3 ? 'urgent' : 'normal' };
}

/** Возраст организации в полных годах */
export function yearsSince(value: string | null | undefined, now: Date = new Date()): number | null {
  const d = parseDate(value);
  if (!d) return null;
  let years = now.getFullYear() - d.getFullYear();
  if (now.getMonth() < d.getMonth() || (now.getMonth() === d.getMonth() && now.getDate() < d.getDate())) years--;
  return years;
}

/** 1 год, 2 года, 5 лет */
export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

/** Вклад правила в итог: «+12», «−8», «0» */
export function formatContribution(n: number): string {
  const r = Math.round(n * 10) / 10;
  if (r === 0) return '0';
  return (r > 0 ? '+' : '−') + String(Math.abs(r)).replace('.', ',');
}

export function formatFileSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return formatNumber(bytes / 1024 / 1024, 1) + NBSP + 'МБ';
  return formatNumber(Math.max(1, Math.round(bytes / 1024)), 0) + NBSP + 'КБ';
}
