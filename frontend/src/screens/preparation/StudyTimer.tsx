/** Панель учёта видна только в рабочей области; пропущенное время добавляется явно. */
import { useState } from "react";
import { Button } from "../../components/ui";
import type { useStudyTracking } from "../../hooks/useStudyTracking";
import { preparation, errorText, type Overview } from "../../api/preparation";
import { ManualActivityDialog } from "./ManualActivityDialog";
export function StudyTimer({
  projectId,
  tracking,
}: {
  projectId: string;
  tracking: ReturnType<typeof useStudyTracking>;
}) {
  const [topics, setTopics] = useState<Overview["topics"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <>
      <div className="prep-study-bar">
        <strong>
          {Math.floor(tracking.seconds / 60)}:
          {String(tracking.seconds % 60).padStart(2, "0")} · {tracking.state}
        </strong>
        <Button
          variant="ghost"
          onClick={() => tracking.setPaused(!tracking.paused)}
        >
          {tracking.paused ? "Продолжить учёт" : "Пауза"}
        </Button>
        <Button
          variant="ghost"
          onClick={() => {
            void preparation
              .overview(projectId)
              .then((value) => setTopics(value.topics))
              .catch((caught) => setError(errorText(caught)));
          }}
        >
          Добавить пропущенное время
        </Button>
        {(tracking.error || error) && (
          <span className="prep-study-error" role="alert">
            {tracking.error || error}
            <Button variant="ghost" onClick={() => void tracking.retry()}>
              Повторить отправку
            </Button>
          </span>
        )}
      </div>
      {topics && (
        <ManualActivityDialog
          projectId={projectId}
          topics={topics}
          onClose={() => setTopics(null)}
          onSaved={() => setError(null)}
        />
      )}
    </>
  );
}
