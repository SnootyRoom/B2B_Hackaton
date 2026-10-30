// Поле ввода значения правила — форма зависит от типа поля (диапазон, мультивыбор, число, текст).

import { useState } from 'react';
import type { Operator, RuleValue } from '../api/types';
import type { FieldDef } from '../lib/catalog';
import { formatMoney } from '../lib/format';

interface Props {
  field: FieldDef;
  operator: Operator;
  value: RuleValue;
  onChange: (v: RuleValue) => void;
  idPrefix: string;
}

export default function ValueEditor({ field, operator, value, onChange, idPrefix }: Props) {
  if (operator === 'is_false') return null;

  if (operator === 'between') {
    const [a, b]: [number, number] =
      Array.isArray(value) && value.length === 2 ? (value as [number, number]) : [0, 0];
    return (
      <div className="flex flex-wrap items-center gap-2">
        <NumberInput id={`${idPrefix}-from`} field={field} value={a} onChange={(n) => onChange([n, b])} label="от" />
        <NumberInput id={`${idPrefix}-to`} field={field} value={b} onChange={(n) => onChange([a, n])} label="до" />
      </div>
    );
  }

  if (operator === 'gte' || operator === 'lte') {
    return (
      <NumberInput id={`${idPrefix}-num`} field={field} value={typeof value === 'number' ? value : 0} onChange={onChange} />
    );
  }

  if (operator === 'semantic_match') {
    return (
      <textarea
        id={`${idPrefix}-text`}
        rows={2}
        className="input w-full"
        placeholder="Например: разработка и сопровождение программного обеспечения"
        value={typeof value === 'string' ? value : ''}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  const list = Array.isArray(value) ? (value as (string | number)[]).map(String) : [];

  if (field.valueType === 'enum' && field.options) {
    return field.options.length > 10 ? (
      <SearchMultiSelect id={`${idPrefix}-multi`} field={field} selected={list} onChange={onChange} />
    ) : (
      <div className="flex flex-wrap gap-1.5">
        {field.options.map((o) => {
          const on = list.includes(o.value);
          return (
            <button
              key={o.value}
              type="button"
              aria-pressed={on}
              className={'chip ' + (on ? 'chip-on' : '')}
              onClick={() => onChange(on ? list.filter((x) => x !== o.value) : [...list, o.value])}
            >
              {o.label}
            </button>
          );
        })}
      </div>
    );
  }

  // Коды ОКПД2 и слова — через запятую
  return <CommaListInput id={`${idPrefix}-list`} codes={field.valueType === 'codes'} list={list} onChange={onChange} />;
}

function NumberInput({
  id,
  field,
  value,
  onChange,
  label,
}: {
  id: string;
  field: FieldDef;
  value: number;
  onChange: (n: number) => void;
  label?: string;
}) {
  return (
    <label htmlFor={id} className="flex flex-col gap-0.5">
      <span className="flex items-center gap-1.5">
        {label && <span className="text-sm text-muted">{label}</span>}
        <input
          id={id}
          type="number"
          min={0}
          step="any"
          inputMode="decimal"
          className="input w-36"
          value={Number.isFinite(value) ? value : ''}
          onChange={(e) => onChange(e.target.value === '' ? 0 : Number(e.target.value))}
        />
        <span className="text-sm text-muted">{field.unit}</span>
      </span>
      {field.valueType === 'money' && value >= 1000 && (
        <span className="pl-1 text-xs text-muted tabular-nums">{formatMoney(value)}</span>
      )}
    </label>
  );
}

function CommaListInput({
  id,
  codes,
  list,
  onChange,
}: {
  id: string;
  codes: boolean;
  list: string[];
  onChange: (v: string[]) => void;
}) {
  const [text, setText] = useState(list.join(', '));
  return (
    <input
      id={id}
      className="input w-full"
      placeholder={codes ? 'Например: 62, 63.11' : 'Например: сопровождение, разработка'}
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        onChange(
          e.target.value
            .split(/[,;]/)
            .map((s) => s.trim())
            .filter(Boolean),
        );
      }}
    />
  );
}

/** Мультивыбор для длинных списков (субъекты РФ): выбранные чипами + поиск */
function SearchMultiSelect({
  id,
  field,
  selected,
  onChange,
}: {
  id: string;
  field: FieldDef;
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();
  const matches = q
    ? (field.options ?? []).filter((o) => !selected.includes(o.value) && o.label.toLowerCase().includes(q)).slice(0, 8)
    : [];

  return (
    <div className="flex w-full flex-col gap-2">
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selected.map((v) => (
            <button
              key={v}
              type="button"
              className="chip chip-on"
              onClick={() => onChange(selected.filter((x) => x !== v))}
              title="Убрать"
            >
              {v} <span aria-hidden>✕</span>
            </button>
          ))}
        </div>
      )}
      <div className="relative">
        <input
          id={id}
          className="input w-full"
          placeholder="Начните вводить название, например «Томская»"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoComplete="off"
        />
        {matches.length > 0 && (
          <ul className="absolute z-10 mt-1 max-h-64 w-full overflow-auto rounded-lg border border-line bg-white py-1 shadow-lg">
            {matches.map((o) => (
              <li key={o.value}>
                <button
                  type="button"
                  className="w-full px-3 py-2 text-left hover:bg-canvas"
                  onClick={() => {
                    onChange([...selected, o.value]);
                    setQuery('');
                  }}
                >
                  {o.label}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
