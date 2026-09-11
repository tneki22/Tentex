import { useState } from "react";
import { Ban, Check, ThumbsDown, ThumbsUp } from "lucide-react";
import type { ProgramChatDiffPayload, ProgramChatOperationView } from "../../../api/chat";
import { Button, Checkbox } from "../../../components/ui";

const NODE_TYPE_LABELS: Record<string, string> = {
  section: "раздел", topic: "тема", subpoint: "подпункт",
};

const GOAL_ROLE_LABELS: Record<string, string> = {
  target: "цель", prerequisite: "предпосылка", related: "связанная",
};

interface ProgramDiffCardProps {
  summary: string;
  diff: ProgramChatDiffPayload;
  busy?: boolean;
  onApply?: (selected: number[]) => Promise<void>;
  onReject?: () => Promise<void>;
  /** id узла → формулировка — красит node_id из операций в читаемый текст. */
  nodeTitles?: Record<string, string>;
  headingRef?: (node: HTMLHeadingElement | null) => void;
}

function nodeLabel(id: string | null | undefined, titles: Record<string, string>): string {
  if (!id) return "";
  return titles[id] ?? `узел ${id.slice(0, 8)}…`;
}

function describeOperation(op: ProgramChatOperationView, titles: Record<string, string>): string {
  switch (op.op) {
    case "add": {
      const parent = op.parent_node_id ? ` в «${nodeLabel(op.parent_node_id, titles)}»` : " в корень программы";
      const kind = op.node_type ? NODE_TYPE_LABELS[op.node_type] ?? op.node_type : "узел";
      const outline = op.outline_ref ? " · из оглавления" : "";
      return `Добавить ${kind} «${op.title ?? ""}»${parent}${outline}`;
    }
    case "rename":
      return `Переименовать «${nodeLabel(op.node_id, titles)}» → «${op.title ?? ""}»`;
    case "move": {
      const parent = op.new_parent_node_id
        ? `в «${nodeLabel(op.new_parent_node_id, titles)}»`
        : "в корень программы";
      return `Перенести «${nodeLabel(op.node_id, titles)}» ${parent}`;
    }
    case "change_type": {
      const kind = op.node_type ? NODE_TYPE_LABELS[op.node_type] ?? op.node_type : "узел";
      return `Изменить тип «${nodeLabel(op.node_id, titles)}» → ${kind}`;
    }
    case "set_goal": {
      const role = op.goal_role ? GOAL_ROLE_LABELS[op.goal_role] ?? op.goal_role : "не задана";
      return `Роль в цели «${nodeLabel(op.node_id, titles)}» → ${role}`;
    }
    case "set_visibility":
      return op.is_in_current_program
        ? `Вернуть в программу «${nodeLabel(op.node_id, titles)}»`
        : `Вынести из программы «${nodeLabel(op.node_id, titles)}»`;
    case "merge": {
      const names = (op.node_ids ?? []).map((id) => nodeLabel(id, titles)).join(", ");
      const title = op.title ? ` → «${op.title}»` : "";
      return `Объединить: ${names}${title}`;
    }
    default:
      return op.op;
  }
}

interface OperationRowProps {
  op: ProgramChatOperationView;
  index: number;
  state: "pending" | "applied" | "conflicted";
  checked: boolean;
  onToggle: (index: number, checked: boolean) => void;
  titles: Record<string, string>;
  depth: number;
}

function OperationRow({ op, index, state, checked, onToggle, titles, depth }: OperationRowProps) {
  return (
    <li className={`program-diff-op is-${state}`} style={{ marginInlineStart: depth * 16 }}>
      <Checkbox
        checked={state === "applied" ? true : checked}
        onCheckedChange={(value) => onToggle(index, value)}
        disabled={state !== "pending"}
        label={describeOperation(op, titles)}
      />
      {op.rationale && <p className="program-diff-op-rationale">{op.rationale}</p>}
      {state === "applied" && <span className="program-diff-op-status">Применено</span>}
      {state === "conflicted" && (
        <span className="program-diff-op-status is-conflicted">Устарело — нужен новый диф</span>
      )}
      {op.children && op.children.length > 0 && (
        <ul className="program-diff-op-children">
          {op.children.map((child, childIndex) => (
            <li key={childIndex} className="program-diff-op is-nested" style={{ marginInlineStart: (depth + 1) * 16 }}>
              <span className="program-diff-op-nested-label">{describeOperation(child, titles)}</span>
              {child.rationale && <p className="program-diff-op-rationale">{child.rationale}</p>}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

/** Карточка предложения ИИ-чата построения программы: резюме, плюсы/минусы,
 * операции с чекбоксами (независимые верхнеуровневые группы) и Принять/Отклонить. */
export function ProgramDiffCard({
  summary, diff, busy = false, onApply, onReject, nodeTitles = {}, headingRef,
}: ProgramDiffCardProps) {
  const pendingIndices = diff.operations
    .map((_op, index) => index)
    .filter((index) => diff.operation_states[index] === "pending");
  const [selected, setSelected] = useState<Set<number>>(() => new Set(pendingIndices));

  if (diff.rejected) {
    return (
      <div className="chat-bubble is-assistant program-diff-card is-rejected">
        <p>{summary}</p>
        <p className="program-diff-rejected-note"><Ban size={14} />Предложение отклонено</p>
      </div>
    );
  }

  function toggle(index: number, checked: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(index); else next.delete(index);
      return next;
    });
  }

  const selectedCount = [...selected].filter((index) => diff.operation_states[index] === "pending").length;
  const hasPending = pendingIndices.length > 0;

  return (
    <article className="chat-bubble is-assistant program-diff-card">
      <h3 ref={headingRef} tabIndex={-1} className="program-diff-title">Предложение · {diff.operations.length} изменени{diff.operations.length === 1 ? "е" : "й"}</h3>
      {summary && <p className="program-diff-summary">{summary}</p>}
      {(diff.pros.length > 0 || diff.cons.length > 0) && (
        <div className="program-diff-pros-cons">
          {diff.pros.length > 0 && (
            <ul className="program-diff-pros"><ThumbsUp size={13} aria-hidden="true" />
              {diff.pros.map((item, index) => <li key={index}>{item}</li>)}
            </ul>
          )}
          {diff.cons.length > 0 && (
            <ul className="program-diff-cons"><ThumbsDown size={13} aria-hidden="true" />
              {diff.cons.map((item, index) => <li key={index}>{item}</li>)}
            </ul>
          )}
        </div>
      )}
      {diff.operations.length > 0 && (
        <ul className="program-diff-ops">
          {diff.operations.map((op, index) => (
            <OperationRow
              key={index}
              op={op}
              index={index}
              state={diff.operation_states[index] ?? "pending"}
              checked={selected.has(index)}
              onToggle={toggle}
              titles={nodeTitles}
              depth={0}
            />
          ))}
        </ul>
      )}
      {hasPending && (onApply || onReject) && (
        <div className="program-diff-actions">
          {onReject && (
            <Button variant="ghost" disabled={busy} onClick={() => void onReject()}>Отклонить</Button>
          )}
          {onApply && (
            <Button disabled={busy || selectedCount === 0} onClick={() => void onApply([...selected])}>
              <Check size={14} />Принять выбранное · {selectedCount}
            </Button>
          )}
        </div>
      )}
    </article>
  );
}
