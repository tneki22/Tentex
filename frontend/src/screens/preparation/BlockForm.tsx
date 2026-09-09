/** Форма блока: свободное название отдельно от назначения, пересечения не сохраняются. */
import { useState } from "react";
import { Button, Dialog, Field, Select } from "../../components/ui";
import type { Overview, Phase } from "../../api/preparation";
import { dateLabel } from "./dates";
import { overlappingPhase, PHASE_KINDS } from "./model";

interface BlockFormProps {
  overview: Overview;
  /** Существующий блок или диапазон для нового. */
  value: Phase | { start: string; end: string };
  onClose: () => void;
  onSave: (phases: Phase[]) => void;
  busy?: boolean;
}

const isPhase = (value: BlockFormProps["value"]): value is Phase => "id" in value;

/**
 * Создание и правка блока подготовки.
 *
 * Пересечение не отклоняется молча: показывается, с чем именно, и предлагается
 * подвинуть границу соседа вместо ручного подбора дат.
 */
const kindLabel = (kind: Phase["kind"]) => PHASE_KINDS.find((entry) => entry.value === kind)?.label ?? kind;

export function BlockForm({ overview, value, onClose, onSave, busy = false }: BlockFormProps) {
  const existing = isPhase(value) ? value : null;
  const [title, setTitle] = useState(existing?.title ?? kindLabel("learn"));
  const [kind, setKind] = useState<Phase["kind"]>(existing?.kind ?? "learn");
  const [start, setStart] = useState(value.start);
  const [end, setEnd] = useState(value.end);
  // Пока пользователь не тронул название сам, оно следует за выбранным назначением.
  const [titleFollowsKind, setTitleFollowsKind] = useState(!existing);

  const id = existing?.id ?? "";
  const others = overview.plan.phases.filter((phase) => phase.id !== id);
  const conflict = start && end && start <= end ? overlappingPhase(others, { id, start, end }) : null;
  const invalid = !title.trim() || !start || !end || end < start;

  const build = (): Phase => ({
    id: existing?.id ?? crypto.randomUUID(),
    title: title.trim(),
    start,
    end,
    kind,
    order: existing?.order ?? overview.plan.phases.length,
    origin: "manual",
  });

  const save = (phases: Phase[]) =>
    onSave(phases.sort((left, right) => left.start.localeCompare(right.start)).map((phase, order) => ({ ...phase, order })));

  /** Сосед уступает границу: конфликт решается одним действием, а не подбором дат. */
  function pushNeighbour() {
    if (!conflict) return;
    const shifted =
      conflict.start < start
        ? { ...conflict, end: shiftDay(start, -1) }
        : { ...conflict, start: shiftDay(end, 1) };
    const kept = shifted.start <= shifted.end ? [shifted] : [];
    save([...others.filter((phase) => phase.id !== conflict.id), ...kept, build()]);
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={existing ? "Блок подготовки" : "Новый блок подготовки"}
      description="Блок описывает период. Вопросы он не переносит."
      footer={
        <>
          {existing && (
            <Button
              variant="ghost"
              className="is-destructive"
              disabled={busy}
              onClick={() => save(others)}
            >
              Удалить блок
            </Button>
          )}
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Отмена
          </Button>
          <Button disabled={busy || invalid || !!conflict} onClick={() => save([...others, build()])}>
            Сохранить
          </Button>
        </>
      }
    >
      <div className="prep-form">
        <Field label="Название">
          <input
            value={title}
            onChange={(event) => {
              setTitle(event.target.value);
              setTitleFollowsKind(false);
            }}
            maxLength={160}
          />
        </Field>
        <Field label="Назначение" hint="Календарь берёт назначение отсюда, а не из текста названия">
          <Select
            ariaLabel="Назначение блока"
            value={kind}
            options={PHASE_KINDS.map((entry) => ({ value: entry.value, label: entry.label }))}
            onValueChange={(next) => {
              if (!next) return;
              setKind(next as Phase["kind"]);
              if (titleFollowsKind) setTitle(kindLabel(next as Phase["kind"]));
            }}
          />
        </Field>
        <Field label="С даты">
          <input type="date" value={start} onChange={(event) => setStart(event.target.value)} />
        </Field>
        <Field label="По дату" error={end && start && end < start ? "Конец раньше начала" : undefined}>
          <input type="date" min={start} value={end} onChange={(event) => setEnd(event.target.value)} />
        </Field>
      </div>
      {conflict && (
        <div className="prep-conflict">
          <p>
            Пересекается с «{conflict.title}», {dateLabel(conflict.start)} — {dateLabel(conflict.end)}.
          </p>
          <Button variant="secondary" onClick={pushNeighbour} disabled={busy}>
            Подвинуть границу соседа
          </Button>
        </div>
      )}
    </Dialog>
  );
}

const shiftDay = (value: string, days: number) => {
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
};
