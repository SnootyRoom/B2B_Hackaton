import { useMemo, useRef, useState, type DragEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { api, USE_MOCK } from '../api';
import type { Task, TaskFile } from '../api/types';
import { ACCEPTED_EXT, MAX_REG_NUMBERS, UPLOAD_LIMITS, errorText } from '../lib/catalog';
import { lawOfNumber, parseRegNumbers } from '../lib/regNumbers';
import { formatDate, formatFileSize, plural } from '../lib/format';
import { taskIsRunning, useTask } from '../lib/hooks';
import { Alert, ProgressBar } from '../components/ui';
import Breadcrumbs from '../components/Breadcrumbs';

const MB = 1024 * 1024;

/** Проверка до отправки — чтобы не ждать ответа сервера на заведомо неподходящий файл */
function checkFile(f: File): string | null {
  const name = f.name.toLowerCase();
  if (!ACCEPTED_EXT.some((ext) => name.endsWith(ext)))
    return 'Подходят только файлы .xml, .json и архивы .zip';
  // архив распаковывается на сервере, у него свой лимит
  const isZip = name.endsWith('.zip');
  const limitMb = isZip ? UPLOAD_LIMITS.archiveMb : UPLOAD_LIMITS.fileMb;
  if (f.size > limitMb * MB) return `${isZip ? 'Архив' : 'Файл'} больше ${limitMb} МБ`;
  return null;
}

type Mode = 'files' | 'numbers';

export default function UploadPage() {
  const [params, setParams] = useSearchParams();
  const taskId = params.get('task');
  const mode: Mode = params.get('mode') === 'numbers' ? 'numbers' : 'files';
  const [files, setFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const start = useMutation({
    mutationFn: (toSend: File[] | 'demo') => (toSend === 'demo' ? api.uploadDemo() : api.upload(toSend)),
    onSuccess: (r) => {
      setFiles([]);
      setParams({ task: r.task_id });
    },
  });

  function addFiles(list: FileList | null) {
    if (!list) return;
    setFiles((prev) => {
      const names = new Set(prev.map((f) => f.name));
      return [...prev, ...Array.from(list).filter((f) => !names.has(f.name))];
    });
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragOver(false);
    addFiles(e.dataTransfer.files);
  }

  const good = files.filter((f) => !checkFile(f));
  const tooMany = good.length > UPLOAD_LIMITS.maxFiles;

  if (taskId)
    return (
      <TaskView taskId={taskId} onReset={(m) => setParams(m === 'numbers' ? { mode: 'numbers' } : {})} />
    );

  return (
    <div className="mx-auto flex max-w-[880px] flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-[60ch]">
          <p className="mb-2 text-[13px] font-semibold tracking-[0.08em] text-muted uppercase">
            Шаг 2 из 3 · Загрузка
          </p>
          <h1 className="font-display text-[28px] leading-tight font-bold text-balance sm:text-[36px]">
            Добавьте закупки из ЕИС
          </h1>
          <p className="mt-2 text-muted sm:text-base">
            {mode === 'numbers'
              ? 'Вставьте реестровые номера — система сама скачает извещения и оценит каждое.'
              : 'Можно сразу много файлов — каждый оценится по вашим параметрам.'}
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Link to="/profile" className="btn-ghost">
            ← Параметры
          </Link>
          <Link to="/results" className="btn-ghost">
            Далее: результаты →
          </Link>
        </div>
      </div>
      <div
        role="tablist"
        aria-label="Способ загрузки"
        className="flex rounded-2xl bg-white p-1.5 ring-1 ring-line/70"
      >
        {(
          [
            ['files', 'Файлы'],
            ['numbers', 'По номеру'],
          ] as const
        ).map(([m, label]) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={mode === m}
            onClick={() => setParams(m === 'numbers' ? { mode: 'numbers' } : {})}
            className={
              'min-h-11 flex-1 rounded-xl px-3 text-sm font-semibold transition-colors sm:text-[15px] ' +
              (mode === m
                ? 'bg-brand text-white shadow-[0_8px_18px_-10px_rgba(214,32,47,0.7)]'
                : 'text-muted hover:text-brand')
            }
          >
            {label}
          </button>
        ))}
      </div>

      {mode === 'numbers' ? (
        <NumbersForm onStarted={(id) => setParams({ task: id })} />
      ) : (
        <>
          <ol className="grid gap-2.5 sm:grid-cols-3">
            {[
              ['Найдите закупку', 'на zakupki.gov.ru, раздел «Закупки»'],
              ['Сохраните извещение', 'печатную форму в формате XML'],
              ['Перетащите сюда', 'или выберите файлы кнопкой'],
            ].map(([title, text], i) => (
              <li
                key={title}
                className="flex items-start gap-3 rounded-2xl bg-white/70 p-3.5 ring-1 ring-line/70"
              >
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-brand font-display text-xs font-bold text-white">
                  {i + 1}
                </span>
                <span className="text-sm leading-snug">
                  <b className="block">{title}</b>
                  <span className="text-muted">{text}</span>
                </span>
              </li>
            ))}
          </ol>

          <div
            role="button"
            tabIndex={0}
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            className={
              'group flex cursor-pointer flex-col items-center gap-2 rounded-3xl border-2 border-dashed px-4 py-12 text-center transition-all sm:py-16 ' +
              (dragOver
                ? 'scale-[1.01] border-brand bg-brand-tint'
                : 'border-brand/25 bg-white hover:border-brand/60 hover:bg-brand-tint')
            }
          >
            <span
              className={
                'mb-2 grid h-14 w-14 place-items-center rounded-2xl bg-brand text-white shadow-[0_10px_22px_-10px_rgba(214,32,47,0.7)] transition-transform ' +
                (dragOver ? '-translate-y-1' : 'group-hover:-translate-y-0.5')
              }
              aria-hidden
            >
              <svg
                width="26"
                height="26"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 16V4M6 10l6-6 6 6M4 20h16" />
              </svg>
            </span>
            <span className="font-display text-xl font-bold">
              {dragOver ? 'Отпускайте' : 'Перетащите файлы сюда'}
            </span>
            <span className="text-muted">или нажмите, чтобы выбрать на компьютере</span>
            <span className="mt-3 flex flex-wrap justify-center gap-1.5 text-xs text-muted">
              {ACCEPTED_EXT.map((x) => (
                <span key={x} className="rounded-md bg-brand-soft px-2 py-0.5 font-mono text-brand-dark">
                  {x}
                </span>
              ))}
              <span className="px-1 py-0.5">
                файл до {UPLOAD_LIMITS.fileMb} МБ · архив до {UPLOAD_LIMITS.archiveMb} МБ · до{' '}
                {UPLOAD_LIMITS.maxFiles} файлов
              </span>
            </span>
            <input
              ref={inputRef}
              id="file-input"
              type="file"
              multiple
              hidden
              accept={ACCEPTED_EXT.join(',')}
              onChange={(e) => {
                addFiles(e.target.files);
                e.target.value = '';
              }}
            />
          </div>

          {files.length > 0 && (
            <section className="card">
              <div className="mb-2 flex items-center justify-between gap-2">
                <h2 className="font-semibold">
                  Выбрано: {files.length} {plural(files.length, 'файл', 'файла', 'файлов')}
                </h2>
                <button type="button" className="btn-ghost btn-sm" onClick={() => setFiles([])}>
                  Очистить
                </button>
              </div>
              <ul className="max-h-72 divide-y divide-line overflow-auto">
                {files.map((f) => {
                  const problem = checkFile(f);
                  return (
                    <li key={f.name} className="flex items-center gap-3 py-2">
                      <span className="min-w-0 flex-1">
                        <span className="block truncate">{f.name}</span>
                        {problem && (
                          <span className="text-sm text-bad">{problem} — файл не будет отправлен</span>
                        )}
                      </span>
                      <span className="text-sm whitespace-nowrap text-muted">{formatFileSize(f.size)}</span>
                      <button
                        type="button"
                        className="rounded p-1 text-muted hover:text-bad"
                        aria-label={`Убрать ${f.name}`}
                        onClick={() => setFiles(files.filter((x) => x !== f))}
                      >
                        ✕
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}

          {tooMany && (
            <Alert>За один раз можно загрузить до {UPLOAD_LIMITS.maxFiles} файлов. Разбейте на части.</Alert>
          )}
          {start.isError && <Alert>{start.error.message}</Alert>}

          <div className="flex flex-wrap items-center justify-between gap-3">
            {USE_MOCK && (
              <button
                type="button"
                className="btn-ghost"
                disabled={start.isPending}
                onClick={() => start.mutate('demo')}
              >
                Попробовать на примере
              </button>
            )}
            <button
              type="button"
              className="btn-primary ml-auto"
              disabled={good.length === 0 || tooMany || start.isPending}
              onClick={() => start.mutate(good)}
            >
              {start.isPending
                ? 'Отправляем…'
                : good.length
                  ? `Оценить ${good.length} ${plural(good.length, 'файл', 'файла', 'файлов')}`
                  : 'Оценить'}
            </button>
          </div>
          {USE_MOCK && (
            <p className="text-sm text-muted">
              Нет своих файлов? «Попробовать на примере» добавит несколько готовых извещений, чтобы
              посмотреть, как всё работает.
            </p>
          )}
        </>
      )}
    </div>
  );
}

/** Для «Подставить пример» в демо: известные, новые, ненайденные и неправильные номера вперемешку */
const NUMBERS_EXAMPLE = [
  '0365100002326000147',
  '0151300015026000233',
  'https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=0338300012324000045',
  '32616487757',
  '0373100056726000000',
  '0373100056726009999',
  '0373100056726007777',
  '12345',
  '32616487757',
].join('\n');

/** Поле для списка реестровых номеров с проверкой прямо при вводе */
function NumbersForm({ onStarted }: { onStarted: (taskId: string) => void }) {
  const [text, setText] = useState('');
  const parsed = useMemo(() => parseRegNumbers(text), [text]);
  const n = parsed.valid.length;
  const n223 = parsed.valid.filter((x) => lawOfNumber(x) === '223').length;
  const tooMany = n > MAX_REG_NUMBERS;

  const start = useMutation({
    mutationFn: () => api.fetchByNumbers(parsed.valid),
    onSuccess: (r) => onStarted(r.task_id),
  });

  return (
    <>
      <ol className="grid gap-2.5 sm:grid-cols-3">
        {[
          ['Скопируйте номера', 'из поиска ЕИС, таблицы или письма'],
          ['Вставьте в поле', 'каждый с новой строки или через запятую'],
          ['Нажмите «Загрузить»', 'извещения скачаются и оценятся сами'],
        ].map(([title, hint], i) => (
          <li
            key={title}
            className="flex items-start gap-3 rounded-2xl bg-white/70 p-3.5 ring-1 ring-line/70"
          >
            <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-brand font-display text-xs font-bold text-white">
              {i + 1}
            </span>
            <span className="text-sm leading-snug">
              <b className="block">{title}</b>
              <span className="text-muted">{hint}</span>
            </span>
          </li>
        ))}
      </ol>

      <section className="card flex flex-col gap-3.5 sm:p-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <label htmlFor="reg-numbers" className="text-lg font-bold">
            Реестровые номера закупок
          </label>
          {USE_MOCK && !text && (
            <button
              type="button"
              className="text-sm font-semibold text-brand underline decoration-brand/30 underline-offset-4 hover:decoration-brand"
              onClick={() => setText(NUMBERS_EXAMPLE)}
            >
              Подставить пример
            </button>
          )}
        </div>
        <textarea
          id="reg-numbers"
          rows={7}
          spellCheck={false}
          className="input w-full resize-y font-mono text-[15px] leading-relaxed"
          placeholder={'0338300012324000045\n32616487757\nили ссылка на карточку закупки с zakupki.gov.ru'}
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-describedby="reg-numbers-hint"
        />
        <p id="reg-numbers-hint" className="text-sm text-muted">
          Номер — в карточке закупки после «№»: по 44-ФЗ в нём 19 цифр, по 223-ФЗ — 11 (у старых — 18). Можно
          вставить столбец из Excel. Повторы уберём сами.
        </p>

        {text.trim() && (
          <div className="flex flex-col gap-2" aria-live="polite">
            <div className="flex flex-wrap gap-2 text-sm">
              <span
                className={`rounded-full px-3 py-1 font-semibold ${n ? 'bg-good-soft text-good' : 'bg-track text-muted'}`}
              >
                {n ? `✓ ${n} ${plural(n, 'номер', 'номера', 'номеров')}` : 'Номеров пока нет'}
                {n > 0 && n223 > 0 && n223 < n && (
                  <span className="font-normal">
                    {' '}
                    · 44-ФЗ: {n - n223}, 223-ФЗ: {n223}
                  </span>
                )}
              </span>
              {parsed.duplicates > 0 && (
                <span className="rounded-full bg-track px-3 py-1 text-muted">
                  Повторы убраны: {parsed.duplicates}
                </span>
              )}
            </div>
            {parsed.invalid.length > 0 && (
              <div className="rounded-xl bg-bad-soft px-4 py-3 text-sm text-bad">
                <b>Не похоже на номер закупки — пропустим:</b>{' '}
                {parsed.invalid.slice(0, 8).map((x, i) => (
                  <span key={x + i}>
                    {i > 0 && ', '}
                    <span className="font-mono">{x}</span>
                  </span>
                ))}
                {parsed.invalid.length > 8 && ` и ещё ${parsed.invalid.length - 8}`}
              </div>
            )}
          </div>
        )}

        {tooMany && (
          <Alert>За один раз можно загрузить до {MAX_REG_NUMBERS} номеров. Разбейте список на части.</Alert>
        )}
        {start.isError && <Alert>{start.error.message}</Alert>}

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-track pt-4">
          <span className="text-sm text-muted">
            Уже загруженные закупки не задвоятся — их данные обновятся.
          </span>
          <button
            type="button"
            className="btn-primary ml-auto"
            disabled={n === 0 || tooMany || start.isPending}
            onClick={() => start.mutate()}
          >
            {start.isPending
              ? 'Отправляем…'
              : n
                ? `Загрузить ${n} ${plural(n, 'закупку', 'закупки', 'закупок')}`
                : 'Загрузить'}
          </button>
        </div>
      </section>
    </>
  );
}

/** Повторять имеет смысл всё, кроме неверного формата номера */
const retryableFile = (f: TaskFile) => f.status === 'error' && f.error?.code !== 'INVALID_REG_NUMBER';

function TaskView({ taskId, onReset }: { taskId: string; onReset: (mode: Mode) => void }) {
  const [, setParams] = useSearchParams();
  const task = useTask(taskId);
  const t = task.data;
  const retry = useMutation({
    mutationFn: (numbers: string[]) => api.fetchByNumbers(numbers),
    onSuccess: (r) => setParams({ task: r.task_id }),
  });

  if (task.isError) return <Alert>{task.error.message}</Alert>;

  const running = taskIsRunning(t);
  const byNumbers = t?.kind === 'fetch';
  const ok = t?.files.filter((f) => f.status === 'ok').length ?? 0;
  const failed = t?.files.filter((f) => f.status === 'error').length ?? 0;
  const lots = t?.files.reduce((s, f) => s + (f.status === 'ok' ? f.procurement_ids.length : 0), 0) ?? 0;
  const retryable = byNumbers ? (t?.files.filter(retryableFile) ?? []) : [];
  const unit = byNumbers ? (['номер', 'номера', 'номеров'] as const) : (['файл', 'файла', 'файлов'] as const);

  return (
    <div className="mx-auto flex max-w-[880px] flex-col gap-6">
      <Breadcrumbs
        items={[
          { label: 'История', to: '/history' },
          {
            label: t
              ? `Загрузка${byNumbers ? ' по номерам' : ''} от ${formatDate(t.created_at)}, ${new Date(t.created_at).toTimeString().slice(0, 5)}`
              : 'Загрузка',
          },
        ]}
      />
      <section className="card flex flex-col gap-5 sm:p-7">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="mb-1.5 text-[13px] font-semibold tracking-[0.08em] text-muted uppercase">
              {running ? 'Идёт обработка' : t?.status === 'failed' ? 'Не получилось' : 'Готово'}
            </p>
            <h1 className="font-display text-2xl leading-tight font-bold sm:text-3xl">
              {running
                ? byNumbers
                  ? 'Получаем из ЕИС и оцениваем…'
                  : 'Разбираем и оцениваем…'
                : `Оценено ${lots} ${plural(lots, 'закупка', 'закупки', 'закупок')}`}
            </h1>
          </div>
          <div
            className="font-display text-4xl leading-none font-bold tabular-nums sm:text-5xl"
            aria-live="polite"
          >
            {t?.processed ?? 0}
            <span className="text-muted"> / {t?.total ?? '…'}</span>
          </div>
        </div>
        <ProgressBar value={t?.processed ?? 0} max={t?.total ?? 1} />
        {t && t.processed > 0 && (
          <div className="flex flex-wrap gap-2 text-sm">
            <span className="rounded-full bg-good-soft px-3 py-1 text-good">
              Готово: <b>{ok}</b>
            </span>
            {running && (
              <span className="rounded-full bg-track px-3 py-1 text-muted">
                Ждут: <b>{(t.total ?? 0) - t.processed}</b>
              </span>
            )}
            <span
              className={`rounded-full px-3 py-1 ${failed ? 'bg-bad-soft text-bad' : 'bg-track text-muted'}`}
            >
              Ошибок: <b>{failed}</b>
            </span>
          </div>
        )}
        {running && (
          <p className="text-sm text-muted">
            Можно не ждать — результаты появляются по мере обработки. Ошибка по одному номеру не останавливает
            остальные.
          </p>
        )}
        {!running && failed > 0 && t?.status !== 'failed' && (
          <p className="text-sm text-muted">
            Не удалось обработать {failed} {plural(failed, unit[0], unit[1], unit[2])} — причина указана у
            каждого ниже.
          </p>
        )}
        {t?.status === 'failed' && (
          <Alert>
            {byNumbers
              ? 'Не удалось получить ни одну закупку. Проверьте номера и попробуйте ещё раз.'
              : 'Не удалось разобрать ни один файл. Проверьте, что это извещения из ЕИС.'}
          </Alert>
        )}
        {retry.isError && <Alert>{retry.error.message}</Alert>}

        <div className="flex flex-wrap justify-end gap-2.5">
          {!running && retryable.length > 0 && (
            <button
              type="button"
              className="btn-ghost mr-auto"
              disabled={retry.isPending}
              onClick={() => retry.mutate(retryable.map((f) => f.filename))}
            >
              Повторить для ошибок · {retryable.length}
            </button>
          )}
          <button
            type="button"
            className="btn-ghost"
            onClick={() => onReset(byNumbers ? 'numbers' : 'files')}
          >
            Загрузить ещё
          </button>
          {ok > 0 ? (
            <Link to="/results" className="btn-primary">
              Показать результаты →
            </Link>
          ) : (
            <button type="button" className="btn-primary" disabled>
              Показать результаты →
            </button>
          )}
        </div>
      </section>

      {t && t.files.length > 0 && (
        <section className="card">
          <h2 className="mb-2 font-semibold">{byNumbers ? 'Номера' : 'Файлы'}</h2>
          <ul className="divide-y divide-line">
            {t.files.map((f, i) => (
              <FileRow key={f.id} file={f} index={i} task={t} byNumbers={byNumbers} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

/** Совет к ошибке по номеру */
const ADVICE: Record<string, string> = {
  EIS_NOT_FOUND: 'Проверьте номер в карточке закупки или скачайте извещение с zakupki.gov.ru вручную.',
  EIS_UNAVAILABLE: 'Нажмите «Повторить для ошибок» чуть позже или скачайте извещение вручную.',
  INVALID_REG_NUMBER: 'Номер по 44-ФЗ — 19 цифр, по 223-ФЗ — 11 или 18.',
};

const STATUS_VIEW = {
  pending: { icon: '…', cls: 'bg-track text-muted', text: 'Ждёт' },
  processing: { icon: '', cls: 'bg-brand-tint text-brand', text: 'Загружаем' },
  ok: { icon: '✓', cls: 'bg-good-soft text-good', text: 'Готово' },
  error: { icon: '✕', cls: 'bg-bad-soft text-bad', text: 'Ошибка' },
} as const;

function FileRow({
  file,
  index,
  task,
  byNumbers,
}: {
  file: TaskFile;
  index: number;
  task: Task;
  byNumbers: boolean;
}) {
  // Задача обрабатывает записи по порядку: первая ещё не готовая — та, что в работе сейчас
  const current = taskIsRunning(task) && file.status === 'pending' && index === task.processed;
  const state = current ? 'processing' : file.status;
  const v = STATUS_VIEW[state];
  const notFound = file.warnings.some((w) => w.code === 'CUSTOMER_NOT_FOUND');
  return (
    <li
      className="animate-rise flex flex-col gap-2 py-2.5"
      style={{ animationDelay: `${Math.min(index, 12) * 40}ms` }}
    >
      <div className="flex items-start gap-3">
        <span
          className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-sm font-bold ${v.cls}`}
          aria-label={v.text}
          title={v.text}
        >
          {state === 'processing' ? (
            <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-brand/30 border-t-brand" />
          ) : (
            v.icon
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className={`truncate ${byNumbers ? 'font-mono' : ''}`}>{file.filename}</span>
            {byNumbers && /^\d+$/.test(file.filename) && (
              <span className="rounded-md bg-track px-1.5 py-0.5 text-xs text-muted">
                {lawOfNumber(file.filename)}-ФЗ
              </span>
            )}
            {byNumbers && (
              <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${v.cls}`}>{v.text}</span>
            )}
          </div>
          {state === 'processing' && (
            <div className="text-sm text-brand">
              {byNumbers ? 'Скачиваем извещение из ЕИС…' : 'Разбираем файл…'}
            </div>
          )}
          {file.status !== 'pending' && file.error && (
            <div className="text-sm text-bad">{errorText(file.error.code, file.error.message)}</div>
          )}
          {byNumbers && file.status === 'error' && file.error && ADVICE[file.error.code] && (
            <div className="text-sm text-muted">
              {ADVICE[file.error.code]}{' '}
              <Link
                to="/upload"
                className="font-semibold text-brand underline decoration-brand/30 underline-offset-4"
              >
                Загрузить файл
              </Link>
            </div>
          )}
          {file.status !== 'pending' &&
            file.warnings.map((w) => (
              <div
                key={w.code}
                className={`text-sm ${w.code === 'EIS_FALLBACK_SAMPLE' ? 'text-muted' : 'text-mid'}`}
              >
                {errorText(w.code, w.message)}
              </div>
            ))}
          {file.status === 'ok' && file.procurement_ids.length > 1 && (
            <div className="text-sm text-muted">
              {byNumbers ? 'В извещении' : 'В файле'} {file.procurement_ids.length}{' '}
              {plural(file.procurement_ids.length, 'лот', 'лота', 'лотов')} — каждый оценён отдельно
            </div>
          )}
        </div>
        {file.status === 'ok' && file.procurement_ids[0] !== undefined && (
          <Link
            to={`/procurements/${file.procurement_ids[0]}`}
            className="text-sm font-semibold whitespace-nowrap text-brand underline decoration-brand/30 underline-offset-4 hover:decoration-brand"
          >
            Открыть
          </Link>
        )}
      </div>
      {USE_MOCK && notFound && file.status === 'ok' && file.procurement_ids[0] !== undefined && (
        <ManualInn procurementId={file.procurement_ids[0]} />
      )}
    </li>
  );
}

function ManualInn({ procurementId }: { procurementId: string }) {
  const [inn, setInn] = useState('');
  const [taskId, setTaskId] = useState<string | null>(null);
  const send = useMutation({
    mutationFn: () => api.setCustomerInn(procurementId, inn.trim()),
    onSuccess: (r) => setTaskId(r.task_id),
  });
  const task = useTask(taskId);
  const valid = /^\d{10}$|^\d{12}$/.test(inn.trim());

  if (taskId) {
    return (
      <p className="pl-9 text-sm text-muted">
        {taskIsRunning(task.data) ? 'Ищем заказчика и пересчитываем оценку…' : 'Готово — оценка пересчитана.'}
      </p>
    );
  }

  return (
    <form
      className="flex flex-wrap items-center gap-2 pl-9"
      onSubmit={(e) => {
        e.preventDefault();
        if (valid) send.mutate();
      }}
    >
      <label htmlFor={`inn-${procurementId}`} className="text-sm text-muted">
        Знаете ИНН заказчика?
      </label>
      <input
        id={`inn-${procurementId}`}
        inputMode="numeric"
        maxLength={12}
        className="input w-36 py-1.5"
        placeholder="10 цифр"
        value={inn}
        onChange={(e) => setInn(e.target.value.replace(/\D/g, ''))}
      />
      <button className="btn-ghost btn-sm" disabled={!valid || send.isPending}>
        Проверить
      </button>
      {send.isError && <span className="text-sm text-bad">{send.error.message}</span>}
    </form>
  );
}
