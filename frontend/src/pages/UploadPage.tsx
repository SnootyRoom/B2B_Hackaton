import { useRef, useState, type DragEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { api, USE_MOCK } from '../api';
import type { TaskFile } from '../api/types';
import { ACCEPTED_EXT, UPLOAD_LIMITS, errorText } from '../lib/catalog';
import { formatDate, formatFileSize, plural } from '../lib/format';
import { taskIsRunning, useTask } from '../lib/hooks';
import { Alert, ProgressBar } from '../components/ui';
import Breadcrumbs from '../components/Breadcrumbs';

const MB = 1024 * 1024;

/** Проверка до отправки — чтобы не ждать ответа сервера на заведомо неподходящий файл */
function checkFile(f: File): string | null {
  const name = f.name.toLowerCase();
  if (!ACCEPTED_EXT.some((ext) => name.endsWith(ext))) return 'Подходят только файлы .xml и .json';
  if (f.size > UPLOAD_LIMITS.fileMb * MB) return `Файл больше ${UPLOAD_LIMITS.fileMb} МБ`;
  return null;
}

export default function UploadPage() {
  const [params, setParams] = useSearchParams();
  const taskId = params.get('task');
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

  if (taskId) return <TaskView taskId={taskId} onReset={() => setParams({})} />;

  return (
    <div className="mx-auto flex max-w-[880px] flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-[60ch]">
          <p className="mb-2 text-[13px] font-semibold tracking-[0.08em] text-muted uppercase">Шаг 2 из 3 · Загрузка</p>
          <h1 className="font-display text-[28px] leading-tight font-bold text-balance sm:text-[36px]">Добавьте закупки из ЕИС</h1>
          <p className="mt-2 text-muted sm:text-base">Можно сразу много файлов — каждый оценится по вашим параметрам.</p>
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

      <ol className="grid gap-2.5 sm:grid-cols-3">
        {[
          ['Найдите закупку', 'на zakupki.gov.ru, раздел «Закупки»'],
          ['Сохраните извещение', 'печатную форму в формате XML'],
          ['Перетащите сюда', 'или выберите файлы кнопкой'],
        ].map(([title, text], i) => (
          <li key={title} className="flex items-start gap-3 rounded-2xl bg-white/70 p-3.5 ring-1 ring-line/70">
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
          (dragOver ? 'scale-[1.01] border-brand bg-brand-tint' : 'border-brand/25 bg-white hover:border-brand/60 hover:bg-brand-tint')
        }
      >
        <span
          className={
            'mb-2 grid h-14 w-14 place-items-center rounded-2xl bg-brand text-white shadow-[0_10px_22px_-10px_rgba(214,32,47,0.7)] transition-transform ' +
            (dragOver ? '-translate-y-1' : 'group-hover:-translate-y-0.5')
          }
          aria-hidden
        >
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 16V4M6 10l6-6 6 6M4 20h16" />
          </svg>
        </span>
        <span className="font-display text-xl font-bold">{dragOver ? 'Отпускайте' : 'Перетащите файлы сюда'}</span>
        <span className="text-muted">или нажмите, чтобы выбрать на компьютере</span>
        <span className="mt-3 flex flex-wrap justify-center gap-1.5 text-xs text-muted">
          {ACCEPTED_EXT.map((x) => (
            <span key={x} className="rounded-md bg-brand-soft px-2 py-0.5 font-mono text-brand-dark">
              {x}
            </span>
          ))}
          <span className="px-1 py-0.5">
            файл до {UPLOAD_LIMITS.fileMb} МБ · до {UPLOAD_LIMITS.maxFiles} файлов
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
                    {problem && <span className="text-sm text-bad">{problem} — файл не будет отправлен</span>}
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

      {tooMany && <Alert>За один раз можно загрузить до {UPLOAD_LIMITS.maxFiles} файлов. Разбейте на части.</Alert>}
      {start.isError && <Alert>{start.error.message}</Alert>}

      <div className="flex flex-wrap items-center justify-between gap-3">
        {USE_MOCK && (
          <button type="button" className="btn-ghost" disabled={start.isPending} onClick={() => start.mutate('demo')}>
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
          Нет своих файлов? «Попробовать на примере» добавит несколько готовых извещений, чтобы посмотреть, как всё работает.
        </p>
      )}
    </div>
  );
}

function TaskView({ taskId, onReset }: { taskId: string; onReset: () => void }) {
  const task = useTask(taskId);
  const t = task.data;

  if (task.isError) return <Alert>{task.error.message}</Alert>;

  const running = taskIsRunning(t);
  const ok = t?.files.filter((f) => f.status === 'ok').length ?? 0;
  const failed = t?.files.filter((f) => f.status === 'error').length ?? 0;
  const lots = t?.files.reduce((s, f) => s + (f.status === 'ok' ? f.procurement_ids.length : 0), 0) ?? 0;

  return (
    <div className="mx-auto flex max-w-[880px] flex-col gap-6">
      <Breadcrumbs
        items={[
          { label: 'История', to: '/history' },
          { label: t ? `Загрузка от ${formatDate(t.created_at)}, ${new Date(t.created_at).toTimeString().slice(0, 5)}` : 'Загрузка' },
        ]}
      />
      <section className="card flex flex-col gap-5 sm:p-7">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="mb-1.5 text-[13px] font-semibold tracking-[0.08em] text-muted uppercase">
              {running ? 'Идёт обработка' : t?.status === 'failed' ? 'Не получилось' : 'Готово'}
            </p>
            <h1 className="font-display text-2xl leading-tight font-bold sm:text-3xl">
              {running ? 'Разбираем и оцениваем…' : `Оценено ${lots} ${plural(lots, 'закупка', 'закупки', 'закупок')}`}
            </h1>
          </div>
          <div className="font-display text-4xl leading-none font-bold tabular-nums sm:text-5xl" aria-live="polite">
            {t?.processed ?? 0}
            <span className="text-muted"> / {t?.total ?? '…'}</span>
          </div>
        </div>
        <ProgressBar value={t?.processed ?? 0} max={t?.total ?? 1} />
        {running && <p className="text-sm text-muted">Можно не ждать — результаты появляются по мере обработки.</p>}
        {!running && failed > 0 && t?.status !== 'failed' && (
          <p className="text-sm text-muted">
            Не удалось разобрать {failed} {plural(failed, 'файл', 'файла', 'файлов')} — причина указана ниже.
          </p>
        )}
        {t?.status === 'failed' && <Alert>Не удалось разобрать ни один файл. Проверьте, что это извещения из ЕИС.</Alert>}

        <div className="flex flex-wrap justify-end gap-2.5">
          <button type="button" className="btn-ghost" onClick={onReset}>
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
          <h2 className="mb-2 font-semibold">Файлы</h2>
          <ul className="divide-y divide-line">
            {t.files.map((f, i) => (
              <FileRow key={f.id} file={f} index={i} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

const STATUS_VIEW = {
  pending: { icon: '…', cls: 'bg-track text-muted', text: 'Ждёт обработки' },
  ok: { icon: '✓', cls: 'bg-good-soft text-good', text: 'Готово' },
  error: { icon: '✕', cls: 'bg-bad-soft text-bad', text: 'Ошибка' },
} as const;

function FileRow({ file, index }: { file: TaskFile; index: number }) {
  const v = STATUS_VIEW[file.status];
  const notFound = file.warnings.some((w) => w.code === 'CUSTOMER_NOT_FOUND');
  return (
    <li className="animate-rise flex flex-col gap-2 py-2.5" style={{ animationDelay: `${Math.min(index, 12) * 40}ms` }}>
      <div className="flex items-start gap-3">
        <span
          className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-sm font-bold ${v.cls}`}
          aria-label={v.text}
          title={v.text}
        >
          {v.icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate">{file.filename}</div>
          {file.status !== 'pending' && file.error && <div className="text-sm text-bad">{errorText(file.error.code, file.error.message)}</div>}
          {file.status !== 'pending' && file.warnings.map((w) => (
            <div key={w.code} className="text-sm text-mid">
              {errorText(w.code, w.message)}
            </div>
          ))}
          {file.status === 'ok' && file.procurement_ids.length > 1 && (
            <div className="text-sm text-muted">
              В файле {file.procurement_ids.length} лота — каждый оценён отдельно
            </div>
          )}
        </div>
        {file.status === 'ok' && file.procurement_ids[0] !== undefined && (
          <Link to={`/procurements/${file.procurement_ids[0]}`} className="text-sm font-semibold whitespace-nowrap text-brand underline decoration-brand/30 underline-offset-4 hover:decoration-brand">
            Открыть
          </Link>
        )}
      </div>
      {USE_MOCK && notFound && file.status === 'ok' && file.procurement_ids[0] !== undefined && <ManualInn procurementId={file.procurement_ids[0]} />}
    </li>
  );
}

/** Ручной ввод ИНН, если заказчик не найден в ЕГРЮЛ */
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
