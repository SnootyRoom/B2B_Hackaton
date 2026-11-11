import { useEffect } from 'react';
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api, USE_MOCK } from '../api';
import type { User } from '../api/types';
import { qk, taskIsRunning, useProfiles, useTask } from '../lib/hooks';
import { clearRescoreIndicator, useRescoreJob, type RescoreJob } from '../lib/rescore';
import Logo from './Logo';

const TABS = [
  { to: '/profile', label: 'Параметры', short: 'Профиль' },
  { to: '/upload', label: 'Загрузка' },
  { to: '/results', label: 'Результаты' },
  { to: '/compare', label: 'Сравнение' },
  { to: '/history', label: 'История' },
];

export default function Layout({ user }: { user: User }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const logout = useMutation({
    mutationFn: api.logout,
    onSettled: () => {
      qc.clear();
      qc.setQueryData(qk.me, null);
      navigate('/');
    },
  });

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-20 border-t-[3px] border-b border-t-brand border-b-line/70 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1240px] flex-wrap items-center gap-x-7 gap-y-2 px-4 py-3 sm:px-6">
          <NavLink to="/" className="flex items-center gap-2.5 text-[17px] font-bold whitespace-nowrap">
            <Logo />
            Скоринг закупок
          </NavLink>
          <nav className="order-3 -mx-1 flex w-full gap-0.5 overflow-x-auto px-1 sm:order-none sm:mx-0 sm:w-auto sm:flex-1 sm:gap-1 sm:overflow-visible sm:px-0">
            {TABS.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                className={({ isActive }) =>
                  'shrink-0 grow rounded-lg px-[3px] py-2.5 text-center text-[12px] font-semibold whitespace-nowrap sm:grow-0 sm:px-3 sm:text-[15px] lg:px-4 ' +
                  (isActive
                    ? 'text-brand shadow-[inset_0_-3px_0_var(--color-brand)]'
                    : 'text-muted hover:text-brand')
                }
              >
                {'short' in t ? (
                  <>
                    <span className="sm:hidden">{t.short}</span>
                    <span className="hidden sm:inline">{t.label}</span>
                  </>
                ) : (
                  t.label
                )}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex min-w-0 items-center gap-3">
            <ActiveProfileChip />
            <span className="hidden truncate text-sm text-muted 2xl:inline" title={user.email}>
              {user.email}
            </span>
            <button className="btn-ghost btn-sm" onClick={() => logout.mutate()} disabled={logout.isPending}>
              Выйти
            </button>
          </div>
        </div>
        <RescoreIndicator />
      </header>
      {USE_MOCK && (
        <div className="border-b border-mid-soft bg-mid-soft px-4 py-1.5 text-center text-xs text-mid">
          Демо-режим: тестовые данные, сервер не подключён
        </div>
      )}
      <main className="mx-auto w-full max-w-[1240px] flex-1 px-4 pt-6 pb-16 sm:px-6 sm:pt-8">
        <Outlet />
      </main>
      <Footer />
    </div>
  );
}

/** В шапке на всех экранах — имя активного профиля, во время пересчёта — значок загрузки */
function ActiveProfileChip() {
  const profiles = useProfiles();
  const job = useRescoreJob();
  const task = useTask(job?.taskId ?? null);
  const active = profiles.data?.find((p) => p.is_active);
  if (!active) return null;
  const busy = Boolean(job?.taskId) && !task.isError && taskIsRunning(task.data);
  return (
    <Link
      to={`/profile?id=${encodeURIComponent(active.id)}`}
      className="flex min-w-0 items-center gap-1.5 rounded-full bg-brand-tint py-1 pr-3 pl-2 text-sm hover:bg-brand-soft"
      title={busy ? `Пересчитываем оценки по профилю «${active.name}»` : `Активный профиль: «${active.name}»`}
    >
      {busy ? (
        <span
          className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-brand/30 border-t-brand"
          aria-hidden
        />
      ) : (
        <span className="h-2 w-2 shrink-0 rounded-full bg-brand" aria-hidden />
      )}
      <span className="hidden text-muted md:inline">Профиль:</span>
      <b className="max-w-[28vw] truncate sm:max-w-[180px]">{active.name}</b>
      {busy && <span className="sr-only">— пересчитываем оценки</span>}
    </Link>
  );
}

