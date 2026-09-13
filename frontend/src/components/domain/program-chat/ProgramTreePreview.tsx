import type { ProgramChatOperationView } from "../../../api/chat";
import type { ProgramNodeRead, ProgramState } from "../../../api/projects";
import { EmptyState } from "../../ui";

const NODE_TYPE_LABELS: Record<string, string> = {
  section: "раздел", topic: "тема", subpoint: "подпункт",
};

interface PreviewChange {
  removed: boolean;
  nextTitle?: string;
  nextType?: string;
}

interface PreviewRow {
  key: string;
  depth: number;
  title: string;
  nodeType: string;
  status: "unchanged" | "new" | "removed";
  nextTitle?: string;
  nextType?: string;
  children: PreviewRow[];
}

/** Сворачивает операции дифа в визуальные изменения существующих узлов. */
function collectChanges(
  operations: ProgramChatOperationView[],
  states: Array<"pending" | "applied" | "conflicted">,
): Map<string, PreviewChange> {
  const changes = new Map<string, PreviewChange>();
  const change = (nodeId: string | undefined): PreviewChange | null => {
    if (!nodeId) return null;
    const current = changes.get(nodeId) ?? { removed: false };
    changes.set(nodeId, current);
    return current;
  };

  operations.forEach((op, index) => {
    if (states[index] !== "pending") return;
    if (op.op === "rename" && op.title) {
      const current = change(op.node_id);
      if (current) current.nextTitle = op.title;
    } else if (op.op === "change_type" && op.node_type) {
      const current = change(op.node_id);
      if (current) current.nextType = op.node_type;
    } else if (op.op === "set_visibility" && !op.is_in_current_program) {
      const current = change(op.node_id);
      if (current) current.removed = true;
    } else if (op.op === "merge") {
      const [survivor, ...removed] = op.node_ids ?? [];
      const survivorChange = change(survivor);
      if (survivorChange && op.title) survivorChange.nextTitle = op.title;
      removed.forEach((nodeId) => {
        const current = change(nodeId);
        if (current) current.removed = true;
      });
    }
  });
  return changes;
}

function addRows(operations: ProgramChatOperationView[], depth: number, prefix: string): PreviewRow[] {
  return operations
    .filter((op) => op.op === "add")
    .map((op, index) => ({
      key: `${prefix}-new-${index}`,
      depth,
      title: op.title ?? "",
      nodeType: op.node_type ?? "topic",
      status: "new",
      children: addRows(op.children ?? [], depth + 1, `${prefix}-new-${index}`),
    }));
}

/** Строит дерево текущих узлов и добавляет предложенные ветви рядом с родителями. */
function buildTree(
  program: ProgramState,
  pendingAdds: ProgramChatOperationView[],
  changes: Map<string, PreviewChange>,
): PreviewRow[] {
  const childrenByParent = new Map<string | null, ProgramNodeRead[]>();
  for (const node of program.nodes) {
    if (!node.is_in_current_program || node.is_archived) continue;
    const list = childrenByParent.get(node.parent_id) ?? [];
    list.push(node);
    childrenByParent.set(node.parent_id, list);
  }
  for (const list of childrenByParent.values()) list.sort((a, b) => a.sort_order - b.sort_order);

  const addsByParent = new Map<string | null, ProgramChatOperationView[]>();
  for (const op of pendingAdds) {
    const parentId = op.parent_node_id ?? null;
    const list = addsByParent.get(parentId) ?? [];
    list.push(op);
    addsByParent.set(parentId, list);
  }

  function walk(parentId: string | null, depth: number): PreviewRow[] {
    const rows: PreviewRow[] = (childrenByParent.get(parentId) ?? []).map((node) => {
      const pending = changes.get(node.id);
      return {
        key: node.id,
        depth,
        title: node.title,
        nodeType: node.node_type,
        status: pending?.removed ? "removed" : "unchanged",
        nextTitle: pending?.nextTitle,
        nextType: pending?.nextType,
        children: walk(node.id, depth + 1),
      };
    });
    rows.push(...addRows(addsByParent.get(parentId) ?? [], depth, parentId ?? "root"));
    return rows;
  }
  return walk(null, 0);
}

function Row({ row }: { row: PreviewRow }) {
  return (
    <li className={`program-tree-preview-row is-${row.status}`} style={{ marginInlineStart: row.depth * 16 }}>
      <span className={`program-tree-preview-type ${row.nextType ? "is-removed" : ""}`}>
        {NODE_TYPE_LABELS[row.nodeType] ?? row.nodeType}
      </span>
      <span className={`program-tree-preview-title ${row.nextTitle ? "is-removed" : ""}`}>{row.title}</span>
      {row.nextType && (
        <span className="program-tree-preview-type is-new">{NODE_TYPE_LABELS[row.nextType] ?? row.nextType}</span>
      )}
      {row.nextTitle && <span className="program-tree-preview-title is-new">{row.nextTitle}</span>}
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

/** Read-only предпросмотр текущей программы и последнего непринятого дифа. */
export function ProgramTreePreview({ program, pendingOperations = [], pendingStates = [] }: ProgramTreePreviewProps) {
  const changes = collectChanges(pendingOperations, pendingStates);
  const pendingAdds = pendingOperations.filter((op, index) => pendingStates[index] === "pending" && op.op === "add");
  const rows = buildTree(program, pendingAdds, changes);

  if (rows.length === 0) {
    return (
      <div className="program-tree-preview">
        <PreviewHeader />
        <EmptyState title="Программа пока пуста">
          <p>Предложенные разделы и темы появятся здесь до принятия изменений.</p>
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="program-tree-preview" role="tree" aria-label="Предпросмотр программы">
      <PreviewHeader />
      <ul className="program-tree-preview-root">
        {rows.map((row) => <Row key={row.key} row={row} />)}
      </ul>
    </div>
  );
}

function PreviewHeader() {
  return (
    <header className="program-tree-preview-head">
      <h2>Предпросмотр программы</h2>
      <p><span />Без изменений <span className="is-new" />Добавится <span className="is-removed" />Удалится</p>
    </header>
  );
}
