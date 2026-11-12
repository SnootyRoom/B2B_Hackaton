import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { ApiError } from '../api/client';
import type { Task } from '../api/types';
import { startRescoreIndicator } from './rescore';

export const qk = {
  me: ['me'] as const,
  profile: ['profile'] as const,
  results: (f: object) => ['results', f] as const,
  procurement: (id: string) => ['procurement', id] as const,
  task: (id: string) => ['task', id] as const,
  uploads: ['uploads'] as const,
  catalog: ['catalog'] as const,
  profiles: ['profiles'] as const,
  profileById: (id: string) => ['profile', id] as const,
  compare: (a: string, b: string) => ['compare', a, b] as const,
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

export function useProfiles() {
  return useQuery({ queryKey: qk.profiles, queryFn: () => api.listProfiles() });
}

export function useProfileById(id: string | undefined) {
  return useQuery({
    queryKey: qk.profileById(id ?? ''),
    queryFn: () => api.getProfile(id!),
    enabled: Boolean(id),
  });
}

/** После любых изменений профилей: список, активный, результаты и сравнение */
export async function refreshProfiles(qc: ReturnType<typeof useQueryClient>) {
  await qc.invalidateQueries({ queryKey: ['profiles'] });
  await qc.invalidateQueries({ queryKey: ['profile'] });
  await qc.invalidateQueries({ queryKey: ['results'] });
  await qc.invalidateQueries({ queryKey: ['compare'] });
}

/** Сделать профиль активным: сервер пересчитывает оценки, полоска под шапкой показывает прогресс */
export function useActivateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (p: { id: string; name: string }) => api.activateProfile(p.id),
    onSuccess: async (r, p) => {
      await refreshProfiles(qc);
      // task_id = null — все оценки уже актуальны, полоска сразу скажет «готово»
      startRescoreIndicator({ taskId: r.task_id, profileName: p.name });
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
      // Пересчёт идёт — строки таблицы обновляются по мере готовности, а не только в конце
      if (t.kind === 'rescore' && isRunning(t)) await qc.invalidateQueries({ queryKey: ['results'] });
      if (!isRunning(t)) {
        // Оценки поменялись — обновим таблицу и карточки
        await qc.invalidateQueries({ queryKey: ['results'] });
        await qc.invalidateQueries({ queryKey: ['procurement'] });
        await qc.invalidateQueries({ queryKey: ['uploads'] });
        await qc.invalidateQueries({ queryKey: ['compare'] });
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
