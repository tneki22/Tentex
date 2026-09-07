/** Приглашение общее для всех разделов; начало дня хранится на сервере. */
import { useStudyDayState } from "./useStudyDayState";

/** Перечитывает состояние после начала дня, возврата в окно и смены учебных суток. */
export function usePreparationInvitation(projectId: string, enabled: boolean) {
  const { day } = useStudyDayState(projectId, enabled);
  return Boolean(day?.has_plan && !day.started);
}
