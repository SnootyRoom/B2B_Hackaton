import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api, USE_MOCK } from '../api';
import { qk } from '../lib/hooks';
import { Alert } from '../components/ui';
import Logo from '../components/Logo';

type Mode = 'login' | 'register';

export default function LoginPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const submit = useMutation({
    mutationFn: () => (mode === 'login' ? api.login(email.trim(), password) : api.register(email.trim(), password)),
    onSuccess: (user) => {
      qc.setQueryData(qk.me, user);
      navigate('/', { replace: true }); // дальше Home решит: Параметры или Результаты
    },
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    submit.mutate();
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm overflow-hidden rounded-3xl border-t-4 border-brand bg-white p-6 shadow-[0_20px_50px_-20px_rgba(29,31,39,0.3)] sm:p-8">
        <div className="flex items-center gap-2.5 font-display text-xl font-bold">
          <Logo size={34} />
          Скоринг закупок
        </div>
        <p className="mt-1 text-muted">
          Загрузите закупки из ЕИС — система оценит, стоит ли в них участвовать, и объяснит почему.
        </p>

        <div className="mt-6 flex rounded-lg bg-brand-tint p-1" role="tablist">
          {(['login', 'register'] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              onClick={() => {
                setMode(m);
                submit.reset();
              }}
              className={
                'flex-1 rounded-md py-2 text-sm font-semibold ' +
                (mode === m ? 'bg-white text-brand shadow-sm' : 'text-muted')
              }
            >
              {m === 'login' ? 'Вход' : 'Регистрация'}
            </button>
          ))}
        </div>

        <form onSubmit={onSubmit} className="mt-5 flex flex-col gap-4">
          <div>
            <label className="label" htmlFor="email">
              Электронная почта
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              className="input w-full"
              placeholder="name@company.ru"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="password">
              Пароль
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={mode === 'register' ? 8 : undefined}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              className="input w-full"
              placeholder={mode === 'register' ? 'Не короче 8 символов' : ''}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {submit.isError && <Alert>{submit.error.message}</Alert>}
          <button className="btn-primary w-full" disabled={submit.isPending}>
            {submit.isPending ? 'Подождите…' : mode === 'login' ? 'Войти' : 'Создать аккаунт'}
          </button>
        </form>

        <p className="mt-5 text-center text-xs text-muted">
          Попробовать без регистрации: <b>demo@example.com</b> / <b>demo12345</b>
          {USE_MOCK && (<><br />В демо-режиме подойдёт любая почта — сразу с примерами закупок.<br />Пустой аккаунт, чтобы пройти путь с нуля: <b>new@example.com</b></>)}
        </p>
      </div>
    </div>
  );
}
