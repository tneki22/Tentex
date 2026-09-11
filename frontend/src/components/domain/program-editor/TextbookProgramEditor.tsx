import { useEffect, useMemo, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  BookOpen,
  Copy,
  Pencil,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import { getMaterialOutline, type MaterialRead } from "../../../api/materials";
import {
  createProgramNode,
  importProgramOutlines,
  moveProgramNode,
  removeAllProgramNodes,
  removeProgramNode,
  updateProgramNode,
  type LatestUndoableAction,
  type NodeType,
  type ProgramChangeResult,
  type ProgramOutlineImportItem,
  type ProgramState,
} from "../../../api/projects";
import {
  buildProgramTree,
  filterProgramTree,
  flattenProgramTree,
  type ProgramTreeNode,
} from "../../../screens/programTree";
import {
  Button,
  ConfirmDialog,
  ContextMenu,
  Dialog,
  IconButton,
  LoadingState,
  SegmentedTabs,
} from "../../ui";
import type { ContextMenuItem } from "../../ui";
import {
  outlineItemsWithKeys,
  type OutlineDraftState,
  type OutlinesByMaterialId,
} from "./outlineState";

export type TextbookProgramView = "tree" | "text" | "questions";
const EMPTY_OUTLINES: OutlinesByMaterialId = {};

interface TextbookProgramEditorProps {
  projectId: string;
  projectName: string;
  program: ProgramState;
  latestUndoableAction: LatestUndoableAction | null;
  materials: MaterialRead[];
  outlinesByMaterialId?: OutlinesByMaterialId;
  wizard?: boolean;
  busy?: boolean;
  view: TextbookProgramView;
  onViewChange: (view: TextbookProgramView) => void;
  execute: (
    command: (revision: number) => Promise<ProgramChangeResult>,
  ) => Promise<ProgramChangeResult>;
  onUndo: () => Promise<void>;
  renderHeader?: (actions: TextbookProgramEditorActions) => ReactNode;
  /** «Вручную» — дерево/текст/вопросы и CRUD ниже; «С ИИ» — контентная область
   * заменяется на `aiContent` (чат с дифами), тулбар (Отменить/переключатель
   * режима/Импорт/Удалить все) и диалоги импорта/удаления остаются общими. */
  mode?: "manual" | "ai";
  aiContent?: ReactNode;
}

/** Общая поверхность учебниковой программы для мастера и активного проекта:
 * режим «Вручную» — ручной редактор ниже, «С ИИ» — `aiContent` вызывающей стороны. */
export function TextbookProgramEditor({
  projectId,
  projectName,
  program,
  latestUndoableAction,
  materials,
  outlinesByMaterialId,
  wizard = false,
  busy: parentBusy = false,
  view,
  onViewChange,
  execute,
  onUndo,
  renderHeader,
  mode = "manual",
  aiContent,
}: TextbookProgramEditorProps) {
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [actionError, setActionError] = useState("");
  const [acting, setActing] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [removeAllOpen, setRemoveAllOpen] = useState(false);
  const busy = parentBusy || acting;
  const nodes = program.nodes.filter((node) => node.is_in_current_program && !node.is_archived);
  const tree = useMemo(() => {
    try {
      return buildProgramTree(nodes);
    } catch {
      return [];
    }
  }, [nodes]);
  const flat = useMemo(() => flattenProgramTree(tree), [tree]);
  const visibleFlat = useMemo(
    () => flattenProgramTree(filterProgramTree(tree, query)),
    [query, tree],
  );
  const selected = flat.find((node) => node.id === selectedId) ?? flat[0] ?? null;
  const siblings = selected ? flat.filter((node) => node.parent_id === selected.parent_id) : [];
  const selectedIndex = selected ? siblings.findIndex((node) => node.id === selected.id) : -1;
  const selectedParent = selected?.parent_id
    ? flat.find((node) => node.id === selected.parent_id) ?? null
    : null;
  const previousSibling = selectedIndex > 0 ? siblings[selectedIndex - 1] : null;

  useEffect(() => {
    if (selected && selected.id !== selectedId) setSelectedId(selected.id);
  }, [selected, selectedId]);

  async function run(command: (revision: number) => Promise<ProgramChangeResult>) {
    setActing(true);
    setActionError("");
    try {
      return await execute(command);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось изменить программу");
      return null;
    } finally {
      setActing(false);
    }
  }

  function subtreeHeight(nodeId: string): number {
    const children = flat.filter((node) => node.parent_id === nodeId);
    return children.length
      ? 1 + Math.max(...children.map((child) => subtreeHeight(child.id)))
      : 1;
  }

  const canIndent = Boolean(
    selected && previousSibling && previousSibling.depth + subtreeHeight(selected.id) <= 4,
  );

  async function createNode(
    nodeType: NodeType,
    parentId: string | null,
    position: number | null = null,
  ) {
    const result = await run((revision) => createProgramNode(projectId, {
      expected_program_revision: revision,
      parent_id: parentId,
      position,
      node_type: nodeType,
      exam_kind: null,
      title: nodeType === "section"
        ? "Новый раздел"
        : nodeType === "topic" ? "Новая тема" : "Новый подпункт",
      goal_role: "target",
    }));
    if (result?.changed_node) {
      setSelectedId(result.changed_node.id);
      setEditingId(result.changed_node.id);
      setEditingTitle(result.changed_node.title);
    }
  }

  async function renameNode(node: ProgramTreeNode) {
    const title = editingTitle.trim();
    if (!title || title === node.title) {
      setEditingId(null);
      return;
    }
    const result = await run((revision) => updateProgramNode(projectId, node.id, {
      expected_program_revision: revision,
      title,
    }));
    if (result) setEditingId(null);
  }

  async function moveNode(node: ProgramTreeNode, position: number, parentId = node.parent_id) {
    await run((revision) => moveProgramNode(projectId, node.id, {
      expected_program_revision: revision,
      parent_id: parentId,
      position,
    }));
  }

  async function changeNodeType(node: ProgramTreeNode, nodeType: NodeType) {
    if (node.node_type === nodeType) return;
    await run((revision) => updateProgramNode(projectId, node.id, {
      expected_program_revision: revision,
      node_type: nodeType,
      exam_kind: null,
    }));
  }

  async function duplicateNode(node: ProgramTreeNode) {
    const nodeSiblings = flat.filter((item) => item.parent_id === node.parent_id);
    const index = nodeSiblings.findIndex((item) => item.id === node.id);
    const result = await run((revision) => createProgramNode(projectId, {
      expected_program_revision: revision,
      parent_id: node.parent_id,
      position: index + 1,
      node_type: node.node_type,
      exam_kind: null,
      title: `${node.title} — копия`,
      section_purpose: node.section_purpose,
      goal_role: node.goal_role,
      target_level: node.target_level,
      needs_material: node.needs_material,
    }));
    if (result?.changed_node) setSelectedId(result.changed_node.id);
  }

  function startRename(node: ProgramTreeNode) {
    setSelectedId(node.id);
    setEditingId(node.id);
    setEditingTitle(node.title);
  }

  function childType(node: ProgramTreeNode): NodeType {
    return node.node_type === "section" ? "topic" : "subpoint";
  }

  function nodeMenuItems(node: ProgramTreeNode): ContextMenuItem[] {
    const nodeSiblings = flat.filter((item) => item.parent_id === node.parent_id);
    const index = nodeSiblings.findIndex((item) => item.id === node.id);
    const previous = index > 0 ? nodeSiblings[index - 1] : null;
    const parent = node.parent_id
      ? flat.find((item) => item.id === node.parent_id) ?? null
      : null;
    const canNest = Boolean(previous && previous.depth + subtreeHeight(node.id) <= 4);
    return [
      {
        label: "Добавить внутрь",
        icon: <Plus size={14} />,
        items: (["section", "topic", "subpoint"] as NodeType[]).map((nodeType) => ({
          label: nodeType === "section" ? "Раздел" : nodeType === "topic" ? "Тему" : "Подпункт",
          disabled: busy || node.depth >= 4,
          onSelect: () => void createNode(nodeType, node.id),
        })),
      },
      { label: "Добавить перед", icon: <ArrowUp size={14} />, disabled: busy, onSelect: () => void createNode(node.node_type, node.parent_id, index) },
      { label: "Добавить после", icon: <ArrowDown size={14} />, disabled: busy, onSelect: () => void createNode(node.node_type, node.parent_id, index + 1) },
      { label: "Переименовать", icon: <Pencil size={14} />, disabled: busy, onSelect: () => startRename(node) },
      { label: "Продублировать", icon: <Copy size={14} />, disabled: busy, onSelect: () => void duplicateNode(node) },
      {
        label: "Тип узла",
        items: (["section", "topic", "subpoint"] as NodeType[]).map((nodeType) => ({
          label: nodeType === "section" ? "Раздел" : nodeType === "topic" ? "Тема" : "Подпункт",
          disabled: busy || node.node_type === nodeType,
          onSelect: () => void changeNodeType(node, nodeType),
        })),
      },
      { label: "Поднять", icon: <ArrowUp size={14} />, disabled: busy || index <= 0, onSelect: () => void moveNode(node, index - 1) },
      { label: "Опустить", icon: <ArrowDown size={14} />, disabled: busy || index < 0 || index === nodeSiblings.length - 1, onSelect: () => void moveNode(node, index + 1) },
      { label: "Уменьшить вложенность", icon: <ArrowLeft size={14} />, disabled: busy || !parent, onSelect: () => parent && void moveNode(node, parent.sort_order + 1, parent.parent_id) },
      { label: "Увеличить вложенность", icon: <ArrowRight size={14} />, disabled: busy || !canNest || !previous, onSelect: () => previous && void moveNode(node, previous.children.length, previous.id) },
      { label: "Убрать из программы", icon: <Trash2 size={14} />, destructive: true, disabled: busy, onSelect: () => void run((revision) => removeProgramNode(projectId, node.id, revision)) },
    ];
  }

  async function undo() {
    setActing(true);
    setActionError("");
    try {
      await onUndo();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось отменить действие");
    } finally {
      setActing(false);
    }
  }

  return (
    <section className="textbook-program-editor">
      {renderHeader?.({
        openImport: () => setImportOpen(true),
        openRemoveAll: () => setRemoveAllOpen(true),
        undo,
        busy,
        canUndo: Boolean(latestUndoableAction),
        hasNodes: nodes.length > 0,
      })}
      <div className="textbook-program-error-slot">
        {actionError && <p className="inline-error" role="alert">{actionError}</p>}
      </div>
      {mode === "ai" ? (
        <div className="textbook-program-ai-content">{aiContent}</div>
      ) : (
        <>
          <div className="textbook-program-toolbar">
            <SegmentedTabs label="Представление программы" value={view} onChange={onViewChange} tabs={[{ value: "tree", label: "Дерево" }, { value: "text", label: "Текст" }, { value: "questions", label: "Вопросы" }]} />
            <label className="textbook-search"><Search size={15} aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти тему" aria-label="Найти тему" /></label>
          </div>

          <div className="textbook-manual-toolbar" aria-label="Ручные действия с узлом программы">
            <div className="textbook-add-actions">
              <Button disabled={busy} onClick={() => void createNode("section", null)}><Plus size={15} />Добавить раздел</Button>
              <Button variant="secondary" disabled={busy || !selected || selected.depth >= 4} onClick={() => selected && void createNode(childType(selected), selected.id)}><Plus size={15} />{selected ? selected.node_type === "section" ? "Добавить тему" : "Добавить подпункт" : "Добавить внутрь"}</Button>
              <Button variant="ghost" disabled={busy || !selected} onClick={() => selected && void createNode(selected.node_type, selected.parent_id, selectedIndex + 1)}>Добавить рядом</Button>
            </div>
            <span>Выбрано: <b>{selected?.title ?? "узел не выбран"}</b></span>
            {selected && <label className="textbook-selected-type"><span>Тип</span><select value={selected.node_type} disabled={busy} onChange={(event) => void changeNodeType(selected, event.target.value as NodeType)}><option value="section">Раздел</option><option value="topic">Тема</option><option value="subpoint">Подпункт</option></select></label>}
            <div className="textbook-node-actions">
              <IconButton label="Поднять узел" disabled={busy || selectedIndex <= 0} onClick={() => selected && void moveNode(selected, selectedIndex - 1)}><ArrowUp size={15} /></IconButton>
              <IconButton label="Опустить узел" disabled={busy || selectedIndex < 0 || selectedIndex === siblings.length - 1} onClick={() => selected && void moveNode(selected, selectedIndex + 1)}><ArrowDown size={15} /></IconButton>
              <IconButton label="Уменьшить вложенность" disabled={busy || !selectedParent} onClick={() => selected && selectedParent && void moveNode(selected, selectedParent.sort_order + 1, selectedParent.parent_id)}><ArrowLeft size={15} /></IconButton>
              <IconButton label="Увеличить вложенность" disabled={busy || !canIndent || !previousSibling} onClick={() => selected && previousSibling && void moveNode(selected, previousSibling.children.length, previousSibling.id)}><ArrowRight size={15} /></IconButton>
              <IconButton label="Редактировать формулировку" disabled={busy || !selected} onClick={() => selected && startRename(selected)}><Pencil size={15} /></IconButton>
              <IconButton label="Продублировать узел" disabled={busy || !selected} onClick={() => selected && void duplicateNode(selected)}><Copy size={15} /></IconButton>
              <IconButton label="Убрать узел из программы" disabled={busy || !selected} onClick={() => selected && void run((revision) => removeProgramNode(projectId, selected.id, revision))}><Trash2 size={15} /></IconButton>
            </div>
          </div>

          <div className="textbook-program-content" role={view === "tree" ? "tree" : undefined} aria-label={view === "tree" ? "Дерево программы" : undefined}>
            {view === "tree" && visibleFlat.map((node) => (
              <ContextMenu key={node.id} label={`Действия с «${node.title}»`} items={nodeMenuItems(node)} trigger={renderTreeRow(node, {
                selected: selected?.id === node.id,
                editing: editingId === node.id,
                editingTitle,
                onSelect: setSelectedId,
                onStartRename: startRename,
                onEditingTitle: setEditingTitle,
                onRename: renameNode,
                onCancelRename: () => setEditingId(null),
              })} />
            ))}
            {view === "tree" && visibleFlat.length === 0 && <div className="textbook-editor-empty"><BookOpen size={28} aria-hidden="true" /><h2>{query ? "Ничего не найдено" : "Составьте программу"}</h2><p>{query ? "Измените запрос, чтобы увидеть остальные узлы." : "Добавьте раздел вручную или импортируйте готовое оглавление. До четырёх уровней вложенности."}</p><div>{query ? <Button variant="secondary" onClick={() => setQuery("")}>Очистить поиск</Button> : <><Button disabled={busy} onClick={() => void createNode("section", null)}><Plus size={15} />Добавить первый раздел</Button><Button variant="secondary" disabled={busy} onClick={() => setImportOpen(true)}>Импортировать оглавление</Button></>}</div></div>}
            {view === "text" && <article className="textbook-text-view"><h2>{projectName || "Программа"}</h2>{visibleFlat.map((node) => <p key={node.id}><b>{node.number}. {node.title}</b> — {node.node_type === "section" ? "раздел" : node.node_type === "topic" ? "тема" : "подпункт"}.</p>)}</article>}
            {view === "questions" && <ol className="textbook-question-view">{visibleFlat.filter((node) => node.node_type !== "section").map((node) => <li key={node.id}>Как объяснить: «{node.title}»?</li>)}</ol>}
          </div>
        </>
      )}

      <TextbookOutlineImportDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        projectId={projectId}
        materials={materials}
        program={program}
        outlinesByMaterialId={outlinesByMaterialId}
        wizard={wizard}
        busy={busy}
        onImport={async (sources) => {
          const result = await run((revision) => importProgramOutlines(projectId, {
            expected_program_revision: revision,
            sources,
          }));
          if (result) setImportOpen(false);
        }}
      />
      <ConfirmDialog open={removeAllOpen} onOpenChange={setRemoveAllOpen} title="Удалить всю программу?" confirmLabel="Удалить все" destructive onConfirm={() => void run((revision) => removeAllProgramNodes(projectId, revision)).then((result) => { if (result) setRemoveAllOpen(false); })}>
        <p>Все видимые разделы и темы выйдут из текущей программы. Данные узлов сохранятся, действие отменяется одним нажатием.</p>
      </ConfirmDialog>
    </section>
  );
}

interface TreeRowActions {
  selected: boolean;
  editing: boolean;
  editingTitle: string;
  onSelect: (id: string) => void;
  onStartRename: (node: ProgramTreeNode) => void;
  onEditingTitle: (title: string) => void;
  onRename: (node: ProgramTreeNode) => Promise<void>;
  onCancelRename: () => void;
}

function renderTreeRow(node: ProgramTreeNode, actions: TreeRowActions): ReactNode {
  const sourceTitle = node.source_page_ranges.length
    ? node.source_page_ranges.map((range) => `${range.source_name_snapshot}: с. ${range.page_from}–${range.page_to}`).join("; ")
    : "Узел создан вне оглавления";
  return (
    <div
      className={`textbook-program-row ${actions.selected ? "is-selected" : ""}`.trim()}
      style={{ paddingInlineStart: `calc(var(--space-4) + ${node.depth - 1} * var(--space-6))` }}
      role="treeitem"
      aria-level={node.depth}
      aria-selected={actions.selected}
      tabIndex={actions.selected ? 0 : -1}
      onClick={() => actions.onSelect(node.id)}
      onContextMenu={() => actions.onSelect(node.id)}
      onDoubleClick={() => actions.onStartRename(node)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          actions.onSelect(node.id);
        }
      }}
    >
      <span className="textbook-program-number">{node.number}</span>
      <span className="textbook-program-copy">
        {actions.editing
          ? <input autoFocus value={actions.editingTitle} onClick={(event) => event.stopPropagation()} onChange={(event) => actions.onEditingTitle(event.target.value)} onBlur={() => void actions.onRename(node)} onKeyDown={(event) => { if (event.key === "Enter") void actions.onRename(node); if (event.key === "Escape") actions.onCancelRename(); }} aria-label={`Формулировка «${node.title}»`} />
          : <b>{node.title}</b>}
        <small>{node.node_type === "section" ? "раздел" : node.node_type === "topic" ? "тема" : "подпункт"}</small>
      </span>
      <span className={`textbook-program-basis is-${node.basis_kind}`} title={sourceTitle}>
        <i aria-hidden="true" />
        {node.basis_kind === "outline" ? "По оглавлению" : "Вне оглавления"}
      </span>
    </div>
  );
}

