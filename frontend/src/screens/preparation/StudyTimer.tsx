/** Компактная группа учёта времени в верхней панели рабочей области. */
import { Pause, Play } from "lucide-react";
import { Button, IconButton } from "../../components/ui";
import type { useStudyTracking } from "../../hooks/useStudyTracking";
export function StudyTimer({
  tracking,
}: {
  tracking: ReturnType<typeof useStudyTracking>;
}) {
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
      {tracking.error && (
        <span className="prep-study-error" role="alert">
          {tracking.error}
          <Button variant="ghost" onClick={() => void tracking.retry()}>
            Повторить отправку
          </Button>
        </span>
      )}
    </div>
  );
}
