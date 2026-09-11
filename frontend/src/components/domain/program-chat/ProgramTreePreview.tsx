import type { ProgramChatOperationView } from "../../../api/chat";
import type { ProgramNodeRead, ProgramState } from "../../../api/projects";
import { EmptyState } from "../../ui";

const NODE_TYPE_LABELS: Record<string, string> = {
  section: "раздел", topic: "тема", subpoint: "подпункт",
};

interface PendingNote {
  kind: "rename" | "move" | "change_type" | "set_goal" | "hidden" | "merged";
  text: string;
}

interface PreviewRow {
  key: string;
  depth: number;
  title: string;
  nodeType: string;
  isNew: boolean;
  notes: PendingNote[];
  children: PreviewRow[];
}

function collectNotes(
  operations: ProgramChatOperationView[],
  states: Array<"pending" | "applied" | "conflicted">,
): Map<string, PendingNote[]> {
  const notes = new Map<string, PendingNote[]>();
  function push(nodeId: string | undefined, note: PendingNote) {
    if (!nodeId) return;
    const list = notes.get(nodeId) ?? [];
    list.push(note);
    notes.set(nodeId, list);
  }
  operations.forEach((op, index) => {
    if (states[index] !== "pending") return;
    switch (op.op) {
      case "rename":
        push(op.node_id, { kind: "rename", text: `→ переименовать в «${op.title}»` });
        break;
      case "move":
        push(op.node_id, { kind: "move", text: "→ будет перенесено" });
        break;
      case "change_type":
        push(op.node_id, {
          kind: "change_type",
          text: `→ тип: ${op.node_type ? NODE_TYPE_LABELS[op.node_type] ?? op.node_type : ""}`,
        });
        break;
      case "set_goal":
        push(op.node_id, { kind: "set_goal", text: "→ роль в цели изменится" });
        break;
      case "set_visibility":
        if (!op.is_in_current_program) push(op.node_id, { kind: "hidden", text: "→ выйдет из программы" });
        break;
      case "merge":
        (op.node_ids ?? []).slice(1).forEach((id) => push(id, { kind: "merged", text: "→ будет объединено" }));
        break;
      default:
        break;
    }
  });
  return notes;
}

function addRows(operations: ProgramChatOperationView[], depth: number, prefix: string): PreviewRow[] {
  return operations
    .filter((op) => op.op === "add")
    .map((op, index) => ({
      key: `${prefix}-new-${index}`,
      depth,
      title: op.title ?? "",
      nodeType: op.node_type ?? "topic",
      isNew: true,
      notes: [],
      children: addRows(op.children ?? [], depth + 1, `${prefix}-new-${index}`),
    }));
}

function buildTree(
  program: ProgramState,
  pendingAdds: ProgramChatOperationView[],
  notesById: Map<string, PendingNote[]>,
): PreviewRow[] {
  const childrenByParent = new Map<string | null, ProgramNodeRead[]>();
  for (const node of program.nodes) {
    if (!node.is_in_current_program || node.is_archived) continue;
    const key = node.parent_id;
    const list = childrenByParent.get(key) ?? [];
    list.push(node);
    childrenByParent.set(key, list);
  }
  for (const list of childrenByParent.values()) list.sort((a, b) => a.sort_order - b.sort_order);

  const addsByParent = new Map<string | null, ProgramChatOperationView[]>();
  for (const op of pendingAdds) {
    const key = op.parent_node_id ?? null;
    const list = addsByParent.get(key) ?? [];
    list.push(op);
    addsByParent.set(key, list);
  }

  function walk(parentId: string | null, depth: number): PreviewRow[] {
    const rows: PreviewRow[] = (childrenByParent.get(parentId) ?? []).map((node) => ({
      key: node.id,
      depth,
      title: node.title,
      nodeType: node.node_type,
      isNew: false,
      notes: notesById.get(node.id) ?? [],
      children: walk(node.id, depth + 1),
    }));
    const news = addsByParent.get(parentId) ?? [];
    rows.push(...addRows(news, depth, parentId ?? "root"));
    return rows;
  }
  return walk(null, 0);
}

function Row({ row }: { row: PreviewRow }) {
  return (
    <li className={`program-tree-preview-row ${row.isNew ? "is-new" : ""}`} style={{ marginInlineStart: row.depth * 16 }}>
      <span className="program-tree-preview-type">{NODE_TYPE_LABELS[row.nodeType] ?? row.nodeType}</span>
      <span className="program-tree-preview-title">{row.title}</span>
      {row.notes.map((note, index) => (
        <span key={index} className={`program-tree-preview-note is-${note.kind}`}>{note.text}</span>
      ))}
      {row.children.length > 0 && (
        <ul className="program-tree-preview-children">
          {row.children.map((child) => <Row key={child.key} row={child} />)}
        </ul>
      )}
    </li>
  );
}

interface ProgramTreePreviewProps {
  program: ProgramState;
  /** Операции последнего непринятого предложения — накладываются поверх дерева. */
  pendingOperations?: ProgramChatOperationView[];
  pendingStates?: Array<"pending" | "applied" | "conflicted">;
}

/** Лёгкий read-only предпросмотр дерева для режима «С ИИ»: текущая программа

 * плюс визуальные пометки последнего непринятого дифа. Не переиспользует
 * интерактивные внутренности `TextbookProgramEditor` — тут не нужен CRUD.
 */
export function ProgramTreePreview({ program, pendingOperations = [], pendingStates = [] }: ProgramTreePreviewProps) {
  const notesById = collectNotes(pendingOperations, pendingStates);
  const pendingAdds = pendingOperations.filter((_op, index) => pendingStates[index] === "pending" && _op.op === "add");
  const rows = buildTree(program, pendingAdds, notesById);

  if (rows.length === 0) {
    return (
      <EmptyState title="Программа пока пуста">
        <p>Дерево появится здесь по мере того, как чат его предложит.</p>
      </EmptyState>
    );
  }

  return (
    <div className="program-tree-preview" role="tree" aria-label="Предпросмотр программы">
      <ul className="program-tree-preview-root">
        {rows.map((row) => <Row key={row.key} row={row} />)}
      </ul>
    </div>
  );
}
