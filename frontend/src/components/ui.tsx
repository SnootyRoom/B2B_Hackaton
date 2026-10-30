import type { ReactNode } from 'react';
import type { Recommendation } from '../api/types';
import { RECOMMENDATION } from '../lib/catalog';

const TONE = {
  good: { text: 'text-good', bg: 'bg-good-soft', bar: 'bg-good', border: 'border-good' },
  mid: { text: 'text-mid', bg: 'bg-mid-soft', bar: 'bg-mid-bar', border: 'border-mid' },
  bad: { text: 'text-bad', bg: 'bg-bad-soft', bar: 'bg-bad', border: 'border-bad' },
} as const;

export function toneOf(r: Recommendation) {
  return TONE[RECOMMENDATION[r].tone];
}

/** Цвет всегда дублируется словом (CLAUDE.md) */
export function RecommendationBadge({ value, incomplete }: { value: Recommendation; incomplete?: boolean }) {
  const t = toneOf(value);
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <span className={`rounded-full px-2.5 py-0.5 text-sm font-semibold whitespace-nowrap ${t.bg} ${t.text}`}>
        {RECOMMENDATION[value].label}
      </span>
      {incomplete && (
        <span
          className="rounded-full border border-line px-2 py-0.5 text-xs whitespace-nowrap text-muted"
          title="Для части критериев не хватило данных"
        >
          оценка неполная
        </span>
      )}
    </span>
  );
}

/** Оценка числом + цветная полоска */
export function ScoreBar({ value, recommendation }: { value: number; recommendation: Recommendation }) {
  const t = toneOf(recommendation);
  return (
    <div className="flex min-w-24 items-center gap-2">
      <span className={`w-8 text-right font-bold tabular-nums ${t.text}`}>{value}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-canvas" aria-hidden>
        <div className={`h-full rounded-full ${t.bar}`} style={{ width: `${Math.max(2, value)}%` }} />
      </div>
    </div>
  );
}

export function Loading({ text = 'Загружаем…' }: { text?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-16 text-muted" role="status">
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-line border-t-brand" />
      {text}
    </div>
  );
}

export function Alert({ tone = 'bad', children }: { tone?: 'good' | 'mid' | 'bad'; children: ReactNode }) {
  const t = TONE[tone];
  return <div className={`rounded-xl px-4 py-3 text-sm ${t.bg} ${t.text}`}>{children}</div>;
}

export function EmptyState({ title, text, children }: { title: string; text?: string; children?: ReactNode }) {
  return (
    <div className="card flex flex-col items-center gap-3 py-14 text-center">
      <h2 className="font-display text-xl font-bold">{title}</h2>
      {text && <p className="max-w-md text-muted">{text}</p>}
      {children && <div className="mt-2 flex flex-wrap justify-center gap-2">{children}</div>}
    </div>
  );
}

export function ProgressBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="h-3.5 overflow-hidden rounded-full bg-track" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full bg-brand transition-[width] duration-500" style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Каркас экрана результатов, пока идёт загрузка — вместо «крутилки» */
export function ResultsSkeleton() {
  return (
    <div className="flex flex-col gap-7" role="status" aria-label="Загружаем результаты">
      <div className="flex flex-col gap-3">
        <div className="skeleton h-3 w-40" />
        <div className="skeleton h-10 w-full max-w-lg" />
        <div className="skeleton h-4 w-full max-w-md" />
      </div>
      <div className="skeleton h-11 w-full" />
      <div className="grid gap-4 md:grid-cols-3">
        {[3, 1, 2].map((n, i) => (
          <div key={i} className="flex flex-col gap-3.5 rounded-3xl bg-track/60 p-4">
            <div className="skeleton h-8 w-32 bg-white/70" />
            {Array.from({ length: n }, (_, j) => (
              <div key={j} className="skeleton h-28 bg-white/80" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
