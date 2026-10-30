import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { ApiError } from '../api/client';
import type { Task } from '../api/types';

export const qk = {
  me: ['me'] as const,
  profile: ['profile'] as const,
  results: (f: object) => ['results', f] as const,
  procurement: (id: string) => ['procurement', id] as const,
  task: (id: string) => ['task', id] as const,
  uploads: ['uploads'] as const,
  catalog: ['catalog'] as const,
};

/** Текущий пользователь. null — не вошёл. */
export function useMe() {
  return useQuery({
    queryKey: qk.me,
    queryFn: async () => {
      try {
        return await api.me();
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    retry: false,
    staleTime: Infinity,
  });
}

/** Активный профиль. null — профиля ещё нет (первый вход). */
export function useProfile() {
  return useQuery({
    queryKey: qk.profile,
    queryFn: async () => {
      try {
        return await api.getActiveProfile();
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
  });
}

const isRunning = (t: Task | undefined) => !t || t.status === 'queued' || t.status === 'processing';

/** Опрос фоновой задачи раз в 1,5 с, пока она не закончится (аналитика: 1–2 с) */
export function useTask(id: string | null, onFinish?: (t: Task) => void) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: qk.task(id ?? ''),
    enabled: Boolean(id),
    queryFn: async () => {
      const t = await api.getTask(id!);
      if (!isRunning(t)) {
        // Оценки поменялись — обновим таблицу и карточки
        await qc.invalidateQueries({ queryKey: ['results'] });
        await qc.invalidateQueries({ queryKey: ['procurement'] });
        await qc.invalidateQueries({ queryKey: ['uploads'] });
        onFinish?.(t);
      }
      return t;
    },
    refetchInterval: (q) => (isRunning(q.state.data) ? 1500 : false),
  });
}

export function taskIsRunning(t: Task | undefined): boolean {
  return isRunning(t);
}
