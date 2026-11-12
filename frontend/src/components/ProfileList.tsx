// Список профилей: слева от редактора, на телефоне — выпадающим списком сверху.
// У каждого профиля меню: «Сделать активным», «Дублировать», «Переименовать» (на месте), «Удалить».

import { useEffect, useRef, useState, useSyncExternalStore, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import type { ProfileSummary, ProfileTemplate } from '../api/types';
import { MAX_PROFILE_NAME, MAX_PROFILES, TEMPLATE_LABEL } from '../lib/catalog';
import { formatDate, plural } from '../lib/format';
import { refreshProfiles, useActivateProfile } from '../lib/hooks';
import { startRescoreIndicator } from '../lib/rescore';
import Modal from './Modal';
import { Alert } from './ui';

interface Props {
  profiles: ProfileSummary[];
  selectedId: string;
  /** Выбрать профиль для редактирования (страница сама спросит про несохранённые правки) */
  onSelect: (id: string) => void;
  llmEnabled: boolean;
}

/** Широкий экран (от 1024 px): список слева; уже — выпадающий список сверху. Рисуем только один вариант */
const WIDE = '(min-width: 1024px)';
function useWide(): boolean {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(WIDE);
      m.addEventListener('change', cb);
      return () => m.removeEventListener('change', cb);
    },
    () => window.matchMedia(WIDE).matches,
  );
}

/** «Новый профиль», «Новый профиль 2» — чтобы не упереться в занятое имя */
function freeName(base: string, taken: string[]): string {
  const lower = new Set(taken.map((t) => t.toLowerCase()));
  if (!lower.has(base.toLowerCase())) return base;
  for (let i = 2; ; i++) if (!lower.has(`${base} ${i}`.toLowerCase())) return `${base} ${i}`;
}

export default function ProfileList({ profiles, selectedId, onSelect, llmEnabled }: Props) {
  const qc = useQueryClient();
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<ProfileSummary | null>(null);
  const activate = useActivateProfile();
  const selected = profiles.find((p) => p.id === selectedId) ?? profiles[0]!;
  const canAdd = profiles.length < MAX_PROFILES;
  const wide = useWide();

  const duplicate = useMutation({
    mutationFn: (id: string) => api.duplicateProfile(id),
    onSuccess: async (copy) => {
      await refreshProfiles(qc);
      onSelect(copy.id);
      setRenamingId(copy.id); // копию обычно сразу переименовывают
    },
  });

  const actions: Actions = {
    activate: (p) => activate.mutate({ id: p.id, name: p.name }),
    duplicate: (p) => duplicate.mutate(p.id),
    rename: (p) => setRenamingId(p.id),
    remove: (p) => setDeleting(p),
    single: profiles.length === 1,
    canAdd,
    busy: activate.isPending || duplicate.isPending,
  };
  const error = activate.error ?? duplicate.error;

  const newButton = (
    <button
      type="button"
      className="btn-primary btn-sm w-full"
      disabled={!canAdd}
      title={canAdd ? undefined : `Можно завести не больше ${MAX_PROFILES} профилей`}
      onClick={() => setCreating(true)}
    >
      + Новый профиль
    </button>
  );

  return (
    <>
      {wide ? (
        <aside className="flex w-[264px] shrink-0 flex-col gap-3 lg:sticky lg:top-24" aria-label="Профили">
          <div className="flex items-baseline justify-between px-1">
            <h2 className="text-lg font-bold">Профили</h2>
            <span className="text-xs text-muted">
              {profiles.length} из {MAX_PROFILES}
            </span>
          </div>
          {newButton}
          <ul className="flex flex-col gap-2">
            {profiles.map((p) => (
              <li key={p.id}>
                {renamingId === p.id ? (
                  <RenameForm profile={p} onDone={() => setRenamingId(null)} />
                ) : (
                  <div
                    className={
                      'group relative flex items-start gap-1 rounded-2xl transition-all ' +
                      (p.id === selected.id
                        ? 'bg-brand-tint ring-2 ring-brand'
                        : 'bg-white ring-1 ring-line hover:ring-brand/50')
                    }
                  >
                    <button
                      type="button"
                      aria-current={p.id === selected.id ? 'true' : undefined}
                      onClick={() => p.id !== selected.id && onSelect(p.id)}
                      className="flex min-w-0 flex-1 flex-col items-start gap-1 py-3 pr-1 pl-4 text-left"
                    >
                      <span className="w-full truncate font-semibold" title={p.name}>
                        {p.name}
                      </span>
                      {p.is_active && <ActiveBadge />}
                      <span className="text-xs text-muted">
                        {p.rules_count} {plural(p.rules_count, 'правило', 'правила', 'правил')} · изменён{' '}
                        {formatDate(p.updated_at)}
                      </span>
                    </button>
                    <ProfileMenu profile={p} actions={actions} />
                  </div>
                )}
              </li>
            ))}
          </ul>
          {error && <Alert>{error.message}</Alert>}
        </aside>
      ) : (
        <section className="card flex flex-col gap-3" aria-label="Профили">
          {renamingId === selected.id ? (
            <RenameForm profile={selected} onDone={() => setRenamingId(null)} />
          ) : (
            <div className="flex flex-col gap-1.5">
              <label htmlFor="profile-select" className="text-sm font-semibold text-muted">
                Профиль
              </label>
              <div className="flex items-center gap-2">
                <select
                  id="profile-select"
                  className="input min-w-0 flex-1 font-semibold"
                  value={selected.id}
                  onChange={(e) => onSelect(e.target.value)}
                >
                  {profiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                      {p.is_active ? ' — активный' : ''}
                    </option>
                  ))}
                </select>
                <ProfileMenu profile={selected} actions={actions} framed />
              </div>
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            {selected.is_active ? (
              <ActiveBadge long />
            ) : (
              <button
                type="button"
                className="btn-ghost btn-sm"
                disabled={activate.isPending}
                onClick={() => actions.activate(selected)}
              >
                {activate.isPending ? 'Переключаем…' : 'Сделать активным'}
              </button>
            )}
            <span className="text-xs text-muted">
              {selected.rules_count} {plural(selected.rules_count, 'правило', 'правила', 'правил')} · изменён{' '}
              {formatDate(selected.updated_at)}
            </span>
          </div>
          {newButton}
          {error && <Alert>{error.message}</Alert>}
        </section>
      )}

      {creating && (
        <NewProfileDialog
          taken={profiles.map((p) => p.name)}
          llmEnabled={llmEnabled}
          onClose={() => setCreating(false)}
          onCreated={(id) => {
            setCreating(false);
            onSelect(id);
          }}
        />
      )}
      {deleting && (
        <DeleteDialog
          profile={deleting}
          nextActive={deleting.is_active ? profiles.find((p) => p.id !== deleting.id) : undefined}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            const fallback = profiles.find((p) => p.id !== deleting.id);
            setDeleting(null);
            if (deleting.id === selected.id && fallback) onSelect(fallback.id);
          }}
        />
      )}
    </>
  );
}

