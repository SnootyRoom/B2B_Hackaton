import type { Operator, RuleKind, ScoringRule, Weight } from '../api/types';
import { FIELD_BY_KEY, OPERATOR_LABEL } from '../lib/catalog';
import { describeRule, emptyValue, validateRule, WEIGHT_LABEL } from '../lib/rules';
import ValueEditor from './ValueEditor';

interface Props {
  rule: ScoringRule;
  onChange: (r: ScoringRule) => void;
  onRemove: () => void;
}

/** Карточка правила: формулировка, тип, важность, «включено», значение по типу поля */
export default function RuleCard({ rule, onChange, onRemove }: Props) {
  const field = FIELD_BY_KEY[rule.field];
  const error = rule.enabled ? validateRule(rule) : null;
  const isStop = rule.kind === 'stop';

  /** Любая правка значения пересобирает человеческую формулировку */
  function update(patch: Partial<ScoringRule>) {
    const next = { ...rule, ...patch };
    if ('value' in patch || 'operator' in patch) next.label = describeRule(next);
    onChange(next);
  }

  function setKind(kind: RuleKind) {
    onChange({ ...rule, kind, weight: kind === 'stop' ? null : (rule.weight ?? 2) });
  }

  const idp = `rule-${rule.id}`;

  return (
    <div
      id={idp}
      className={
        'rounded-2xl bg-white p-3.5 shadow-[0_1px_0_rgba(29,31,39,0.04),0_6px_14px_-10px_rgba(29,31,39,0.22)] transition-opacity sm:p-4 ' +
        (isStop ? 'ring-1 ring-bad/30 ' : '') +
        (rule.enabled ? '' : 'opacity-55')
      }
    >
      <div className="flex items-start gap-3">
        <Switch
          id={`${idp}-on`}
          checked={rule.enabled}
          onChange={(enabled) => onChange({ ...rule, enabled })}
          label={rule.enabled ? 'Правило включено' : 'Правило выключено'}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {isStop && (
              <span className="-rotate-[6deg] rounded-md border-2 border-brand px-1.5 font-display text-[10px] font-bold tracking-wider text-brand">
                СТОП
              </span>
            )}
            <span className="font-semibold">{isStop ? rule.label : describeRule(rule)}</span>
          </div>
          {isStop && (
            <p className="mt-0.5 text-sm text-muted">
              Если это условие выполнено — оценка 0 и рекомендация «Пропустить».
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={onRemove}
          className="grid h-9 w-9 place-items-center rounded-lg text-muted hover:bg-bad-soft hover:text-bad"
          aria-label={`Удалить правило «${rule.label}»`}
          title="Удалить правило"
        >
          ✕
        </button>
      </div>

      {rule.enabled && field && (
        <div className="mt-3 flex flex-col gap-3 sm:pl-12">
          <div className="flex flex-wrap items-start gap-2">
            <span className="pt-2 text-sm text-muted">{field.label}</span>
            {field.operators.length > 1 && (
              <select
                id={`${idp}-op`}
                aria-label="Условие"
                className="input py-1.5"
                value={rule.operator}
                onChange={(e) => {
                  const operator = e.target.value as Operator;
                  update({ operator, value: emptyValue(field, operator) });
                }}
              >
                {field.operators.map((o) => (
                  <option key={o} value={o}>
                    {OPERATOR_LABEL[o]}
                  </option>
                ))}
              </select>
            )}
            <div className="min-w-0 basis-full sm:basis-auto sm:flex-1">
              <ValueEditor
                idPrefix={idp}
                field={field}
                operator={rule.operator}
                value={rule.value}
                onChange={(value) => update({ value })}
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
            <label className="flex items-center gap-2">
              <span className="text-muted">Тип</span>
              <select
                id={`${idp}-kind`}
                className="input py-1"
                value={rule.kind}
                onChange={(e) => setKind(e.target.value as RuleKind)}
              >
                <option value="weighted">Критерий (даёт баллы)</option>
                <option value="stop">Стоп-фактор</option>
              </select>
            </label>
            {!isStop && (
              <div className="flex items-center gap-2" role="radiogroup" aria-label="Важность">
                <span className="text-muted">Важность</span>
                <div className="flex rounded-xl bg-track p-0.5">
                  {([1, 2, 3] as Weight[]).map((w) => (
                    <button
                      key={w}
                      type="button"
                      role="radio"
                      aria-checked={rule.weight === w}
                      onClick={() => onChange({ ...rule, weight: w })}
                      className={
                        'rounded-[10px] px-3 py-1.5 font-semibold ' +
                        (rule.weight === w ? 'bg-brand text-white' : 'text-muted hover:text-brand')
                      }
                    >
                      {WEIGHT_LABEL[w]}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {!isStop && rule.soft_margin ? (
              <span className="text-muted" title="Рядом с границей правило даёт часть баллов, а не ноль">
                мягкая граница ±{Math.round(rule.soft_margin * 100)}%
              </span>
            ) : null}
          </div>
          {error && <p className="text-sm text-bad">{error}</p>}
        </div>
      )}
    </div>
  );
}

function Switch({
  id,
  checked,
  onChange,
  label,
}: {
  id: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={label}
      onClick={() => onChange(!checked)}
      className={
        'relative mt-0.5 h-6 w-10 shrink-0 rounded-full transition-colors ' + (checked ? 'bg-brand' : 'bg-line')
      }
    >
      <span
        className={
          'absolute top-1 left-1 h-4 w-4 rounded-full bg-white shadow transition-transform ' +
          (checked ? 'translate-x-4' : '')
        }
      />
    </button>
  );
}
