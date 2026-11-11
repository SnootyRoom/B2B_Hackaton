// Выгрузка текущей выборки результатов: файл собирается в браузере.

import type { CompareRow, ResultRow } from '../api/types';
import { RECOMMENDATION } from './catalog';

const toCsv = (rows: string[][]) =>
  // BOM — чтобы Excel открыл кириллицу правильно
  new Blob(['\ufeff' + rows.map((l) => l.map((v) => `"${v.replace(/"/g, '""')}"`).join(';')).join('\n')], {
    type: 'text/csv;charset=utf-8',
  });

const CHANGE_LABEL = {
  better: 'стало лучше',
  worse: 'стало хуже',
  same: 'без изменений',
  unknown: 'нет оценки',
} as const;

/** Сравнение двух профилей в CSV */
export function buildCompareCsv(rows: CompareRow[], nameA: string, nameB: string): Blob {
  const rec = (r: CompareRow['a']) => (r.recommendation ? RECOMMENDATION[r.recommendation].label : '');
  return toCsv([
    [
      'Реестровый номер',
      'Предмет',
      'Заказчик',
      'НМЦК',
      `Оценка «${nameA}»`,
      `Рекомендация «${nameA}»`,
      `Оценка «${nameB}»`,
      `Рекомендация «${nameB}»`,
      'Изменение',
      'Разница',
      'Почему',
    ],
    ...rows.map((r) => [
      r.reg_number,
      r.subject,
      r.customer_name ?? '',
      String(r.nmck),
      r.a.total === null ? '' : String(r.a.total),
      rec(r.a),
      r.b.total === null ? '' : String(r.b.total),
      rec(r.b),
      CHANGE_LABEL[r.change],
      r.delta === null ? '' : String(r.delta),
      r.explanation,
    ]),
  ]);
}

export function buildExport(format: 'csv' | 'json', rows: ResultRow[]): Blob {
  if (format === 'json') return new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json' });
  const head = [
    'Реестровый номер',
    'Предмет',
    'Заказчик',
    'НМЦК',
    'Регион',
    'Окончание подачи',
    'Оценка',
    'Рекомендация',
  ];
  const lines = rows.map((r) => [
    r.reg_number,
    r.subject,
    r.customer_name ?? '',
    String(r.nmck),
    r.region ?? '',
    r.application_deadline ?? '',
    r.total === null ? '' : String(r.total),
    r.recommendation ? RECOMMENDATION[r.recommendation].label : 'пересчитывается',
  ]);
  const csv = [head, ...lines].map((l) => l.map((v) => `"${v.replace(/"/g, '""')}"`).join(';')).join('\n');
  // BOM — чтобы Excel открыл кириллицу правильно
  return new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
}