function ActiveBadge({ long = false }: { long?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-brand px-2 py-0.5 text-[11px] font-bold text-white">
      <span className="h-1.5 w-1.5 rounded-full bg-white" aria-hidden />
      {long ? 'Активный — по нему считаются оценки' : 'Активный'}
    </span>
  );
}

interface Actions {
  activate: (p: ProfileSummary) => void;
  duplicate: (p: ProfileSummary) => void;
  rename: (p: ProfileSummary) => void;
  remove: (p: ProfileSummary) => void;
  single: boolean;
  canAdd: boolean;
  busy: boolean;
}

function ProfileMenu({
  profile,
  actions,
  framed = false,
}: {
  profile: ProfileSummary;
  actions: Actions;
  framed?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);

  const item = (
    label: string,
    run: () => void,
    opts: { disabled?: boolean; hint?: string; danger?: boolean } = {},
  ) => (
    <button
      type="button"
      role="menuitem"
      disabled={opts.disabled}
      title={opts.hint}
      onClick={() => {
        setOpen(false);
        run();
      }}
      className={
        'flex w-full flex-col items-start rounded-lg px-3 py-2 text-left text-sm disabled:cursor-not-allowed disabled:opacity-50 ' +
        (opts.danger ? 'text-bad hover:bg-bad-soft' : 'hover:bg-brand-tint')
      }
    >
      <span className="font-semibold">{label}</span>
      {opts.disabled && opts.hint && <span className="text-xs text-muted">{opts.hint}</span>}
    </button>
  );

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Действия с профилем «${profile.name}»`}
        onClick={() => setOpen((o) => !o)}
        className={
          'grid place-items-center rounded-xl text-lg leading-none text-muted hover:bg-white hover:text-ink ' +
          (framed ? 'h-12 w-12 ring-1 ring-line' : 'm-1.5 h-9 w-9')
        }
      >
        ⋯
      </button>
      {open && (
        <div
          role="menu"
          className="absolute top-full right-0 z-30 mt-1 w-60 rounded-2xl bg-white p-1.5 shadow-[0_18px_40px_-14px_rgba(29,31,39,0.35)] ring-1 ring-line"
        >
          {!profile.is_active &&
            item('Сделать активным', () => actions.activate(profile), { disabled: actions.busy })}
          {item('Дублировать', () => actions.duplicate(profile), {
            disabled: !actions.canAdd || actions.busy,
            hint: actions.canAdd ? undefined : `Не больше ${MAX_PROFILES} профилей`,
          })}
          {item('Переименовать', () => actions.rename(profile))}
          {item('Удалить', () => actions.remove(profile), {
            danger: true,
            disabled: actions.single,
            hint: actions.single ? 'Нельзя удалить единственный профиль' : undefined,
          })}
        </div>
      )}
    </div>
  );
}

/** Переименование на месте: Enter — сохранить, Escape — отмена */
function RenameForm({ profile, onDone }: { profile: ProfileSummary; onDone: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(profile.name);
  const rename = useMutation({
    mutationFn: (n: string) => api.renameProfile(profile.id, n),
    onSuccess: async () => {
      await refreshProfiles(qc);
      onDone();
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const n = name.trim();
    if (!n || n === profile.name) return onDone();
    rename.mutate(n);
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2 rounded-2xl bg-white p-3 ring-2 ring-brand">
      <label htmlFor={`rename-${profile.id}`} className="text-xs font-semibold text-muted">
        Название профиля
      </label>
      <input
        id={`rename-${profile.id}`}
        className="input w-full"
        autoFocus
        maxLength={MAX_PROFILE_NAME}
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === 'Escape' && onDone()}
        onFocus={(e) => e.currentTarget.select()}
      />
      {rename.isError && <span className="text-sm text-bad">{rename.error.message}</span>}
      <div className="flex gap-2">
        <button className="btn-primary btn-sm flex-1" disabled={rename.isPending || !name.trim()}>
          {rename.isPending ? 'Сохраняем…' : 'Сохранить'}
        </button>
        <button type="button" className="btn-ghost btn-sm" onClick={onDone}>
          Отмена
        </button>
      </div>
    </form>
  );
}

type Source = 'empty' | 'template' | 'text';

/** «Новый профиль»: пустой (правила по умолчанию), из шаблона или по описанию текстом */
function NewProfileDialog(props: {
  taken: string[];
  llmEnabled: boolean;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const qc = useQueryClient();
  const [source, setSource] = useState<Source>('empty');
  const [template, setTemplate] = useState<ProfileTemplate>('cautious');
  const [text, setText] = useState('');
  const [name, setName] = useState(() => freeName('Новый профиль', props.taken));
  const [nameTouched, setNameTouched] = useState(false);

  // Пока имя не меняли руками, подставляем подходящее по выбранному способу
  useEffect(() => {
    if (nameTouched) return;
    setName(freeName(source === 'template' ? TEMPLATE_LABEL[template].name : 'Новый профиль', props.taken));
  }, [source, template, nameTouched, props.taken]);

  const create = useMutation({
    mutationFn: async () => {
      const n = name.trim();
      if (source === 'template') return api.createProfile({ name: n, template });
      if (source === 'text') {
        const parsed = await api.parseProfileText(text.trim());
        return api.createProfile({
          name: n,
          rules: parsed.rules,
          company_description: parsed.company_description,
          source_text: text.trim(),
        });
      }
      return api.createProfile({ name: n });
    },
    onSuccess: async (p) => {
      await refreshProfiles(qc);
      props.onCreated(p.id);
    },
  });

  const taken = props.taken.some((t) => t.toLowerCase() === name.trim().toLowerCase());
  const ready = name.trim() !== '' && !taken && (source !== 'text' || text.trim().length >= 3);

  const SOURCES: [Source, string, string][] = [
    ['empty', 'Пустой', 'проверки заказчика по умолчанию, остальное — вручную'],
    ['template', 'Из шаблона', 'готовая стратегия, которую можно поправить'],
    [
      'text',
      'Текстом',
      props.llmEnabled ? 'опишите словами — правила составятся сами' : 'разбор текста сейчас недоступен',
    ],
  ];

  return (
    <Modal title="Новый профиль" onClose={props.onClose} wide>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (ready) create.mutate();
        }}
      >
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 text-sm font-semibold">С чего начать</legend>
          <div className="grid gap-2 sm:grid-cols-3">
            {SOURCES.map(([key, label, hint]) => {
              const disabled = key === 'text' && !props.llmEnabled;
              return (
                <label
                  key={key}
                  className={
                    'flex cursor-pointer flex-col gap-0.5 rounded-xl p-3 text-sm ring-1 transition-all has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50 ' +
                    (source === key ? 'bg-brand-tint ring-2 ring-brand' : 'ring-line hover:ring-brand/50')
                  }
                >
                  <input
                    type="radio"
                    name="source"
                    className="sr-only"
                    checked={source === key}
                    disabled={disabled}
                    onChange={() => setSource(key)}
                  />
                  <b>{label}</b>
                  <span className="text-xs text-muted">{hint}</span>
                </label>
              );
            })}
          </div>
        </fieldset>

        {source === 'template' && (
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-2 text-sm font-semibold">Шаблон</legend>
            {(Object.keys(TEMPLATE_LABEL) as ProfileTemplate[]).map((t) => (
              <label
                key={t}
                className={
                  'flex cursor-pointer items-start gap-3 rounded-xl p-3 text-sm ring-1 ' +
                  (template === t ? 'bg-brand-tint ring-2 ring-brand' : 'ring-line hover:ring-brand/50')
                }
              >
                <input
                  type="radio"
                  name="template"
                  className="mt-1 accent-[var(--color-brand)]"
                  checked={template === t}
                  onChange={() => setTemplate(t)}
                />
                <span>
                  <b>{TEMPLATE_LABEL[t].name}</b>
                  <span className="block text-muted">{TEMPLATE_LABEL[t].hint}</span>
                </span>
              </label>
            ))}
          </fieldset>
        )}

        {source === 'text' && (
          <div className="flex flex-col gap-1.5">
            <label htmlFor="new-profile-text" className="text-sm font-semibold">
              Какие закупки вам подходят
            </label>
            <textarea
              id="new-profile-text"
              rows={4}
              className="input w-full resize-y"
              placeholder="Например: только Томская область, от 1 до 5 млн, заказчик действует не меньше трёх лет"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </div>
        )}

        <div className="flex flex-col gap-1.5">
          <label htmlFor="new-profile-name" className="text-sm font-semibold">
            Название
          </label>
          <input
            id="new-profile-name"
            className="input w-full"
            maxLength={MAX_PROFILE_NAME}
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setNameTouched(true);
            }}
          />
          {taken && <span className="text-sm text-bad">Профиль с таким названием уже есть</span>}
          <span className="text-xs text-muted">
            Новый профиль не станет активным сам — оценки не изменятся, пока вы его не включите.
          </span>
        </div>

        {create.isError && <Alert>{create.error.message}</Alert>}
        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={props.onClose}>
            Отмена
          </button>
          <button className="btn-primary" disabled={!ready || create.isPending}>
            {create.isPending ? (source === 'text' ? 'Составляем правила…' : 'Создаём…') : 'Создать'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function DeleteDialog(props: {
  profile: ProfileSummary;
  nextActive?: ProfileSummary;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const qc = useQueryClient();
  const remove = useMutation({
    mutationFn: () => api.deleteProfile(props.profile.id),
    onSuccess: async (r) => {
      await refreshProfiles(qc);
      // Удалили активный — сервер сам назначил новый и пересчитывает оценки
      if (r.task_id) {
        const list = await api.listProfiles();
        const active = list.find((p) => p.is_active);
        startRescoreIndicator({ taskId: r.task_id, profileName: active?.name ?? '' });
      }
      props.onDeleted();
    },
  });

  return (
    <Modal title={`Удалить профиль «${props.profile.name}»?`} onClose={props.onClose}>
      <p className="text-sm">Правила профиля и оценки по нему удалятся. Отменить это нельзя.</p>
      {props.profile.is_active && (
        <p className="rounded-xl bg-mid-soft px-4 py-3 text-sm text-mid">
          Это активный профиль. Активным станет недавно изменённый
          {props.nextActive ? (
            <>
              {' '}
              — <b>«{props.nextActive.name}»</b>
            </>
          ) : null}
          , оценки пересчитаются.
        </p>
      )}
      {remove.isError && <Alert>{remove.error.message}</Alert>}
      <div className="flex flex-wrap justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={props.onClose} autoFocus>
          Отмена
        </button>
        <button
          type="button"
          className="btn bg-bad text-white hover:bg-bad/90"
          disabled={remove.isPending}
          onClick={() => remove.mutate()}
        >
          {remove.isPending ? 'Удаляем…' : 'Удалить профиль'}
        </button>
      </div>
    </Modal>
  );
}
