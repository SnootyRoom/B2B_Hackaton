// Экран «Результаты»: итог одной фразой, таблица закупок (как требует ТЗ) с сортировкой по любому столбцу.
// На телефоне вместо строк таблицы — «билеты».

import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, USE_MOCK } from '../api';
import { mockExport } from '../api/mock';
import type { Law, Recommendation, ResultRow, ResultsFilters } from '../api/types';
import { LAW_LABEL, RECOMMENDATION } from '../lib/catalog';
import { deadlineInfo, formatDate, formatMoneyShort, plural, toNumber } from '../lib/format';
import { qk, taskIsRunning, useTask } from '../lib/hooks';
import { Alert, EmptyState, ProgressBar, ResultsSkeleton, toneOf } from '../components/ui';
import Ticket from '../components/Ticket';

type SortKey = 'total' | 'subject' | 'customer_name' | 'nmck' | 'region' | 'application_deadline';
type Sort = { key: SortKey; dir: 'asc' | 'desc' };

const COLUMNS: { key: SortKey; label: string; className?: string }[] = [
  { key: 'total', label: 'Оценка', className: 'w-40 pl-5' },
  { key: 'subject', label: 'Закупка', className: 'min-w-64' },
  { key: 'customer_name', label: 'Заказчик', className: 'min-w-44' },
  { key: 'nmck', label: 'НМЦК', className: 'text-right' },
  { key: 'region', label: 'Регион' },
  { key: 'application_deadline', label: 'Подать до' },
];

const SORTS: { value: string; label: string; sort: Sort }[] = [
  { value: 'best', label: 'Сначала лучшие', sort: { key: 'total', dir: 'desc' } },
  { value: 'worst', label: 'Сначала худшие', sort: { key: 'total', dir: 'asc' } },
  { value: 'cheap', label: 'Сначала дешёвые', sort: { key: 'nmck', dir: 'asc' } },
  { value: 'expensive', label: 'Сначала дорогие', sort: { key: 'nmck', dir: 'desc' } },
  { value: 'deadline', label: 'Сначала скорый срок подачи', sort: { key: 'application_deadline', dir: 'asc' } },
  { value: 'deadline_late', label: 'Сначала поздний срок подачи', sort: { key: 'application_deadline', dir: 'desc' } },
];

/** «2026-11-05» для поля даты */
const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const addDays = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return isoDay(d);
};
/** Быстрые варианты срока подачи */
const DEADLINE_PRESETS: { label: string; days: number }[] = [
  { label: '3 дня', days: 3 },
  { label: 'Неделя', days: 7 },
  { label: 'Месяц', days: 30 },
];

const time = (s: string | null) => (s ? new Date(s).getTime() : Infinity);

function compare(a: ResultRow, b: ResultRow, key: SortKey): number {
  if (key === 'total') return a.total - b.total;
  if (key === 'nmck') return (toNumber(a.nmck) ?? 0) - (toNumber(b.nmck) ?? 0);
  if (key === 'application_deadline') return time(a.application_deadline) - time(b.application_deadline);
  return String(a[key] ?? '').localeCompare(String(b[key] ?? ''), 'ru');
}

/** Фон под «билетами» на телефоне — им же закрашиваются вырезы перфорации */
const TICKET_BG: Record<Recommendation, string> = {
  participate: 'bg-good-soft',
  consider: 'bg-mid-soft',
  skip: 'bg-bad-soft',
};

const DEADLINE_TONE = {
  normal: 'text-muted',
  urgent: 'font-semibold text-bad',
  closed: 'text-muted line-through decoration-muted/50',
} as const;

