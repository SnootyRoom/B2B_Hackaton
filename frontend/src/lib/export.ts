// Выгрузка текущей выборки результатов: файл собирается в браузере.

import type { ResultRow } from '../api/types';
import { RECOMMENDATION } from './catalog';

export function buildExport(format: 'csv' | 'json', rows: ResultRow[]): Blob {
  if (format === 'json') return new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json' });
  const head = ['Реестровый номер', 'Предмет', 'Заказчик', 'НМЦК', 'Регион', 'Окончание подачи', 'Оценка', 'Рекомендация'];
  const lines = rows.map((r) => [
    r.reg_number,
    r.subject,
    r.customer_name ?? '',
    String(r.nmck),
    r.region ?? '',
    r.application_deadline ?? '',
    String(r.total),
    RECOMMENDATION[r.recommendation].label,
  ]);
  const csv = [head, ...lines].map((l) => l.map((v) => `"${v.replace(/"/g, '""')}"`).join(';')).join('\n');
  // BOM — чтобы Excel открыл кириллицу правильно
  return new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
}
