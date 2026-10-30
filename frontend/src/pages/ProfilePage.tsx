import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import type { Group, GroupWeights, ScoringProfileInput, ScoringRule } from '../api/types';
import { FIELDS, GROUPS } from '../lib/catalog';
import { qk, useProfile } from '../lib/hooks';
import { newRule, validateProfile } from '../lib/rules';
import RuleCard from '../components/RuleCard';
import { Alert, Loading } from '../components/ui';

const EMPTY: ScoringProfileInput = {
  name: 'Мой профиль',
  company_description: '',
  source_text: '',
  group_weights: { procurement: 0.4, fit: 0.35, customer: 0.25 },
  thresholds: { participate: 70, consider: 40 },
  rules: [],
};

const EXAMPLE =
  'Мы IT-компания из Томска, разрабатываем и сопровождаем ПО. Интересны аукционы и запросы котировок в Томской и Новосибирской областях от 500 тыс. до 15 млн, обеспечение контракта не больше 10%, не меньше 5 дней на подачу заявки.';
const PLACEHOLDER = 'Например: ' + EXAMPLE;

export default function ProfilePage() {
  const profile = useProfile();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const catalog = useQuery({ queryKey: qk.catalog, queryFn: () => api.getCatalog(), staleTime: Infinity });
  const llmEnabled = catalog.data?.llm_enabled === true;

  const [draft, setDraft] = useState<ScoringProfileInput | null>(null);
  const [unparsed, setUnparsed] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [showErrors, setShowErrors] = useState(false);

  // Черновик заполняется один раз, когда профиль загрузился
  useEffect(() => {
    if (draft === null && !profile.isPending && !profile.isError) {
      const p = profile.data;
      setDraft(
        p
          ? {
              name: p.name,
              company_description: p.company_description,
              source_text: p.source_text,
              group_weights: p.group_weights,
              thresholds: p.thresholds,
              rules: p.rules,
            }
          : EMPTY,
      );
    }
  }, [draft, profile.isPending, profile.isError, profile.data]);

  const parse = useMutation({
    mutationFn: (text: string) => api.parseProfileText(text),
    onSuccess: (r) => {
      setDraft((d) => d && { ...d, rules: r.rules, company_description: r.company_description || d.company_description });
      setUnparsed(r.unparsed);
      setNotice('Правила составлены по вашему тексту. Проверьте их ниже, поправьте при необходимости и сохраните.');
    },
  });

  const save = useMutation({
    mutationFn: async ({ rescore }: { rescore: boolean }) => {
      const { profile: saved, task_id } = await api.saveActiveProfile(draft!, rescore);
      qc.setQueryData(qk.profile, saved);
      return task_id;
    },
    onSuccess: (taskId) => {
      setNotice(null);
      if (taskId) navigate(`/results?task=${encodeURIComponent(taskId)}`);
      else setNotice('Сохранено. Новые загрузки будут оцениваться по этим правилам.');
    },
  });

  if (profile.isError) return <Alert>{profile.error.message}</Alert>;
  if (!draft) return <Loading text="Загружаем параметры…" />;

  const errors = validateProfile(draft);
  const set = (patch: Partial<ScoringProfileInput>) => setDraft({ ...draft, ...patch });
  const setRule = (r: ScoringRule) => set({ rules: draft.rules.map((x) => (x.id === r.id ? r : x)) });
  const removeRule = (id: string) => set({ rules: draft.rules.filter((x) => x.id !== id) });
  const addRule = (fieldKey: string) => {
    const r = newRule(fieldKey);
    set({ rules: [...draft.rules, r] });
    // Прокрутим к новому правилу, чтобы было видно, что оно добавилось
    setTimeout(() => document.getElementById(`rule-${r.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 50);
  };

  const weightSum = draft.group_weights.procurement + draft.group_weights.fit + draft.group_weights.customer;
  const share = (g: Group) => (weightSum > 0 ? Math.round((draft.group_weights[g] / weightSum) * 100) : 0);

  function trySave(rescore: boolean) {
    setShowErrors(true);
    if (errors.length === 0) save.mutate({ rescore });
  }

  const saveButtons = (
    <>
      {showErrors && errors.length > 0 && (
        <Alert>
          Исправьте, чтобы сохранить:
          <ul className="mt-1 list-inside list-disc">
            {errors.slice(0, 5).map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </Alert>
      )}
      {save.isError && <Alert>{save.error.message}</Alert>}
      <button type="button" className="btn-primary w-full" disabled={save.isPending} onClick={() => trySave(true)}>
        {save.isPending ? 'Сохраняем…' : 'Сохранить и пересчитать'}
      </button>
      <button type="button" className="btn-ghost w-full" disabled={save.isPending} onClick={() => trySave(false)}>
        Только сохранить
      </button>
    </>
  );

  return (
    <div className="flex flex-col gap-7 pb-28 md:pb-0">
      <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="max-w-[60ch]">
        <p className="mb-2 text-[13px] font-semibold tracking-[0.08em] text-muted uppercase">Шаг 1 из 3 · Ваш профиль поставщика</p>
        <h1 className="font-display text-[28px] leading-tight font-bold text-balance sm:text-[36px]">
          Какие закупки вам подходят
        </h1>
        <p className="mt-2 text-muted sm:text-base">
          Опишите это своими словами — система составит правила. По ним будет оценена каждая загруженная закупка.
        </p>
      </div>
        <Link to="/upload" className="btn-ghost shrink-0">
          Далее: загрузка →
        </Link>
      </div>

      <div className="flex flex-wrap items-start gap-6">
        {/* Левая колонка: текст и правила */}
        <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-6">
          <section className="card flex flex-col gap-3.5 sm:p-6">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <label className="text-lg font-bold" htmlFor="source-text">
                Опишите словами
              </label>
              {!draft.source_text && (
                <button
                  type="button"
                  className="text-sm font-semibold text-brand underline decoration-brand/30 underline-offset-4 hover:decoration-brand"
                  onClick={() => set({ source_text: EXAMPLE })}
                >
                  Подставить пример
                </button>
              )}
            </div>
            <textarea
              id="source-text"
              rows={4}
              className="input w-full resize-y text-base leading-relaxed"
              placeholder={PLACEHOLDER}
              value={draft.source_text}
              onChange={(e) => set({ source_text: e.target.value })}
            />
            {llmEnabled ? (
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  className="btn-primary"
                  disabled={parse.isPending || draft.source_text.trim().length < 10}
                  onClick={() => parse.mutate(draft.source_text)}
                >
                  {parse.isPending ? (
                    <>
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" aria-hidden />
                      Разбираем…
                    </>
                  ) : (
                    'Составить правила'
                  )}
                </button>
                <span className="text-sm text-muted">Текущие правила заменятся составленными по тексту</span>
              </div>
            ) : (
              <p className="text-sm text-muted">Автоматический разбор текста сейчас недоступен — задайте правила ниже вручную.</p>
            )}
            {parse.isError && <Alert>{parse.error.message || 'Не удалось разобрать текст, задайте правила вручную'}</Alert>}

            <div className="mt-1 border-t border-track pt-4">
              <label className="label" htmlFor="company">
                Чем занимается ваша компания
                <span className="ml-1 font-normal text-muted">— по этому описанию ищем похожие закупки</span>
              </label>
              <input
                id="company"
                className="input w-full"
                placeholder="Например: разработка и сопровождение программного обеспечения"
                value={draft.company_description}
                onChange={(e) => set({ company_description: e.target.value })}
              />
            </div>
          </section>

          {notice && (
            <div className="animate-rise">
              <Alert tone="good">{notice}</Alert>
            </div>
          )}

          {unparsed.length > 0 && (
            <section className="animate-rise rounded-2xl bg-mid-soft p-5">
              <h2 className="font-bold text-mid">Эти фразы система не поняла</h2>
              <div className="mt-2 flex flex-wrap gap-2">
                {unparsed.map((u) => (
                  <span key={u} className="rounded-full bg-white px-3 py-1 text-sm">
                    «{u}»
                  </span>
                ))}
              </div>
              <p className="mt-2.5 text-sm text-muted">
                Уточните их цифрами (например, «до 15 млн» вместо «крупные») или добавьте правило вручную.
              </p>
            </section>
          )}

          {GROUPS.map((g, gi) => {
            const rules = draft.rules.filter((r) => r.group === g.key);
            const fields = FIELDS.filter((f) => f.group === g.key);
            return (
              <section
                key={g.key}
                className="animate-rise flex flex-col gap-3 rounded-3xl bg-white/60 p-3 ring-1 ring-line/70 sm:p-4"
                style={{ animationDelay: `${gi * 60}ms` }}
                aria-labelledby={`group-${g.key}`}
              >
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-1 pt-1">
                  <div className="flex items-center gap-3">
                    <span className={`h-9 w-1.5 rounded-full ${GROUP_COLOR[g.key]}`} aria-hidden />
                    <div>
                      <h2 id={`group-${g.key}`} className="font-display text-lg font-bold">
                        {g.label}
                      </h2>
                      <p className="text-sm text-muted">{g.hint}</p>
                    </div>
                  </div>
                  <label className="flex items-center gap-2.5 text-sm" htmlFor={`weight-${g.key}`}>
                    <span className="text-muted">Вес</span>
                    <input
                      id={`weight-${g.key}`}
                      type="range"
                      min={0}
                      max={100}
                      step={5}
                      className="w-28"
                      value={Math.round(draft.group_weights[g.key] * 100)}
                      onChange={(e) =>
                        set({
                          group_weights: { ...draft.group_weights, [g.key]: Number(e.target.value) / 100 } as GroupWeights,
                        })
                      }
                    />
                    <b className="w-12 text-right font-display tabular-nums">{share(g.key)}%</b>
                  </label>
                </div>

                {rules.length === 0 && (
                  <p className="rounded-2xl border-2 border-dashed border-line p-4 text-center text-sm text-muted">
                    Правил нет — эта группа не влияет на оценку
                  </p>
                )}
                {rules.map((r) => (
                  <RuleCard key={r.id} rule={r} onChange={setRule} onRemove={() => removeRule(r.id)} />
                ))}

                <label className="sr-only" htmlFor={`add-${g.key}`}>
                  Добавить правило в группу «{g.label}»
                </label>
                <select
                  id={`add-${g.key}`}
                  className="input cursor-pointer border-2 border-dashed bg-transparent text-center font-semibold text-muted hover:border-brand/50 hover:text-brand"
                  value=""
                  onChange={(e) => e.target.value && addRule(e.target.value)}
                >
                  <option value="">+ Добавить правило</option>
                  {fields.map((f) => (
                    <option key={f.key} value={f.key}>
                      {f.label}
                    </option>
                  ))}
                </select>
              </section>
            );
          })}
        </div>

        {/* Правая колонка: как будет считаться оценка + сохранение */}
        <aside className="flex min-w-0 flex-[1_1_300px] flex-col gap-4 md:sticky md:top-24">
          <section className="card flex flex-col gap-5 sm:p-6">
            <div>
              <h2 className="text-lg font-bold">Как будет считаться оценка</h2>
              <p className="mt-1 text-sm text-muted">Доля каждой группы в итоговых 100 баллах</p>
            </div>
            <div className="flex flex-col gap-2.5">
              <div className="flex h-3 gap-[3px] overflow-hidden rounded-full" aria-hidden>
                {GROUPS.map((g) =>
                  share(g.key) > 0 ? (
                    <div key={g.key} className={`${GROUP_COLOR[g.key]} transition-[flex-grow] duration-300`} style={{ flexGrow: share(g.key) }} />
                  ) : null,
                )}
              </div>
              <ul className="flex flex-col gap-1.5 text-sm">
                {GROUPS.map((g) => (
                  <li key={g.key} className="flex items-center gap-2">
                    <span className={`h-2.5 w-2.5 rounded-full ${GROUP_COLOR[g.key]}`} aria-hidden />
                    <span className="flex-1">{g.label}</span>
                    <b className="tabular-nums">{share(g.key)}%</b>
                  </li>
                ))}
              </ul>
            </div>

            <div className="flex flex-col gap-3 border-t border-track pt-5">
              <h3 className="font-bold">Пороги рекомендаций</h3>
              {/* Шкала 0–100 с тремя зонами — сразу видно, где какая рекомендация */}
              <div className="flex h-3 overflow-hidden rounded-full" aria-hidden>
                <div className="bg-bad" style={{ width: `${draft.thresholds.consider}%` }} />
                <div className="bg-mid-bar" style={{ width: `${draft.thresholds.participate - draft.thresholds.consider}%` }} />
                <div className="flex-1 bg-good" />
              </div>
              <div className="flex justify-between text-xs text-muted tabular-nums">
                <span>0</span>
                <span>100</span>
              </div>
              <ThresholdSlider
                id="th-participate"
                label="Участвовать от"
                tone="text-good"
                value={draft.thresholds.participate}
                min={10}
                max={100}
                onChange={(v) => set({ thresholds: { ...draft.thresholds, participate: v } })}
              />
              <ThresholdSlider
                id="th-consider"
                label="Рассмотреть от"
                tone="text-mid"
                value={draft.thresholds.consider}
                min={0}
                max={95}
                onChange={(v) => set({ thresholds: { ...draft.thresholds, consider: v } })}
              />
              <p className="text-sm text-muted">
                Ниже {draft.thresholds.consider} — <span className="font-semibold text-bad">Пропустить</span>
              </p>
            </div>

            <div className="hidden flex-col gap-2.5 border-t border-track pt-5 md:flex">{saveButtons}</div>
          </section>
        </aside>
      </div>

      {/* Телефон: кнопки сохранения парят внизу экрана */}
      <div className="fixed inset-x-3 bottom-3 z-20 flex flex-col gap-2 rounded-2xl bg-white/95 p-3 shadow-[0_12px_40px_-12px_rgba(29,31,39,0.3)] backdrop-blur md:hidden">
        {saveButtons}
      </div>
    </div>
  );
}

const GROUP_COLOR: Record<Group, string> = {
  procurement: 'bg-brand',
  fit: 'bg-[#EE7C85]',
  customer: 'bg-[#F6C3C7]',
};

function ThresholdSlider(props: {
  id: string;
  label: string;
  tone: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  return (
    <label htmlFor={props.id} className="flex items-center gap-3">
      <span className={`w-32 shrink-0 text-sm font-semibold ${props.tone}`}>{props.label}</span>
      <input
        id={props.id}
        type="range"
        min={props.min}
        max={props.max}
        step={5}
        className="min-w-0 flex-1"
        value={props.value}
        onChange={(e) => props.onChange(Number(e.target.value))}
      />
      <b className="w-8 text-right font-display tabular-nums">{props.value}</b>
    </label>
  );
}
