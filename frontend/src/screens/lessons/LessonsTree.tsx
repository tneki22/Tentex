import { useState, type ReactNode } from "react";
import { Search, X } from "lucide-react";
import type { LessonSummaryRead } from "../../api/lessons";
import { ProgramSectionRow, ProgramTopicRow } from "../../components/domain";
import { Button, Checkbox, Tooltip } from "../../components/ui";
import { filterProgramTree, type ProgramTreeNode } from "../programTree";
import { countsByNode, isVisible, lessonStateMark, studyNodesOf, sumCounts } from "./lessonTree";

interface LessonsTreeProps {
  tree: ProgramTreeNode[];
  lessons: LessonSummaryRead[];
  activeNodeId: string | null;
  selection: Set<string>;
  onSelectNode(nodeId: string): void;
  onSelectionChange(next: Set<string>): void;
}

/** Дерево программы раздела «Уроки»: состояние уроков у темы, суммы у разделов, массовый выбор. */
export function LessonsTree({ tree, lessons, activeNodeId, selection, onSelectNode, onSelectionChange }: LessonsTreeProps) {
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const counts = countsByNode(lessons);
  const needle = query.trim().toLocaleLowerCase("ru");
  const lessonMatches = needle
    ? new Set(lessons.filter((lesson) => lesson.title.toLocaleLowerCase("ru").includes(needle)).flatMap((lesson) => lesson.program_node_ids))
    : new Set<string>();
  const filtered = needle ? filterTree(tree, needle, lessonMatches) : tree;

  function toggleSelection(nodes: ProgramTreeNode[], checked: boolean) {
    const next = new Set(selection);
    for (const node of nodes) {
      if (checked) next.add(node.id);
      else next.delete(node.id);
    }
    onSelectionChange(next);
  }

  function render(nodes: ProgramTreeNode[]): ReactNode {
    return nodes.map((node) => {
      if (!isVisible(node)) return null;
      const open = Boolean(needle) || !collapsed.has(node.id);
      if (node.node_type === "section") {
        const study = studyNodesOf(node.children);
        const total = sumCounts(node.children, counts);
        const allChecked = study.length > 0 && study.every((item) => selection.has(item.id));
        return (
          <section className="workspace-tree-section" key={node.id}>
            <ProgramSectionRow
              number={node.number}
              title={node.title}
              open={open}
              active={activeNodeId === node.id}
              leading={<Checkbox label={`Выбрать темы раздела «${node.title}»`} checked={allChecked} disabled={study.length === 0} onCheckedChange={(checked) => toggleSelection(study, checked)} />}
              aside={<span className="lessons-section-sum" aria-label={`Готовых ${total.ready}, черновиков ${total.drafts}, требуют проверки ${total.needsReview}`}>{total.ready > 0 && `✓ ${total.ready}`}{total.drafts > 0 && ` ● ${total.drafts}`}{total.needsReview > 0 && ` ⚠ ${total.needsReview}`}{total.ready + total.drafts === 0 && "—"}</span>}
              onToggle={() => setCollapsed((current) => {
                const next = new Set(current);
                if (next.has(node.id)) next.delete(node.id); else next.add(node.id);
                return next;
              })}
              onSelect={() => onSelectNode(node.id)}
            />
            {open && <div className="workspace-question-list">{render(node.children)}</div>}
          </section>
        );
      }
      const state = lessonStateMark(counts.get(node.id));
      return (
        <div className="workspace-question-node lessons-tree-node" key={node.id}>
          <div className={`lessons-tree-row depth-${Math.min(Math.max(node.depth - 2, 0), 3)}`}>
            <Checkbox label={`Выбрать «${node.title}»`} checked={selection.has(node.id)} onCheckedChange={(checked) => toggleSelection([node], checked)} />
            <ProgramTopicRow
              depth={node.depth}
              active={activeNodeId === node.id}
              onClick={() => onSelectNode(node.id)}
              status={null}
              eyebrow={`${node.node_type === "subpoint" ? "Подпункт" : "Тема"} ${node.number}`}
              title={node.title}
              signals={<Tooltip label={state.label}><span className={`lessons-state-mark ${state.tone}`} aria-label={state.label}>{state.mark}</span></Tooltip>}
            />
          </div>
          {node.children.length > 0 && <div className="workspace-question-list is-nested">{render(node.children)}</div>}
        </div>
      );
    });
  }

  return (
    <>
      <div className="workspace-tree-tools is-search-only">
        <label className="workspace-tree-search">
          <Search size={15} />
          <span className="sr-only">Найти тему или урок</span>
          <input type="search" placeholder="Найти тему или урок" value={query} onChange={(event) => setQuery(event.target.value)} />
          {query && <button type="button" onClick={() => setQuery("")} aria-label="Очистить поиск"><X size={14} /></button>}
        </label>
      </div>
      {selection.size > 0 && (
        <div className="lessons-selection-bar">
          <span>Выбрано тем: {selection.size}</span>
          <Button variant="ghost" onClick={() => onSelectionChange(new Set())}>Очистить выбор</Button>
        </div>
      )}
      <nav className="workspace-question-tree lessons-tree" aria-label="Программа">
        {filtered.length > 0 ? render(filtered) : <p className="workspace-tree-empty">По запросу ничего не найдено.</p>}
      </nav>
    </>
  );
}

function filterTree(tree: ProgramTreeNode[], needle: string, lessonMatches: Set<string>): ProgramTreeNode[] {
  const byTitle = filterProgramTree(tree, needle);
  if (lessonMatches.size === 0) return byTitle;
  return tree.flatMap((node) => {
    const children = filterTree(node.children, needle, lessonMatches);
    const matches = node.title.toLocaleLowerCase("ru").includes(needle) || lessonMatches.has(node.id);
    return matches || children.length ? [{ ...node, children }] : [];
  });
}
