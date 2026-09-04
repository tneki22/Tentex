/** Сохранённая очередь открывает вопросы билета по одному, сохраняя билет единицей плана. */
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { Button } from "../../components/ui";
import { preparation, errorText, type Queue } from "../../api/preparation";
export function StudyQueue({
  projectId,
  nodeId,
  onSelect,
}: {
  projectId: string;
  nodeId: string | null;
  onSelect: (id: string) => void;
}) {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const date = params.get("queue");
  const [queue, setQueue] = useState<Queue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!date) return;
    const controller = new AbortController();
    preparation
      .queue(projectId, date, false, controller.signal)
      .then(setQueue)
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorText(caught));
      });
    return () => controller.abort();
  }, [projectId, date]);
  if (!date) return null;
  const current = queue?.items[queue.position];
  const expected = current?.topic_ids[queue?.topic_position ?? 0];
  async function move(direction: number, finish = false) {
    if (!queue || !date) return;
    setBusy(true);
    try {
      let position = queue.position;
      let topic = queue.topic_position + direction;
      if (finish) {
        position = queue.items.length;
        topic = 0;
      } else if (topic >= queue.items[position].topic_ids.length) {
        position++;
        topic = 0;
      } else if (topic < 0) {
        position--;
        topic = queue.items[position]?.topic_ids.length - 1;
      }
      const next = await preparation.position(projectId, date, {
        position,
        topic_position: Math.max(0, topic),
      });
      setQueue(next);
      if (next.completed) {
        navigate(`/projects/${projectId}/plan?date=${date}`);
        return;
      }
      const target = next.items[next.position]?.topic_ids[next.topic_position];
      if (target) {
        onSelect(target);
        setParams(
          (previous) => {
            const value = new URLSearchParams(previous);
            value.set("topic", target);
            value.set("tab", "chat");
            return value;
          },
          { replace: true },
        );
      }
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="prep-queue" aria-label="Очередь дня">
      <strong>
        {current
          ? `${queue!.position + 1}/${queue!.items.length} · ${current.title} · вопрос ${queue!.topic_position + 1}/${current.topic_ids.length}`
          : "Загружаем очередь…"}
      </strong>
      <Button
        variant="ghost"
        disabled={
          busy || !queue || (queue.position === 0 && queue.topic_position === 0)
        }
        onClick={() => void move(-1)}
      >
        Назад
      </Button>
      <Button
        variant="secondary"
        disabled={busy || !queue || nodeId !== expected}
        onClick={() => void move(1)}
      >
        Далее
      </Button>
      <Button
        variant="ghost"
        disabled={busy || !queue}
        onClick={() => void move(0, true)}
      >
        Завершить день
      </Button>
      <Button
        variant="ghost"
        onClick={() =>
          setParams(
            (previous) => {
              const value = new URLSearchParams(previous);
              value.delete("queue");
              return value;
            },
            { replace: true },
          )
        }
      >
        Выйти из очереди
      </Button>
      {expected && nodeId !== expected && (
        <p>
          Выбран другой вопрос.{" "}
          <Button variant="ghost" onClick={() => onSelect(expected)}>
            Вернуться к очереди
          </Button>
        </p>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
