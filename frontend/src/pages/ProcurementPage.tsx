// Карточка закупки в стиле «сортировочный стол»: крупная оценка и шкала «как сложилась оценка».

import { useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import type { CustomerProfile, Procurement, RuleResult, ScoreResult } from '../api/types';
import {
  CUSTOMER_SOURCE_LABEL,
  CUSTOMER_STATUS_LABEL,
  GROUPS,
  LAW_LABEL,
  METHOD_LABEL,
  RECOMMENDATION,
  RESTRICTION_LABEL,
  errorText,
} from '../lib/catalog';
import {
  deadlineInfo,
  formatContribution,
  formatDate,
  formatDateTime,
  formatMoney,
  isPast,
  plural,
  yearsSince,
} from '../lib/format';
import { qk, useProfile } from '../lib/hooks';
import { Alert, Loading, toneOf } from '../components/ui';
import Breadcrumbs from '../components/Breadcrumbs';

export default function ProcurementPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const pid = Number(id);
  const q = useQuery({ queryKey: qk.procurement(pid), queryFn: () => api.getProcurement(pid), enabled: Number.isFinite(pid) });
  const profile = useProfile();
  const [hovered, setHovered] = useState<string | null>(null);
  // Порядок «как в таблице результатов» (лучшие сверху) — для кнопок «предыдущая / следующая»
  const all = useQuery({ queryKey: qk.results({}), queryFn: () => api.getResults({}) });
  const order = useMemo(() => [...(all.data ?? [])].sort((a, b) => b.total - a.total), [all.data]);

  if (q.isPending) return <Loading text="Загружаем закупку…" />;
  if (q.isError) {
    return (
      <div className="flex flex-col gap-3">
        <Alert>{q.error.message}</Alert>
        <Link to="/results" className="btn-ghost self-start">
          ← Ко всем закупкам
        </Link>
      </div>
    );
  }

  const { procurement: p, customer, customer_error, score } = q.data;
  const thresholds = profile.data?.thresholds ?? { participate: 70, consider: 40 };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Breadcrumbs items={[{ label: 'Результаты', to: '/results' }, { label: shorten(p.subject) }]} />
        <PrevNext order={order} current={pid} onBack={() => navigate('/results')} />
      </div>

      <Hero p={p} score={score} thresholds={thresholds} />

      {score && score.stop_factors.length > 0 && (
        <section className="flex items-start gap-4 rounded-2xl bg-bad-soft p-4 sm:p-5" aria-label="Стоп-факторы">
          <span className="shrink-0 -rotate-[8deg] rounded-md border-2 border-brand px-2 py-0.5 font-display text-xs font-bold tracking-wider text-brand">
            СТОП
          </span>
          <div>
            <h2 className="font-bold text-bad">Участвовать не рекомендуется</h2>
            <ul className="mt-1 flex flex-col gap-0.5">
              {score.stop_factors.map((s) => (
                <li key={s.rule_id} className="text-bad">
                  {s.message}
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {!score && (
        <Alert tone="mid">Закупка ещё не оценена. Задайте параметры на вкладке «Параметры» и сохраните их с пересчётом.</Alert>
      )}

      <div className="flex flex-wrap items-start gap-6">
        {score && (
          <Breakdown score={score} hovered={hovered} thresholds={thresholds} />
        )}
        <aside className="flex min-w-0 flex-[1_1_320px] flex-col gap-4">
          {score && <Short score={score} setHovered={setHovered} />}
          <CustomerBlock customer={customer} error={customer_error} inn={p.customer_inn} name={p.customer_name} />
        </aside>
      </div>

      <ProcurementBlock p={p} />
      {p.items.length > 0 && <ItemsBlock p={p} />}
    </div>
  );
}

const shorten = (s: string, n = 48) => (s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s);

/** «← Предыдущая · 3 из 11 · Следующая →» — листать закупки, не возвращаясь к таблице */
function PrevNext({ order, current, onBack }: { order: { procurement_id: number }[]; current: number; onBack: () => void }) {
  const i = order.findIndex((r) => r.procurement_id === current);
  if (i < 0) return null;
  const prev = order[i - 1];
  const next = order[i + 1];
  const btn = 'btn-ghost btn-sm min-w-0';
  return (
    <div className="flex items-center gap-2">
      {prev ? (
        <Link to={`/procurements/${prev.procurement_id}`} className={btn} aria-label="Предыдущая закупка">
          ← <span className="hidden sm:inline">Предыдущая</span>
        </Link>
      ) : (
        <button type="button" className={btn} disabled aria-label="Предыдущая закупка">
          ← <span className="hidden sm:inline">Предыдущая</span>
        </button>
      )}
      <button type="button" onClick={onBack} className="px-1 text-sm whitespace-nowrap text-muted tabular-nums hover:text-brand" title="Ко всем закупкам">
        {i + 1} из {order.length}
      </button>
      {next ? (
        <Link to={`/procurements/${next.procurement_id}`} className={btn} aria-label="Следующая закупка">
          <span className="hidden sm:inline">Следующая</span> →
        </Link>
      ) : (
        <button type="button" className={btn} disabled aria-label="Следующая закупка">
          <span className="hidden sm:inline">Следующая</span> →
        </button>
      )}
    </div>
  );
}

/** Крупная оценка, рекомендация, название и главные факты */
function Hero({
  p,
  score,
  thresholds,
}: {
  p: Procurement;
  score: ScoreResult | null;
  thresholds: { participate: number; consider: number };
}) {
  const tone = score ? toneOf(score.recommendation) : null;
  const dl = deadlineInfo(p.application_deadline);
  // Сколько не хватило до следующей ступени — помогает понять, «почти» это или «далеко»
  let gap: string | null = null;
  if (score && score.stop_factors.length === 0) {
    const next =
      score.total < thresholds.consider
        ? { at: thresholds.consider, name: 'Рассмотреть' }
        : score.total < thresholds.participate
          ? { at: thresholds.participate, name: 'Участвовать' }
          : null;
    if (next) {
      const n = next.at - score.total;
      gap = `до «${next.name}» не хватило ${n} ${plural(n, 'балла', 'баллов', 'баллов')}`;
    }
  }

  return (
    <section className="flex flex-wrap items-center gap-x-9 gap-y-4">
      {score && tone && (
        <div className="flex items-baseline gap-1.5">
          <span className={`font-display text-[80px] leading-[0.9] font-bold sm:text-[104px] ${tone.text}`}>{score.total}</span>
          <span className={`font-display text-3xl font-bold ${tone.text}`}>%</span>
        </div>
      )}
      <div className="flex min-w-0 flex-[1_1_480px] flex-col gap-2.5">
        {score && tone && (
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-3.5 py-1 font-bold ${tone.bg} ${tone.text}`}>
              {RECOMMENDATION[score.recommendation].label}
            </span>
            {score.incomplete && <span className="text-sm text-muted">оценка неполная — части данных нет</span>}
            {gap && <span className="text-sm text-muted">{gap}</span>}
          </div>
        )}
        <h1 className="font-display text-2xl leading-snug font-medium text-balance sm:text-[28px]">{p.subject}</h1>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
          <span className="font-mono">№ {p.reg_number}</span>
          {p.law && <span>{LAW_LABEL[p.law]}</span>}
          {(p.method_raw || p.method) && <span>{p.method_raw ?? METHOD_LABEL[p.method!]}</span>}
          <span className="font-semibold text-ink">{formatMoney(p.nmck)}</span>
          <span className={dl.tone === 'normal' ? '' : 'font-semibold text-bad'}>{dl.text}</span>
        </div>
      </div>
    </section>
  );
}

/**
 * «Как сложилась оценка»: все 100 баллов разложены по правилам друг за другом.
 * Тёмное — получено, штриховка — недобрано. Внизу итог с отметками порогов.
 */
function Breakdown({
  score,
  hovered,
  thresholds,
}: {
  score: ScoreResult;
  hovered: string | null;
  thresholds: { participate: number; consider: number };
}) {
  const weighted = score.rules.filter((r) => r.kind === 'weighted');
  const numbers = useRuleNumbers(score);
  // Сумма максимумов применимых правил — обычно 100; на неё нормируем шкалу
  const scale = weighted.reduce((s, r) => s + (r.no_data ? 0 : (r.max_contribution ?? 0)), 0) || 100;
  let offset = 0;
  const tone = toneOf(score.recommendation);

  return (
    <section className="card flex min-w-0 flex-[999_1_620px] flex-col gap-4 sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-5 gap-y-2">
        <h2 className="text-xl font-bold">Как сложилась оценка</h2>
        <div className="flex gap-4 text-[13px] text-muted">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-3.5 rounded-sm bg-ink" aria-hidden />
            получено
          </span>
          <span className="flex items-center gap-1.5">
            <span className="hatch h-2.5 w-3.5 rounded-sm" aria-hidden />
            недобрано
          </span>
        </div>
      </div>
      <p className="-mt-2 text-sm text-muted">
        Каждое ваше правило может дать свою долю из 100 баллов. Полоски идут друг за другом и складываются в итог.
      </p>

      {GROUPS.map((g) => {
        const group = score.groups.find((x) => x.group === g.key);
        const rules = weighted.filter((r) => r.group === g.key);
        if (rules.length === 0) return null;
        const got = rules.reduce((s, r) => s + (r.contribution ?? 0), 0);
        const max = rules.reduce((s, r) => s + (r.no_data ? 0 : (r.max_contribution ?? 0)), 0);
        return (
          <div key={g.key} className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-track pt-2 pb-1.5">
              <span className="text-[13px] font-bold tracking-[0.08em] uppercase">{g.label}</span>
              <span className="flex items-center gap-2 text-[13px] text-muted">
                {group?.low_data && (
                  <span className="rounded-full bg-mid-soft px-2 py-0.5 text-xs font-semibold text-mid">мало данных</span>
                )}
                {group?.score === null
                  ? 'не учитывается'
                  : `вес ${Math.round((group?.weight ?? 0) * 100)}% · получено ${Math.round(got)} из ${Math.round(max)}`}
              </span>
            </div>
            {rules.map((r) => {
              const left = (offset / scale) * 100;
              const maxW = r.no_data ? 0 : ((r.max_contribution ?? 0) / scale) * 100;
              const gotW = r.no_data ? 0 : ((r.contribution ?? 0) / scale) * 100;
              if (!r.no_data) offset += r.max_contribution ?? 0;
              return (
                <div
                  key={r.rule_id}
                  id={`res-${r.rule_id}`}
                  className={
                    'grid grid-cols-[24px_minmax(0,1fr)_64px] items-center gap-x-3 gap-y-1.5 rounded-lg px-1 py-1.5 transition-colors sm:grid-cols-[24px_minmax(0,1.3fr)_minmax(120px,1fr)_72px] ' +
                    (hovered === r.rule_id ? 'bg-brand-soft' : '')
                  }
                >
                  <span className="grid h-[22px] w-[22px] place-items-center rounded-full bg-track text-xs font-bold">
                    {numbers[r.rule_id]}
                  </span>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold">{r.label}</div>
                    <div className="text-[13px] text-muted">
                      {r.no_data ? 'нет данных — правило не учтено' : (r.field_value_text ?? '—')}
                    </div>
                  </div>
                  {/* Шкала: на телефоне уходит на отдельную строку под текстом */}
                  <div className="relative col-span-3 col-start-1 h-3 rounded-[3px] bg-canvas sm:col-span-1 sm:col-start-auto" aria-hidden>
                    {!r.no_data && (
                      <>
                        <div className="hatch absolute inset-y-0 rounded-[3px]" style={{ left: `${left}%`, width: `${maxW}%` }} />
                        <div className="absolute inset-y-0 rounded-[3px] bg-ink" style={{ left: `${left}%`, width: `${gotW}%` }} />
                      </>
                    )}
                  </div>
                  <div className="col-start-3 row-start-1 sm:col-start-auto sm:row-start-auto">
                    <Points r={r} />
                  </div>
                </div>
              );
            })}
          </div>
        );
      })}

      <div className="grid grid-cols-[minmax(0,1fr)_64px] items-center gap-3 border-t-2 border-ink pt-3.5 sm:grid-cols-[24px_minmax(0,1.3fr)_minmax(120px,1fr)_72px]">
        <span className="hidden sm:block" />
        <div className="text-base font-bold">Итог</div>
        <div className="relative col-span-2 h-9 sm:col-span-1" aria-hidden>
          <div className="absolute inset-x-0 top-[18px] h-3.5 rounded-[3px] bg-canvas" />
          <div className={`absolute top-[18px] left-0 h-3.5 rounded-[3px] ${tone.bar}`} style={{ width: `${score.total}%` }} />
          <Threshold at={thresholds.consider} label={String(thresholds.consider)} className="border-mid text-mid" />
          <Threshold at={thresholds.participate} label={`${thresholds.participate} — участвовать`} className="border-good text-good" />
        </div>
        <div className={`row-start-1 text-right font-display text-[22px] font-bold sm:row-start-auto ${tone.text}`} style={{ gridColumn: '-2' }}>
          {score.total}%
        </div>
      </div>
    </section>
  );
}

function Threshold({ at, label, className }: { at: number; label: string; className: string }) {
  return (
    <>
      <div className={`absolute top-3 bottom-0 border-l-2 border-dashed ${className}`} style={{ left: `${at}%` }} />
      <span
        className={`absolute -top-1 -translate-x-1/2 text-[11px] whitespace-nowrap ${className}`}
        style={{ left: `${at}%` }}
      >
        {label}
      </span>
    </>
  );
}

function Points({ r }: { r: RuleResult }) {
  if (r.no_data || r.contribution === null) return <span className="text-right text-[13px] text-muted">—</span>;
  const max = r.max_contribution ?? 0;
  const color = r.contribution <= 0.05 ? 'text-bad' : r.contribution < max - 0.05 ? 'text-mid' : 'text-ink';
  return (
    <div className="text-right tabular-nums">
      <b className={color}>{formatContribution(r.contribution)}</b>
      <div className="text-xs text-muted">из {formatContribution(max).replace('+', '')}</div>
    </div>
  );
}

/** Номера правил для ссылок из обоснования: [p4] → 3. Стоп-факторы не нумеруем — они отдельным блоком */
function useRuleNumbers(score: ScoreResult) {
  return useMemo(() => {
    const m: Record<string, number> = {};
    let n = 0;
    GROUPS.forEach((g) =>
      score.rules.filter((r) => r.kind === 'weighted' && r.group === g.key).forEach((r) => (m[r.rule_id] = ++n)),
    );
    return m;
  }, [score.rules]);
}

/** Тёмная карточка «Коротко»: обоснование, где [rule_id] превращается в номер правила */
function Short({ score, setHovered }: { score: ScoreResult; setHovered: (id: string | null) => void }) {
  const numbers = useRuleNumbers(score);
  const parts: ReactNode[] = [];
  const re = /\[([\w.-]+)\]/g;
  const text = score.justification.text;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    const ruleId = m[1]!;
    parts.push(text.slice(last, m.index));
    if (numbers[ruleId]) {
      parts.push(
        <button
          key={m.index}
          type="button"
          onMouseEnter={() => setHovered(ruleId)}
          onMouseLeave={() => setHovered(null)}
          onFocus={() => setHovered(ruleId)}
          onBlur={() => setHovered(null)}
          onClick={() => document.getElementById(`res-${ruleId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
          className="mx-0.5 inline-grid h-5 min-w-5 place-items-center rounded-full bg-white/25 px-1.5 align-text-top text-xs font-bold text-white hover:bg-white hover:text-brand"
          title="Показать правило"
        >
          {numbers[ruleId]}
        </button>,
      );
    }
    last = m.index + m[0].length;
  }
  parts.push(text.slice(last));

  return (
    <section className="rounded-2xl bg-brand p-5 text-white shadow-[0_14px_30px_-14px_rgba(214,32,47,0.6)] sm:p-6">
      <h2 className="mb-2.5 text-[17px] font-bold">Коротко</h2>
      <p className="leading-relaxed">{parts}</p>
      {score.justification.source === 'llm' && (
        <p className="mt-3 text-xs text-white/80">Текст составлен ИИ по уже посчитанной оценке — сама оценка от него не зависит.</p>
      )}
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="min-w-0 break-words">{children ?? '—'}</dd>
    </>
  );
}

const NO_DATA = <span className="text-muted">нет данных</span>;

function CustomerBlock({
  customer: c,
  error,
  inn,
  name,
}: {
  customer: CustomerProfile | null;
  error: string | null;
  inn: string | null;
  name: string | null;
}) {
  const age = c ? yearsSince(c.registration_date) : null;
  return (
    <section className="card">
      <h2 className="mb-3 text-lg font-bold">Заказчик</h2>
      {!c ? (
        <div className="flex flex-col gap-2">
          <Alert tone="mid">{errorText(error ?? 'EGRUL_UNAVAILABLE')} — группа «Заказчик» не учтена в оценке.</Alert>
          <dl className="grid grid-cols-[minmax(7rem,40%)_1fr] gap-x-3 gap-y-2">
            <Row label="Из извещения">{name ?? NO_DATA}</Row>
            <Row label="ИНН">{inn ?? NO_DATA}</Row>
          </dl>
        </div>
      ) : (
        <dl className="grid grid-cols-[minmax(7rem,40%)_1fr] gap-x-3 gap-y-2">
          <Row label="Наименование">{c.name ?? NO_DATA}</Row>
          <Row label="ИНН / ОГРН">
            {c.inn} / {c.ogrn ?? '—'}
          </Row>
          <Row label="Статус">
            <span
              className={`rounded-full px-2 py-0.5 text-sm font-semibold ${c.status === 'active' ? 'bg-good-soft text-good' : c.status === 'unknown' || c.status === 'reorganizing' ? 'bg-mid-soft text-mid' : 'bg-bad-soft text-bad'}`}
            >
              {CUSTOMER_STATUS_LABEL[c.status]}
            </span>
          </Row>
          <Row label="Возраст">
            {age === null ? NO_DATA : `${age} ${plural(age, 'год', 'года', 'лет')} (с ${formatDate(c.registration_date)})`}
          </Row>
          {c.liquidation_date && <Row label="Дата ликвидации">{formatDate(c.liquidation_date)}</Row>}
          <Row label="Отметки о недостоверности">
            {c.unreliable_flags.length ? <span className="text-bad">{c.unreliable_flags.join('; ')}</span> : 'нет'}
          </Row>
          <Row label="Основной вид деятельности">{c.okved_main ?? NO_DATA}</Row>
          <Row label="Адрес">{c.address ?? NO_DATA}</Row>
          <Row label="Источник">
            <span className="text-sm text-muted">{CUSTOMER_SOURCE_LABEL[c.source]}</span>
          </Row>
        </dl>
      )}
    </section>
  );
}

function ProcurementBlock({ p }: { p: Procurement }) {
  const pct = (v: Procurement['bid_security']) => {
    const n = Number(v);
    const total = Number(p.nmck);
    return v === null || !total ? '' : ` (${(Math.round((n / total) * 1000) / 10).toString().replace('.', ',')}%)`;
  };
  return (
    <section className="card">
      <h2 className="mb-3 text-lg font-bold">Закупка</h2>
      <dl className="grid grid-cols-[minmax(7rem,40%)_1fr] gap-x-3 gap-y-2">
        <Row label="НМЦК">
          {formatMoney(p.nmck)}
          {p.currency && p.currency !== 'RUB' && ` (${p.currency})`}
        </Row>
        <Row label="Способ">{p.method_raw ?? (p.method ? METHOD_LABEL[p.method] : NO_DATA)}</Row>
        <Row label="Закон">{p.law ? LAW_LABEL[p.law] : NO_DATA}</Row>
        <Row label="Регион">{p.region ?? NO_DATA}</Row>
        {p.delivery_place && <Row label="Место поставки">{p.delivery_place}</Row>}
        <Row label="Размещена">{formatDate(p.published_at)}</Row>
        <Row label="Подать заявку до">
          <span className={isPast(p.application_deadline) ? 'font-semibold text-bad' : ''}>
            {p.application_deadline ? formatDateTime(p.application_deadline) : NO_DATA}
            {isPast(p.application_deadline) && ' — приём завершён'}
          </span>
        </Row>
        <Row label="Срок поставки">
          {p.delivery_term_text ?? (p.delivery_days ? `${p.delivery_days} дн.` : NO_DATA)}
        </Row>
        <Row label="Обеспечение заявки">{p.bid_security === null ? NO_DATA : formatMoney(p.bid_security) + pct(p.bid_security)}</Row>
        <Row label="Обеспечение контракта">
          {p.contract_security === null ? NO_DATA : formatMoney(p.contract_security) + pct(p.contract_security)}
        </Row>
        <Row label="Ограничения">
          {p.restrictions.length ? p.restrictions.map((r) => RESTRICTION_LABEL[r]).join('; ') : 'нет'}
        </Row>
        <Row label="ОКПД2">{p.okpd2_codes.length ? p.okpd2_codes.join(', ') : NO_DATA}</Row>
      </dl>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        {p.source_url && (
          <a href={p.source_url} target="_blank" rel="noreferrer" className="font-semibold text-brand underline decoration-brand/30 underline-offset-4 hover:decoration-brand">
            Открыть в ЕИС ↗
          </a>
        )}
        <span className="text-xs text-muted" title="Каким способом система прочитала файл">
          Прочитано: {p.parsed_by.startsWith('adapter') ? 'по известному формату' : p.parsed_by === 'universal' ? 'универсальным способом' : 'с помощью ИИ'}
        </span>
      </div>
    </section>
  );
}

function ItemsBlock({ p }: { p: Procurement }) {
  return (
    <section className="card">
      <h2 className="mb-3 text-lg font-bold">Позиции</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th className="py-2 pr-3 font-semibold">Наименование</th>
              <th className="py-2 pr-3 text-right font-semibold">Кол-во</th>
              <th className="py-2 text-right font-semibold">Цена</th>
            </tr>
          </thead>
          <tbody>
            {p.items.map((it, i) => (
              <tr key={i} className="border-b border-line last:border-0">
                <td className="py-2 pr-3">{it.name}</td>
                <td className="py-2 pr-3 text-right whitespace-nowrap tabular-nums">
                  {it.quantity ?? '—'} {it.unit ?? ''}
                </td>
                <td className="py-2 text-right whitespace-nowrap tabular-nums">{it.price === null ? '—' : formatMoney(it.price)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
