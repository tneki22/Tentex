import { Scissors } from "lucide-react";
import { STUDY_TASK_FORM_LABELS, type LessonProposalOp, type LessonProposalRead } from "../../../api/lessons";
import { Checkbox } from "../../ui";
import { MachineMark } from "../MachineMark";
import { LessonMarkdown } from "./LessonMarkdown";
import { TaskCard } from "./tasks/TaskCard";

/** Предложение модели в документе урока: что выбрано к принятию и кто что переключает. */
export interface LessonProposalView {
  proposal: LessonProposalRead;
  chosen: ReadonlySet<string>;
  onToggle(opId: string): void;
}

const VARIANT_LABEL: Record<string, string> = {
  text: "Текст",
  explanation: "Пояснение",
  important: "Важно",
  example: "Пример",
  definition: "Определение",
  warning: "Предупреждение",
};

function pages(from: number, to: number): string {
  return from === to ? `с. ${from}` : `с. ${from}–${to}`;
}

function title(op: LessonProposalOp): string {
  switch (op.op) {
    case "insert_note":
      return `+ ${VARIANT_LABEL[op.variant ?? "explanation"] ?? "Пояснение"}`;
    case "rewrite_note":
      return "Переписать пояснение";
    case "set_collapsed":
      return op.collapsed ? "Свернуть кусок под пояснением" : "Развернуть кусок";
    case "rename_lesson":
      return `Новое название: «${op.text}»`;
    case "set_goal":
      return `Цель урока: ${op.text}`;
    case "insert_task":
      return `+ Задание · ${op.task ? STUDY_TASK_FORM_LABELS[op.task.form].toLowerCase() : ""}`;
  }
}

/**
 * Одно изменение предложения на своём месте в уроке — «призрачный» блок с флажком.
 * Метка происхождения та же, что у принятого блока: читатель видит, на что опирается
 * текст модели, ещё до принятия.
 */
export function LessonProposalCard({ op, view }: { op: LessonProposalOp; view: LessonProposalView }) {
  const sources = new Map(view.proposal.sources.map((item) => [item.label, item]));
  const titles = Object.fromEntries(view.proposal.sources.map((item) => [
    item.label, `${item.source_name}, ${pages(item.page_from, item.page_to)}`,
  ]));
  const origin = op.basis === "model_only" || op.supports.length === 0
    ? "ИИ · знания модели — не подтверждено материалами"
    : `ИИ · ${op.supports.map((label) => {
      const item = sources.get(label);
      return item ? `${item.source_name}, ${pages(item.page_from, item.page_to)} [${label}]` : label;
    }).join("; ")}`;
  const chosen = view.chosen.has(op.id);
  return (
    <aside className={`lesson-proposal-card${chosen ? " is-chosen" : ""}`} aria-label={`Предложение: ${title(op)}`}
      onClick={(event) => event.stopPropagation()}>
      <header>
        <Checkbox checked={chosen} onCheckedChange={() => view.onToggle(op.id)} label={title(op)} />
        {(op.body_md !== null || op.task) && <MachineMark origin={origin} />}
      </header>
      {op.op === "insert_note" && op.after_fragment_id && (
        <p className="lesson-proposal-cut"><Scissors size={12} aria-hidden="true" /> кусок разрежется, пояснение встанет внутрь</p>
      )}
      {op.body_md && (
        <LessonMarkdown className={`lesson-note is-${op.variant ?? "explanation"}`} text={op.body_md} citationTitles={titles} />
      )}
      {op.task && (
        <TaskCard
          label="Задание"
          task={{
            ...op.task,
            sources: op.task.supports.map((label) => sources.get(label)).filter((item) => item !== undefined),
          }}
        />
      )}
      <p className="lesson-proposal-reason">{op.reason}</p>
    </aside>
  );
}
