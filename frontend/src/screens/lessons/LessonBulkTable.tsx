import { useState } from "react";
import type { LessonSummaryRead } from "../../api/lessons";
import { Button, Select, Tooltip } from "../../components/ui";
import type { ProgramTreeNode } from "../programTree";
import { countsByNode } from "./lessonTree";

type BulkAction = "quick" | "manual" | "skip" | "ai";

const ACTION_OPTIONS = [
  { value: "quick", label: "быстрый урок" },
  { value: "manual", label: "вручную" },
  { value: "skip", label: "пропустить" },
  { value: "ai", label: "с ИИ — этап 7", disabled: true },
];

interface LessonBulkTableProps {
  topics: ProgramTreeNode[];
  lessons: LessonSummaryRead[];
  onClear(): void;
}

function rangeLabel(topic: ProgramTreeNode): string {
  const range = topic.source_page_ranges[0];
  if (!range) return "—";
  const extra = topic.source_page_ranges.length > 1 ? ` +${topic.source_page_ranges.length - 1}` : "";
  return `${range.source_name_snapshot} ${range.page_from}–${range.page_to}${extra}`;
}

/** Массовая подготовка: действие по умолчанию из записки §4.5; создание — этап 3. */
export function LessonBulkTable({ topics, lessons, onClear }: LessonBulkTableProps) {
  const counts = countsByNode(lessons);
  const [overrides, setOverrides] = useState<Record<string, BulkAction>>({});

  const defaultAction = (topic: ProgramTreeNode): BulkAction => {
    if ((counts.get(topic.id)?.ready ?? 0) > 0) return "skip";
    return topic.source_page_ranges.length > 0 ? "quick" : "manual";
  };
  const actionOf = (topic: ProgramTreeNode) => overrides[topic.id] ?? defaultAction(topic);
  const drafts = topics.filter((topic) => actionOf(topic) === "quick").length;

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
                      onValueChange={(value) => value && setOverrides((current) => ({ ...current, [topic.id]: value as BulkAction }))}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <footer className="lessons-bulk-footer">
        <Button variant="ghost" onClick={onClear}>Очистить выбор</Button>
        <Tooltip label="Появится на этапе 3 — массовая подготовка" side="top">
          <span><Button disabled>Создать {drafts} черновиков</Button></span>
        </Tooltip>
      </footer>
    </div>
  );
}
