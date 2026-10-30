import { describe, expect, it } from 'vitest';
import { formatContribution, formatDate, formatMoney, formatMoneyShort, plural, yearsSince } from './format';

const clean = (s: string) => s.replace(/\u00a0/g, ' ');

describe('суммы (CLAUDE.md: «4 200 000 ₽», в таблице «4,2 млн ₽»)', () => {
  it('полная сумма с разделителями разрядов', () => {
    expect(clean(formatMoney(4200000))).toBe('4 200 000 ₽');
    expect(clean(formatMoney(1234.5))).toBe('1 234,5 ₽');
  });
  it('короткая сумма для таблицы', () => {
    expect(clean(formatMoneyShort(4200000))).toBe('4,2 млн ₽');
    expect(clean(formatMoneyShort(680000))).toBe('680 тыс. ₽');
    expect(clean(formatMoneyShort(18500000))).toBe('18,5 млн ₽');
    expect(clean(formatMoneyShort(1250000000))).toBe('1,25 млрд ₽');
  });
  it('нет данных', () => {
    expect(formatMoney(null)).toBe('нет данных');
    expect(formatMoneyShort(undefined)).toBe('—');
  });
});

describe('даты ДД.ММ.ГГГГ', () => {
  it('форматирует дату', () => {
    expect(formatDate('2026-11-10T12:00:00')).toBe('10.11.2026');
    expect(formatDate(null)).toBe('—');
  });
  it('считает возраст в полных годах', () => {
    expect(yearsSince('2020-06-15', new Date('2026-06-14'))).toBe(5);
    expect(yearsSince('2020-06-15', new Date('2026-06-15'))).toBe(6);
  });
});

describe('мелочи', () => {
  it('склоняет слова', () => {
    expect(plural(1, 'год', 'года', 'лет')).toBe('год');
    expect(plural(3, 'год', 'года', 'лет')).toBe('года');
    expect(plural(11, 'год', 'года', 'лет')).toBe('лет');
    expect(plural(22, 'год', 'года', 'лет')).toBe('года');
  });
  it('вклад правила со знаком', () => {
    expect(formatContribution(12)).toBe('+12');
    expect(formatContribution(-8)).toBe('−8');
    expect(formatContribution(4.25)).toBe('+4,3');
    expect(formatContribution(0)).toBe('0');
  });
});
