/** Редактор вопросов дня: сначала выделение, затем тумблеры (§3.10). */
import { useEffect, useMemo, useRef, useState } from "react";
import { Check, PenLine } from "lucide-react";
import { Button, Disclosure, Tooltip } from "../../components/ui";
import { PurposeDot } from "../../components/domain";
import type { Overview, PlanItem } from "../../api/preparation";
import { duration } from "./dates";
import { longDateLabel, todaySecondsByTopic, WEEKDAYS_LONG, weekdayIndexOf } from "./model";

type Assignment = { learn: boolean; review: boolean };

interface DayQuestionsEditorProps {
  overview: Overview;
  date: string;
  onSave: (items: PlanItem[]) => void;
  onDropDebt: () => void;
  onCatchUp: () => void;
  onEditProgram: () => void;
  hasDebt: boolean;
  busy?: boolean;
  disabled?: boolean;
}

const EMPTY: Assignment = { learn: false, review: false };

/** Назначения дня из серверного снимка. */
function baseAssignments(overview: Overview, date: string) {
  const map = new Map<string, Assignment>();
  for (const item of overview.plan.items) {
    if (item.on_date !== date) continue;
    const current = map.get(item.unit_id) ?? { learn: false, review: false };
    if (item.kind === "review") current.review = true;
    else current.learn = true;
    map.set(item.unit_id, current);
  }
  return map;
}

const purposeOfAssignment = (value: Assignment) =>
  value.learn && value.review ? "both" : value.review ? "review" : value.learn ? "study" : "none";

/**
 * Дерево вопросов выбранного дня с выделением и двумя тумблерами.
 *
 * Билет неделим: единицей назначения служит сам билет, поэтому отдельный
 * его вопрос на другую дату не попадает ни одним способом.
 */
