/** Компактная группа учёта времени в верхней панели рабочей области. */
import { Pause, Play } from "lucide-react";
import { useState } from "react";
import { Button, IconButton } from "../../components/ui";
import type { useWorkspaceStudyTracking } from "../../hooks/useWorkspaceStudyTracking";
import type { useLessonStudyTracking } from "../../hooks/useLessonStudyTracking";
import type { useStudyTracking } from "../../hooks/useStudyTracking";

function TimerControls({ tracking, error }: {
  tracking: ReturnType<typeof useStudyTracking>;
  error?: string | null;
}) {
  return (
    <div className="workspace-timer-group">
      <IconButton
        label={tracking.paused ? "Продолжить учёт" : "Пауза"}
        onClick={() => tracking.setPaused(!tracking.paused)}
      >
        {tracking.paused ? <Play size={15} /> : <Pause size={15} />}
      </IconButton>
      <strong>{Math.floor(tracking.seconds / 60)}:{String(tracking.seconds % 60).padStart(2, "0")}</strong>
      {(tracking.error || error) && (
        <span className="prep-study-error" role="alert">
          {tracking.error ?? error}
          {tracking.error && <Button variant="ghost" onClick={() => void tracking.retry()}>Повторить отправку</Button>}
        </span>
      )}
    </div>
  );
}

/** Учебник начинает учёт при включённом разделе и открытом готовом уроке. */
export function LessonStudyTimer({ study }: { study: ReturnType<typeof useLessonStudyTracking> }) {
  if (study.loading) return <div className="workspace-timer-group is-not-started">Проверяем занятия</div>;
  if (!study.hasLesson || study.error) {
    return <div className="workspace-timer-group is-not-started">
      <span title="Время учитывается только за открытым готовым уроком">Без учёта</span>
      {study.error && <span className="prep-study-error" role="alert">{study.error}</span>}
    </div>;
  }
  return <TimerControls tracking={study.tracking} />;
}
export function StudyTimer({
  study,
}: {
  study: ReturnType<typeof useWorkspaceStudyTracking>;
}) {
  const [starting, setStarting] = useState(false);
  const { dayState, tracking } = study;
  if (!dayState.day?.started) {
    return (
      <div className="workspace-timer-group is-not-started">
        <span title={dayState.loading ? "Проверяем учебный день" : "Время не учитывается"}>{dayState.loading ? "Проверяем день" : "Без учёта"}</span>
        {!dayState.loading && (
          <Button
            variant="secondary"
            disabled={starting}
            onClick={() => {
              setStarting(true);
              void dayState.start()
                .catch(() => undefined)
                .finally(() => setStarting(false));
            }}
          >
            {starting ? "Начинаем…" : "Начать день"}
          </Button>
        )}
        {dayState.error && <span className="prep-study-error" role="alert">{dayState.error}</span>}
      </div>
    );
  }
  return <TimerControls tracking={tracking} error={dayState.error} />;
}
