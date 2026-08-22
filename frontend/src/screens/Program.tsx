import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { DragEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import {
  ArrowLeft,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  Copy,
  Files,
  GripVertical,
  LibraryBig,
  Pencil,
  Plus,
  RotateCcw,
  Search,
  Sparkles,
  Target,
  Trash2,
  Undo2,
  WandSparkles,
  Upload,
} from "lucide-react";
import {
  importExamProgramFromMaterial,
  previewExamProgram,
  type ExamProgramPreview,
  type LibraryMaterialRead,
} from "../api/materials";
import {
  createProgramNode,
  getProject,
  moveProgramNode,
  removeProgramNode,
  restoreProgramNode,
  setProgramTargetLevel,
  swapProgramNodes,
  undoProjectAction,
  updateProgramNode,
  ProjectApiError,
  type ExamKind,
  type ProgramChangeResult,
  type ProgramNodeRead,
  type ProjectDetail,
  type TargetOutcome,
} from "../api/projects";
import { GOAL_LEVELS, GoalLevelPicker, LibraryMaterialPickerDialog, ProjectNav } from "../components/domain";
import type { GoalLevelValue } from "../components/domain";
import {
  Button,
  ContextMenu,
  Dialog,
  Disclosure,
  EmptyState,
  ErrorState,
  Field,
  IconButton,
  Kbd,
  LoadingState,
  PageHead,
  SegmentedTabs,
  Tooltip,
} from "../components/ui";
import type { ContextMenuItem } from "../components/ui";
import {
  buildProgramTree,
  filterProgramTree,
  flattenProgramTree,
  visibleHiddenRoots,
  type ProgramTreeNode,
} from "./programTree";
import { useBindings } from "../hooks/useBindings";
import { useProjectMaterials } from "../hooks/useProjectMaterials";
import { AiGroupingDialog } from "./AiGroupingDialog";
import { AiImportRepairDialog } from "./AiImportRepairDialog";

type AddKind = "section" | "ticket" | "question" | "task" | "topic" | "subpoint";
type OutlineFilter = "all" | "sections" | "ungrouped";

function apiKind(kind: AddKind): { node_type: ProgramNodeRead["node_type"]; exam_kind: ExamKind | null } {
  switch (kind) {
    case "ticket": return { node_type: "section", exam_kind: "ticket" };
    case "question": return { node_type: "topic", exam_kind: "question" };
    case "task": return { node_type: "topic", exam_kind: "task" };
    case "subpoint": return { node_type: "subpoint", exam_kind: null };
    case "topic": return { node_type: "topic", exam_kind: null };
    default: return { node_type: "section", exam_kind: null };
  }
}

function nodeKind(node: ProgramNodeRead, textbook: boolean): AddKind {
  if (textbook) return node.node_type;
  if (node.exam_kind === "ticket") return "ticket";
  if (node.exam_kind === "task") return "task";
  if (node.exam_kind === "question") return "question";
  return "section";
}

function kindLabel(kind: AddKind) {
  switch (kind) {
    case "ticket": return "билет";
    case "question": return "вопрос";
    case "task": return "задача";
    case "topic": return "тема";
    case "subpoint": return "подпункт";
    default: return "раздел";
  }
}

export function Program() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const preferredTopic = searchParams.get("topic");
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [commandError, setCommandError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<OutlineFilter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [addOpen, setAddOpen] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newKind, setNewKind] = useState<AddKind>("question");
  const [newParentId, setNewParentId] = useState<string | null>(null);
  const [newPosition, setNewPosition] = useState<number | null>(null);
  const [addPlacementLabel, setAddPlacementLabel] = useState("");
  const [duplicateWarning, setDuplicateWarning] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [dropTargetId, setDropTargetId] = useState<string | null>(null);
  const materials = useProjectMaterials(projectId);
  const bindings = useBindings(detail?.project.workspace_variant === "exam" ? projectId : undefined);
  const bindingsSummaryByNode = useMemo(
    () => new Map(bindings.summary.map((item) => [item.program_node_id, item])),
    [bindings.summary],
  );
  const importInput = useRef<HTMLInputElement>(null);
  const titleInput = useRef<HTMLInputElement>(null);
  const focusTitleAfterMenu = useRef(false);
  const [importOpen, setImportOpen] = useState(false);
  const [libraryPickerOpen, setLibraryPickerOpen] = useState(false);
  const [importMaterialId, setImportMaterialId] = useState("");
  const [importPreview, setImportPreview] = useState<ExamProgramPreview | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState("");
  const [groupingOpen, setGroupingOpen] = useState(false);
  const [groupingNotice, setGroupingNotice] = useState(false);
  const [importRepairOpen, setImportRepairOpen] = useState(false);
  const [importRepairNotice, setImportRepairNotice] = useState(false);

  async function load(signal?: AbortSignal) {
    setLoading(true);
    setLoadError(null);
    setConflict(false);
    try {
      const next = await getProject(projectId, signal);
      setDetail(next);
      const first = next.program.nodes.find((node) => node.is_in_current_program && !node.is_archived);
      const preferred = preferredTopic && next.program.nodes.some((node) =>
        node.id === preferredTopic && node.is_in_current_program && !node.is_archived) ? preferredTopic : null;
      setSelectedId((current) => preferred ?? (current && next.program.nodes.some((node) => node.id === current) ? current : first?.id ?? null));
      setExpanded(new Set(next.program.nodes.filter((node) => node.node_type === "section").map((node) => node.id)));
    } catch (error) {
      if (!signal?.aborted) setLoadError(error);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [projectId, preferredTopic]);

  const treeResult = useMemo(() => {
    try {
      return { tree: buildProgramTree(detail?.program.nodes ?? []), error: "" };
    } catch (error) {
      return { tree: [], error: error instanceof Error ? error.message : "Некорректное дерево программы" };
    }
  }, [detail?.program.nodes]);
  const flat = useMemo(() => flattenProgramTree(treeResult.tree), [treeResult.tree]);
  const selected = detail?.program.nodes.find((node) => node.id === selectedId) ?? null;
  const textbook = detail?.project.workspace_variant === "textbook";
  const kindOptions: Array<[AddKind, string]> = textbook
    ? [["section", "Раздел"], ["topic", "Тема"], ["subpoint", "Подпункт"]]
    : [["section", "Раздел"], ["ticket", "Билет"], ["question", "Вопрос"], ["task", "Задача"]];
  const addParentOptions = flat.filter((node) => node.is_in_current_program && !node.is_archived && node.depth < 4);

  useEffect(() => setTitleDraft(selected?.title ?? ""), [selected?.id, selected?.title]);

  function acceptResult(result: ProgramChangeResult) {
    setDetail((current) => current ? {
      ...current,
      program: result.program,
      latest_undoable_action: result.latest_undoable_action,
    } : current);
    const visibleIds = new Set(result.program.nodes
      .filter((node) => node.is_in_current_program && !node.is_archived)
      .map((node) => node.id));
    setSelectedId((current) => {
      if (result.changed_node && visibleIds.has(result.changed_node.id)) return result.changed_node.id;
      if (current && visibleIds.has(current)) return current;
      return result.program.nodes.find((node) => visibleIds.has(node.id))?.id ?? null;
    });
  }

  const examMaterials = materials.materials.filter((material) =>
    material.purposes.includes("exam_structure"));
  const importMaterial = examMaterials.find((material) => material.id === importMaterialId) ?? null;

  async function loadImportPreview(materialId: string) {
    setImportBusy(true);
    setImportError("");
    try {
      setImportPreview(await previewExamProgram(projectId, materialId));
    } catch (error) {
      setImportPreview(null);
      setImportError(error instanceof Error ? error.message : "Не удалось подготовить список");
    } finally {
      setImportBusy(false);
    }
  }

  function openImport() {
    const only = examMaterials.length === 1 ? examMaterials[0] : null;
    setImportMaterialId(only?.id ?? "");
    setImportPreview(null);
    setImportError("");
    setImportOpen(true);
    if (only?.status === "ready") void loadImportPreview(only.id);
  }

  useEffect(() => {
    if (!importOpen || !importMaterial || importMaterial.status !== "ready") return;
    if (importPreview?.material_id === importMaterial.id || importBusy) return;
    void loadImportPreview(importMaterial.id);
  }, [importMaterial?.id, importMaterial?.status, importOpen]);

  async function uploadExamMaterial(file: File) {
    const created = await materials.upload(file, "reference", ["exam_structure"]);
    if (!created) return;
    setImportMaterialId(created.id);
    setImportPreview(null);
  }

  async function attachExamMaterial(selected: LibraryMaterialRead[]) {
    const material = selected[0];
    if (!material) return;
    setImportMaterialId(material.id);
    setImportPreview(null);
    await materials.refresh();
  }

  async function confirmImport() {
    if (!detail || !importPreview) return;
    setImportBusy(true);
    setImportError("");
    try {
      const result = await importExamProgramFromMaterial(
        projectId,
        importPreview.material_id,
        detail.program.revision,
      );
      acceptResult(result);
      setGroupingNotice(false);
      setImportRepairNotice(false);
      setImportOpen(false);
    } catch (error) {
      setImportError(error instanceof Error ? error.message : "Импорт не выполнен");
    } finally {
      setImportBusy(false);
    }
  }

  async function runCommand(command: Promise<ProgramChangeResult>) {
    setBusy(true);
    setCommandError("");
    try {
      acceptResult(await command);
      setGroupingNotice(false);
      setImportRepairNotice(false);
    } catch (error) {
      if (error instanceof ProjectApiError && ["stale_program_revision", "stale_action_sequence"].includes(error.code ?? "")) {
        setConflict(true);
      } else {
        setCommandError(error instanceof Error ? error.message : "Не удалось изменить программу");
      }
    } finally {
      setBusy(false);
    }
  }

  function toggle(nodeId: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(nodeId)) next.delete(nodeId); else next.add(nodeId);
      return next;
    });
  }

  function siblingInfo(node: ProgramNodeRead) {
    const siblings = detail ? [...detail.program.nodes]
      .filter((item) => item.parent_id === node.parent_id && item.is_in_current_program && !item.is_archived)
      .sort((left, right) => left.sort_order - right.sort_order) : [];
    return { siblings, index: siblings.findIndex((item) => item.id === node.id) };
  }

  function move(node: ProgramNodeRead, offset: number) {
    if (!detail) return;
    const { index } = siblingInfo(node);
    void runCommand(moveProgramNode(projectId, node.id, {
      expected_program_revision: detail.program.revision,
      parent_id: node.parent_id,
      position: index + offset,
    }));
  }

  function indent(node: ProgramNodeRead) {
    if (!detail) return;
    const { siblings, index } = siblingInfo(node);
    const previous = siblings[index - 1];
    if (!previous) return;
    void runCommand(moveProgramNode(projectId, node.id, {
      expected_program_revision: detail.program.revision,
      parent_id: previous.id,
      position: null,
    }));
  }

  function outdent(node: ProgramNodeRead) {
    if (!detail || !node.parent_id) return;
    const parent = detail.program.nodes.find((item) => item.id === node.parent_id);
    if (!parent) return;
    const parentSiblings = [...detail.program.nodes]
      .filter((item) => item.parent_id === parent.parent_id && item.is_in_current_program && !item.is_archived)
      .sort((left, right) => left.sort_order - right.sort_order);
    const parentIndex = parentSiblings.findIndex((item) => item.id === parent.id);
    void runCommand(moveProgramNode(projectId, node.id, {
      expected_program_revision: detail.program.revision,
      parent_id: parent.parent_id,
      position: parentIndex + 1,
    }));
  }

  function addNode(force = false) {
    if (!detail || !newTitle.trim()) return;
    const duplicate = detail.program.nodes.some((node) =>
      node.title.trim().toLocaleLowerCase("ru") === newTitle.trim().toLocaleLowerCase("ru"));
    if (duplicate && !force) {
      setDuplicateWarning(true);
      return;
    }
    const kind = apiKind(newKind);
    setDuplicateWarning(false);
    setAddOpen(false);
    void runCommand(createProgramNode(projectId, {
      expected_program_revision: detail.program.revision,
      parent_id: newParentId,
      position: newPosition,
      ...kind,
      title: newTitle.trim(),
      goal_role: "target",
    }));
    setNewTitle("");
  }

  function openAddDialog(options?: { kind?: AddKind; parentId?: string | null; position?: number | null; placementLabel?: string }) {
    const kind = options?.kind ?? (textbook ? "topic" : "question");
    setNewTitle("");
    setNewKind(kind);
    setNewParentId(options?.parentId ?? null);
    setNewPosition(options?.position ?? null);
    setAddPlacementLabel(options?.placementLabel ?? "");
    setDuplicateWarning(false);
    setAddOpen(true);
  }

  function openAddDialogFromMenu(options: { kind: AddKind; parentId: string | null; position: number | null; placementLabel: string }) {
    window.setTimeout(() => openAddDialog(options), 0);
  }

  function changeNewKind(kind: AddKind) {
    setNewKind(kind);
  }

  function startRename(node: ProgramNodeRead) {
    setSelectedId(node.id);
    setTitleDraft(node.title);
    focusTitleAfterMenu.current = true;
  }

  function handleContextMenuCloseAutoFocus(event: Event) {
    if (!focusTitleAfterMenu.current) return;
    event.preventDefault();
    focusTitleAfterMenu.current = false;
    window.requestAnimationFrame(() => {
      titleInput.current?.focus();
      titleInput.current?.select();
    });
  }

  function subtreeHeight(nodeId: string): number {
    const children = flat.filter((node) => node.parent_id === nodeId);
    return children.length ? 1 + Math.max(...children.map((child) => subtreeHeight(child.id))) : 1;
  }

  function duplicate(node: ProgramNodeRead) {
    if (!detail) return;
    const { index } = siblingInfo(node);
    void runCommand(createProgramNode(projectId, {
      expected_program_revision: detail.program.revision,
      parent_id: node.parent_id,
      position: index + 1,
      node_type: node.node_type,
      exam_kind: node.exam_kind,
      title: `${node.title} — копия`,
      section_purpose: node.section_purpose,
      goal_role: node.goal_role,
      target_level: node.target_level,
      needs_material: node.needs_material,
    }));
  }

  function changeKind(node: ProgramNodeRead, kind: AddKind) {
    if (!detail) return;
    const mapped = apiKind(kind);
    void runCommand(updateProgramNode(projectId, node.id, {
      expected_program_revision: detail.program.revision,
      ...mapped,
    }));
  }

  async function undo() {
    if (!detail?.latest_undoable_action) return;
    setBusy(true);
    setCommandError("");
    try {
      const result = await undoProjectAction(projectId, detail.latest_undoable_action.sequence);
      if (result.program) {
        setDetail({ ...detail, program: result.program, latest_undoable_action: result.latest_undoable_action });
        const visible = result.program.nodes.filter((node) => node.is_in_current_program && !node.is_archived);
        setSelectedId((current) => current && visible.some((node) => node.id === current) ? current : visible[0]?.id ?? null);
        setGroupingNotice(false);
        setImportRepairNotice(false);
      }
    } catch (error) {
      if (error instanceof ProjectApiError && error.code === "stale_action_sequence") setConflict(true);
      else setCommandError(error instanceof Error ? error.message : "Не удалось отменить действие");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <div className="screen"><LoadingState label="Загружаем программу" placement="page" /></div>;
  if (loadError) {
    const notFound = loadError instanceof ProjectApiError && loadError.status === 404;
    return <div className="screen"><ErrorState title={notFound ? "Проект не найден" : undefined} message={notFound ? "Проверьте адрес или вернитесь к списку проектов." : loadError instanceof Error ? loadError.message : "Не удалось загрузить программу"} /><Button onClick={() => void load()}>Повторить загрузку</Button><Link className="secondary-button" to="/projects">К проектам</Link></div>;
  }
  if (!detail) return null;
  if (treeResult.error) return <div className="screen"><ErrorState title="Программа повреждена" message={treeResult.error} /></div>;

  const currentFlat = flat.filter((node) => node.is_in_current_program && !node.is_archived);
  const filteredTree = filterProgramTree(treeResult.tree, query);
  const shown = flattenProgramTree(filteredTree)
    .filter((node) => node.is_in_current_program && !node.is_archived);
  const hiddenRoots = visibleHiddenRoots(detail.program.nodes);
  const sectionCount = currentFlat.filter((node) => node.node_type === "section").length;
  const ungroupedCount = currentFlat.filter((node) => node.parent_id === null && node.node_type !== "section").length;
  const groupingNodes = currentFlat.filter((node) => node.exam_kind === "question" || node.exam_kind === "task");
  const groupingProblem = detail.project.status !== "active"
    ? "Разложить вопросы можно только в активном проекте"
    : currentFlat.some((node) => node.exam_kind === "ticket")
      ? "Билеты раскладываются вручную"
      : currentFlat.some((node) => node.node_type === "section" || node.parent_id !== null)
        ? "Сначала уберите существующие разделы"
        : groupingNodes.length < 6
          ? "Нужно не меньше 6 вопросов"
          : groupingNodes.length !== currentFlat.length
            ? "В плоском списке должны остаться только вопросы и задачи"
            : null;
  const hasTicketNodes = currentFlat.some((node) => node.exam_kind === "ticket");
  const repairNodes = currentFlat.filter((node) => node.node_type !== "subpoint"
    && (node.node_type !== "section" || (hasTicketNodes && node.exam_kind === "ticket")));
  const repairProblem = detail.project.status !== "active"
    ? "Исправить формулировки можно только в активном проекте"
    : repairNodes.length === 0
      ? "В программе нет вопросов, задач или тем"
      : null;
  const filteredNodes = shown.filter((node) => {
    if (filter === "sections") return node.node_type === "section";
    if (filter === "ungrouped") return node.parent_id === null && node.node_type !== "section";
    return true;
  });
  const usesTreeRenderer = filter === "all" || Boolean(query.trim());
  const visibleNodes = usesTreeRenderer ? shown : filteredNodes;

  function nodeActions(node: ProgramNodeRead) {
    const info = siblingInfo(node);
    const previous = info.index > 0 ? flat.find((item) => item.id === info.siblings[info.index - 1]?.id) ?? null : null;
    const canNest = Boolean(previous && previous.depth + subtreeHeight(node.id) <= 4);
    return (
      <div className="program-row-actions">
        <Button variant="ghost" aria-label="Вверх" disabled={busy || info.index <= 0} onClick={() => move(node, -1)}><ArrowUp size={14} /></Button>
        <Button variant="ghost" aria-label="Вниз" disabled={busy || info.index >= info.siblings.length - 1} onClick={() => move(node, 1)}><ArrowDown size={14} /></Button>
        <Button variant="ghost" aria-label="Сделать дочерним" disabled={busy || !canNest} onClick={() => indent(node)}><ArrowRight size={14} /></Button>
        <Button variant="ghost" aria-label="Поднять на уровень" disabled={busy || !node.parent_id} onClick={() => outdent(node)}><ArrowLeft size={14} /></Button>
      </div>
    );
  }

  function nodeMenuItems(node: ProgramTreeNode): ContextMenuItem[] {
    if (!detail) return [];
    const revision = detail.program.revision;
    const info = siblingInfo(node);
    const previous = info.index > 0 ? flat.find((item) => item.id === info.siblings[info.index - 1]?.id) ?? null : null;
    const canNest = Boolean(previous && previous.depth + subtreeHeight(node.id) <= 4);
    return [
      {
        label: "Добавить внутрь",
        icon: <Plus size={14} />,
        items: kindOptions.map(([kind, label]) => ({
          label,
          disabled: busy || node.depth >= 4,
          onSelect: () => openAddDialogFromMenu({ kind, parentId: node.id, position: null, placementLabel: `Внутрь «${node.title}»` }),
        })),
      },
      { label: "Добавить перед", icon: <ArrowUp size={14} />, disabled: busy, onSelect: () => openAddDialogFromMenu({ kind: nodeKind(node, textbook), parentId: node.parent_id, position: info.index, placementLabel: `Перед «${node.title}»` }) },
      { label: "Добавить после", icon: <ArrowDown size={14} />, disabled: busy, onSelect: () => openAddDialogFromMenu({ kind: nodeKind(node, textbook), parentId: node.parent_id, position: info.index + 1, placementLabel: `После «${node.title}»` }) },
      { label: "Переименовать", icon: <Pencil size={14} />, disabled: busy, onSelect: () => startRename(node) },
      { label: "Продублировать", icon: <Copy size={14} />, disabled: busy, onSelect: () => duplicate(node) },
      {
        label: "Тип узла",
        items: kindOptions.map(([kind, label]) => ({
          label,
          disabled: busy || nodeKind(node, textbook) === kind,
          onSelect: () => changeKind(node, kind),
        })),
      },
      { label: "Поднять", icon: <ArrowUp size={14} />, disabled: busy || info.index <= 0, onSelect: () => move(node, -1) },
      { label: "Опустить", icon: <ArrowDown size={14} />, disabled: busy || info.index >= info.siblings.length - 1, onSelect: () => move(node, 1) },
      { label: "Увеличить вложенность", icon: <ArrowRight size={14} />, disabled: busy || !canNest, onSelect: () => indent(node) },
      { label: "Уменьшить вложенность", icon: <ArrowLeft size={14} />, disabled: busy || !node.parent_id, onSelect: () => outdent(node) },
      { label: "Открыть в рабочей области", icon: <Target size={14} />, disabled: node.node_type === "section", onSelect: () => navigate(`/projects/${projectId}?topic=${node.id}`) },
      { label: "Убрать из программы", icon: <Trash2 size={14} />, destructive: true, disabled: busy, onSelect: () => void runCommand(removeProgramNode(projectId, node.id, revision)) },
    ];
  }

  function startDrag(event: DragEvent<HTMLElement>, node: ProgramNodeRead) {
    if (busy || node.node_type === "section") return;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", node.id);
    setDraggedId(node.id);
  }

  function endDrag() {
    setDraggedId(null);
    setDropTargetId(null);
  }

  function allowDrop(event: DragEvent<HTMLElement>, target: ProgramNodeRead) {
    if (!draggedId || draggedId === target.id) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setDropTargetId(target.id);
  }

  function dropNode(event: DragEvent<HTMLElement>, target: ProgramNodeRead) {
    event.preventDefault();
    const source = detail?.program.nodes.find((node) => node.id === draggedId);
    endDrag();
    if (!detail || !source || source.id === target.id || source.node_type === "section") return;
    if (target.node_type === "section") {
      void runCommand(moveProgramNode(projectId, source.id, {
        expected_program_revision: detail.program.revision,
        parent_id: target.id,
        position: null,
      }));
      return;
    }
    void runCommand(swapProgramNodes(projectId, source.id, {
      expected_program_revision: detail.program.revision,
      target_node_id: target.id,
    }));
  }

  function questionRow(node: ProgramTreeNode, includeChildren = true) {
    const children = node.children.filter((child) => child.is_in_current_program && !child.is_archived);
    const row = (
      <div
        className={`program-question-row ${selectedId === node.id ? "is-selected" : ""} ${draggedId === node.id ? "is-dragging" : ""} ${dropTargetId === node.id ? "is-drop-target" : ""}`.trim()}
        style={{ paddingInlineStart: `calc(${node.depth} * var(--space-5))` }}
        onContextMenu={() => setSelectedId(node.id)}
        onDragOver={(event) => allowDrop(event, node)}
        onDrop={(event) => dropNode(event, node)}
      >
        <span className="program-drag-handle" draggable={!busy} title="Перетащить вопрос" aria-hidden="true" onDragStart={(event) => startDrag(event, node)} onDragEnd={endDrag}><GripVertical size={15} /></span>
        <button type="button" className="program-question-main" onClick={() => setSelectedId(node.id)}>
          <span className="program-question-number">{node.number}</span>
          <span className="program-question-copy"><strong>{node.title}</strong><small>{kindLabel(nodeKind(node, textbook))}</small></span>
        </button>
        <span className="program-goal-label"><Target size={14} />{GOAL_LEVELS.find((level) => level.value === node.target_level)?.label ?? "уровень не задан"}</span>
        {nodeActions(node)}
      </div>
    );
    return (
      <Fragment key={node.id}>
        <ContextMenu label={`Действия с «${node.title}»`} trigger={row} items={nodeMenuItems(node)} onCloseAutoFocus={handleContextMenuCloseAutoFocus} />
        {includeChildren && children.map(renderNode)}
      </Fragment>
    );
  }

  function sectionCard(node: ProgramTreeNode) {
    const children = node.children.filter((child) => child.is_in_current_program && !child.is_archived);
    const open = expanded.has(node.id) || Boolean(query.trim());
    const row = (
      <div className={`program-section-row ${selectedId === node.id ? "is-selected" : ""} ${dropTargetId === node.id ? "is-drop-target" : ""}`.trim()} onContextMenu={() => setSelectedId(node.id)} onDragOver={(event) => allowDrop(event, node)} onDrop={(event) => dropNode(event, node)}>
        <IconButton label={open ? "Свернуть раздел" : "Раскрыть раздел"} onClick={() => toggle(node.id)}>
          {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </IconButton>
        <button type="button" className="program-section-main" onClick={() => setSelectedId(node.id)}>
          <span className="program-section-index">{node.number}</span>
          <span><strong>{node.title}</strong><small>{children.length} элементов</small></span>
        </button>
        <span className="program-goal-label"><Target size={14} />{GOAL_LEVELS.find((level) => level.value === node.target_level)?.label ?? "уровень не задан"}</span>
        {nodeActions(node)}
      </div>
    );
    return (
      <article className="program-section-card" key={node.id}>
        <ContextMenu label={`Действия с «${node.title}»`} trigger={row} items={nodeMenuItems(node)} onCloseAutoFocus={handleContextMenuCloseAutoFocus} />
        {open && children.length > 0 && <div className="program-section-children">{children.map(renderNode)}</div>}
      </article>
    );
  }

  function renderNode(node: ProgramTreeNode) {
    return node.node_type === "section" ? sectionCard(node) : questionRow(node);
  }

  function renderFlatNode(node: ProgramTreeNode) {
    return questionRow(node, false);
  }

  function hiddenRootsDisclosure() {
    if (!detail || hiddenRoots.length === 0) return null;
    return (
      <Disclosure summary={`Убрано из списка (${hiddenRoots.length})`}>
        {hiddenRoots.map((node) => (
          <div className="dash-archive-row" key={node.id}>
            <span>{node.title}</span>
            <Button variant="ghost" disabled={busy} onClick={() => void runCommand(restoreProgramNode(projectId, node.id, detail.program.revision))}><RotateCcw size={14} />Вернуть</Button>
          </div>
        ))}
      </Disclosure>
    );
  }

  return (
    <div className="program-screen">
      <aside className="program-project-panel">
        <header className="program-project-title">
          <Tooltip label="Вернуться в рабочую область">
            <Link className="workspace-back-button" to={`/projects/${projectId}`} aria-label="Вернуться в рабочую область"><ArrowLeft size={15} /></Link>
          </Tooltip>
          <strong>{detail.project.name}</strong>
        </header>
        <nav className="program-quick-filters" aria-label="Быстрые выборки программы">
          {[
            ["all", textbook ? "Все узлы" : "Все вопросы", currentFlat.length],
            ["sections", "Разделы", sectionCount],
            ["ungrouped", "Без раздела", ungroupedCount],
          ].map(([value, label, amount]) => (
            <button type="button" className={filter === value ? "is-active" : ""} key={value} onClick={() => setFilter(value as OutlineFilter)}>
              <span>{label}</span><small>{amount}</small>
            </button>
          ))}
        </nav>
        <ProjectNav
          projectId={projectId}
          active="program"
          textbook={textbook}
          modules={detail.project.enabled_modules}
          counts={{
            program: currentFlat.filter((node) => node.node_type !== "section").length,
            materials: materials.materials.length,
          }}
          className="program-project-nav"
        />
      </aside>

      <main className="program-main">
        <PageHead
          eyebrow={textbook ? "Ручная структура" : "Структура экзамена"}
          title={textbook ? "Программа" : "Вопросы экзамена"}
          actions={<>
            {!textbook && <Button variant="secondary" disabled={busy} onClick={openImport}><Files size={15} />Импорт</Button>}
            {!textbook && <Tooltip label={groupingProblem ?? "Предложить смысловые разделы без изменения формулировок"}><Button variant="secondary" disabled={busy || Boolean(groupingProblem)} onClick={() => setGroupingOpen(true)}><WandSparkles size={15} />Разложить по разделам</Button></Tooltip>}
            <Tooltip label={repairProblem ?? "Переписать формулировки, если разбор файла что-то склеил или порвал"}><Button variant="secondary" disabled={busy || Boolean(repairProblem)} onClick={() => setImportRepairOpen(true)}><Sparkles size={15} />Исправить список</Button></Tooltip>
            <Button variant="secondary" disabled={busy || !detail.latest_undoable_action} onClick={() => void undo()}><Undo2 size={15} />Отменить</Button>
            <Button disabled={busy} onClick={() => openAddDialog()}><Plus size={15} />Добавить</Button>
          </>}
        />
        {groupingNotice && detail.latest_undoable_action?.action_type === "ai_program_grouping" && (
          <section className="program-plan-notice" role="status">
            <span>Вопросы разложены по разделам. Стабильные id и связанные данные сохранены.</span>
            <Button variant="secondary" disabled={busy} onClick={() => void undo()}><Undo2 size={14} />Отменить раскладку</Button>
          </section>
        )}
        {importRepairNotice && detail.latest_undoable_action?.action_type === "ai_import_repair" && (
          <section className="program-plan-notice" role="status">
            <span>Формулировки исправлены. Число и порядок пунктов не изменились.</span>
            <Button variant="secondary" disabled={busy} onClick={() => void undo()}><Undo2 size={14} />Отменить исправление</Button>
          </section>
        )}
        {conflict && <section className="program-plan-notice" role="alert"><span>Программа изменилась в другой вкладке.</span><Button onClick={() => void load()}>Загрузить серверную версию</Button></section>}
        {commandError && <p className="inline-error" role="alert">{commandError}</p>}
          {textbook && <section className="program-metrics is-three-columns" aria-label="Состояние программы">
            <button type="button" onClick={() => setFilter("all")}><strong>{currentFlat.length}</strong><span>узлов программы</span></button>
            <button type="button" onClick={() => setFilter("sections")}><strong>{sectionCount}</strong><span>разделов</span></button>
            <button type="button" onClick={() => setFilter("ungrouped")}><strong>{ungroupedCount}</strong><span>без раздела</span></button>
          </section>}
        <div className="program-toolbar"><label className="program-search"><Search size={16} /><span className="sr-only">Найти в программе</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={textbook ? "Найти тему" : "Найти вопрос"} /></label></div>

        {currentFlat.length === 0 ? (
          <>
            <EmptyState title="Программа пока пуста">
              <p>{textbook ? "Добавьте первую тему вручную." : "Импортируйте список из материала или добавьте вопрос вручную."}</p>
              {!textbook && <Button onClick={openImport}>Импортировать вопросы</Button>}
              <Button variant={textbook ? undefined : "secondary"} onClick={() => openAddDialog({ kind: textbook ? "section" : "question" })}>Добавить первый узел</Button>
            </EmptyState>
            {hiddenRootsDisclosure()}
          </>
        ) : (
          <div className="program-editor-grid">
            <section className="program-outline" aria-label={textbook ? "Структура программы" : "Структура вопросов экзамена"}>
              <p className="program-context-hint">Правой кнопкой по узлу — добавить внутрь или рядом, переименовать и переместить. С клавиатуры: <Kbd>Shift+F10</Kbd>.</p>
              {usesTreeRenderer
                ? filteredTree.filter((node) => node.is_in_current_program && !node.is_archived).map(renderNode)
                : filteredNodes.map(renderFlatNode)}
              {visibleNodes.length === 0 && <EmptyState title={query ? `Нет результатов для «${query}»` : "В этой выборке пока нет узлов"}><Button variant="secondary" onClick={() => { setQuery(""); setFilter("all"); }}>Очистить фильтр</Button></EmptyState>}
              {hiddenRootsDisclosure()}
            </section>

            <aside className="program-inspector" aria-label="Свойства выбранного узла">
              {selected ? <>
                <p className="eyebrow">Свойства</p>
                <h2>{selected.title}</h2>
                <Field label="Формулировка"><input ref={titleInput} value={titleDraft} onChange={(event) => setTitleDraft(event.target.value)} onBlur={() => { const title = titleDraft.trim(); if (title && title !== selected.title) void runCommand(updateProgramNode(projectId, selected.id, { expected_program_revision: detail.program.revision, title })); }} /></Field>
                <SegmentedTabs label="Тип узла" value={nodeKind(selected, textbook)} onChange={(value) => changeKind(selected, value as AddKind)} tabs={(textbook ? [["section", "Раздел"], ["topic", "Тема"], ["subpoint", "Подпункт"]] : [["section", "Раздел"], ["ticket", "Билет"], ["question", "Вопрос"], ["task", "Задача"]]).map(([value, label]) => ({ value, label }))} />
                <GoalLevelPicker label="узла" value={(selected.target_level ?? "understanding") as GoalLevelValue} onChange={(target) => void runCommand(setProgramTargetLevel(projectId, selected.id, { expected_program_revision: detail.program.revision, target_level: target as TargetOutcome, include_descendants: true }))} />
                <section className="program-impact"><h3>Что связано</h3><dl><div><dt>Эталон</dt><dd>Статус доступен на Карте эталонов</dd></div><div><dt>Источник списка</dt><dd>{selected.origin_material_id ? materials.materials.find((item) => item.id === selected.origin_material_id)?.display_name ?? "Материал удалён" : "Добавлено вручную"}</dd></div><div><dt>Привязки</dt><dd>{(() => {
                  const summary = bindingsSummaryByNode.get(selected.id);
                  if (!summary) return "Материал не привязан";
                  return `${summary.fragment_count} фрагм. из ${summary.material_count} ${summary.material_count === 1 ? "файла" : "файлов"}`;
                })()}</dd></div><div><dt>План</dt><dd>Появится на этапе 9</dd></div></dl></section>
                <div className="program-inspector-links"><Link to={`/projects/${projectId}?topic=${selected.id}`}>Открыть в рабочей области</Link>{selected.origin_material_id && <Link to={`/projects/${projectId}/materials/${selected.origin_material_id}`}>Открыть материал списка</Link>}<Link to={`/projects/${projectId}/materials`}>Привязки в материалах</Link></div>
                <div className="program-row-actions"><Button variant="secondary" disabled={busy} onClick={() => duplicate(selected)}><Copy size={15} />Продублировать</Button><Button variant="ghost" disabled={busy} onClick={() => void runCommand(removeProgramNode(projectId, selected.id, detail.program.revision))}><Trash2 size={15} />Убрать из списка</Button></div>
              </> : <p>Выберите узел программы.</p>}
            </aside>
          </div>
        )}
      </main>

      {!textbook && (
        <Dialog
          open={importOpen}
          onOpenChange={setImportOpen}
          title="Импортировать вопросы"
          description={currentFlat.length
            ? "Проверьте новый список. После подтверждения он заменит текущий состав экзамена; совпавшие вопросы сохранят свои данные."
            : "Выберите или загрузите материал со списком вопросов, затем проверьте распознанный состав."}
          footer={<>
            <Button variant="ghost" onClick={() => setImportOpen(false)}>Закрыть</Button>
            {importMaterial?.status === "ready_to_process" && (
              <Button disabled={materials.busy} onClick={() => void materials.start(importMaterial.id)}>
                Начать быстрый разбор
              </Button>
            )}
            {importMaterial?.status === "failed" && (
              <Button disabled={materials.busy} onClick={() => void materials.control(importMaterial.id, "retry")}>
                Повторить разбор
              </Button>
            )}
            {importPreview && (
              <Button disabled={importBusy} onClick={() => void confirmImport()}>
                {currentFlat.length ? "Заменить список вопросов" : "Импортировать вопросы"}
              </Button>
            )}
          </>}
        >
          <input
            ref={importInput}
            className="materials-file-input"
            type="file"
            tabIndex={-1}
            aria-hidden="true"
            accept=".pdf,.docx,.txt,.md,.jpg,.jpeg,.png"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void uploadExamMaterial(file);
              event.target.value = "";
            }}
          />
          {examMaterials.length === 0 ? (
            <section className="program-import-empty">
              <Upload size={24} aria-hidden="true" />
              <h3>Список вопросов ещё не загружен</h3>
              <p>Подойдут PDF, DOCX, текстовый файл или фотография. Ограничение — 100 МБ и 500 страниц.</p>
              <div className="material-entry-actions">
                <Button variant="secondary" disabled={materials.busy} onClick={() => importInput.current?.click()}>
                  Загрузить список вопросов
                </Button>
                <Button variant="secondary" disabled={materials.busy} onClick={() => setLibraryPickerOpen(true)}>
                  <LibraryBig size={15} aria-hidden="true" />Из Библиотеки
                </Button>
              </div>
            </section>
          ) : (
            <div className="program-import-layout">
              {examMaterials.length > 1 && (
                <fieldset className="program-import-materials">
                  <legend>Материал со списком вопросов</legend>
                  {examMaterials.map((material) => (
                    <label key={material.id}>
                      <input
                        type="radio"
                        name="exam-material"
                        value={material.id}
                        checked={importMaterialId === material.id}
                        onChange={() => {
                          setImportMaterialId(material.id);
                          setImportPreview(null);
                          setImportError("");
                        }}
                      />
                      <span><strong>{material.display_name}</strong><small>{material.status === "ready" ? "Разобран" : material.status === "ready_to_process" ? "Ожидает запуска" : material.status === "failed" ? "Ошибка разбора" : "Обрабатывается"}</small></span>
                    </label>
                  ))}
                </fieldset>
              )}
              {examMaterials.length === 1 && <p className="program-import-source"><strong>Источник:</strong> {examMaterials[0].display_name}</p>}
              <div className="material-entry-actions is-start">
                <Button variant="ghost" disabled={materials.busy} onClick={() => importInput.current?.click()}><Upload size={14} />Загрузить другой материал</Button>
                <Button variant="ghost" disabled={materials.busy} onClick={() => setLibraryPickerOpen(true)}><LibraryBig size={14} />Выбрать из Библиотеки</Button>
              </div>
              {importMaterial?.status === "ready_to_process" && (
                <section className="program-import-estimate">
                  <h3>Перед разбором</h3>
                  <p>{importMaterial.page_count ?? 1} стр. · OCR потребуется для {importMaterial.scan_page_count} · примерно {importMaterial.estimated_seconds ?? 1} сек. · стоимость 0 ₽.</p>
                </section>
              )}
              {importMaterial && ["queued", "processing", "paused"].includes(importMaterial.status) && (
                <p className="program-import-progress" role="status">Материал обрабатывается: {importMaterial.task?.done ?? 0} из {importMaterial.task?.total ?? importMaterial.page_count ?? 1} страниц.</p>
              )}
              {importBusy && <LoadingState label="Готовим предпросмотр вопросов" />}
              {importError && <p className="inline-error" role="alert">{importError}</p>}
              {materials.error && <p className="inline-error" role="alert">{materials.error}</p>}
              {importPreview && (
                <section className="program-import-preview" aria-labelledby="program-import-preview-title">
                  <header>
                    <h3 id="program-import-preview-title">Будет импортировано</h3>
                    <p>{importPreview.counts.questions} вопросов · {importPreview.counts.tasks} задач · {importPreview.counts.tickets} билетов</p>
                  </header>
                  {importPreview.warnings.length > 0 && <ul>{importPreview.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
                  <ol>
                    {importPreview.nodes.map((node, index) => (
                      <li key={`${node.title}-${index}`} style={{ "--program-import-depth": node.depth } as React.CSSProperties}>
                        <span>{index + 1}</span><strong>{node.title}</strong><small>{node.exam_kind === "task" ? "Задача" : node.exam_kind === "ticket" ? "Билет" : "Вопрос"}</small>
                      </li>
                    ))}
                  </ol>
                </section>
              )}
            </div>
          )}
        </Dialog>
      )}

      {!textbook && (
        <LibraryMaterialPickerDialog
          open={libraryPickerOpen}
          projectId={projectId}
          title="Выбрать список вопросов из Библиотеки"
          purpose="exam_structure"
          onOpenChange={setLibraryPickerOpen}
          onAttached={attachExamMaterial}
          onCreateNew={() => {
            setLibraryPickerOpen(false);
            window.setTimeout(() => importInput.current?.click(), 0);
          }}
        />
      )}

      {!textbook && (
        <AiGroupingDialog
          open={groupingOpen}
          projectId={projectId}
          projectName={detail.project.name ?? "Экзамен"}
          nodes={groupingNodes}
          onOpenChange={setGroupingOpen}
          onApplied={(result) => {
            acceptResult(result);
            setExpanded(new Set(result.program.nodes
              .filter((node) => node.node_type === "section" && node.is_in_current_program && !node.is_archived)
              .map((node) => node.id)));
            setGroupingNotice(true);
          }}
        />
      )}

      <AiImportRepairDialog
        open={importRepairOpen}
        projectId={projectId}
        nodes={repairNodes}
        onOpenChange={setImportRepairOpen}
        onApplied={(result) => {
          acceptResult(result);
          setImportRepairNotice(true);
        }}
      />

      <Dialog open={addOpen} onOpenChange={setAddOpen} title="Добавить в программу" description="Укажите формулировку, тип и место в дереве. Вложенность можно изменить и после добавления." footer={<><Button variant="ghost" onClick={() => setAddOpen(false)}>Отменить</Button><Button disabled={!newTitle.trim()} onClick={() => addNode(false)}>Добавить узел</Button></>}>
        <Field label="Формулировка" required><input autoFocus value={newTitle} onChange={(event) => { setNewTitle(event.target.value); setDuplicateWarning(false); }} placeholder="Например, индексы и B-деревья" /></Field>
        <Field label="Тип"><select value={newKind} onChange={(event) => changeNewKind(event.target.value as AddKind)}>{kindOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
        {addPlacementLabel
          ? <Field label="Расположение"><div className="program-add-placement">{addPlacementLabel}</div></Field>
          : <Field label="Расположение" hint="Выберите корень или узел, внутрь которого нужно добавить новый пункт."><select value={newParentId ?? ""} onChange={(event) => { setNewParentId(event.target.value || null); setNewPosition(null); }}><option value="">В конце программы</option>{addParentOptions.map((node) => <option key={node.id} value={node.id}>{`${"— ".repeat(Math.max(0, node.depth - 1))}${node.number}. ${node.title}`}</option>)}</select></Field>}
        {duplicateWarning && <div className="inline-error" role="alert"><p>Узел с такой формулировкой уже есть.</p><Button variant="secondary" onClick={() => addNode(true)}>Всё равно добавить</Button></div>}
      </Dialog>
    </div>
  );
}
