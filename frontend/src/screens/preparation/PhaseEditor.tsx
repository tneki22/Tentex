/** Свободные названия блоков не подменяют назначение, нужное алгоритмам. */
import { useState } from "react";
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
  const save = () => onPreview({ phases: [...others, value] });
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
