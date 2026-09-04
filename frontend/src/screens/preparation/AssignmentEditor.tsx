/** Назначение создаётся для целого билета, а его вопросы раскрываются в календаре. */
import { useState } from "react";
import { Button, Dialog, Field, Select } from "../../components/ui";
import {
  workLabels,
  type Overview,
  type PlanItem,
  type DraftWrite,
} from "../../api/preparation";
export function AssignmentEditor({
  overview,
  date,
  item,
  onClose,
  onPreview,
}: {
  overview: Overview;
  date: string;
  item?: PlanItem;
  onClose: () => void;
  onPreview: (value: Partial<DraftWrite>) => void;
}) {
  const [selection, setSelection] = useState(
    new Set(item ? [item.unit_id] : []),
  );
  const [search, setSearch] = useState("");
  const [section, setSection] = useState<string | null>(null);
  const [value, setValue] = useState({
    on_date: item?.on_date ?? date,
    kind: item?.kind ?? "learn",
    minutes: item?.minutes ?? 30,
    phase_id: item?.phase_id ?? null,
    pinned: item?.pinned ?? false,
    order: item?.order ?? overview.plan.items.length,
  });
  const units = overview.units.filter(
    (unit) =>
      (!section || unit.path.includes(section)) &&
      `${unit.title} ${unit.path.join(" ")}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const sections = [...new Set(overview.units.flatMap((unit) => unit.path))];
  function preview() {
    const additions: PlanItem[] = [...selection].map((unit_id, index) => ({
      ...value,
      id: item?.id ?? crypto.randomUUID(),
      unit_id,
      order: value.order + index,
      origin: "manual",
      estimate_source: "Оценка вручную",
      reason: "Назначено вручную",
    }));
    onPreview({
      items: [
        ...overview.plan.items.filter((old) => old.id !== item?.id),
        ...additions,
      ],
    });
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={item ? "Изменить назначение" : "Добавить задания"}
      className="prep-dialog"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Отменить
          </Button>
          <Button
            disabled={!selection.size || !value.on_date || value.minutes < 1}
            onClick={preview}
          >
            Посмотреть изменения
          </Button>
        </>
      }
    >
      {!item && (
        <>
          <div className="prep-form">
            <Field label="Поиск вопроса или билета">
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </Field>
            <Field label="Раздел">
              <Select
                value={section}
                emptyOption="Все разделы"
                ariaLabel="Раздел"
                options={sections.map((value) => ({ value, label: value }))}
                onValueChange={setSection}
              />
            </Field>
          </div>
          <div className="prep-actions">
            <Button
              variant="ghost"
              onClick={() =>
                setSelection(
                  (current) =>
                    new Set([...current, ...units.map((unit) => unit.id)]),
                )
              }
            >
              Выбрать весь список ({units.length})
            </Button>
            <Button variant="ghost" onClick={() => setSelection(new Set())}>
              Снять выбор
            </Button>
          </div>
          <div className="prep-unit-list">
            {units.map((unit) => (
              <label key={unit.id} className="prep-check">
                <input
                  type="checkbox"
                  checked={selection.has(unit.id)}
                  onChange={(event) =>
                    setSelection((current) => {
                      const next = new Set(current);
                      if (event.target.checked) next.add(unit.id);
                      else next.delete(unit.id);
                      return next;
                    })
                  }
                />
                <span>
                  {unit.title}
                  <small>
                    {unit.path.join(" / ")} · {unit.topic_ids.length} вопр.
                  </small>
                </span>
              </label>
            ))}
          </div>
        </>
      )}
      <div className="prep-form">
        <Field label="Дата">
          <input
            type="date"
            value={value.on_date}
            onChange={(event) =>
              setValue({ ...value, on_date: event.target.value })
            }
          />
        </Field>
        <Field label="Вид занятия">
          <Select
            ariaLabel="Вид занятия"
            value={value.kind}
            options={Object.entries(workLabels).map(([value, label]) => ({
              value,
              label,
            }))}
            onValueChange={(kind) =>
              setValue({ ...value, kind: kind as PlanItem["kind"] })
            }
          />
        </Field>
        <Field label="Минут на задание">
          <input
            type="number"
            min={1}
            max={10080}
            value={value.minutes}
            onChange={(event) =>
              setValue({ ...value, minutes: Number(event.target.value) })
            }
          />
        </Field>
        <Field label="Блок">
          <Select
            value={value.phase_id}
            ariaLabel="Блок"
            emptyOption="Без блока"
            options={overview.plan.phases.map((phase) => ({
              value: phase.id,
              label: phase.title,
            }))}
            onValueChange={(phase_id) => setValue({ ...value, phase_id })}
          />
        </Field>
        <Field label="Порядок">
          <input
            type="number"
            min={0}
            value={value.order}
            onChange={(event) =>
              setValue({ ...value, order: Number(event.target.value) })
            }
          />
        </Field>
        <label className="prep-check">
          <input
            type="checkbox"
            checked={value.pinned}
            onChange={(event) =>
              setValue({ ...value, pinned: event.target.checked })
            }
          />
          Закрепить дату
        </label>
      </div>
      {item && (
        <Button
          variant="ghost"
          onClick={() =>
            onPreview({
              items: overview.plan.items.filter((old) => old.id !== item.id),
            })
          }
        >
          Убрать назначение — предпросмотр
        </Button>
      )}
    </Dialog>
  );
}
