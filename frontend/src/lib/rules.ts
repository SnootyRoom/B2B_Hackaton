// Работа с правилами в интерфейсе: человеческая формулировка, новое правило, проверки.
// Сами баллы считает бэкенд (роль 3) — фронтенд оценку не вычисляет.

import type { Operator, RuleValue, ScoringProfileInput, ScoringRule } from '../api/types';
import { FIELD_BY_KEY, type FieldDef } from './catalog';
import { formatMoney, formatNumber, plural } from './format';

export function newRuleId(): string {
  return 'u' + Math.random().toString(36).slice(2, 10);
}

function optionLabel(field: FieldDef, value: string): string {
  const label = field.options?.find((o) => o.value === value)?.label ?? value;
  // Посреди предложения — со строчной: «способ закупки: электронный аукцион». Регионы не трогаем.
  return field.properNames ? label : label.charAt(0).toLowerCase() + label.slice(1);
}

/** «a, b или c» */
function joinOr(items: string[]): string {
  if (items.length <= 1) return items.join('');
  return items.slice(0, -1).join(', ') + ' или ' + items[items.length - 1];
}

function listItems(field: FieldDef, value: RuleValue): string[] {
  const arr = Array.isArray(value) ? (value as (string | number)[]).map(String) : [];
  return arr.map((v) => (field.options ? optionLabel(field, v) : v));
}

function listText(field: FieldDef, value: RuleValue): string {
  const items = listItems(field, value);
  return items.length ? items.join(', ') : '(ничего не выбрано)';
}

const NBSP = '\u00a0';

/** Число с единицей: «5 дней», «1 года», «10 % от НМЦК», «4 200 000 ₽» */
function numText(field: FieldDef, n: unknown, withUnit = true): string {
  if (typeof n !== 'number' || !Number.isFinite(n)) return '?';
  if (field.valueType === 'money') return formatMoney(n);
  const num = formatNumber(n);
  if (!withUnit) return num;
  if (field.unitForms) return num + NBSP + plural(Math.round(n), ...field.unitForms);
  return num + (field.unit ? NBSP + field.unit : '');
}

/** «НМЦК от 1 000 000 ₽ до 10 000 000 ₽», «Способ закупки: Электронный аукцион или Запрос котировок» */
export function describeRule(rule: Pick<ScoringRule, 'field' | 'operator' | 'value'>): string {
  const field = FIELD_BY_KEY[rule.field];
  if (!field) return rule.field;
  const v = rule.value;
  switch (rule.operator) {
    case 'between': {
      const [a, b] = Array.isArray(v) ? (v as number[]) : [];
      // Единицу пишем один раз в конце: «от 3 до 10 дней»; деньги — у каждого числа
      return `${field.label} от ${numText(field, a, field.valueType === 'money')} до ${numText(field, b)}`;
    }
    case 'gte':
      return `${field.label} не меньше ${numText(field, v)}`;
    case 'lte':
      return `${field.label} не больше ${numText(field, v)}`;
    case 'in': {
      const items = listItems(field, v);
      return `${field.label}: ${items.length ? joinOr(items) : '(ничего не выбрано)'}`;
    }
    case 'not_in':
      return `${field.label} — любой, кроме: ${listText(field, v)}`;
    case 'any_in':
      return `${field.label}: есть ${joinOr(listItems(field, v).map((x) => `«${x}»`)) || '(ничего не выбрано)'}`;
    case 'none_in':
      return `${field.label}: нет ${joinOr(listItems(field, v).map((x) => `«${x}»`)) || '(ничего не выбрано)'}`;
    case 'prefix_in':
      return `${field.label} начинаются с ${listText(field, v)}`;
    case 'is_false':
      return field.falseLabel ?? `Нет: ${field.label.charAt(0).toLowerCase()}${field.label.slice(1)}`;
    case 'semantic_match':
      return `${field.label} по смыслу похож на «${typeof v === 'string' ? v : ''}»`;
    case 'contains_any':
      return `${field.label} содержит любое из слов: ${listText(field, v)}`;
  }
}

/** Пустое значение подходящего вида для пары «поле + оператор» */
export function emptyValue(field: FieldDef, operator: Operator): RuleValue {
  if (operator === 'is_false') return null;
  if (operator === 'between') return [0, 0];
  if (operator === 'semantic_match') return '';
  if (field.valueType === 'enum' || field.valueType === 'codes' || field.valueType === 'words') return [];
  if (operator === 'contains_any') return [];
  return 0;
}

export function newRule(fieldKey: string): ScoringRule {
  const field = FIELD_BY_KEY[fieldKey];
  if (!field) throw new Error('Неизвестное поле ' + fieldKey);
  const operator = field.operators[0] as Operator;
  const value = emptyValue(field, operator);
  return {
    id: newRuleId(),
    group: field.group,
    kind: 'weighted',
    field: field.key,
    operator,
    value,
    weight: 2,
    soft_margin: null,
    label: describeRule({ field: field.key, operator, value }),
    enabled: true,
  };
}

/** Текст проблемы правила или null, если всё в порядке (проверки из аналитики) */
export function validateRule(rule: ScoringRule): string | null {
  const field = FIELD_BY_KEY[rule.field];
  if (!field) return 'Это поле больше не поддерживается — удалите правило';
  if (!field.operators.includes(rule.operator)) return 'Такое условие нельзя задать для этого поля';
  const v = rule.value;
  switch (rule.operator) {
    case 'between': {
      const [a, b]: unknown[] = Array.isArray(v) ? v : [];
      if (typeof a !== 'number' || typeof b !== 'number' || !Number.isFinite(a) || !Number.isFinite(b))
        return 'Укажите обе границы';
      if (a > b) return '«От» должно быть не больше «до»';
      if (a < 0) return 'Значение не может быть отрицательным';
      return null;
    }
    case 'gte':
    case 'lte':
      if (typeof v !== 'number' || !Number.isFinite(v)) return 'Укажите число';
      if (v < 0) return 'Значение не может быть отрицательным';
      return null;
    case 'semantic_match':
      return typeof v === 'string' && v.trim().length >= 3 ? null : 'Опишите, что вы поставляете';
    case 'is_false':
      return null;
    default:
      return Array.isArray(v) && v.length > 0 ? null : 'Выберите хотя бы одно значение';
  }
}

export function validateProfile(p: ScoringProfileInput): string[] {
  const errors: string[] = [];
  const w = p.group_weights;
  if (w.procurement + w.fit + w.customer <= 0) errors.push('Хотя бы у одной группы вес должен быть больше нуля');
  if (p.thresholds.consider >= p.thresholds.participate)
    errors.push('Порог «Рассмотреть» должен быть ниже порога «Участвовать»');
  p.rules.forEach((r) => {
    if (!r.enabled) return;
    const e = validateRule(r);
    if (e) errors.push(`${r.label}: ${e}`);
  });
  return errors;
}

export const WEIGHT_LABEL: Record<1 | 2 | 3, string> = { 1: 'низкая', 2: 'средняя', 3: 'высокая' };