export function DayQuestionsEditor({
  overview,
  date,
  onSave,
  onDropDebt,
  onCatchUp,
  onEditProgram,
  hasDebt,
  busy = false,
  disabled = false,
}: DayQuestionsEditorProps) {
  const base = useMemo(() => baseAssignments(overview, date), [overview, date]);
  const [edits, setEdits] = useState<Map<string, Assignment>>(new Map());
  const [selection, setSelection] = useState<Set<string>>(new Set());
  const [anchor, setAnchor] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const [marquee, setMarquee] = useState<{ top: number; left: number; width: number; height: number } | null>(null);

  useEffect(() => {
    setEdits(new Map());
    setSelection(new Set());
    setAnchor(null);
  }, [date, overview.plan.revision]);

  const completed = new Set(overview.plan.completed_ids);
  const openedUnits = new Set(
    overview.plan.items.filter((item) => item.on_date === date && completed.has(item.id)).map((item) => item.unit_id),
  );
  const seconds = todaySecondsByTopic(overview);

  const sections = useMemo(() => {
    const order: string[] = [];
    const map = new Map<string, Overview["units"]>();
    for (const unit of overview.units) {
      const title = unit.path[0] ?? "Без раздела";
      if (!map.has(title)) {
        map.set(title, []);
        order.push(title);
      }
      map.get(title)!.push(unit);
    }
    return order.map((title) => ({ title, units: map.get(title)! }));
  }, [overview.units]);

  const flat = useMemo(() => sections.flatMap((section) => section.units.map((unit) => unit.id)), [sections]);
  const valueOf = (unitId: string): Assignment => edits.get(unitId) ?? base.get(unitId) ?? EMPTY;
  const dirty = edits.size > 0;

  const selectedValues = [...selection].map(valueOf);
  const state = (key: keyof Assignment): boolean | "mixed" => {
    if (!selectedValues.length) return false;
    const on = selectedValues.filter((value) => value[key]).length;
    if (on === 0) return false;
    if (on === selectedValues.length) return true;
    return "mixed";
  };

  function applyToggle(key: keyof Assignment) {
    const next = new Map(edits);
    const target = state(key) !== true;
    for (const unitId of selection) {
      const current = { ...valueOf(unitId) };
      current[key] = target;
      next.set(unitId, current);
    }
    setEdits(next);
  }

  function pick(unitId: string, event: React.MouseEvent) {
    if (event.shiftKey && anchor) {
      const from = flat.indexOf(anchor);
      const to = flat.indexOf(unitId);
      const range = flat.slice(Math.min(from, to), Math.max(from, to) + 1);
      setSelection(new Set(range));
      return;
    }
    if (event.ctrlKey || event.metaKey) {
      const next = new Set(selection);
      if (next.has(unitId)) next.delete(unitId);
      else next.add(unitId);
      setSelection(next);
      setAnchor(unitId);
      return;
    }
    setSelection(new Set([unitId]));
    setAnchor(unitId);
  }

  /** Рамка выделения: строки собираются по пересечению прямоугольников. */
  function startMarquee(event: React.PointerEvent<HTMLDivElement>) {
    const node = listRef.current;
    if (!node || event.button !== 0) return;
    if ((event.target as HTMLElement).closest("button, input, .prep-unit")) return;
    const box = node.getBoundingClientRect();
    const originX = event.clientX - box.left + node.scrollLeft;
    const originY = event.clientY - box.top + node.scrollTop;
    const additive = event.ctrlKey || event.metaKey;
    const subtractive = event.altKey;
    const startSelection = new Set(selection);
    node.setPointerCapture(event.pointerId);

    const move = (moveEvent: PointerEvent) => {
      const x = moveEvent.clientX - box.left + node.scrollLeft;
      const y = moveEvent.clientY - box.top + node.scrollTop;
      const rect = {
        left: Math.min(originX, x),
        top: Math.min(originY, y),
        width: Math.abs(x - originX),
        height: Math.abs(y - originY),
      };
      setMarquee(rect);
      const hit = new Set<string>();
      node.querySelectorAll<HTMLElement>("[data-unit]").forEach((row) => {
        const top = row.offsetTop;
        const bottom = top + row.offsetHeight;
        if (bottom >= rect.top && top <= rect.top + rect.height) hit.add(row.dataset.unit!);
      });
      if (additive) setSelection(new Set([...startSelection, ...hit]));
      else if (subtractive) setSelection(new Set([...startSelection].filter((id) => !hit.has(id))));
      else setSelection(hit);
    };
    const finish = () => {
      node.removeEventListener("pointermove", move);
      node.removeEventListener("pointerup", finish);
      setMarquee(null);
    };
    node.addEventListener("pointermove", move);
    node.addEventListener("pointerup", finish);
  }

  /** Новый список назначений: этот день пересобирается, остальные не трогаются. */
  function save() {
    const kept = overview.plan.items.filter((item) => item.on_date !== date);
    const units = new Map(overview.units.map((unit) => [unit.id, unit]));
    const merged = new Map(base);
    for (const [unitId, value] of edits) merged.set(unitId, value);
    const fresh: PlanItem[] = [];
    let order = 0;
    for (const [unitId, value] of merged) {
      const existing = overview.plan.items.filter((item) => item.on_date === date && item.unit_id === unitId);
      for (const kind of ["learn", "review"] as const) {
        if (!value[kind]) continue;
        const previous = existing.find((item) => (kind === "review" ? item.kind === "review" : item.kind !== "review"));
        fresh.push(
          previous ?? {
            id: crypto.randomUUID(),
            unit_id: unitId,
            on_date: date,
            kind,
            phase_id: null,
            minutes: units.get(unitId)?.minutes ?? 30,
            order: order,
            pinned: false,
            origin: "manual",
            estimate_source: units.get(unitId)?.estimate_source ?? "initial",
            reason: kind === "review" ? "Повторение назначено вручную" : "Изучение назначено вручную",
          },
        );
        order += 1;
      }
    }
    onSave([...kept, ...fresh]);
  }

  const plannedCount = [...new Set([...base.keys(), ...edits.keys()])].filter(
    (unitId) => valueOf(unitId).learn || valueOf(unitId).review,
  ).length;

  return (
    <div className="prep-editor">
      <header className="prep-editor-head">
        <h3>
          {longDateLabel(date)}, {WEEKDAYS_LONG[weekdayIndexOf(date)]}
        </h3>
        <p>
          {plannedCount} назначено, {openedUnits.size} открыто
        </p>
      </header>

      <div className="prep-toggles">
        {(["learn", "review"] as const).map((key) => {
          const value = state(key);
          return (
            <button
              key={key}
              type="button"
              className={`prep-toggle${value === true ? " is-on" : ""}${value === "mixed" ? " is-mixed" : ""}`}
              disabled={disabled || !selection.size}
              aria-pressed={value === true}
              onClick={() => applyToggle(key)}
            >
              <i aria-hidden="true" />
              {key === "learn" ? "Изучить" : "Повторить"}
              {value === "mixed" && <small>частично</small>}
            </button>
          );
        })}
        <span className="prep-selection-count">
          {selection.size ? `Выделено: ${selection.size}` : "Выделите вопросы"}
        </span>
      </div>

      <div className="prep-unit-tree" ref={listRef} onPointerDown={startMarquee}>
        {marquee && (
          <span
            className="prep-marquee"
            style={{ top: marquee.top, left: marquee.left, width: marquee.width, height: marquee.height }}
          />
        )}
        {sections.map((section) => (
          <Disclosure key={section.title} summary={section.title} defaultOpen className="prep-unit-section">
            <ul>
              {section.units.map((unit) => {
                const value = valueOf(unit.id);
                const purpose = purposeOfAssignment(value);
                const spent = unit.topic_ids.reduce((sum, id) => sum + (seconds.get(id) ?? 0), 0);
                return (
                  <li key={unit.id}>
                    <button
                      type="button"
                      data-unit={unit.id}
                      className={`prep-unit${selection.has(unit.id) ? " is-selected" : ""}${
                        edits.has(unit.id) ? " is-dirty" : ""
                      }`}
                      onClick={(event) => pick(unit.id, event)}
                    >
                      <PurposeDot purpose={purpose} />
                      <Tooltip label={unit.title} side="top">
                        <span className="prep-unit-title">{unit.title}</span>
                      </Tooltip>
                      {unit.kind === "ticket" && <em className="prep-unit-kind">билет</em>}
                      {spent > 0 && <em className="prep-unit-time">{duration(spent)}</em>}
                      {openedUnits.has(unit.id) && <Check size={13} className="prep-unit-check" />}
                    </button>
                  </li>
                );
              })}
            </ul>
          </Disclosure>
        ))}
      </div>

      <footer className={`prep-editor-foot${dirty ? " is-dirty" : ""}`}>
        {dirty && <span className="prep-dirty-note">Изменения не сохранены · {edits.size}</span>}
        <div className="prep-actions">
          <Button disabled={disabled || busy || !dirty} onClick={save}>
            Сохранить
          </Button>
          {dirty && (
            <Button variant="secondary" disabled={busy} onClick={() => setEdits(new Map())}>
              Отменить
            </Button>
          )}
          <Button variant="ghost" disabled={disabled || busy || !hasDebt} onClick={onDropDebt}>
            Снять долг
          </Button>
          <Button variant="ghost" disabled={disabled || busy || !hasDebt} onClick={onCatchUp}>
            Наверстать
          </Button>
          <Button variant="ghost" onClick={onEditProgram}>
            <PenLine size={13} /> Изменить вопросы
          </Button>
        </div>
      </footer>
    </div>
  );
}