/** Полоска под шапкой: пересчёт оценок после смены профиля */
function RescoreIndicator() {
  const job = useRescoreJob();
  return job ? <RescoreStrip key={job.taskId ?? 'none'} job={job} /> : null;
}

function RescoreStrip({ job }: { job: RescoreJob }) {
  const task = useTask(job.taskId);
  const t = task.data;
  const running = job.taskId !== null && !task.isError && taskIsRunning(t);
  const onResults = useLocation().pathname === '/results';

  // Готово — показываем пару секунд и убираем
  useEffect(() => {
    if (running) return;
    const timer = setTimeout(() => clearRescoreIndicator(job.taskId), task.isError ? 8000 : 5000);
    return () => clearTimeout(timer);
  }, [running, task.isError, job.taskId]);

  const pct = t && t.total > 0 ? Math.round((t.processed / t.total) * 100) : 0;

  return (
    <div className="border-t border-line/70 bg-brand-tint" role="status" aria-live="polite">
      <div className="mx-auto flex max-w-[1240px] flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2 text-sm sm:px-6">
        {running ? (
          <>
            <span
              className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-brand/30 border-t-brand"
              aria-hidden
            />
            <span className="min-w-0 flex-1">
              Пересчитываем оценки по профилю <b>«{job.profileName}»</b>
              {t && t.total > 0 && (
                <span className="text-muted">
                  {' '}
                  · {t.processed} из {t.total}
                </span>
              )}
            </span>
          </>
        ) : task.isError ? (
          <span className="flex-1 text-bad">Не удалось узнать, как идёт пересчёт: {task.error.message}</span>
        ) : (
          <>
            <span
              className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-good text-xs font-bold text-white"
              aria-hidden
            >
              ✓
            </span>
            <span className="min-w-0 flex-1 font-semibold text-good">
              {job.taskId === null
                ? `Профиль «${job.profileName}» активен — оценки уже актуальны`
                : `Оценки пересчитаны по профилю «${job.profileName}»`}
            </span>
            {!onResults && (
              <Link
                to="/results"
                className="font-semibold text-brand underline decoration-brand/30 underline-offset-4"
              >
                К результатам
              </Link>
            )}
          </>
        )}
        <button
          type="button"
          className="text-muted hover:text-ink"
          aria-label="Скрыть"
          onClick={() => clearRescoreIndicator(job.taskId)}
        >
          ✕
        </button>
      </div>
      {running && (
        <div className="h-1 bg-brand/15">
          <div
            className="h-full bg-brand transition-[width] duration-500"
            style={{ width: `${Math.max(4, pct)}%` }}
          />
        </div>
      )}
    </div>
  );
}

function Footer() {
  const links = [
    { to: '/profile', label: 'Параметры оценки', hint: 'профили и правила' },
    { to: '/upload', label: 'Загрузка', hint: 'файлы или номера из ЕИС' },
    { to: '/results', label: 'Результаты', hint: 'оценки и рекомендации' },
    { to: '/history', label: 'История', hint: 'все прошлые загрузки' },
  ];
  return (
    <footer className="border-t border-line bg-white">
      <div className="mx-auto flex max-w-[1240px] flex-wrap items-start justify-between gap-x-10 gap-y-6 px-4 py-8 sm:px-6">
        <div className="flex max-w-xs flex-col gap-2">
          <span className="flex items-center gap-2.5 font-bold">
            <Logo />
            Скоринг закупок
          </span>
          <p className="text-sm text-muted">
            Оценка закупок ЕИС по вашим параметрам с данными ЕГРЮЛ. Решение всегда за вами.
          </p>
        </div>
        <nav
          aria-label="Карта сайта"
          className="grid flex-1 grid-cols-2 gap-x-8 gap-y-3 sm:max-w-xl sm:grid-cols-4"
        >
          {links.map((l, i) => (
            <Link key={l.to} to={l.to} className="group flex flex-col">
              <span className="text-xs font-bold text-brand">0{i + 1}</span>
              <span className="font-semibold group-hover:text-brand">{l.label}</span>
              <span className="text-xs text-muted">{l.hint}</span>
            </Link>
          ))}
        </nav>
      </div>
    </footer>
  );
}
