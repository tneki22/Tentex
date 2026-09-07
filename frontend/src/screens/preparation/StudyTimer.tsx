/** Компактная группа учёта времени в верхней панели рабочей области. */
import { Pause, Play } from "lucide-react";
import { useState } from "react";
import { Button, IconButton } from "../../components/ui";
import type { useWorkspaceStudyTracking } from "../../hooks/useWorkspaceStudyTracking";
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
        <span>{dayState.loading ? "Проверяем учебный день" : "Время не учитывается"}</span>
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
  return (
    <div className="workspace-timer-group">
      <IconButton
        label={tracking.paused ? "Продолжить учёт" : "Пауза"}
        onClick={() => tracking.setPaused(!tracking.paused)}
      >
        {tracking.paused ? <Play size={15} /> : <Pause size={15} />}
      </IconButton>
      <strong>
        {Math.floor(tracking.seconds / 60)}:
        {String(tracking.seconds % 60).padStart(2, "0")}
      </strong>
      {(tracking.error || dayState.error) && (
        <span className="prep-study-error" role="alert">
          {tracking.error ?? dayState.error}
          <Button variant="ghost" onClick={() => void tracking.retry()}>
            Повторить отправку
          </Button>
        </span>
      )}
    </div>
  );
}
