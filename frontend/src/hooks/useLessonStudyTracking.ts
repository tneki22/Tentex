/** Учебниковый таймер использует тот же механизм активности вкладки и буфер, что экзамен. */
import { useCallback, useEffect, useState } from "react";
import { lessonPlanning, type LessonPlanningOverview } from "../api/lessonPlanning";
import { errorText } from "../api/preparation";
import { useStudyTracking } from "./useStudyTracking";

export function useLessonStudyTracking(projectId: string, lessonId: string | null, enabled: boolean) {
  const [overview, setOverview] = useState<LessonPlanningOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!enabled) return;
    try {
      const value = await lessonPlanning.overview(projectId, signal);
      if (!signal?.aborted) {
        setOverview(value);
        setError(null);
      }
    } catch (caught) {
      if (!signal?.aborted) {
        setOverview(null);
        setError(errorText(caught));
      }
    }
  }, [projectId, enabled]);

  useEffect(() => {
    if (!enabled) {
      setOverview(null);
      setError(null);
      return;
    }
    const controller = new AbortController();
    const update = () => void refresh(controller.signal);
    update();
    window.addEventListener("focus", update);
    window.addEventListener("tentex-lesson-planning-changed", update);
    const timer = window.setInterval(update, 60_000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      window.removeEventListener("focus", update);
      window.removeEventListener("tentex-lesson-planning-changed", update);
    };
  }, [enabled, refresh]);

  const tracking = useStudyTracking(projectId, lessonId, "lesson", {
    lesson: true,
    enabled: enabled && Boolean(overview) && Boolean(lessonId),
    studyDate: overview?.today ?? "",
    initialSeconds: overview?.today_by_lesson.find((row) => row.lesson_id === lessonId)?.seconds ?? 0,
  });
  return { tracking, error, loading: enabled && !overview && !error, hasLesson: Boolean(lessonId) };
}
