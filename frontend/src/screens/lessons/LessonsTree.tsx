import { memo, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Search, X } from "lucide-react";
import type { LessonSummaryRead } from "../../api/lessons";
import { ProgramSectionRow, ProgramTopicRow } from "../../components/domain/ProgramTreeRows";
import { Button, Checkbox, Tooltip } from "../../components/ui";
import { filterProgramTree, type ProgramTreeNode } from "../programTree";
import { countsByNode, isVisible, lessonStateMark, studyNodesOf, sumCounts, type LessonCounts } from "./lessonTree";

interface LessonsTreeProps {
  tree: ProgramTreeNode[];
  lessons: LessonSummaryRead[];
  activeNodeId: string | null;
  selection: Set<string>;
  onSelectNode(nodeId: string): void;
  onSelectionChange(next: Set<string>): void;
}

/**
 * Дерево программы раздела «Уроки»: состояние уроков у темы, суммы у разделов, массовый выбор.
 *
 * У крупного учебника сотни строк. Строки мемоизированы и получают только
 * примитивы и постоянные обработчики, поэтому выбор темы или флажка
 * перерисовывает две-три строки, а не всё дерево.
 */
export function LessonsTree({ tree, lessons, activeNodeId, selection, onSelectNode, onSelectionChange }: LessonsTreeProps) {
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const counts = useMemo(() => countsByNode(lessons), [lessons]);
  const needle = query.trim().toLocaleLowerCase("ru");
  const filtered = useMemo(() => {
    if (!needle) return tree;
    const lessonMatches = new Set(lessons.filter((lesson) => lesson.title.toLocaleLowerCase("ru").includes(needle)).flatMap((lesson) => lesson.program_node_ids));
    return filterTree(tree, needle, lessonMatches);
  }, [tree, lessons, needle]);
  // Изучаемые темы раздела не зависят от выбора: один массив на раздел и дерево.
  const studyBySection = useMemo(() => {
    const result = new Map<string, string[]>();
    const visit = (nodes: ProgramTreeNode[]) => {
      for (const node of nodes) {
        if (node.node_type === "section") result.set(node.id, studyNodesOf(node.children).map((item) => item.id));
        visit(node.children);
      }
    };
    visit(filtered);
    return result;
  }, [filtered]);

  // Обработчики строк постоянны: свежие выбор и колбэк родителя читаются из ref.
  const latest = useRef({ selection, onSelectNode, onSelectionChange });
  useEffect(() => { latest.current = { selection, onSelectNode, onSelectionChange }; });
  const toggleSelection = useCallback((ids: string[], checked: boolean) => {
    const next = new Set(latest.current.selection);
    for (const id of ids) {
      if (checked) next.add(id);
      else next.delete(id);
    }
    latest.current.onSelectionChange(next);
  }, []);
  const selectNode = useCallback((nodeId: string) => latest.current.onSelectNode(nodeId), []);
  const toggleSection = useCallback((nodeId: string) => setCollapsed((current) => {
    const next = new Set(current);
    if (next.has(nodeId)) next.delete(nodeId); else next.add(nodeId);
    return next;
  }), []);

  function render(nodes: ProgramTreeNode[]): ReactNode {
    return nodes.map((node) => {
      if (!isVisible(node)) return null;
      const open = Boolean(needle) || !collapsed.has(node.id);
      if (node.node_type === "section") {
        const study = studyBySection.get(node.id) ?? [];
        const total = sumCounts(node.children, counts);
        return (
          <section className="workspace-tree-section" key={node.id}>
            <SectionRow
              id={node.id}
              number={node.number}
              title={node.title}
              open={open}
              active={activeNodeId === node.id}
              study={study}
              allChecked={study.length > 0 && study.every((id) => selection.has(id))}
              ready={total.ready}
              drafts={total.drafts}
              needsReview={total.needsReview}
              onToggle={toggleSection}
              onSelect={selectNode}
              onCheck={toggleSelection}
            />
            {open && <div className="workspace-question-list">{render(node.children)}</div>}
          </section>
        );
      }
      return (
        <div className="workspace-question-node lessons-tree-node" key={node.id}>
          <TopicRow
            id={node.id}
            number={node.number}
            title={node.title}
            depth={node.depth}
            subpoint={node.node_type === "subpoint"}
            active={activeNodeId === node.id}
            checked={selection.has(node.id)}
            counts={counts.get(node.id)}
            onSelect={selectNode}
            onCheck={toggleSelection}
          />
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

interface SectionRowProps {
  id: string;
  number: string;
  title: string;
  open: boolean;
  active: boolean;
  study: string[];
  allChecked: boolean;
  ready: number;
  drafts: number;
  needsReview: number;
  onToggle(id: string): void;
  onSelect(id: string): void;
  onCheck(ids: string[], checked: boolean): void;
}

const SectionRow = memo(function SectionRow({ id, number, title, open, active, study, allChecked, ready, drafts, needsReview, onToggle, onSelect, onCheck }: SectionRowProps) {
  return (
    <ProgramSectionRow
      number={number}
      title={title}
      open={open}
      active={active}
      leading={<Checkbox label={`Выбрать темы раздела «${title}»`} checked={allChecked} disabled={study.length === 0} onCheckedChange={(checked) => onCheck(study, checked)} />}
      aside={<span className="lessons-section-sum" aria-label={`Готовых ${ready}, черновиков ${drafts}, требуют проверки ${needsReview}`}>{ready > 0 && `✓ ${ready}`}{drafts > 0 && ` ● ${drafts}`}{needsReview > 0 && ` ⚠ ${needsReview}`}{ready + drafts === 0 && "—"}</span>}
      onToggle={() => onToggle(id)}
      onSelect={() => onSelect(id)}
    />
  );
});

interface TopicRowProps {
  id: string;
  number: string;
  title: string;
  depth: number;
  subpoint: boolean;
  active: boolean;
  checked: boolean;
  counts: LessonCounts | undefined;
  onSelect(id: string): void;
  onCheck(ids: string[], checked: boolean): void;
}

const TopicRow = memo(function TopicRow({ id, number, title, depth, subpoint, active, checked, counts, onSelect, onCheck }: TopicRowProps) {
  const state = lessonStateMark(counts);
  return (
    <div className={`lessons-tree-row depth-${Math.min(Math.max(depth - 2, 0), 3)}`}>
      <Checkbox label={`Выбрать «${title}»`} checked={checked} onCheckedChange={(value) => onCheck([id], value)} />
      <ProgramTopicRow
        depth={depth}
        active={active}
        onClick={() => onSelect(id)}
        status={null}
        eyebrow={`${subpoint ? "Подпункт" : "Тема"} ${number}`}
        title={title}
        signals={<Tooltip lazy label={state.label}><span className={`lessons-state-mark ${state.tone}`} aria-label={state.label}>{state.mark}</span></Tooltip>}
      />
    </div>
  );
});

function filterTree(tree: ProgramTreeNode[], needle: string, lessonMatches: Set<string>): ProgramTreeNode[] {
  const byTitle = filterProgramTree(tree, needle);
  if (lessonMatches.size === 0) return byTitle;
  return tree.flatMap((node) => {
    const children = filterTree(node.children, needle, lessonMatches);
    const matches = node.title.toLocaleLowerCase("ru").includes(needle) || lessonMatches.has(node.id);
    return matches || children.length ? [{ ...node, children }] : [];
  });
}
