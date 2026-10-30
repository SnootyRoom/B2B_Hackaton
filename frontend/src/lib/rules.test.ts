import { describe, expect, it } from 'vitest';
import type { ScoringRule } from '../api/types';
import { describeRule, newRule, validateProfile, validateRule } from './rules';
import { FIELDS } from './catalog';

const clean = (s: string) => s.replace(/ /g, ' ');

const rule = (patch: Partial<ScoringRule>): ScoringRule => ({ ...newRule('nmck'), ...patch });

describe('человеческая формулировка правила', () => {
  it('диапазон денег', () => {
    expect(clean(describeRule({ field: 'nmck', operator: 'between', value: [500000, 15000000] }))).toBe(
      'Начальная цена (НМЦК) от 500 000 ₽ до 15 000 000 ₽',
    );
  });
  it('мультивыбор показывает названия, а не коды', () => {
    expect(describeRule({ field: 'method', operator: 'in', value: ['auction', 'quotation'] })).toBe(
      'Способ закупки: электронный аукцион или запрос котировок',
    );
  });
  it('единицы склоняются', () => {
    expect(clean(describeRule({ field: 'days_to_deadline', operator: 'gte', value: 5 }))).toBe('Срок на подачу заявки не меньше 5 дней');
    expect(clean(describeRule({ field: 'customer.age_years', operator: 'gte', value: 1 }))).toBe('Возраст заказчика не меньше 1 года');
    expect(clean(describeRule({ field: 'delivery_days', operator: 'between', value: [3, 10] }))).toBe('Срок поставки от 3 до 10 дней');
  });
  it('без технических терминов', () => {
    const text = describeRule({ field: 'customer.has_unreliable_flags', operator: 'is_false', value: null });
    expect(text).not.toMatch(/customer|flags|is_false/);
  });
});

describe('проверки при сохранении (аналитика)', () => {
  it('у between левая граница не больше правой', () => {
    expect(validateRule(rule({ operator: 'between', value: [10, 5] }))).toMatch(/не больше/);
    expect(validateRule(rule({ operator: 'between', value: [5, 10] }))).toBeNull();
  });
  it('мультивыбор не пустой', () => {
    expect(validateRule({ ...newRule('method'), value: [] })).not.toBeNull();
  });
  it('оператор допустим для поля', () => {
    expect(validateRule(rule({ operator: 'in', value: ['1'] }))).not.toBeNull();
  });
  it('пороги и веса групп', () => {
    const base = {
      name: 'п',
      company_description: '',
      source_text: '',
      rules: [],
      group_weights: { procurement: 0, fit: 0, customer: 0 },
      thresholds: { participate: 40, consider: 70 },
    };
    expect(validateProfile(base)).toHaveLength(2);
  });
  it('каждое поле каталога создаёт правило без ошибок формулировки', () => {
    FIELDS.forEach((f) => expect(newRule(f.key).label.length).toBeGreaterThan(3));
  });
});