interface ImportSource {
  material: MaterialRead;
  outline: OutlineDraftState;
}

interface TextbookOutlineImportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  materials: MaterialRead[];
  program: ProgramState;
  outlinesByMaterialId?: OutlinesByMaterialId;
  wizard: boolean;
  busy: boolean;
  onImport: (sources: Array<{ material_id: string; items: ProgramOutlineImportItem[] }>) => Promise<void>;
}

function TextbookOutlineImportDialog({
  open,
  onOpenChange,
  projectId,
  materials,
  program,
  outlinesByMaterialId = EMPTY_OUTLINES,
  wizard,
  busy,
  onImport,
}: TextbookOutlineImportDialogProps) {
  const [sources, setSources] = useState<ImportSource[]>([]);
  const [selectedSources, setSelectedSources] = useState<Set<string>>(new Set());
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [depth, setDepth] = useState(4);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    const abort = new AbortController();
    setLoading(true);
    setError("");
    Promise.all(materials.map(async (material): Promise<ImportSource> => {
      const saved = outlinesByMaterialId[material.id];
      if (saved) return { material, outline: saved };
      const detail = await getMaterialOutline(projectId, material.id, "auto", abort.signal);
      return {
        material,
        outline: {
          material_id: material.id,
          source: detail.source,
          items: outlineItemsWithKeys(material.id, detail.source, detail.items),
          source_pages: detail.source_pages,
          review_pages: detail.review_pages,
          review_needs_check: detail.review_needs_check,
          edited: false,
          checked_at: null,
        },
      };
    }))
      .then((loaded) => {
        if (abort.signal.aborted) return;
        const ordered = loaded.sort((left, right) => left.material.priority - right.material.priority);
        setSources(ordered);
        setSelectedSources(new Set(ordered.filter((source) => source.outline.items.length).map((source) => source.material.id)));
        setSelectedKeys(new Set(ordered.flatMap((source) => source.outline.items.map((item) => item.outline_item_key))));
      })
      .catch((caught) => {
        if (!abort.signal.aborted) setError(caught instanceof Error ? caught.message : "Не удалось загрузить оглавления");
      })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [open, projectId, materials, outlinesByMaterialId]);

  const currentKeys = useMemo(() => new Set(program.nodes
    .filter((node) => node.is_in_current_program && !node.is_archived)
    .flatMap((node) => node.source_page_ranges.map((range) => `${range.material_id}:${range.outline_item_key}`))), [program.nodes]);
  const selectedCount = sources.reduce((count, source) => count + (
    selectedSources.has(source.material.id)
      ? source.outline.items.filter((item) => item.level <= depth
        && selectedKeys.has(item.outline_item_key)
        && !currentKeys.has(`${source.material.id}:${item.outline_item_key}`)).length
      : 0
  ), 0);
  const similarCount = similarPathCount(
    sources.filter((source) => selectedSources.has(source.material.id)),
    depth,
    selectedKeys,
  );

  function changeDepth(nextDepth: number) {
    setDepth(nextDepth);
    setSelectedKeys(new Set(sources.flatMap((source) => source.outline.items
      .filter((item) => item.level <= nextDepth)
      .map((item) => item.outline_item_key))));
  }

  function toggleSource(source: ImportSource, checked: boolean) {
    setSelectedSources((current) => {
      const next = new Set(current);
      if (checked) next.add(source.material.id); else next.delete(source.material.id);
      return next;
    });
  }

  function toggleItem(source: ImportSource, index: number, checked: boolean) {
    const item = source.outline.items[index];
    const affected = [item.outline_item_key];
    for (const candidate of source.outline.items.slice(index + 1)) {
      if (candidate.level <= item.level) break;
      affected.push(candidate.outline_item_key);
    }
    setSelectedKeys((current) => {
      const next = new Set(current);
      affected.forEach((key) => checked ? next.add(key) : next.delete(key));
      if (checked) {
        let parentLevel = item.level;
        for (let cursor = index - 1; cursor >= 0 && parentLevel > 1; cursor -= 1) {
          const candidate = source.outline.items[cursor];
          if (candidate.level < parentLevel) {
            next.add(candidate.outline_item_key);
            parentLevel = candidate.level;
          }
        }
      }
      return next;
    });
  }

  async function submit() {
    const selected = sources
      .filter((source) => selectedSources.has(source.material.id))
      .map((source) => ({
        material_id: source.material.id,
        items: source.outline.items.map((item) => ({
          outline_item_key: item.outline_item_key,
          level: item.level,
          title: item.title,
          page: item.page,
          selected: item.level <= depth && selectedKeys.has(item.outline_item_key),
        })),
      }))
      .filter((source) => source.items.some((item) => item.selected));
    if (selected.length) await onImport(selected);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Импортировать программу из оглавления"
      description="Выберите источники и ветви. Они добавятся отдельными корневыми ветвями в порядке приоритета источников."
      footer={<><Button variant="ghost" onClick={() => onOpenChange(false)}>Закрыть</Button><Button disabled={busy || loading || selectedCount === 0} onClick={() => void submit()}>Импортировать {selectedCount} {selectedCount === 1 ? "пункт" : "пунктов"}</Button></>}
    >
      {wizard && <p className="textbook-import-note">Проверить и исправить оглавления можно на предыдущем шаге.</p>}
      <label className="textbook-import-depth"><span>Глубина импорта</span><select value={depth} onChange={(event) => changeDepth(Number(event.target.value))}><option value={1}>1 уровень</option><option value={2}>2 уровня</option><option value={3}>3 уровня</option><option value={4}>4 уровня</option></select></label>
      {loading && <LoadingState label="Загружаем оглавления" />}
      {error && <p className="inline-error" role="alert">{error}</p>}
      {!loading && <div className="textbook-import-sources">
        {sources.map((source) => {
          const enabled = selectedSources.has(source.material.id);
          return <section key={source.material.id} className="textbook-import-source">
            <label className="textbook-import-source-head"><input type="checkbox" checked={enabled} disabled={source.outline.items.length === 0} onChange={(event) => toggleSource(source, event.target.checked)} /><span><b>{source.material.display_name}</b><small>{source.outline.items.length ? `${source.outline.items.length} пунктов · приоритет ${source.material.priority + 1}` : "Оглавление не найдено — источник можно оставить без импорта"}</small></span></label>
            {enabled && source.outline.items.length > 0 && <div className="textbook-import-tree">{source.outline.items.map((item, index) => {
              const hiddenByDepth = item.level > depth;
              const already = currentKeys.has(`${source.material.id}:${item.outline_item_key}`);
              return <label key={item.outline_item_key} style={{ "--outline-depth": Math.min(item.level - 1, 3) } as CSSProperties}>
                <CascadeCheckbox checked={!hiddenByDepth && selectedKeys.has(item.outline_item_key)} disabled={hiddenByDepth || already} onChange={(checked) => toggleItem(source, index, checked)} />
                <span><b>{item.title}</b><small>стр. {item.page}{already ? " · уже импортирован" : ""}</small></span>
              </label>;
            })}</div>}
          </section>;
        })}
      </div>}
      {!loading && sources.length === 0 && <p className="textbook-import-note">В проекте пока нет источников.</p>}
      {similarCount > 0 && <p className="textbook-import-warning" role="status">В выбранных источниках найдено {similarCount} похожих путей. Они будут импортированы отдельно — объедините их вручную после импорта.</p>}
    </Dialog>
  );
}

function CascadeCheckbox({ checked, disabled, onChange }: { checked: boolean; disabled: boolean; onChange: (checked: boolean) => void }) {
  return <input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />;
}

function similarPathCount(sources: ImportSource[], depth: number, selectedKeys: Set<string>): number {
  const seen = new Map<string, string>();
  let count = 0;
  for (const source of sources) {
    const path: string[] = [];
    for (const item of source.outline.items) {
      path.length = Math.max(0, item.level - 1);
      path.push(item.title.trim().toLocaleLowerCase("ru").replace(/[^\p{L}\p{N}]+/gu, " "));
      if (item.level > depth || !selectedKeys.has(item.outline_item_key)) continue;
      const key = path.join(" / ");
      const owner = seen.get(key);
      if (owner && owner !== source.material.id) count += 1;
      else seen.set(key, source.material.id);
    }
  }
  return count;
}

/** Действия общей шапки, привязанные к внутренним диалогам редактора. */
export interface TextbookProgramEditorActions {
  openImport: () => void;
  openRemoveAll: () => void;
  undo: () => Promise<void>;
  busy: boolean;
  canUndo: boolean;
  hasNodes: boolean;
}
