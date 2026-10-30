import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api, USE_MOCK } from '../api';
import type { User } from '../api/types';
import { qk } from '../lib/hooks';
import Logo from './Logo';

const TABS = [
  { to: '/profile', label: 'Параметры' },
  { to: '/upload', label: 'Загрузка' },
  { to: '/results', label: 'Результаты' },
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
          <nav className="order-3 flex w-full gap-1 sm:order-none sm:w-auto sm:flex-1">
            {TABS.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                className={({ isActive }) =>
                  'min-w-0 flex-1 rounded-lg px-1 py-2.5 text-center text-[13px] font-semibold sm:flex-none sm:px-4 sm:text-[15px] ' +
                  (isActive ? 'text-brand shadow-[inset_0_-3px_0_var(--color-brand)]' : 'text-muted hover:text-brand')
                }
              >
                {t.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex min-w-0 items-center gap-3">
            <span className="hidden truncate text-sm text-muted sm:inline" title={user.email}>
              {user.email}
            </span>
            <button className="btn-ghost btn-sm" onClick={() => logout.mutate()} disabled={logout.isPending}>
              Выйти
            </button>
          </div>
        </div>
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

/** Подвал: карта сайта — все разделы в одном месте */
function Footer() {
  const links = [
    { to: '/profile', label: 'Параметры оценки', hint: 'какие закупки вам подходят' },
    { to: '/upload', label: 'Загрузка', hint: 'добавить файлы из ЕИС' },
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
          <p className="text-sm text-muted">Оценка закупок ЕИС по вашим параметрам с данными ЕГРЮЛ. Решение всегда за вами.</p>
        </div>
        <nav aria-label="Карта сайта" className="grid flex-1 grid-cols-2 gap-x-8 gap-y-3 sm:max-w-xl sm:grid-cols-4">
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

