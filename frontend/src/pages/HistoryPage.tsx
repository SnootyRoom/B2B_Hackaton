// «История»: все загрузки пользователя по датам — когда, сколько файлов, что получилось.
// Из каждой загрузки можно открыть только её закупки или подробности по файлам.

import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import type { Task } from '../api/types';
import { formatDate, plural } from '../lib/format';
import { qk } from '../lib/hooks';
import { Alert, EmptyState, Loading } from '../components/ui';

const pad = (n: number) => String(n).padStart(2, '0');
const timeOf = (iso: string) => {
  const d = new Date(iso);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

/** «Сегодня», «Вчера» или «28 октября» */
function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((startOf(today) - startOf(d)) / 86400000);
  if (diff === 0) return 'Сегодня';
  if (diff === 1) return 'Вчера';
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: d.getFullYear() === today.getFullYear() ? undefined : 'numeric' });
}

export default function HistoryPage() {
  const uploads = useQuery({ queryKey: qk.uploads, queryFn: () => api.listUploads() });

  if (uploads.isPending) return <Loading text="Загружаем историю…" />;
  if (uploads.isError) return <Alert>{uploads.error.message}</Alert>;

  const list = uploads.data;
  // Группируем по дням, сохраняя порядок «новые сверху»
  const groups: { day: string; items: Task[] }[] = [];
  list.forEach((t) => {
    const day = dayLabel(t.created_at);
    const last = groups[groups.length - 1];
    if (last && last.day === day) last.items.push(t);
    else groups.push({ day, items: [t] });
  });

  const totalLots = list.reduce(
    (s, t) => s + t.files.filter((f) => f.status === 'ok').reduce((a, f) => a + f.procurement_ids.length, 0),
    0,
  );

  return (
    <div className="mx-auto flex max-w-[880px] flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-[60ch]">
          <p className="mb-2 text-[13px] font-semibold tracking-[0.08em] text-muted uppercase">История</p>
          <h1 className="font-display text-[28px] leading-tight font-bold text-balance sm:text-[36px]">Ваши загрузки</h1>
          {list.length > 0 && (
            <p className="mt-2 text-muted sm:text-base">
              {list.length} {plural(list.length, 'загрузка', 'загрузки', 'загрузок')}, всего оценено {totalLots}{' '}
              {plural(totalLots, 'закупка', 'закупки', 'закупок')}.
            </p>
          )}
        </div>
        <Link to="/upload" className="btn-primary">
          Новая загрузка
        </Link>
      </div>

      {list.length === 0 ? (
        <EmptyState title="Загрузок пока не было" text="Добавьте файлы из ЕИС — здесь появится история с датами и итогами.">
          <Link to="/upload" className="btn-primary">
            Загрузить закупки
          </Link>
        </EmptyState>
      ) : (
        groups.map((g) => (
          <section key={g.day} className="flex flex-col gap-3" aria-label={g.day}>
            <h2 className="flex items-center gap-3 text-sm font-bold tracking-[0.06em] text-muted uppercase">
              {g.day}
              <span className="h-px flex-1 bg-line" aria-hidden />
            </h2>
            {g.items.map((t, i) => (
              <UploadCard key={t.id} task={t} index={i} />
            ))}
          </section>
        ))
      )}
    </div>
  );
}

function UploadCard({ task: t, index }: { task: Task; index: number }) {
  const lots = t.files.filter((f) => f.status === 'ok').reduce((a, f) => a + f.procurement_ids.length, 0);
  const errors = t.files.filter((f) => f.status === 'error').length;
  const running = t.status === 'queued' || t.status === 'processing';
  const s = t.summary;
  const total = s ? s.participate + s.consider + s.skip : 0;

  return (
    <article className="card animate-rise flex flex-col gap-4 sm:flex-row sm:items-center sm:p-6" style={{ animationDelay: `${index * 50}ms` }}>
      <div className="flex shrink-0 items-baseline gap-3 sm:w-28 sm:flex-col sm:gap-0.5">
        <span className="font-display text-2xl font-bold tabular-nums">{timeOf(t.created_at)}</span>
        <span className="text-sm text-muted">{formatDate(t.created_at)}</span>
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="font-semibold">
          {running
            ? `Обрабатывается: ${t.processed} из ${t.total}`
            : `${t.total} ${plural(t.total, 'файл', 'файла', 'файлов')} → оценено ${lots} ${plural(lots, 'закупка', 'закупки', 'закупок')}`}
          {errors > 0 && (
            <span className="ml-2 rounded-full bg-bad-soft px-2 py-0.5 text-xs font-semibold text-bad">
              {errors} {plural(errors, 'ошибка', 'ошибки', 'ошибок')}
            </span>
          )}
        </div>
        {s && total > 0 && (
          <>
            <div className="flex h-2 gap-[2px] overflow-hidden rounded-full" aria-hidden>
              {s.participate > 0 && <div className="bg-good" style={{ flex: s.participate }} />}
              {s.consider > 0 && <div className="bg-mid-bar" style={{ flex: s.consider }} />}
              {s.skip > 0 && <div className="bg-bad" style={{ flex: s.skip }} />}
            </div>
            <div className="flex flex-wrap gap-x-4 text-[13px] text-muted">
              <span>
                <b className="text-good">{s.participate}</b> участвовать
              </span>
              <span>
                <b className="text-mid">{s.consider}</b> рассмотреть
              </span>
              <span>
                <b className="text-bad">{s.skip}</b> пропустить
              </span>
            </div>
          </>
        )}
      </div>

      <div className="flex shrink-0 flex-wrap gap-2 sm:flex-col">
        <Link to={`/results?upload=${encodeURIComponent(t.id)}`} className="btn-primary btn-sm flex-1">
          Открыть закупки
        </Link>
        <Link to={`/upload?task=${encodeURIComponent(t.id)}`} className="btn-ghost btn-sm flex-1">
          Файлы
        </Link>
      </div>
    </article>
  );
}