export default function ResultsPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const rescoreTask = params.get('task');
  /** Пришли из «Истории»: показываем только закупки одной загрузки */
  const uploadId = params.get('upload');
  const uploads = useQuery({ queryKey: qk.uploads, queryFn: () => api.listUploads(), enabled: Boolean(uploadId) });
  const upload = uploads.data?.find((t) => t.id === uploadId);
  const task = useTask(rescoreTask);

  // Фильтры, которые применяет сервер; рекомендацию и поиск — здесь, чтобы счётчики были по всей выборке
  const [filters, setFilters] = useState<Omit<ResultsFilters, 'recommendation'>>({});
  const [rec, setRec] = useState<Recommendation | null>(null);
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<Sort>({ key: 'total', dir: 'desc' });
  const [showFilters, setShowFilters] = useState(false);
  /** Окончание подачи заявок: с / по (ГГГГ-ММ-ДД). Фильтруем прямо в браузере */
  const [deadlineFrom, setDeadlineFrom] = useState('');
  const [deadlineTo, setDeadlineTo] = useState('');

  const serverFilters = useMemo(() => ({ ...filters, upload_id: uploadId ?? undefined }), [filters, uploadId]);
  const results = useQuery({ queryKey: qk.results(serverFilters), queryFn: () => api.getResults(serverFilters) });
  // Полный список — для итогов наверху и списка регионов
  const all = useQuery({ queryKey: qk.results({}), queryFn: () => api.getResults({}) });

  const searched = useMemo(() => {
    const q = query.trim().toLowerCase();
    const from = deadlineFrom ? new Date(deadlineFrom + 'T00:00:00').getTime() : -Infinity;
    const to = deadlineTo ? new Date(deadlineTo + 'T23:59:59').getTime() : Infinity;
    return (results.data ?? [])
      .filter((r) => !q || [r.subject, r.customer_name, r.reg_number].some((v) => v?.toLowerCase().includes(q)))
      .filter((r) => {
        if (!deadlineFrom && !deadlineTo) return true;
        if (!r.application_deadline) return false;
        const t = new Date(r.application_deadline).getTime();
        return t >= from && t <= to;
      });
  }, [results.data, query, deadlineFrom, deadlineTo]);

  const counts = useMemo(() => {
    const c = { all: searched.length, participate: 0, consider: 0, skip: 0 };
    searched.forEach((r) => c[r.recommendation]++);
    return c;
  }, [searched]);

  const shown = useMemo(
    () =>
      searched
        .filter((r) => !rec || r.recommendation === rec)
        .sort((a, b) => (sort.dir === 'asc' ? 1 : -1) * compare(a, b, sort.key)),
    [searched, rec, sort],
  );

  const regions = useMemo(
    () => [...new Set((all.data ?? []).map((r) => r.region).filter((r): r is string => Boolean(r)))].sort(),
    [all.data],
  );
  const activeFilterCount =
    Object.values(filters).filter((v) => v !== undefined && v !== false).length + (deadlineFrom || deadlineTo ? 1 : 0);
  const resetFilters = () => {
    setFilters({});
    setDeadlineFrom('');
    setDeadlineTo('');
  };

  function toggleSort(key: SortKey) {
    setSort((s) =>
      s.key === key
        ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: key === 'total' || key === 'nmck' ? 'desc' : 'asc' },
    );
  }

  async function exportAs(format: 'csv' | 'json') {
    if (!USE_MOCK) {
      window.location.href = api.exportUrl(format, {
        ...filters,
        recommendation: rec ?? undefined,
        deadline_from: deadlineFrom || undefined,
        deadline_to: deadlineTo || undefined,
      });
      return;
    }
    const blob = await mockExport(format, shown);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `закупки.${format}`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const rescoreBanner = rescoreTask && (
    <section className="card flex flex-col gap-2">
      {taskIsRunning(task.data) ? (
        <>
          <span className="font-semibold">
            Пересчитываем оценки по новым параметрам: {task.data?.processed ?? 0} из {task.data?.total ?? '…'}
          </span>
          <ProgressBar value={task.data?.processed ?? 0} max={task.data?.total ?? 1} />
        </>
      ) : (
        <div className="flex items-center justify-between gap-3">
          <span className="font-semibold text-good">Оценки пересчитаны по новым параметрам</span>
          <button type="button" className="btn-ghost btn-sm" onClick={() => setParams({})}>
            Скрыть
          </button>
        </div>
      )}
    </section>
  );

  if (results.isPending) return <ResultsSkeleton />;
  if (results.isError) return <Alert>{results.error.message}</Alert>;

  const total = all.data ?? [];
  if (total.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        {rescoreBanner}
        <EmptyState title="Пока нет закупок" text="Загрузите файлы или попробуйте пример — здесь появятся оценки.">
          <Link to="/upload" className="btn-primary">
            Загрузить закупки
          </Link>
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {rescoreBanner}
      <Summary rows={total} />

      {uploadId && (
        <div className="animate-rise flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-brand-tint px-4 py-3 ring-1 ring-brand/20">
          <span className="text-sm">
            Показаны только закупки из загрузки
            {upload && (
              <b>
                {' '}
                от {formatDate(upload.created_at)}, {new Date(upload.created_at).toTimeString().slice(0, 5)}
              </b>
            )}
          </span>
          <div className="flex gap-2">
            <Link to="/history" className="btn-ghost btn-sm">
              ← К истории
            </Link>
            <button type="button" className="btn-ghost btn-sm" onClick={() => setParams({})}>
              Показать все
            </button>
          </div>
        </div>
      )}

      {/* Счётчики — они же фильтр по рекомендации */}
      <div role="tablist" aria-label="Рекомендация" className="grid grid-cols-2 gap-2 sm:grid-cols-4 sm:gap-3">
        {(
          [
            [null, 'Все закупки', counts.all],
            ['participate', RECOMMENDATION.participate.label, counts.participate],
            ['consider', RECOMMENDATION.consider.label, counts.consider],
            ['skip', RECOMMENDATION.skip.label, counts.skip],
          ] as const
        ).map(([key, label, n]) => {
          const on = rec === key;
          const tone = key ? toneOf(key) : null;
          return (
            <button
              key={label}
              type="button"
              role="tab"
              aria-selected={on}
              onClick={() => setRec(key)}
              className={
                'flex items-center gap-3 rounded-2xl px-4 py-3 text-left transition-all ' +
                (on
                  ? `${tone ? tone.bg : 'bg-brand text-white'} ring-2 ${tone ? 'ring-current ' + tone.text : 'ring-brand'}`
                  : 'bg-white ring-1 ring-line/70 hover:ring-brand/40')
              }
            >
              <span className={`font-display text-2xl leading-none font-bold ${tone && !on ? tone.text : ''}`}>{n}</span>
              <span className={`text-sm font-semibold ${on ? '' : 'text-muted'}`}>{label}</span>
            </button>
          );
        })}
      </div>

      {/* Поиск, фильтры, выгрузка */}
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <label htmlFor="search" className="sr-only">
            Поиск
          </label>
          <input
            id="search"
            type="search"
            className="input min-h-11 flex-[1_1_280px]"
            placeholder="Найти по названию, заказчику или номеру"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="flex w-full flex-wrap gap-2.5 sm:w-auto">
            <button
              type="button"
              className="btn-ghost flex-1 sm:flex-none"
              aria-expanded={showFilters}
              onClick={() => setShowFilters((v) => !v)}
            >
              Фильтры{activeFilterCount ? ` · ${activeFilterCount}` : ''}
            </button>
            <label className="sr-only" htmlFor="sort">
              Сортировка
            </label>
            <select
              id="sort"
              className="input min-h-11 flex-[2_1_200px] sm:flex-none"
              value={SORTS.find((s) => s.sort.key === sort.key && s.sort.dir === sort.dir)?.value ?? ''}
              onChange={(e) => {
                const found = SORTS.find((s) => s.value === e.target.value);
                if (found) setSort(found.sort);
              }}
            >
              {!SORTS.some((s) => s.sort.key === sort.key && s.sort.dir === sort.dir) && (
                <option value="" disabled>
                  Своя сортировка
                </option>
              )}
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
            <button type="button" className="btn-ghost flex-1 sm:flex-none" onClick={() => exportAs('csv')}>
              Скачать для Excel
            </button>
            <button type="button" className="btn-ghost" onClick={() => exportAs('json')}>
              JSON
            </button>
          </div>
        </div>

        {showFilters && (
          <div className="card animate-rise flex flex-wrap items-end gap-3 p-4">
            <label className="flex min-w-40 flex-1 flex-col gap-1 text-sm">
              <span className="text-muted">Регион</span>
              <select
                id="f-region"
                className="input"
                value={filters.region ?? ''}
                onChange={(e) => setFilters({ ...filters, region: e.target.value || undefined })}
              >
                <option value="">Все регионы</option>
                {regions.map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted">НМЦК, млн ₽</span>
              <span className="flex items-center gap-1.5">
                <MillionsInput id="f-min" placeholder="от" value={filters.nmck_min} onChange={(v) => setFilters({ ...filters, nmck_min: v })} />
                <span className="text-muted">—</span>
                <MillionsInput id="f-max" placeholder="до" value={filters.nmck_max} onChange={(v) => setFilters({ ...filters, nmck_max: v })} />
              </span>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted">Закон</span>
              <select
                id="f-law"
                className="input"
                value={filters.law ?? ''}
                onChange={(e) => setFilters({ ...filters, law: (e.target.value || undefined) as Law | undefined })}
              >
                <option value="">Любой</option>
                {(Object.keys(LAW_LABEL) as Law[]).map((l) => (
                  <option key={l} value={l}>
                    {LAW_LABEL[l]}
                  </option>
                ))}
              </select>
            </label>
            <fieldset className="flex flex-col gap-1 text-sm">
              <legend className="mb-1 text-muted">Окончание подачи заявок</legend>
              <div className="flex flex-wrap items-center gap-1.5">
                <label className="sr-only" htmlFor="f-dl-from">
                  с
                </label>
                <input
                  id="f-dl-from"
                  type="date"
                  className="input w-[150px] py-2"
                  value={deadlineFrom}
                  max={deadlineTo || undefined}
                  onChange={(e) => setDeadlineFrom(e.target.value)}
                />
                <span className="text-muted">—</span>
                <label className="sr-only" htmlFor="f-dl-to">
                  по
                </label>
                <input
                  id="f-dl-to"
                  type="date"
                  className="input w-[150px] py-2"
                  value={deadlineTo}
                  min={deadlineFrom || undefined}
                  onChange={(e) => setDeadlineTo(e.target.value)}
                />
                {DEADLINE_PRESETS.map((p) => {
                  const on = deadlineFrom === isoDay(new Date()) && deadlineTo === addDays(p.days);
                  return (
                    <button
                      key={p.label}
                      type="button"
                      aria-pressed={on}
                      className={'chip ' + (on ? 'chip-on' : '')}
                      onClick={() => {
                        setDeadlineFrom(isoDay(new Date()));
                        setDeadlineTo(addDays(p.days));
                      }}
                    >
                      {p.label}
                    </button>
                  );
                })}
              </div>
            </fieldset>
            <label className="flex items-center gap-2 py-2 text-sm">
              <input
                id="f-expired"
                type="checkbox"
                className="h-4 w-4 accent-ink"
                checked={Boolean(filters.hide_expired)}
                onChange={(e) => setFilters({ ...filters, hide_expired: e.target.checked || undefined })}
              />
              Скрыть просроченные
            </label>
            {activeFilterCount > 0 && (
              <button type="button" className="btn-ghost btn-sm" onClick={resetFilters}>
                Сбросить
              </button>
            )}
          </div>
        )}
      </div>

      {shown.length === 0 ? (
        <EmptyState title="Ничего не найдено" text="Под поиск и фильтры не подходит ни одна закупка. Попробуйте их ослабить." />
      ) : (
        <>
          {/* Таблица — от 768 px */}
          <div className="hidden overflow-x-auto rounded-3xl bg-white shadow-[0_1px_0_rgba(29,31,39,0.04),0_12px_28px_-18px_rgba(29,31,39,0.25)] md:block">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="bg-brand-tint text-left text-xs text-muted">
                  {COLUMNS.map((c) => {
                    const active = sort.key === c.key;
                    return (
                      <th
                        key={c.key}
                        scope="col"
                        aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                        className={`border-b border-track px-3 py-3.5 font-semibold tracking-[0.06em] whitespace-nowrap uppercase ${c.className ?? ''}`}
                      >
                        <button
                          type="button"
                          onClick={() => toggleSort(c.key)}
                          className={'inline-flex items-center gap-1 uppercase hover:text-brand ' + (active ? 'text-brand' : '')}
                        >
                          {c.label}
                          <span aria-hidden className={active ? '' : 'opacity-0'}>
                            {sort.dir === 'asc' ? '↑' : '↓'}
                          </span>
                        </button>
                      </th>
                    );
                  })}
                  <th scope="col" className="border-b border-track px-3 py-3.5 pr-5 font-semibold tracking-[0.06em] uppercase">
                    Рекомендация
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r, i) => {
                  const tone = toneOf(r.recommendation);
                  const dl = deadlineInfo(r.application_deadline);
                  const open = () => navigate(`/procurements/${r.procurement_id}`);
                  return (
                    <tr
                      key={r.procurement_id}
                      tabIndex={0}
                      onClick={open}
                      onKeyDown={(e) => e.key === 'Enter' && open()}
                      className="group animate-rise cursor-pointer border-b border-track transition-colors last:border-0 hover:bg-brand-tint/70 focus-visible:bg-brand-tint/70"
                      style={{ animationDelay: `${Math.min(i, 12) * 35}ms` }}
                    >
                      <td className="py-3.5 pr-3 pl-5">
                        <div className="flex items-center gap-2.5">
                          <span className={`min-w-[72px] shrink-0 font-display text-[22px] leading-none font-bold whitespace-nowrap tabular-nums ${tone.text}`}>
                            {r.total}
                            <span className="text-xs font-semibold">%</span>
                          </span>
                          <span className="h-1.5 w-12 overflow-hidden rounded-full bg-track" aria-hidden>
                            <span className={`block h-full rounded-full ${tone.bar}`} style={{ width: `${Math.max(3, r.total)}%` }} />
                          </span>
                        </div>
                      </td>
                      <td className="max-w-[340px] px-3 py-3.5">
                        <div className="line-clamp-2 font-semibold group-hover:underline group-hover:decoration-line group-hover:underline-offset-4">
                          {r.subject}
                        </div>
                        <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-muted">
                          <span className="font-mono">№ {r.reg_number}</span>
                          {r.reason && <span>· {r.reason}</span>}
                        </div>
                      </td>
                      <td className="max-w-[240px] px-3 py-3.5">
                        <span className="line-clamp-2">{r.customer_name ?? '—'}</span>
                      </td>
                      <td className="px-3 py-3.5 text-right font-semibold whitespace-nowrap tabular-nums">{formatMoneyShort(r.nmck)}</td>
                      <td className="px-3 py-3.5">{r.region ?? '—'}</td>
                      <td className="px-3 py-3.5 whitespace-nowrap">
                        <div>{formatDate(r.application_deadline)}</div>
                        <div className={`text-xs ${DEADLINE_TONE[dl.tone]}`}>{dl.text}</div>
                      </td>
                      <td className="px-3 py-3.5 pr-5">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className={`rounded-full px-2.5 py-1 text-[13px] font-bold whitespace-nowrap ${tone.bg} ${tone.text}`}>
                            {RECOMMENDATION[r.recommendation].label}
                          </span>
                          {r.has_stop_factor && (
                            <span
                              className="-rotate-[8deg] rounded border-2 border-brand px-1 font-display text-[10px] font-bold tracking-wider text-brand"
                              title="Сработал стоп-фактор"
                            >
                              СТОП
                            </span>
                          )}
                          {r.incomplete && (
                            <span className="text-xs text-muted" title="Для части критериев не хватило данных">
                              неполная
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Телефон — билеты */}
          <div className="flex flex-col gap-3 md:hidden">
            {shown.map((r, i) => (
              <div key={r.procurement_id} className={`${TICKET_BG[r.recommendation]} rounded-[22px] p-1.5`}>
                <Ticket row={r} notchClass={TICKET_BG[r.recommendation]} index={i} />
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/** Итог одной фразой + полоска распределения + ближайший срок */
function Summary({ rows }: { rows: ResultRow[] }) {
  const c = { participate: 0, consider: 0, skip: 0 };
  rows.forEach((r) => c[r.recommendation]++);

  const nearest = rows
    .filter((r) => r.recommendation !== 'skip' && deadlineInfo(r.application_deadline).tone !== 'closed' && r.application_deadline)
    .sort((a, b) => time(a.application_deadline) - time(b.application_deadline))[0];

  const title =
    c.participate > 0 ? (
      <>
        <span className="text-brand">
          {c.participate} {plural(c.participate, 'закупку', 'закупки', 'закупок')}
        </span>{' '}
        стоит взять в работу
      </>
    ) : (
      'Подходящих закупок пока нет'
    );

  return (
    <section className="flex flex-wrap items-end gap-x-12 gap-y-5">
      <div className="min-w-0 flex-[1_1_480px]">
        <p className="mb-2.5 text-[13px] font-semibold tracking-[0.08em] text-muted uppercase">
          Оценено {rows.length} {plural(rows.length, 'закупка', 'закупки', 'закупок')}
        </p>
        <h1 className="font-display text-[28px] leading-tight font-bold text-balance sm:text-[38px]">{title}</h1>
        <p className="mt-2.5 max-w-[60ch] text-muted sm:text-base">
          {c.consider > 0 && `${c.consider} — на ваше усмотрение. `}
          {c.skip > 0 && `${c.skip} не ${plural(c.skip, 'подходит', 'подходят', 'подходят')}. `}
          {nearest && (
            <>
              Ближайший срок подачи —{' '}
              <b className="text-ink">
                {formatDate(nearest.application_deadline)}, {deadlineInfo(nearest.application_deadline).text}
              </b>
              : «{nearest.subject}».
            </>
          )}
        </p>
      </div>
      <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-2" aria-hidden>
        <div className="flex h-3.5 gap-[3px] overflow-hidden rounded-full">
          {c.participate > 0 && <div className="bg-good" style={{ flex: c.participate }} />}
          {c.consider > 0 && <div className="bg-mid-bar" style={{ flex: c.consider }} />}
          {c.skip > 0 && <div className="bg-bad" style={{ flex: c.skip }} />}
        </div>
        <div className="flex justify-between text-[13px] text-muted">
          <span>
            <b className="text-good">{c.participate}</b> участвовать
          </span>
          <span>
            <b className="text-mid">{c.consider}</b> рассмотреть
          </span>
          <span>
            <b className="text-bad">{c.skip}</b> пропустить
          </span>
        </div>
      </div>
    </section>
  );
}

/** Ввод суммы в миллионах, наружу отдаём рубли */
function MillionsInput(props: { id: string; placeholder: string; value?: number; onChange: (v: number | undefined) => void }) {
  return (
    <input
      id={props.id}
      type="number"
      min={0}
      step="any"
      inputMode="decimal"
      className="input w-20"
      placeholder={props.placeholder}
      value={props.value === undefined ? '' : props.value / 1e6}
      onChange={(e) => props.onChange(e.target.value === '' ? undefined : Number(e.target.value) * 1e6)}
    />
  );
}
