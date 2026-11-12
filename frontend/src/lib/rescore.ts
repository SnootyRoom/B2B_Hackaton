// Общий на всё приложение «индикатор пересчёта»: когда пользователь сменил активный профиль,
// оценки пересчитываются в фоне, а полоска под шапкой показывает прогресс на любой странице.

import { useSyncExternalStore } from 'react';

export interface RescoreJob {
  /** null — пересчитывать было нечего, сразу «готово» */
  taskId: string | null;
  /** Название профиля, по которому пересчитываем */
  profileName: string;
}

let current: RescoreJob | null = null;
const listeners = new Set<() => void>();

export function startRescoreIndicator(job: RescoreJob) {
  current = job;
  listeners.forEach((l) => l());
}

export function clearRescoreIndicator(taskId?: string | null) {
  if (taskId !== undefined && current?.taskId !== taskId) return;
  current = null;
  listeners.forEach((l) => l());
}

export function useRescoreJob(): RescoreJob | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => current,
  );
}
