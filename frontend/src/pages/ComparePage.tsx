// «Сравнение»: одни и те же закупки, оценённые по двум профилям.
// Данные и объяснение разницы — от бэкенда (GET /results/compare). Если каких-то оценок нет,
// досчитываем их задачами POST /score {profile_id, only_stale} и показываем прогресс.

import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import type { Change, CompareRow, ProfileSummary, ScoreBrief } from '../api/types';
import { RECOMMENDATION } from '../lib/catalog';
import { buildCompareCsv } from '../lib/export';
import { formatMoneyShort, plural } from '../lib/format';
import { qk, taskIsRunning, useProfiles, useTask } from '../lib/hooks';
import { Alert, EmptyState, Loading, ProgressBar, ResultsSkeleton, toneOf } from '../components/ui';

type Filter = 'all' | 'changed' | 'better' | 'worse';
type SortMode = 'changed' | 'up' | 'down';

const SORTS: [SortMode, string, string, string][] = [
  ['changed', 'Сначала изменившиеся', '', ''],
  ['up', 'Сильнее выросла оценка', '▲', 'text-good'],
  ['down', 'Сильнее упала оценка', '▼', 'text-bad'],
];

const CHANGE_VIEW: Record<Change, { label: string; arrow: string; cls: string; row: string }> = {
  better: { label: 'Стало лучше', arrow: '▲', cls: 'text-good', row: 'bg-good-soft/45' },
  worse: { label: 'Стало хуже', arrow: '▼', cls: 'text-bad', row: 'bg-bad-soft/45' },
  same: { label: 'Без изменений', arrow: '=', cls: 'text-muted', row: '' },
  unknown: { label: 'Нет оценки', arrow: '…', cls: 'text-muted', row: '' },
};

export default function ComparePage() {
  const profiles = useProfiles();
  const [params, setParams] = useSearchParams();

  if (profiles.isPending) return <Loading text="Загружаем профили…" />;
  if (profiles.isError) return <Alert>{profiles.error.message}</Alert>;

  const list = profiles.data;
  if (list.length < 2) {
    return (
      <EmptyState
        title="Нужно хотя бы два профиля"
        text="Создайте второй профиль — например, из шаблона «Осторожный» или «Агрессивный» — и сравните, как меняются рекомендации."
      >
        <Link to="/profile" className="btn-primary">
          К профилям
        </Link>
      </EmptyState>
    );
  }

  const active = list.find((p) => p.is_active) ?? list[0]!;
  const a = list.find((p) => p.id === params.get('a')) ?? active;
  const b = list.find((p) => p.id === params.get('b') && p.id !== a.id) ?? list.find((p) => p.id !== a.id)!;
  const set = (na: string, nb: string) => setParams({ a: na, b: nb });

  return (
    <div className="flex flex-col gap-6">
      <div className="max-w-[62ch]">
        <p className="mb-2 text-[13px] font-semibold tracking-[0.08em] text-muted uppercase">
          Сравнение профилей
        </p>
        <h1 className="font-display text-[28px] leading-tight font-bold text-balance sm:text-[36px]">
          Как меняется рекомендация при смене стратегии
        </h1>
        <p className="mt-2 text-muted sm:text-base">
          Те же закупки по двум профилям. Активный профиль не меняется, загружать заново ничего не нужно.
        </p>
        <p className="mt-2 text-sm text-muted">
          Нужны просто оценки закупок по одному профилю — они на странице{' '}
          <Link
            to="/results"
            className="font-semibold text-brand underline decoration-brand/30 underline-offset-4"
          >
            «Результаты»
          </Link>
          .
        </p>
      </div>

      <div className="card flex flex-wrap items-end gap-3 p-4">
        <ProfileSelect
          id="cmp-a"
          label="Профиль A"
          value={a}
          list={list}
          onChange={(id) => set(id, id === b.id ? a.id : b.id)}
        />
        <button
          type="button"
          className="btn-ghost btn-sm mb-0.5"
          onClick={() => set(b.id, a.id)}
          title="Поменять местами"
        >
          ⇄ <span className="sm:hidden lg:inline">Поменять местами</span>
        </button>
        <ProfileSelect
          id="cmp-b"
          label="Профиль B"
          value={b}
          list={list}
          onChange={(id) => set(id === a.id ? b.id : a.id, id)}
        />
      </div>

      <CompareView key={`${a.id}:${b.id}`} a={a} b={b} />
    </div>
  );
}

