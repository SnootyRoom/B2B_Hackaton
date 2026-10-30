// Стартовая страница после входа: что делает сервис, три шага и кнопка «Начать» / «Далее».

import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { GROUPS } from '../lib/catalog';
import { plural } from '../lib/format';
import { qk, useProfile } from '../lib/hooks';
import Logo from '../components/Logo';

const GROUP_TEXT: Record<string, string> = {
  procurement: 'Цена, способ закупки, регион, сроки подачи и обеспечение — из извещения ЕИС.',
  fit: 'Насколько предмет закупки похож на то, чем занимается ваша компания.',
  customer: 'Надёжность заказчика по ЕГРЮЛ: действует ли, сколько лет, нет ли отметок.',
};

export default function WelcomePage() {
  const profile = useProfile();
  const results = useQuery({ queryKey: qk.results({}), queryFn: () => api.getResults({}) });

  const hasProfile = Boolean(profile.data);
  const rows = results.data ?? [];
  const hasResults = rows.length > 0;
  const participate = rows.filter((r) => r.recommendation === 'participate').length;

  // Куда ведёт главная кнопка — к следующему непройденному шагу
  const cta = !hasProfile
    ? { to: '/profile', label: 'Начать' }
    : !hasResults
      ? { to: '/upload', label: 'Далее: загрузить закупки' }
      : { to: '/results', label: 'Далее: к результатам' };

  const steps = [
    {
      n: 1,
      title: 'Опишите, что вам интересно',
      text: 'Своими словами — система составит правила оценки. Их можно поправить вручную.',
      to: '/profile',
      done: hasProfile,
    },
    {
      n: 2,
      title: 'Загрузите закупки',
      text: 'Файлы извещений из ЕИС (.xml, .json или .zip). Можно сразу много.',
      to: '/upload',
      done: hasResults,
    },
    {
      n: 3,
      title: 'Смотрите результат',
      text: 'Оценка 0–100%, рекомендация и объяснение по каждой закупке.',
      to: '/results',
      done: false,
    },
  ];
  const nextStep = steps.find((s) => !s.done)?.n ?? 3;

  return (
    <div className="flex flex-col gap-10">
      {/* Приветствие и главная кнопка */}
      <section className="card relative overflow-hidden px-6 py-10 sm:px-10 sm:py-14">
        <div className="pointer-events-none absolute -top-10 -right-8 opacity-[0.07] sm:right-6" aria-hidden>
          <Logo size={260} />
        </div>
        <div className="relative flex max-w-2xl flex-col gap-5">
          <p className="text-[13px] font-semibold tracking-[0.08em] text-brand uppercase">Скоринг закупок</p>
          <h1 className="font-display text-[30px] leading-[1.15] font-bold text-balance sm:text-[44px]">
            Отберём закупки, в которых стоит участвовать
          </h1>
          <p className="max-w-[56ch] text-base text-muted sm:text-lg">
            Опишите, какие закупки вам подходят, и загрузите извещения из ЕИС. Система оценит каждую от 0 до 100%,
            подскажет — участвовать, рассмотреть или пропустить — и объяснит почему. Решение всегда за вами.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Link to={cta.to} className="btn-primary px-6 text-base">
              {cta.label} →
            </Link>
            {hasResults && (
              <span className="text-sm text-muted">
                Оценено {rows.length} {plural(rows.length, 'закупка', 'закупки', 'закупок')},{' '}
                <b className="text-good">
                  {participate} {plural(participate, 'подходит', 'подходят', 'подходят')}
                </b>
              </span>
            )}
          </div>
        </div>
      </section>

      {/* Три шага — навигация по сайту */}
      <section className="flex flex-col gap-4" aria-labelledby="steps-title">
        <h2 id="steps-title" className="font-display text-xl font-bold">
          Как это работает
        </h2>
        <ol className="grid gap-4 md:grid-cols-3">
          {steps.map((s, i) => {
            const isNext = s.n === nextStep;
            return (
              <li key={s.n} className="animate-rise" style={{ animationDelay: `${i * 70}ms` }}>
                <Link
                  to={s.to}
                  className={
                    'group flex h-full flex-col gap-3 rounded-3xl bg-white p-5 transition-all hover:-translate-y-0.5 sm:p-6 ' +
                    (isNext
                      ? 'ring-2 ring-brand shadow-[0_14px_30px_-16px_rgba(214,32,47,0.5)]'
                      : 'ring-1 ring-line/70 hover:ring-brand/40')
                  }
                >
                  <div className="flex items-center justify-between gap-3">
                    <span
                      className={
                        'grid h-10 w-10 place-items-center rounded-full font-display text-lg font-bold ' +
                        (s.done ? 'bg-good-soft text-good' : isNext ? 'bg-brand text-white' : 'bg-track text-muted')
                      }
                    >
                      {s.done ? '✓' : s.n}
                    </span>
                    <span
                      className={
                        'rounded-full px-2.5 py-1 text-xs font-bold ' +
                        (s.done ? 'bg-good-soft text-good' : isNext ? 'bg-brand-soft text-brand-dark' : 'text-muted')
                      }
                    >
                      {s.done ? 'Готово' : isNext ? 'Следующий шаг' : `Шаг ${s.n}`}
                    </span>
                  </div>
                  <h3 className="text-lg font-bold group-hover:text-brand">{s.title}</h3>
                  <p className="flex-1 text-sm text-muted">{s.text}</p>
                  <span className="text-sm font-semibold text-brand">{s.done ? 'Открыть' : isNext ? 'Перейти' : 'Посмотреть'} →</span>
                </Link>
              </li>
            );
          })}
        </ol>
      </section>

      {/* Из чего складывается оценка */}
      <section className="flex flex-col gap-4" aria-labelledby="groups-title">
        <div>
          <h2 id="groups-title" className="font-display text-xl font-bold">
            Что учитывается в оценке
          </h2>
          <p className="mt-1 text-sm text-muted">Три группы критериев. Их долю в итоге вы задаёте сами на шаге 1.</p>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {GROUPS.map((g) => (
            <div key={g.key} className="rounded-2xl bg-white/70 p-5 ring-1 ring-line/70">
              <div className="font-bold">{g.label}</div>
              <p className="mt-1 text-sm text-muted">{GROUP_TEXT[g.key]}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
