/** Полный ответ и исходный вердикт доступны без повторной проверки и изменения Grade. */
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { getAttempt, type AttemptDetailRead } from "../../api/chat";
import { errorText, type Activity } from "../../api/preparation";
import { ErrorState, LoadingState } from "../../components/ui";
import { VerdictCard, verdictFromGrade } from "../workspace/chat/VerdictCard";
import { QualityControl } from "./QualityControl";
export function AttemptDetails({
  projectId,
  activity,
}: {
  projectId: string;
  activity: Activity;
}) {
  const [detail, setDetail] = useState<AttemptDetailRead | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!activity.attempt_id) return;
    const controller = new AbortController();
    getAttempt(projectId, activity.attempt_id, controller.signal)
      .then(setDetail)
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorText(caught));
      });
    return () => controller.abort();
  }, [projectId, activity.attempt_id]);
  if (error)
    return <ErrorState title="Попытка не загрузилась" message={error} />;
  if (!detail) return <LoadingState label="Загружаем попытку" />;
  return (
    <section className="prep-attempt">
      <p>
        {detail.attempt.persona} · {detail.attempt.strictness} ·{" "}
        {new Date(detail.attempt.created_at).toLocaleString("ru-RU")}
      </p>
      <div className="chat-answer-text">{detail.attempt.text}</div>
      {detail.grade ? (
        <VerdictCard
          verdict={verdictFromGrade(detail.grade)}
          answer={detail.attempt.text}
          attemptId={detail.attempt.id}
        />
      ) : (
        <p>Проверка ещё не завершена.</p>
      )}
      <QualityControl
        projectId={projectId}
        attemptId={detail.attempt.id}
        value={activity.quality}
      />
      {activity.chat_id && (
        <Link
          to={`/projects/${projectId}?topic=${activity.node_id}&tab=chat&chat=${activity.chat_id}`}
        >
          Открыть исходный чат
        </Link>
      )}
    </section>
  );
}
