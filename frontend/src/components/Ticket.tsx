// «Билет» закупки для сортировочного стола: слева оценка, справа — отрывная часть с данными.

import { Link } from 'react-router-dom';
import type { ResultRow } from '../api/types';
import { deadlineInfo, formatMoneyShort } from '../lib/format';
import { toneOf } from './ui';

const DEADLINE_TONE = {
  normal: 'bg-track text-ink',
  urgent: 'bg-bad-soft text-bad',
  closed: 'bg-track text-muted',
} as const;

/** notchClass — цвет фона под билетом: «вырезы» перфорации закрашиваются им */
export default function Ticket({ row, notchClass, index = 0 }: { row: ResultRow; notchClass: string; index?: number }) {
  const tone = toneOf(row.recommendation);
  const dl = deadlineInfo(row.application_deadline);

  return (
    <Link
      to={`/procurements/${row.procurement_id}`}
      className="group animate-rise relative flex rounded-2xl bg-white text-ink shadow-[0_1px_0_rgba(29,31,39,0.04),0_8px_18px_-10px_rgba(29,31,39,0.2)] transition-[transform,box-shadow] hover:-translate-y-0.5 hover:shadow-[0_1px_0_rgba(29,31,39,0.04),0_16px_28px_-14px_rgba(214,32,47,0.3)]"
      style={{ animationDelay: `${Math.min(index, 10) * 50}ms` }}
    >
      {/* Корешок с оценкой */}
      <div className="flex w-20 shrink-0 flex-col items-center justify-center border-r-2 border-dashed border-line py-3.5 sm:w-[86px]">
        <span className={`font-display text-2xl leading-none font-bold sm:text-[28px] ${tone.text}`}>
          {row.total}
          <span className="text-sm">%</span>
        </span>
        <span className="mt-1 text-[11px] text-muted">оценка</span>
      </div>
      {/* Полукруглые вырезы перфорации */}
      <span aria-hidden className={`absolute -top-2 left-[72px] h-4 w-4 rounded-full sm:left-[78px] ${notchClass}`} />
      <span aria-hidden className={`absolute -bottom-2 left-[72px] h-4 w-4 rounded-full sm:left-[78px] ${notchClass}`} />

      <div className="flex min-w-0 flex-1 flex-col gap-1.5 px-4 py-3.5">
        <div className={`line-clamp-2 font-semibold leading-snug ${row.has_stop_factor ? 'pr-14' : ''}`}>{row.subject}</div>
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-sm text-muted">
          <span className="font-semibold text-ink tabular-nums">{formatMoneyShort(row.nmck)}</span>
          {row.region && <span>{row.region}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[13px]">
          <span className={`rounded-md px-2 py-0.5 font-semibold ${DEADLINE_TONE[dl.tone]}`}>{dl.text}</span>
          {row.reason && <span className="text-muted">{row.reason}</span>}
          {row.incomplete && <span className="text-muted">· оценка неполная</span>}
        </div>
      </div>

      {row.has_stop_factor && (
        <span
          className="absolute top-3 right-3 -rotate-[8deg] rounded-md border-2 border-brand px-1.5 py-0.5 font-display text-[11px] font-bold tracking-wider text-brand"
          title="Сработал стоп-фактор"
        >
          СТОП
        </span>
      )}
    </Link>
  );
}
