import { useMemo, useState } from "react";
import { ListOrdered, Undo2 } from "lucide-react";
import { createBulkLessons, type LessonBulkAction, type LessonSummaryRead } from "../../api/lessons";
import { undoProjectAction } from "../../api/projects";
import { Button, Select, Tooltip } from "../../components/ui";
import type { ProgramTreeNode } from "../programTree";
import { countsByNode, errorText } from "./lessonTree";

type BulkAction = LessonBulkAction | "skip" | "ai";

const ACTION_OPTIONS = [
  { value: "quick", label: "быстрый урок" },
  { value: "manual", label: "вручную" },
  { value: "skip", label: "пропустить" },
  { value: "ai", label: "с ИИ — этап 7", disabled: true },
];

interface LessonBulkTableProps {
  projectId: string;
  topics: ProgramTreeNode[];
  lessons: LessonSummaryRead[];
  onClear(): void;
  /** Состав уроков изменился: перечитать обзор. */
  onChanged(): void;
  onOpenLesson(nodeId: string, lessonId: string): void;
}

function rangeLabel(topic: ProgramTreeNode): string {
  const range = topic.source_page_ranges[0];
  if (!range) return "—";
  const extra = topic.source_page_ranges.length > 1 ? ` +${topic.source_page_ranges.length - 1}` : "";
  return `${range.source_name_snapshot} ${range.page_from}–${range.page_to}${extra}`;
}

function plural(count: number): string {
  const tail = count % 100 > 10 && count % 100 < 20 ? 0 : count % 10;
  if (tail === 1) return "черновик";
  return tail >= 2 && tail <= 4 ? "черновика" : "черновиков";
}

/** Массовая подготовка: умолчания и одна отмена на всё — записка «Уроки» §4.5. */
export function LessonBulkTable({ projectId, topics, lessons, onClear, onChanged, onOpenLesson }: LessonBulkTableProps) {
  const counts = useMemo(() => countsByNode(lessons), [lessons]);
  const [overrides, setOverrides] = useState<Record<string, BulkAction>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Одна транзакция — одна отмена, и она остаётся рядом с действием (записка §4.5).
  const [created, setCreated] = useState<{ lessons: LessonSummaryRead[]; sequence: number } | null>(null);

  // «Тема с диапазоном и без урока — быстрый урок»: черновик тоже урок, второй молча не нужен.
  const defaultAction = (topic: ProgramTreeNode): BulkAction => {
    const item = counts.get(topic.id);
    if (item && item.ready + item.drafts > 0) return "skip";
    return topic.source_page_ranges.length > 0 ? "quick" : "manual";
  };
  const actionOf = (topic: ProgramTreeNode) => overrides[topic.id] ?? defaultAction(topic);
  const planned = topics
    .map((topic) => ({ topic, action: actionOf(topic) }))
    .filter((row): row is { topic: ProgramTreeNode; action: LessonBulkAction } =>
      row.action === "quick" || row.action === "manual");

  async function create() {
    setBusy(true);
    setError("");
    try {
      const result = await createBulkLessons(
        projectId,
        planned.map(({ topic, action }) => ({ program_node_id: topic.id, action })),
      );
      const sequence = result.latest_undoable_action?.sequence;
      setCreated(sequence ? { lessons: result.lessons, sequence } : null);
      onChanged();
    } catch (caught) {
      setError(errorText(caught, "Не удалось создать черновики"));
    } finally {
      setBusy(false);
    }
  }

  async function undo() {
    if (!created) return;
    setBusy(true);
    setError("");
    try {
      await undoProjectAction(projectId, created.sequence);
      setCreated(null);
      onChanged();
    } catch (caught) {
      setError(errorText(caught, "Не удалось отменить создание"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="lessons-center-scroll">
      <header className="lessons-center-head">
        <span className="lessons-eyebrow">Массовая подготовка</span>
        <h1>Подготовка уроков · {topics.length} тем</h1>
        <p>Готовый урок молча не перезаписывается; тема без диапазона оглавления собирается вручную.</p>
      </header>
      <div className="lessons-bulk-scroll">
        <table className="lessons-bulk-table">
          <thead><tr><th>#</th><th>Тема</th><th>Материал</th><th>Уроки</th><th>Действие</th></tr></thead>
          <tbody>
            {topics.map((topic, index) => {
              const item = counts.get(topic.id);
              return (
                <tr key={topic.id}>
                  <td>{index + 1}</td>
                  <td>{topic.title}</td>
                  <td>{rangeLabel(topic)}</td>
                  <td>{item && item.ready + item.drafts > 0 ? `${item.ready > 0 ? `✓ ${item.ready}` : ""}${item.drafts > 0 ? ` ● ${item.drafts}` : ""}` : "—"}</td>
                  <td>
                    <Select
                      ariaLabel={`Действие для «${topic.title}»`}
                      value={actionOf(topic)}
                      options={ACTION_OPTIONS.map((option) => option.value === "quick" && topic.source_page_ranges.length === 0 ? { ...option, disabled: true } : option)}
                      onValueChange={(value) => {
                        if (!value) return;
                        setCreated(null);
                        setOverrides((current) => ({ ...current, [topic.id]: value as BulkAction }));
                      }}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {created && (
        <div className="lessons-bulk-result" role="status">
          <span>Создано черновиков: {created.lessons.length}</span>
          <Button variant="ghost" disabled={busy} onClick={() => {
            const first = created.lessons[0];
            if (first) onOpenLesson(first.program_node_ids[0], first.id);
          }}>Открыть первый</Button>
          <Button variant="ghost" disabled={busy} onClick={() => void undo()}><Undo2 size={14} />Отменить</Button>
        </div>
      )}
      <footer className="lessons-bulk-footer">
        {error && <p className="inline-error" role="alert">{error}</p>}
        <Button variant="ghost" onClick={onClear} disabled={busy}>Очистить выбор</Button>
        <Tooltip label="Вернуть каждой теме действие по умолчанию: готовый урок — пропустить, диапазон есть — быстрый урок" side="top">
          <Button variant="secondary" onClick={() => { setCreated(null); setOverrides({}); }} disabled={busy}>
            <ListOrdered size={15} />Создать по порядку
          </Button>
        </Tooltip>
        <Button onClick={() => void create()} disabled={busy || planned.length === 0 || created !== null}>
          {busy ? "Создаём…" : `Создать ${planned.length} ${plural(planned.length)}`}
        </Button>
      </footer>
    </div>
  );
}