function ProfileSelect(props: {
  id: string;
  label: string;
  value: ProfileSummary;
  list: ProfileSummary[];
  onChange: (id: string) => void;
}) {
  return (
    <label htmlFor={props.id} className="flex min-w-0 flex-[1_1_220px] flex-col gap-1 text-sm">
      <span className="font-semibold text-muted">{props.label}</span>
      <select
        id={props.id}
        className="input font-semibold"
        value={props.value.id}
        onChange={(e) => props.onChange(e.target.value)}
      >
        {props.list.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
            {p.is_active ? ' (активный)' : ''}
          </option>
        ))}
      </select>
    </label>
  );
}

function CompareView({ a, b }: { a: ProfileSummary; b: ProfileSummary }) {
  const cmp = useQuery({ queryKey: qk.compare(a.id, b.id), queryFn: () => api.compareProfiles(a.id, b.id) });
  const [filter, setFilter] = useState<Filter | null>(null);
  const [sort, setSort] = useState<SortMode>('changed');
  const [open, setOpen] = useState<Set<string>>(new Set());

  // Недостающие оценки досчитываем один раз; по окончании задач сравнение перезапросится само
  const [tasks, setTasks] = useState<string[]>([]);
  const [startError, setStartError] = useState<string | null>(null);
  const started = useRef(false);
  const missing = cmp.data?.missing ?? 0;
  useEffect(() => {
    if (missing === 0 || started.current) return;
    started.current = true;
    Promise.all([api.scoreStale(a.id), api.scoreStale(b.id)]).then(
      (r) => setTasks(r.map((x) => x.task_id)),
      (e: Error) => setStartError(e.message),
    );
  }, [missing, a.id, b.id]);
  const ta = useTask(tasks[0] ?? null);
  const tb = useTask(tasks[1] ?? null);
  const computing =
    tasks.length > 0 && (taskIsRunning(ta.data) || taskIsRunning(tb.data)) && !ta.isError && !tb.isError;
  const done = (ta.data?.processed ?? 0) + (tb.data?.processed ?? 0);
  const total = (ta.data?.total ?? 0) + (tb.data?.total ?? 0);

  const rows = useMemo(() => cmp.data?.rows ?? [], [cmp.data]);
  const summary = cmp.data?.summary ?? { better: 0, worse: 0, same: 0, unknown: 0 };
  const changedCount = summary.better + summary.worse;
  const current: Filter = filter ?? (changedCount > 0 ? 'changed' : 'all');

  const shown = useMemo(() => {
    const f = rows.filter(
      (r) =>
        current === 'all' ||
        (current === 'changed' && (r.change === 'better' || r.change === 'worse')) ||
        r.change === current,
    );
    if (sort === 'changed') return f; // сервер уже отдал: сначала изменившиеся, затем по |разнице|
    const d = (r: CompareRow) => r.delta ?? (sort === 'up' ? -Infinity : Infinity);
    return [...f].sort((x, y) => (sort === 'up' ? d(y) - d(x) : d(x) - d(y)));
  }, [rows, current, sort]);

  const toggle = (id: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  function exportCsv() {
    const blob = buildCompareCsv(shown, a.name, b.name);
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `сравнение-${a.name}-${b.name}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  if (cmp.isPending) return <ResultsSkeleton />;
  if (cmp.isError) return <Alert>{cmp.error.message}</Alert>;
  if (rows.length === 0) {
    return (
      <EmptyState
        title="Пока нечего сравнивать"
        text="Загрузите закупки — и здесь будет видно, как их оценивает каждый профиль."
      >
        <Link to="/upload" className="btn-primary">
          Загрузить закупки
        </Link>
      </EmptyState>
    );
  }

  return (
    <>
      {(computing || (missing > 0 && tasks.length === 0 && !startError)) && (
        <section className="card flex flex-col gap-2.5" role="status">
          <span className="font-semibold">
            Досчитываем оценки по двум профилям{total > 0 ? `: ${done} из ${total}` : '…'}
          </span>
          <ProgressBar value={done} max={total || 1} />
          <span className="text-sm text-muted">
            Закупки уже загружены — заново ничего не скачивается. Строки обновятся сами.
          </span>
        </section>
      )}
      {startError && <Alert>Не удалось досчитать оценки: {startError}</Alert>}
      <div
        role="tablist"
        aria-label="Какие закупки показать"
        className="grid grid-cols-2 gap-2 sm:grid-cols-4 sm:gap-3"
      >
        <SummaryTab
          on={current === 'changed'}
          onClick={() => setFilter('changed')}
          n={changedCount}
          label="Только где отличается"
          tone="text-brand"
        />
        <SummaryTab
          on={current === 'better'}
          onClick={() => setFilter('better')}
          n={summary.better}
          label="Стало лучше"
          tone="text-good"
          icon="▲"
        />
        <SummaryTab
          on={current === 'worse'}
          onClick={() => setFilter('worse')}
          n={summary.worse}
          label="Стало хуже"
          tone="text-bad"
          icon="▼"
        />
        <SummaryTab
          on={current === 'all'}
          onClick={() => setFilter('all')}
          n={rows.length}
          label="Все закупки"
          tone="text-ink"
        />
      </div>
      <p className="-mt-2 text-sm text-muted">
        От «{a.name}» к «{b.name}»: стало лучше — <b className="text-good">{summary.better}</b>, стало хуже —{' '}
        <b className="text-bad">{summary.worse}</b>, без изменений — <b>{summary.same}</b>
        {summary.unknown > 0 && (
          <>
            , пока без оценки — <b>{summary.unknown}</b>
          </>
        )}
        .
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <span id="cmp-sort-label" className="mr-1 text-sm font-semibold text-muted">
          Порядок:
        </span>
        <div role="radiogroup" aria-labelledby="cmp-sort-label" className="flex flex-wrap gap-2">
          {SORTS.map(([key, label, icon, tone]) => {
            const on = sort === key;
            return (
              <button
                key={key}
                type="button"
                role="radio"
                aria-checked={on}
                onClick={() => setSort(key)}
                className={
                  'flex min-h-11 items-center gap-2 rounded-2xl px-4 py-2 text-sm font-semibold transition-all ' +
                  (on
                    ? 'bg-brand text-white shadow-[0_10px_22px_-12px_rgba(214,32,47,0.7)]'
                    : 'bg-white ring-1 ring-line hover:ring-brand/50')
                }
              >
                {icon && <span className={on ? 'text-white' : tone}>{icon}</span>}
                {label}
              </button>
            );
          })}
        </div>
        <button type="button" className="btn-ghost ml-auto" onClick={exportCsv} disabled={shown.length === 0}>
          Скачать для Excel
        </button>
      </div>

      {shown.length === 0 ? (
        <EmptyState title="Таких закупок нет" text="Попробуйте другой фильтр.">
          <button type="button" className="btn-ghost" onClick={() => setFilter('all')}>
            Показать все
          </button>
        </EmptyState>
      ) : (
        <>
          <div className="hidden overflow-x-auto rounded-3xl bg-white shadow-[0_1px_0_rgba(29,31,39,0.04),0_12px_28px_-18px_rgba(29,31,39,0.25)] md:block">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="bg-brand-tint text-left text-xs text-muted">
                  <Th className="pl-5">Закупка</Th>
                  <Th className="text-right">НМЦК</Th>
                  <Th>Заказчик</Th>
                  <Th>A · {a.name}</Th>
                  <Th className="px-1 text-center">
                    <span className="sr-only">Изменение</span>
                  </Th>
                  <Th>B · {b.name}</Th>
                  <Th className="pr-5 text-right">Разница</Th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r, i) => {
                  const v = CHANGE_VIEW[r.change];
                  const isOpen = open.has(r.procurement_id);
                  return (
                    <Fragment key={r.procurement_id}>
                      <tr
                        className={`animate-rise border-b border-track transition-colors ${v.row} ${isOpen ? 'border-b-0' : ''}`}
                        style={{ animationDelay: `${Math.min(i, 12) * 30}ms` }}
                      >
                        <td className="max-w-[300px] py-3.5 pr-3 pl-5">
                          <Link
                            to={`/procurements/${r.procurement_id}`}
                            className="line-clamp-2 font-semibold hover:underline hover:underline-offset-4"
                          >
                            {r.subject}
                          </Link>
                          <div className="mt-0.5 font-mono text-xs text-muted">№ {r.reg_number}</div>
                        </td>
                        <td className="px-3 py-3.5 text-right font-semibold whitespace-nowrap tabular-nums">
                          {formatMoneyShort(r.nmck)}
                        </td>
                        <td className="max-w-[200px] px-3 py-3.5">
                          <span className="line-clamp-2">{r.customer_name ?? '—'}</span>
                        </td>
                        <td className="px-3 py-3.5">
                          <ScoreCell s={r.a} />
                        </td>
                        <td
                          className={`px-1 py-3.5 text-center text-base font-bold ${v.cls}`}
                          title={v.label}
                        >
                          <span aria-hidden>{v.arrow}</span>
                          <span className="sr-only">{v.label}</span>
                        </td>
                        <td className="px-3 py-3.5">
                          <ScoreCell s={r.b} />
                        </td>
                        <td className="px-3 py-3.5 pr-5 text-right">
                          <div className="flex flex-col items-end gap-1">
                            <Delta value={r.delta} />
                            {r.explanation && (
                              <button
                                type="button"
                                aria-expanded={isOpen}
                                className="text-xs font-semibold text-brand underline decoration-brand/30 underline-offset-4"
                                onClick={() => toggle(r.procurement_id)}
                              >
                                {isOpen ? 'Скрыть' : 'Почему?'}
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className={`border-b border-track ${v.row}`}>
                          <td colSpan={7} className="px-5 pb-4">
                            <Explanation text={r.explanation} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="flex flex-col gap-3 md:hidden">
            {shown.map((r) => {
              const v = CHANGE_VIEW[r.change];
              const isOpen = open.has(r.procurement_id);
              return (
                <div key={r.procurement_id} className={`card flex flex-col gap-3 p-4 ${v.row}`}>
                  <div>
                    <Link to={`/procurements/${r.procurement_id}`} className="line-clamp-2 font-semibold">
                      {r.subject}
                    </Link>
                    <div className="mt-0.5 text-xs text-muted">
                      № {r.reg_number} · {formatMoneyShort(r.nmck)}
                      {r.customer_name ? ` · ${r.customer_name}` : ''}
                    </div>
                  </div>
                  <div className="flex items-end gap-3">
                    <dl className="grid min-w-0 flex-1 grid-cols-[auto_1fr] items-center gap-x-2.5 gap-y-1.5">
                      <dt className="text-xs font-bold text-muted">A</dt>
                      <dd>
                        <ScoreCell s={r.a} />
                      </dd>
                      <dt className="text-xs font-bold text-muted">B</dt>
                      <dd>
                        <ScoreCell s={r.b} />
                      </dd>
                    </dl>
                    <div className="flex flex-col items-end gap-1">
                      <span className={`text-xs font-bold ${v.cls}`}>
                        {v.arrow} {v.label}
                      </span>
                      <Delta value={r.delta} />
                    </div>
                  </div>
                  {r.explanation && (
                    <>
                      <button
                        type="button"
                        aria-expanded={isOpen}
                        className="self-start text-sm font-semibold text-brand underline decoration-brand/30 underline-offset-4"
                        onClick={() => toggle(r.procurement_id)}
                      >
                        {isOpen ? 'Скрыть объяснение' : 'Почему так?'}
                      </button>
                      {isOpen && <Explanation text={r.explanation} />}
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </>
  );
}

function Th({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <th
      scope="col"
      className={`border-b border-track px-3 py-3.5 font-semibold tracking-[0.06em] uppercase ${className}`}
    >
      {children}
    </th>
  );
}

function SummaryTab(props: {
  on: boolean;
  onClick: () => void;
  n: number;
  label: string;
  tone: string;
  icon?: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={props.on}
      onClick={props.onClick}
      className={
        'flex min-h-14 items-center gap-2.5 rounded-2xl px-4 py-2.5 text-left transition-all ' +
        (props.on
          ? 'bg-brand text-white shadow-[0_10px_22px_-12px_rgba(214,32,47,0.7)]'
          : 'bg-white ring-1 ring-line hover:ring-brand/50')
      }
    >
      <span
        className={`font-display text-2xl font-bold tabular-nums ${props.on ? 'text-white' : props.tone}`}
      >
        {props.icon && <span className="mr-1 text-base">{props.icon}</span>}
        {props.n}
      </span>
      <span className="text-sm leading-tight font-semibold">{props.label}</span>
    </button>
  );
}

function ScoreCell({ s }: { s: ScoreBrief }) {
  if (s.total === null || !s.recommendation) {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm font-semibold whitespace-nowrap text-brand">
        <span
          className="h-3 w-3 animate-spin rounded-full border-2 border-brand/30 border-t-brand"
          aria-hidden
        />
        пересчитывается
      </span>
    );
  }
  const tone = toneOf(s.recommendation);
  return (
    <span
      className={`inline-flex items-center gap-2 whitespace-nowrap ${s.stale ? 'opacity-50' : ''}`}
      title={s.stale ? 'Оценка устарела — пересчитывается' : undefined}
    >
      <b className={`font-display text-lg tabular-nums ${tone.text}`}>
        {s.total}
        <span className="text-xs">%</span>
      </b>
      <span className={`rounded-full px-2.5 py-0.5 text-[13px] font-bold ${tone.bg} ${tone.text}`}>
        {RECOMMENDATION[s.recommendation].label}
      </span>
    </span>
  );
}

function Delta({ value }: { value: number | null }) {
  if (value === null) return <span className="text-muted">—</span>;
  if (value === 0) return <span className="text-muted">0</span>;
  const up = value > 0;
  return (
    <b className={`font-display tabular-nums whitespace-nowrap ${up ? 'text-good' : 'text-bad'}`}>
      {up ? '+' : '−'}
      {Math.abs(value)}
      <span className="sr-only"> {plural(Math.abs(value), 'балл', 'балла', 'баллов')}</span>
    </b>
  );
}

/** Объяснение разницы: ссылки на правила [rule_id] показываем аккуратными метками */
function Explanation({ text }: { text: string }) {
  const parts = text.split(/(\[[^\]]+\])/g).filter(Boolean);
  return (
    <p className="rounded-xl bg-white/80 px-4 py-3 text-sm leading-relaxed ring-1 ring-line/70">
      <b className="mr-1">Почему:</b>
      {parts.map((p, i) =>
        /^\[[^\]]+\]$/.test(p) ? (
          <span key={i} className="mx-0.5 rounded bg-track px-1 py-px font-mono text-[11px] text-muted">
            {p.slice(1, -1)}
          </span>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        ),
      )}
    </p>
  );
}
