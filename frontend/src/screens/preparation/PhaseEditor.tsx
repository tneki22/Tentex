/** Свободные названия блоков не подменяют назначение, нужное алгоритмам. */
import { useState } from "react";
import { addDays } from "./dates";
import { Button, Dialog, Field, Select } from "../../components/ui";
import {
  workLabels,
  type Phase,
  type Overview,
  type DraftWrite,
} from "../../api/preparation";
export function PhaseEditor({
  phase,
  overview,
  onClose,
  onPreview,
}: {
  phase: Phase;
  overview: Overview;
  onClose: () => void;
  onPreview: (change: Partial<DraftWrite>) => void;
}) {
  const [value, setValue] = useState(phase);
  const [remove, setRemove] = useState(false);
  const [destination, setDestination] = useState<string | null>(null);
  const exists = overview.plan.phases.some((item) => item.id === phase.id);
  const others = overview.plan.phases.filter((item) => item.id !== phase.id);
  const save = () => {
    const shift = Math.round((Date.parse(value.start) - Date.parse(phase.start)) / 86400000);
    const items = overview.plan.items.map((item) => {
      if (item.phase_id !== phase.id) return item;
      const fixed = item.pinned || item.on_date < overview.today || overview.plan.completed_ids.includes(item.id);
      if (fixed) return item.on_date < value.start || item.on_date > value.end
        ? {...item, phase_id: null} : item;
      const shifted = addDays(item.on_date, shift);
      return {...item, on_date: shifted < value.start ? value.start : shifted > value.end ? value.end : shifted};
    });
    onPreview({ phases: [...others, value], items });
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={exists ? "Изменить блок" : "Добавить блок"}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Отменить
          </Button>
          <Button
            disabled={!value.title.trim() || value.end < value.start}
            onClick={save}
          >
            Посмотреть изменения
          </Button>
        </>
      }
    >
      <div className="prep-form">
        <Field label="Название">
          <input
            value={value.title}
            onChange={(event) =>
              setValue({ ...value, title: event.target.value })
            }
          />
        </Field>
        <Field label="Назначение">
          <Select
            value={value.kind}
            ariaLabel="Назначение блока"
            options={Object.entries(workLabels).map(([value, label]) => ({
              value,
              label,
            }))}
            onValueChange={(kind) =>
              setValue({ ...value, kind: kind as Phase["kind"] })
            }
          />
        </Field>
        <Field label="Начало">
          <input
            type="date"
            value={value.start}
            onChange={(event) =>
              setValue({ ...value, start: event.target.value })
            }
          />
        </Field>
        <Field label="Конец">
          <input
            type="date"
            min={value.start}
            value={value.end}
            onChange={(event) =>
              setValue({ ...value, end: event.target.value })
            }
          />
        </Field>
      </div>
      {exists && <p className="prep-muted">При переносе блока сдвигаются его будущие задания.
        Выполненные и закреплённые сохранят дату; за новыми границами они останутся без блока.
        Распределение и нагрузка будут видны перед применением.</p>}
      {exists && (
        <div className="prep-actions">
          <Button
            variant="secondary"
            onClick={() =>
              onPreview({
                phases: [
                  ...overview.plan.phases,
                  {
                    ...value,
                    id: crypto.randomUUID(),
                    title: `${value.title} — копия`,
                    order: overview.plan.phases.length,
                  },
                ],
              })
            }
          >
            Дублировать блок
          </Button>
          <Button variant="ghost" onClick={() => setRemove(true)}>
            Удалить блок…
          </Button>
        </div>
      )}
      {remove && (
        <section className="prep-card">
          <p>
            Задания сохранят свои даты. Выберите, к какому блоку они будут
            относиться.
          </p>
          <Select
            value={destination}
            ariaLabel="Куда перенести задания"
            emptyOption="Оставить без блока"
            options={others.map((item) => ({
              value: item.id,
              label: item.title,
            }))}
            onValueChange={setDestination}
          />
          <Button
            variant="secondary"
            onClick={() =>
              onPreview({
                phases: others,
                items: overview.plan.items.map((item) =>
                  item.phase_id === phase.id
                    ? { ...item, phase_id: destination }
                    : item,
                ),
              })
            }
          >
            Предпросмотр удаления
          </Button>
        </section>
      )}
    </Dialog>
  );
}
