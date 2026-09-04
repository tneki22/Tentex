/** Общий preview ручных, локальных и модельных изменений: до принятия план не меняется. */
import { useState } from "react";
import { Button, Dialog, ErrorState } from "../../components/ui";
import {
  preparation,
  errorText,
  type Draft,
  type Overview,
} from "../../api/preparation";
import { dateLabel } from "./dates";
export function DraftDialog({
  draft,
  overview,
  onClose,
  onApplied,
}: {
  draft: Draft;
  overview: Overview;
  onClose: () => void;
  onApplied: () => void;
}) {
  const changed = draft.items.filter(
    (item) =>
      JSON.stringify(item) !==
      JSON.stringify(overview.plan.items.find((old) => old.id === item.id)),
  );
  const ids = [...changed.map((item) => item.id), ...draft.removed_ids];
  const [selected, setSelected] = useState(new Set(ids));
  const [phases, setPhases] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const title = (id: string) =>
    overview.units.find((unit) => unit.id === id)?.title ??
    "Вопрос удалён из программы";
  async function apply() {
    setBusy(true);
    try {
      await preparation.apply(overview.project_id, draft.id, {
        selected_item_ids: [...selected],
        apply_phases: phases,
      });
      onApplied();
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
        if (!open && !busy) onClose();
      }}
      title="Изменения плана"
      className="prep-dialog"
      description="Выберите изменения. Прошлые дни, выполнение и закрепления проверяются ещё раз при сохранении."
      footer={
        <>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            Оставить текущий
          </Button>
          <Button disabled={busy} onClick={() => void apply()}>
            {busy ? "Сохраняем…" : "Применить выбранное"}
          </Button>
        </>
      }
    >
      {error && <ErrorState title="План не изменён" message={error} />}
      {draft.changes.map((change, i) => (
        <p key={i}>{change}</p>
      ))}
      <label className="prep-check">
        <input
          type="checkbox"
          checked={phases}
          onChange={(event) => setPhases(event.target.checked)}
        />
        Применить блоки подготовки
      </label>
      <div className="prep-comparison">
        <section>
          <h3>Было</h3>
          {overview.plan.phases.map((phase) => (
            <p key={phase.id}>
              {phase.title}: {dateLabel(phase.start)} — {dateLabel(phase.end)}
            </p>
          ))}
        </section>
        <section>
          <h3>Будет</h3>
          {draft.phases.map((phase) => (
            <p key={phase.id}>
              {phase.title}: {dateLabel(phase.start)} — {dateLabel(phase.end)}
            </p>
          ))}
        </section>
      </div>
      <div className="prep-diff-list">
        {ids.map((id) => {
          const old = overview.plan.items.find((item) => item.id === id);
          const next = draft.items.find((item) => item.id === id);
          return (
            <label key={id} className="prep-diff-row">
              <input
                type="checkbox"
                checked={selected.has(id)}
                onChange={(event) =>
                  setSelected((current) => {
                    const result = new Set(current);
                    if (event.target.checked) result.add(id);
                    else result.delete(id);
                    return result;
                  })
                }
              />
              <span>
                <strong>{title((next ?? old)!.unit_id)}</strong>
                <small>
                  {old
                    ? `${dateLabel(old.on_date)}, ${old.minutes} мин`
                    : "Без даты"}{" "}
                  →{" "}
                  {next
                    ? `${dateLabel(next.on_date)}, ${next.minutes} мин${next.pinned ? ", закреплено" : ""}`
                    : "Без даты"}
                </small>
                {next && <small>{next.reason}</small>}
              </span>
            </label>
          );
        })}
      </div>
      <details>
        <summary>Нагрузка после изменений</summary>
        {draft.days.map((day) => (
          <p key={day.date}>
            {dateLabel(day.date)}: {day.planned_minutes} мин, доступно{" "}
            {day.capacity_minutes} мин
            {day.overload_minutes > 0
              ? `, сверх бюджета ${day.overload_minutes} мин`
              : ""}
          </p>
        ))}
      </details>
    </Dialog>
  );
}
