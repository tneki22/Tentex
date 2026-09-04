/** Ручная запись всегда остаётся отличимой от автоматического учёта и проверки. */
import { useState } from "react";
import { Button, Dialog, Field, Select, ErrorState } from "../../components/ui";
import {
  preparation,
  errorText,
  type Activity,
  type Overview,
} from "../../api/preparation";
export function ManualActivityDialog({
  projectId,
  topics,
  activity,
  onClose,
  onSaved,
}: {
  projectId: string;
  topics: Overview["topics"];
  activity?: Activity;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [activityId] = useState(() => activity?.id ?? crypto.randomUUID());
  const [node, setNode] = useState<string | null>(activity?.node_id ?? null);
  const [date, setDate] = useState(() => {
    const value = new Date(activity?.occurred_at ?? Date.now());
    return new Date(value.getTime() - value.getTimezoneOffset() * 60000)
      .toISOString()
      .slice(0, 16);
  });
  const [minutes, setMinutes] = useState(
    Math.round((activity?.seconds ?? 1800) / 60),
  );
  const [note, setNote] = useState(activity?.note ?? "");
  const [understood, setUnderstood] = useState(activity?.understood ?? false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true);
    try {
      await preparation.activity(projectId, {
        id: activityId,
        node_id: node,
        occurred_at: new Date(date).toISOString(),
        seconds: Math.round(minutes * 60),
        note,
        understood,
      });
      onSaved();
      onClose();
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={activity ? "Изменить занятие" : "Добавить пропущенное время"}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Отменить
          </Button>
          <Button
            disabled={busy || !date || minutes < 0 || minutes > 1440}
            onClick={() => void save()}
          >
            Сохранить занятие
          </Button>
        </>
      }
    >
      {error && <ErrorState title="Занятие не сохранено" message={error} />}
      <div className="prep-form">
        <Field label="Вопрос">
          <Select
            value={node}
            emptyOption="Без вопроса"
            ariaLabel="Вопрос"
            options={topics.map((topic) => ({
              value: topic.node_id,
              label: topic.title,
            }))}
            onValueChange={setNode}
          />
        </Field>
        <Field label={`Когда занимался (${Intl.DateTimeFormat().resolvedOptions().timeZone})`}>
          <input
            type="datetime-local"
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        </Field>
        <Field label="Минут">
          <input
            type="number"
            min={0}
            max={1440}
            value={minutes}
            onChange={(event) => setMinutes(Number(event.target.value))}
          />
        </Field>
        <Field label="Что сделал">
          <textarea
            maxLength={2000}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </Field>
        <label className="prep-check">
          <input
            type="checkbox"
            checked={understood}
            onChange={(event) => setUnderstood(event.target.checked)}
          />
          Разобрался с вопросом
        </label>
      </div>
    </Dialog>
  );
}
