import type { CSSProperties } from "react";
import type { ProgramTreeNode } from "./programTree";

const NODE_TYPE_LABEL: Record<ProgramTreeNode["node_type"], string> = {
  section: "раздел",
  topic: "тема",
  subpoint: "подпункт",
};

/** Строки программы на экране проверки мастера: отступ по глубине дерева,
 * разделы выделены как заголовки групп. Общая для учебникового и свободного мастера. */
export function ProgramReviewList({ nodes }: { nodes: ProgramTreeNode[] }) {
  return (
    <>
      {nodes.map((node) => (
        <div
          key={node.id}
          className={`program-review-row is-${node.node_type}`}
          style={{ "--depth": node.depth - 1 } as CSSProperties}
        >
          <span>{node.number}</span>
          <b>{node.title}</b>
          <small>{NODE_TYPE_LABEL[node.node_type]}</small>
        </div>
      ))}
    </>
  );
}
