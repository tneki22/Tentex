import {
  ArrowLeft,
  BookOpen,
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleDashed,
  FileText,
  Files,
  Filter,
  History,
  GraduationCap,
  Info,
  Layers,
  Link2Off,
  ListTree,
  MessageSquare,
  NotebookPen,
  PanelRightClose,
  PanelsTopLeft,
  Plus,
  RotateCcw,
  Search,
  Settings,
  StickyNote,
  X,
} from "lucide-react";
import type { CSSProperties } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router";
import { ContextMenu } from "radix-ui";
import {
  Button,
  Checkbox,
  Dialog,
  IconButton,
  Menu,
  PanelResizeHandle,
  Popover,
  StatusBadge,
  Tooltip,
} from "../components/ui";
import {
  MachineMark,
  OfflineNotice,
  QualityBadge,
  SourceChip,
  TaskRow,
  topicStatusLabel,
} from "../components/domain";
import { resolveWorkspaceProject } from "./workspaceDemo";
import { LessonDocument } from "./lessons/LessonDocument";
import { lessonsForTopic } from "./lessons/lessonsDemo";
import { StudioPanel } from "./StudioPanel";
import type {
  WorkspaceAttemptDemo,
  WorkspaceNode,
  WorkspaceProjectDemo,
  WorkspaceSourceRef,
  WorkspaceVariant,
} from "./workspaceDemo";

type WorkspaceTab = "answer" | "source" | "lesson" | "conspect" | "history" | "chat" | "summary";

interface EditorGroup {
  id: string;
  tabs: WorkspaceTab[];
  activeTab: WorkspaceTab | null;
}

interface StoredWorkspaceState {
  selectedNodeId: string;
  selectedSourceIds: Record<string, string>;
  selectedLessonIds: Record<string, string>;
  treeWidth: number;
  groupWeights: number[];
  groups: EditorGroup[];
  expandedNodeIds: string[];
  notes: Record<string, string>;
  noteRepeats: Record<string, boolean>;
  conspects: Record<string, string>;
  removedBindingIds: string[];
  studioExpanded: boolean;
}

interface LegacyWorkspaceState extends Partial<StoredWorkspaceState> {
  selectedQuestionId?: string;
  expandedSectionIds?: string[];
}

interface ProgramDialogState {
  questionId: string;
}

const TAB_KINDS: WorkspaceTab[] = ["answer", "source", "lesson", "conspect", "history", "chat", "summary"];
const EXAM_TABS: WorkspaceTab[] = ["answer", "source", "conspect", "chat", "summary"];
const TEXTBOOK_TABS: WorkspaceTab[] = ["source", "conspect", "history", "chat"];

const TAB_ICONS = {
  answer: BookOpen,
  source: FileText,
  lesson: GraduationCap,
  conspect: NotebookPen,
  history: History,
  chat: MessageSquare,
  summary: ListTree,
} satisfies Record<WorkspaceTab, typeof BookOpen>;

const DEFAULT_NOTES: Record<string, string> = {
  "data-models": "Не забыть привести пример сетевой модели.",
  normalization: "Повторить отличие третьей нормальной формы от НФБК.",
};

const SOURCE_ROLE_LABELS = {
  primary: "Основной",
  additional: "Дополнительный",
  reference: "Справочный",
} as const;

const BINDING_LABELS = {
  manual: "ручная",
  confirmed: "подтверждена",
  machine: "машинная",
  removed: "снята",
} as const;

const ATTEMPT_LABELS: Record<WorkspaceAttemptDemo["kind"], string> = {
  reading: "Чтение",
  card: "Карточки",
  "free-answer": "Свободный ответ",
  sql: "SQL",
};

function flattenNodes(nodes: WorkspaceNode[]): WorkspaceNode[] {
  return nodes.flatMap((node) => [node, ...flattenNodes(node.children ?? [])]);
}

function findNode(nodes: WorkspaceNode[], nodeId: string): WorkspaceNode | undefined {
  for (const node of nodes) {
    if (node.id === nodeId) return node;
    const child = findNode(node.children ?? [], nodeId);
    if (child) return child;
  }
  return undefined;
}

function allowedTabs(variant: WorkspaceVariant, lessonsEnabled: boolean): WorkspaceTab[] {
  const tabs = variant === "textbook" ? TEXTBOOK_TABS : EXAM_TABS;
  return lessonsEnabled ? [...tabs, "lesson"] : tabs;
}

function tabLabel(kind: WorkspaceTab, variant: WorkspaceVariant): string {
  if (kind === "source") return variant === "textbook" ? "Источник" : "Материал";
  return {
    answer: "Ответ",
    lesson: "Урок",
    conspect: "Мой конспект",
    history: "История",
    chat: "Чат",
    summary: "Сводный конспект",
  }[kind];
}

function createDefaultGroups(variant: WorkspaceVariant): EditorGroup[] {
  const initialTab: WorkspaceTab = variant === "textbook" ? "source" : "answer";
  return [
    { id: "primary", tabs: [initialTab], activeTab: initialTab },
    { id: "secondary", tabs: [], activeTab: null },
  ];
}

function isTabKind(value: unknown): value is WorkspaceTab {
  return typeof value === "string" && TAB_KINDS.includes(value as WorkspaceTab);
}

function parseGroups(value: unknown, variant: WorkspaceVariant, lessonsEnabled: boolean): EditorGroup[] {
  const permitted = allowedTabs(variant, lessonsEnabled);
  if (!Array.isArray(value)) return createDefaultGroups(variant);

  const groups = value.slice(0, 3).flatMap((candidate, index) => {
    if (!candidate || typeof candidate !== "object") return [];
    const stored = candidate as Partial<EditorGroup>;
    const tabs = Array.isArray(stored.tabs)
      ? [...new Set(stored.tabs.filter(isTabKind).filter((tab) => permitted.includes(tab)))]
      : [];
    const activeTab = isTabKind(stored.activeTab)
      && permitted.includes(stored.activeTab)
      && tabs.includes(stored.activeTab)
      ? stored.activeTab
      : tabs[0] ?? null;
    return [{
      id: typeof stored.id === "string" ? stored.id : `restored-${index}`,
      tabs,
      activeTab,
    }];
  });

  return groups.length > 0 ? groups : createDefaultGroups(variant);
}

function stringRecord(value: unknown): Record<string, string> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value).filter((entry): entry is [string, string] => typeof entry[1] === "string"),
  );
}

function booleanRecord(value: unknown): Record<string, boolean> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value).filter((entry): entry is [string, boolean] => typeof entry[1] === "boolean"),
  );
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function initialNodeId(project: WorkspaceProjectDemo): string {
  if (project.variant === "textbook") return project.nodes[0]?.id ?? "";
  return flattenNodes(project.nodes).find((node) => node.type !== "section")?.id ?? project.nodes[0]?.id ?? "";
}

function loadStoredState(storageKey: string, project: WorkspaceProjectDemo): StoredWorkspaceState {
  const allNodes = flattenNodes(project.nodes);
  const fallbackGroups = createDefaultGroups(project.variant);
  const fallback: StoredWorkspaceState = {
    selectedNodeId: initialNodeId(project),
    selectedSourceIds: {},
    selectedLessonIds: {},
    treeWidth: 320,
    groupWeights: [1.25, 0.75],
    groups: fallbackGroups,
    expandedNodeIds: project.nodes.filter((node) => node.type === "section").map((node) => node.id),
    notes: project.variant === "exam" ? DEFAULT_NOTES : {},
    noteRepeats: project.variant === "exam" ? { normalization: true } : {},
    conspects: Object.fromEntries(allNodes.map((node) => [node.id, node.conspect])),
    removedBindingIds: [],
    studioExpanded: false,
  };

  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey) ?? "null") as LegacyWorkspaceState | null;
    if (!parsed) return fallback;
    const groups = parseGroups(parsed.groups, project.variant, project.lessonsEnabled);
    const storedNodeId = parsed.selectedNodeId ?? parsed.selectedQuestionId;
    const selectedNodeId = allNodes.some((node) => node.id === storedNodeId)
      ? storedNodeId as string
      : fallback.selectedNodeId;
    const treeWidth = typeof parsed.treeWidth === "number" && Number.isFinite(parsed.treeWidth)
      ? Math.min(460, Math.max(260, parsed.treeWidth))
      : fallback.treeWidth;
    const groupWeights = Array.isArray(parsed.groupWeights)
      && parsed.groupWeights.length === groups.length
      && parsed.groupWeights.every((weight) => typeof weight === "number" && Number.isFinite(weight) && weight > 0)
      ? parsed.groupWeights
      : groups.map(() => 1);

    return {
      selectedNodeId,
      selectedSourceIds: stringRecord(parsed.selectedSourceIds),
      selectedLessonIds: stringRecord(parsed.selectedLessonIds),
      treeWidth,
      groupWeights,
      groups,
      expandedNodeIds: stringArray(parsed.expandedNodeIds ?? parsed.expandedSectionIds),
      notes: { ...fallback.notes, ...stringRecord(parsed.notes) },
      noteRepeats: { ...fallback.noteRepeats, ...booleanRecord(parsed.noteRepeats) },
      conspects: { ...fallback.conspects, ...stringRecord(parsed.conspects) },
      removedBindingIds: stringArray(parsed.removedBindingIds),
      studioExpanded: typeof parsed.studioExpanded === "boolean" ? parsed.studioExpanded : fallback.studioExpanded,
    };
  } catch {
    return fallback;
  }
}

function deadlineTone(days: number) {
  if (days < 4) return "danger";
  if (days <= 7) return "warning";
  return "success";
}

function sourcePriority(source: WorkspaceSourceRef): number {
  const unavailable = source.available === false ? 100 : 0;
  if (source.role === "primary" && (source.bindingStatus === "manual" || source.bindingStatus === "confirmed")) return unavailable;
  if (source.role === "primary" && source.bindingStatus === "machine") return unavailable + 1;
  if (source.role === "additional") return unavailable + 2;
  return unavailable + 3;
}

function visibleSources(node: WorkspaceNode, removedBindingIds: string[]): WorkspaceSourceRef[] {
  return node.sources
    .filter((source) => !removedBindingIds.includes(source.id))
    .sort((left, right) => sourcePriority(left) - sourcePriority(right));
}

function hasAvailableMaterial(node: WorkspaceNode, removedBindingIds: string[]): boolean {
  return node.status !== "no-material"
    && visibleSources(node, removedBindingIds).some((source) => source.available !== false);
}

function studyState(node: WorkspaceNode, removedBindingIds: string[]): "no-material" | "studied" {
  return hasAvailableMaterial(node, removedBindingIds) ? "studied" : "no-material";
}

function nodeMatches(
  node: WorkspaceNode,
  query: string,
  filters: { noAnswer: boolean; noMaterial: boolean; notStarted: boolean; notes: boolean },
  notes: Record<string, string>,
  removedBindingIds: string[],
): boolean {
  if (query && !node.title.toLocaleLowerCase("ru").includes(query)) return false;
  if (filters.noAnswer && node.answer) return false;
  if (filters.noMaterial && hasAvailableMaterial(node, removedBindingIds)) return false;
  if (filters.notStarted && (node.attempts.length > 0 || !hasAvailableMaterial(node, removedBindingIds))) return false;
  if (filters.notes && !(notes[node.id] ?? "").trim()) return false;
  return node.type !== "section" || (!filters.noAnswer && !filters.noMaterial && !filters.notStarted && !filters.notes);
}

function filterNodeTree(
  nodes: WorkspaceNode[],
  query: string,
  filters: { noAnswer: boolean; noMaterial: boolean; notStarted: boolean; notes: boolean },
  notes: Record<string, string>,
  removedBindingIds: string[],
): WorkspaceNode[] {
  return nodes.flatMap((node) => {
    const children = filterNodeTree(node.children ?? [], query, filters, notes, removedBindingIds);
    if (nodeMatches(node, query, filters, notes, removedBindingIds)) return [{ ...node, children }];
    return children.length ? [{ ...node, children }] : [];
  });
}

export function ProjectWorkspace() {
  const { projectId = "demo" } = useParams();
  const project = resolveWorkspaceProject(projectId);
  return <Workspace project={project} key={project.id} />;
}

function Workspace({ project }: { project: WorkspaceProjectDemo }) {
  const navigate = useNavigate();
  const location = useLocation();
  const storageKey = `tentex:workspace:${project.id}`;
  const stored = useMemo(() => loadStoredState(storageKey, project), [project, storageKey]);
  const [selectedNodeId, setSelectedNodeId] = useState(stored.selectedNodeId);
  const [selectedSourceIds, setSelectedSourceIds] = useState(stored.selectedSourceIds);
  const [selectedLessonIds, setSelectedLessonIds] = useState(stored.selectedLessonIds);
  const [treeWidth, setTreeWidth] = useState(stored.treeWidth);
  const [groups, setGroups] = useState<EditorGroup[]>(stored.groups);
  const [groupWeights, setGroupWeights] = useState(stored.groupWeights);
  const [activeGroupId, setActiveGroupId] = useState(stored.groups[0].id);
  const [expandedNodeIds, setExpandedNodeIds] = useState(stored.expandedNodeIds);
  const [notes, setNotes] = useState(stored.notes);
  const [noteRepeats, setNoteRepeats] = useState(stored.noteRepeats);
  const [conspects, setConspects] = useState(stored.conspects);
  const [removedBindingIds, setRemovedBindingIds] = useState(stored.removedBindingIds);
  const [studioExpanded, setStudioExpanded] = useState(stored.studioExpanded);
  const [lastRemovedBinding, setLastRemovedBinding] = useState<{ nodeId: string; sourceId: string } | null>(null);
  const [conspectSaving, setConspectSaving] = useState(false);
  const [chatIncludesConspect, setChatIncludesConspect] = useState(false);
  const [programDialog, setProgramDialog] = useState<ProgramDialogState | null>(null);
  const [cardDraftNodeIds, setCardDraftNodeIds] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState({ noAnswer: false, noMaterial: false, notStarted: false, notes: false });
  const editorGridRef = useRef<HTMLDivElement>(null);
  const conspectSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isTextbook = project.variant === "textbook";
  const allNodes = useMemo(() => flattenNodes(project.nodes), [project.nodes]);
  const navigableNodes = useMemo(
    () => allNodes.filter((node) => node.type !== "section" && !node.isDraft),
    [allNodes],
  );
  const selectedNode = findNode(project.nodes, selectedNodeId) ?? allNodes[0];
  const selectedIndex = navigableNodes.findIndex((node) => node.id === selectedNode.id);
  const hasNavigableSelection = selectedIndex >= 0;
  const selectedNodeSources = visibleSources(selectedNode, removedBindingIds);
  const selectedSource = selectedNodeSources.find((source) => source.id === selectedSourceIds[selectedNode.id])
    ?? selectedNodeSources[0];

  const filteredNodes = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase("ru");
    return filterNodeTree(project.nodes, normalizedQuery, filters, notes, removedBindingIds);
  }, [filters, notes, project.nodes, query, removedBindingIds]);

  useEffect(() => {
    const state: StoredWorkspaceState = {
      selectedNodeId,
      selectedSourceIds,
      selectedLessonIds,
      treeWidth,
      groupWeights,
      groups,
      expandedNodeIds,
      notes,
      noteRepeats,
      conspects,
      removedBindingIds,
      studioExpanded,
    };
    localStorage.setItem(storageKey, JSON.stringify(state));
  }, [conspects, expandedNodeIds, groupWeights, groups, noteRepeats, notes, removedBindingIds, selectedLessonIds, selectedNodeId, selectedSourceIds, storageKey, studioExpanded, treeWidth]);

  useEffect(() => {
    const query = new URLSearchParams(location.search);
    const topicId = query.get("topic");
    const lessonId = query.get("lesson");
    if (topicId && allNodes.some((node) => node.id === topicId)) setSelectedNodeId(topicId);
    if (lessonId && topicId) setSelectedLessonIds((current) => ({ ...current, [topicId]: lessonId }));
    if (query.get("tab") === "lesson" && project.lessonsEnabled) {
      setGroups((current) => {
        const sourceGroup = current[0] ?? { id: "primary", tabs: [], activeTab: null };
        const lessonGroup = current[1] ?? { id: "secondary", tabs: [], activeTab: null };
        return [
          { ...sourceGroup, tabs: sourceGroup.tabs.includes("source") ? sourceGroup.tabs : [...sourceGroup.tabs, "source"], activeTab: "source" },
          { ...lessonGroup, tabs: lessonGroup.tabs.includes("lesson") ? lessonGroup.tabs : [...lessonGroup.tabs, "lesson"], activeTab: "lesson" },
        ];
      });
      setGroupWeights([1, 1]);
    }
  }, [allNodes, location.search, project.lessonsEnabled]);

  useEffect(() => {
    if (!groups.some((group) => group.id === activeGroupId)) setActiveGroupId(groups[0].id);
  }, [activeGroupId, groups]);

  useEffect(() => () => {
    if (conspectSaveTimer.current) clearTimeout(conspectSaveTimer.current);
  }, []);

  function toggleNode(nodeId: string) {
    setExpandedNodeIds((current) => current.includes(nodeId)
      ? current.filter((id) => id !== nodeId)
      : [...current, nodeId]);
  }

  function selectRelativeNode(delta: number) {
    const next = navigableNodes[selectedIndex + delta];
    if (next) setSelectedNodeId(next.id);
  }

  function openTab(kind: WorkspaceTab, groupId = activeGroupId) {
    if (!allowedTabs(project.variant, project.lessonsEnabled).includes(kind)) return;
    setGroups((current) => current.map((group) => {
      const tabs = isTextbook && kind === "source" && group.id !== groupId
        ? group.tabs.filter((tab) => tab !== "source")
        : group.tabs;
      if (group.id !== groupId) {
        return { ...group, tabs, activeTab: group.activeTab === "source" && !tabs.includes("source") ? tabs[0] ?? null : group.activeTab };
      }
      return {
        ...group,
        tabs: tabs.includes(kind) ? tabs : [...tabs, kind],
        activeTab: kind,
      };
    }));
    setActiveGroupId(groupId);
  }

  function closeTab(groupId: string, kind: WorkspaceTab) {
    setGroups((current) => current.map((group) => {
      if (group.id !== groupId) return group;
      const tabs = group.tabs.filter((tab) => tab !== kind);
      return { ...group, tabs, activeTab: group.activeTab === kind ? tabs.at(-1) ?? null : group.activeTab };
    }));
  }

  function addGroup() {
    if (groups.length >= 3) return;
    const nextId = `group-${Date.now()}`;
    setGroups((current) => [...current, { id: nextId, tabs: [], activeTab: null }]);
    setGroupWeights(Array.from({ length: groups.length + 1 }, () => 1));
    setActiveGroupId(nextId);
  }

  function closeGroup(groupId: string) {
    if (groups.length <= 1) return;
    const index = groups.findIndex((group) => group.id === groupId);
    setGroups((current) => current.filter((group) => group.id !== groupId));
    setGroupWeights((current) => current.filter((_, weightIndex) => weightIndex !== index));
  }

  function resizeGroups(leftIndex: number, deltaPixels: number) {
    const width = editorGridRef.current?.clientWidth ?? 1;
    setGroupWeights((current) => {
      const next = [...current];
      const pairTotal = next[leftIndex] + next[leftIndex + 1];
      const minWeight = Math.min(0.55, pairTotal / 2);
      const deltaWeight = (deltaPixels / width) * next.reduce((sum, weight) => sum + weight, 0);
      const left = Math.min(pairTotal - minWeight, Math.max(minWeight, next[leftIndex] + deltaWeight));
      next[leftIndex] = left;
      next[leftIndex + 1] = pairTotal - left;
      return next;
    });
  }

  function openMenu(groupId: string, compact = false) {
    return (
      <Menu
        label="Открыть в панели"
        trigger={compact ? (
          <IconButton label="Открыть в этой панели"><Plus size={15} aria-hidden="true" /></IconButton>
        ) : (
          <Button variant="secondary"><Plus size={15} aria-hidden="true" />Открыть<ChevronDown size={14} aria-hidden="true" /></Button>
        )}
        items={allowedTabs(project.variant, project.lessonsEnabled).map((kind) => {
          const TabIcon = TAB_ICONS[kind];
          return {
            label: tabLabel(kind, project.variant),
            icon: <TabIcon size={15} aria-hidden="true" />,
            onSelect: () => openTab(kind, groupId),
          };
        })}
      />
    );
  }

  function updateConspect(value: string) {
    setConspects((current) => ({ ...current, [selectedNode.id]: value }));
    setConspectSaving(true);
    if (conspectSaveTimer.current) clearTimeout(conspectSaveTimer.current);
    conspectSaveTimer.current = setTimeout(() => setConspectSaving(false), 600);
  }

  function removeMachineBinding(sourceId: string) {
    setRemovedBindingIds((current) => current.includes(sourceId) ? current : [...current, sourceId]);
    const nextSource = selectedNodeSources.find((source) => source.id !== sourceId);
    setSelectedSourceIds((current) => {
      const next = { ...current };
      if (nextSource) next[selectedNode.id] = nextSource.id;
      else delete next[selectedNode.id];
      return next;
    });
    setLastRemovedBinding({ nodeId: selectedNode.id, sourceId });
  }

  function restoreMachineBinding(nodeId: string, sourceId: string) {
    setRemovedBindingIds((current) => current.filter((id) => id !== sourceId));
    setSelectedSourceIds((current) => ({ ...current, [nodeId]: sourceId }));
    setLastRemovedBinding(null);
  }

  function renderSourceSelector() {
    if (!selectedNodeSources.length) return null;
    const materials = [...new Set(selectedNodeSources.map((source) => source.materialName))];
    return (
      <div className="workspace-source-selector">
        <label htmlFor={`workspace-source-${selectedNode.id}`}>Источник</label>
        <select
          id={`workspace-source-${selectedNode.id}`}
          value={selectedSource?.id ?? ""}
          onChange={(event) => setSelectedSourceIds((current) => ({ ...current, [selectedNode.id]: event.target.value }))}
        >
          {materials.map((materialName) => (
            <optgroup label={materialName} key={materialName}>
              {selectedNodeSources.filter((source) => source.materialName === materialName).map((source) => (
                <option value={source.id} key={source.id}>
                  {SOURCE_ROLE_LABELS[source.role]} — {source.pageLabel} — {source.fragmentCount} фрагм.{source.available === false ? " — недоступен" : ""}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </div>
    );
  }

  function renderTextbookSource() {
    if (!selectedNodeSources.length) {
      return (
        <div className="workspace-empty-copy">
          <CircleDashed size={26} aria-hidden="true" />
          <h2>Нужно найти материал по теме</h2>
          <p>Это нормальный пробел программы. Tentex не будет придумывать содержание без источника.</p>
          {lastRemovedBinding?.nodeId === selectedNode.id && <Button variant="secondary" onClick={() => restoreMachineBinding(lastRemovedBinding.nodeId, lastRemovedBinding.sourceId)}>Отменить снятие привязки</Button>}
          <Tooltip label="Учебная конфигурация Материалов будет спроектирована отдельно"><span><Button variant="secondary" disabled>Добавить источник</Button></span></Tooltip>
        </div>
      );
    }

    if (!selectedSource) return null;

    return (
      <div className="workspace-textbook-source">
        {renderSourceSelector()}
        {lastRemovedBinding?.nodeId === selectedNode.id && (
          <div className="workspace-binding-undo" role="status">
            <span>Машинная привязка снята.</span>
            <Button variant="ghost" onClick={() => restoreMachineBinding(lastRemovedBinding.nodeId, lastRemovedBinding.sourceId)}>Отменить</Button>
          </div>
        )}
        {selectedSource.available === false ? (
          <div className="workspace-empty-copy">
            <Link2Off size={26} aria-hidden="true" />
            <h2>Источник недоступен</h2>
            <p>{selectedSource.materialName}, {selectedSource.pageLabel}. Привязка сохранена, но текст нельзя показать или подменить.</p>
            <p>Выберите другой источник, если он есть, либо восстановите материал позднее.</p>
          </div>
        ) : (
          <article className="workspace-reading workspace-source-preview">
            <div className="workspace-reading-meta">
              <StatusBadge tone="neutral">{SOURCE_ROLE_LABELS[selectedSource.role]}</StatusBadge>
              <span>{selectedSource.materialName}</span>
              <span>{selectedSource.pageLabel}</span>
              <span>{selectedSource.fragmentCount} фрагмента</span>
              <QualityBadge quality={selectedSource.quality} />
            </div>
            <div className="workspace-source-provenance">
              <SourceChip source={selectedSource.bindingStatus === "manual" ? { kind: "manual" } : { kind: "pass1", pages: selectedSource.pageLabel }} />
              <StatusBadge tone={selectedSource.bindingStatus === "machine" ? "info" : "success"}>{BINDING_LABELS[selectedSource.bindingStatus]}</StatusBadge>
              {selectedSource.bindingStatus === "machine" && <MachineMark origin="проход 2" />}
            </div>
            {selectedSource.quality === "ocr_low" && (
              <p className="workspace-source-warning"><Info size={15} aria-hidden="true" />Текст распознан плохо. Сверьте формулировки с оригинальной страницей.</p>
            )}
            <h2>Связанный фрагмент</h2>
            <blockquote>{selectedSource.fragmentText}</blockquote>
            {selectedSource.surroundingText && (
              <div className="workspace-source-context"><strong>Соседний контекст</strong><p>{selectedSource.surroundingText}</p></div>
            )}
            <div className="workspace-source-actions">
              <Tooltip label="Просмотрщик источника ещё не зарегистрирован"><span><Button variant="secondary" disabled>Открыть полностью</Button></span></Tooltip>
              {selectedSource.bindingStatus === "machine" && (
                <Button variant="ghost" onClick={() => removeMachineBinding(selectedSource.id)}>Это не по теме</Button>
              )}
            </div>
          </article>
        )}
      </div>
    );
  }

  function renderExamSource() {
    const source = selectedNodeSources[0];
    if (!source || source.available === false) {
      return (
        <div className="workspace-empty-copy">
          <CircleDashed size={26} aria-hidden="true" />
          <h2>К вопросу ещё нет материала</h2>
          <p>Это нормальное состояние. Материал можно добавить или привязать позднее.</p>
          <Button variant="secondary" disabled>Перейти к материалам</Button>
        </div>
      );
    }
    return (
      <article className="workspace-reading workspace-source-preview">
        <div className="workspace-reading-meta"><StatusBadge tone="neutral">Источник</StatusBadge><span>{source.materialName}</span><span>{source.pageLabel}</span></div>
        <h2>Связанный фрагмент</h2>
        <blockquote>{source.fragmentText}</blockquote>
        <p className="workspace-source-caption">Фрагмент подтверждён и относится к выбранному вопросу.</p>
        <Button variant="secondary" disabled>Открыть полностью</Button>
      </article>
    );
  }

  function renderHistory() {
    if (!selectedNode.attempts.length) {
      return (
        <div className="workspace-empty-copy">
          <History size={26} aria-hidden="true" />
          <h2>История пока пуста</h2>
          <p>Подтверждённых попыток по теме ещё нет. Прогноз появится только после реальной работы.</p>
        </div>
      );
    }
    return (
      <div className="workspace-history">
        <header><h2>История темы</h2><span>{selectedNode.attempts.length} записи</span></header>
        {selectedNode.attempts.map((attempt) => (
          <article key={attempt.id}>
            <div><strong>{ATTEMPT_LABELS[attempt.kind]}</strong><time>{attempt.happenedAt}</time></div>
            <p>{attempt.resultLabel}</p>
            <small>{attempt.durationMinutes} минут{attempt.kind === "reading" ? " · сила свидетельства 0" : ""}{attempt.usedHint ? " · использована подсказка" : ""}</small>
            {attempt.nextDueLabel && <em>{attempt.nextDueLabel}</em>}
          </article>
        ))}
      </div>
    );
  }

  function renderChat() {
    if (!isTextbook) {
      return (
        <div className="workspace-chat-stub">
          <div className="workspace-chat-context"><StatusBadge tone="neutral">Текущий вопрос</StatusBadge>{hasAvailableMaterial(selectedNode, removedBindingIds) && <StatusBadge tone="info">1 источник</StatusBadge>}</div>
          <MessageSquare size={28} aria-hidden="true" />
          <h2>Чат откроется здесь</h2>
          <p>В прототипе видна его позиция и контекст. Подключение модели появится на отдельном этапе.</p>
          <div className="workspace-chat-prompts"><Button variant="secondary" disabled>Объяснить проще</Button><Button variant="secondary" disabled>Проверить мой ответ</Button></div>
        </div>
      );
    }

    return (
      <div className="workspace-chat-stub workspace-textbook-chat">
        <div className="workspace-chat-context">
          <StatusBadge tone="neutral">Текущая тема</StatusBadge>
          {selectedSource?.available !== false && selectedSource && <StatusBadge tone="info">Выбранный источник</StatusBadge>}
          <StatusBadge tone="neutral">Подтверждённые фрагменты</StatusBadge>
        </div>
        <OfflineNotice reason={project.modelsEnabled ? "unreachable" : "disabled"} alternative="Источники, конспект и история работают без модели." />
        <Checkbox
          label="Добавлять мой конспект в контекст"
          checked={chatIncludesConspect}
          disabled={!(conspects[selectedNode.id] ?? "").trim()}
          onCheckedChange={setChatIncludesConspect}
        />
        <p>Чат не записывает ответы в конспект и не меняет привязки без подтверждения.</p>
        <div className="workspace-chat-prompts" aria-label="Быстрые действия чата">
          <Button variant="secondary" disabled={!project.modelsEnabled}>Объяснить проще</Button>
          <Button variant="secondary" disabled={!project.modelsEnabled}>Привести пример</Button>
          <Button variant="secondary" disabled={!project.modelsEnabled}>Задать проверочный вопрос</Button>
        </div>
      </div>
    );
  }

  function renderLesson() {
    const lessons = lessonsForTopic(selectedNode.id);
    const selectedLesson = lessons.find((lesson) => lesson.id === selectedLessonIds[selectedNode.id]) ?? lessons[0];
    if (!selectedLesson) {
      return (
        <div className="workspace-empty-copy">
          <GraduationCap size={26} aria-hidden="true" />
          <h2>Для этой темы ещё нет урока</h2>
          <p>Уроки создаются и редактируются в отдельном разделе проекта.</p>
          <Button onClick={() => navigate(`/projects/${project.id}/lessons?topic=${selectedNode.id}`)}>Создать урок</Button>
        </div>
      );
    }
    return (
      <div className="lessons-workspace">
        <div className="lessons-workspace-head">
          {lessons.length > 1 && <select aria-label="Выбрать урок" value={selectedLesson.id} onChange={(event) => setSelectedLessonIds((current) => ({ ...current, [selectedNode.id]: event.target.value }))}>{lessons.map((lesson) => <option key={lesson.id} value={lesson.id}>{lesson.title}</option>)}</select>}
          <StatusBadge tone={selectedLesson.status === "draft" ? "warning" : "success"}>{selectedLesson.status === "draft" ? "Черновик" : "Готов"}</StatusBadge>
          <Button variant="secondary" onClick={() => navigate(`/projects/${project.id}/lessons?topic=${selectedNode.id}&lesson=${selectedLesson.id}`)}>{selectedLesson.status === "draft" ? "Продолжить редактирование" : "Редактировать"}</Button>
        </div>
        <LessonDocument document={selectedLesson.document} mode="study" />
      </div>
    );
  }

  function renderTabContent(kind: WorkspaceTab) {
    if (kind === "answer") {
      if (!selectedNode.answer) {
        return (
          <div className="workspace-empty-copy"><BookOpen size={26} aria-hidden="true" /><h2>Ответ пока не найден</h2><p>Выберите фрагмент в материалах или добавьте файл с ответами.</p><Button variant="secondary" disabled>Открыть материалы</Button></div>
        );
      }
      const source = selectedNodeSources[0];
      return (
        <article className="workspace-reading">
          <div className="workspace-reading-meta"><StatusBadge tone="info">Эталонный ответ</StatusBadge><span>{source?.materialName ?? "Файл с ответами"}</span>{source && <span>{source.pageLabel}</span>}</div>
          <h2>{selectedNode.title}</h2>
          {selectedNode.answer.split("\n\n").map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
        </article>
      );
    }
    if (kind === "source") return isTextbook ? renderTextbookSource() : renderExamSource();
    if (kind === "lesson") return renderLesson();
    if (kind === "conspect") {
      return (
        <div className="workspace-conspect">
          <div className="workspace-conspect-head"><span>Текст сохраняется для выбранной {isTextbook ? "темы" : "вопроса"}</span><StatusBadge tone="neutral">{conspectSaving ? "Сохранение…" : "Сохранено"}</StatusBadge></div>
          <textarea
            aria-label={`Мой конспект по ${isTextbook ? "теме" : "вопросу"}`}
            placeholder={isTextbook ? "Запишите определения, связи и собственные выводы по теме." : "Сформулируйте ответ своими словами. Затем откройте рядом эталон и сравните."}
            value={conspects[selectedNode.id] ?? ""}
            onChange={(event) => updateConspect(event.target.value)}
          />
        </div>
      );
    }
    if (kind === "history") return renderHistory();
    if (kind === "chat") return renderChat();

    const filledConspects = navigableNodes.filter((node) => (conspects[node.id] ?? "").trim());
    return (
      <div className="workspace-summary">
        <div className="workspace-summary-head"><h2>Сводный конспект</h2><span>{filledConspects.length} из {navigableNodes.length} вопросов</span></div>
        {filledConspects.map((node) => (
          <button type="button" key={node.id} onClick={() => { setSelectedNodeId(node.id); openTab("conspect"); }}>
            <strong>{node.number}. {node.title}</strong><span>{conspects[node.id]}</span>
          </button>
        ))}
      </div>
    );
  }

  function renderSectionOverview(section: WorkspaceNode) {
    const studyNodes = flattenNodes(section.children ?? []).filter((node) => node.type !== "section");
    const availableMaterials = new Set(studyNodes.flatMap((node) => visibleSources(node, removedBindingIds).filter((source) => source.available !== false).map((source) => source.materialName)));
    const studied = studyNodes.filter((node) => studyState(node, removedBindingIds) === "studied").length;
    const continueNode = studyNodes.find((node) => hasAvailableMaterial(node, removedBindingIds) && node.attempts.length === 0) ?? studyNodes[0];
    const hasStarted = studyNodes.some((node) => node.attempts.length > 0 || (conspects[node.id] ?? "").trim());

    return (
      <div className="workspace-section-overview">
        <div className="workspace-section-overview-intro">
          <span>Раздел {section.number}</span>
          <h2>{section.title}</h2>
          <p>{section.purpose ?? `В разделе ${studyNodes.length} ${isTextbook ? "тем" : "вопросов"}. Откройте строку, чтобы продолжить работу.`}</p>
          <dl><div><dt>{isTextbook ? "Разобрано" : "С материалом"}</dt><dd>{studied} из {studyNodes.length}</dd></div><div><dt>Источники</dt><dd>{availableMaterials.size}</dd></div></dl>
          {continueNode && <Button onClick={() => setSelectedNodeId(continueNode.id)}>{hasStarted ? "Продолжить" : `Открыть ${isTextbook ? "первую тему" : "первый вопрос"}`}</Button>}
        </div>
        <div className="workspace-section-topic-list">
          {studyNodes.map((node) => (
            <button type="button" key={node.id} onClick={() => setSelectedNodeId(node.id)}>
              <span><small>{node.number}</small><strong>{node.title}</strong></span>
              {isTextbook ? (
                <em className={`workspace-study-state is-${studyState(node, removedBindingIds)}`}>{studyState(node, removedBindingIds) === "no-material" ? "нет материала" : "разобран"}</em>
              ) : (
                <em>{topicStatusLabel(node.status)}</em>
              )}
            </button>
          ))}
        </div>
      </div>
    );
  }

  function renderNodeRows(nodes: WorkspaceNode[], depth = 0) {
    return nodes.map((node) => {
      const hasActiveNote = Boolean((notes[node.id] ?? "").trim());
      const row = (
        <button
          type="button"
          className={`workspace-question-row depth-${Math.min(depth, 3)} ${selectedNode.id === node.id ? "is-active" : ""}`.trim()}
          onClick={() => setSelectedNodeId(node.id)}
        >
          {isTextbook ? (
            <span className={`workspace-study-state is-${studyState(node, removedBindingIds)}`}>{studyState(node, removedBindingIds) === "no-material" ? "нет материала" : "разобран"}</span>
          ) : (
            <span className={`workspace-question-status is-${node.status}`} aria-label={topicStatusLabel(node.status)} />
          )}
          <span className="workspace-question-copy">
            <small>{node.isDraft ? "Новый узел" : `${isTextbook ? node.type === "subpoint" ? "Подпункт" : "Тема" : "Вопрос"} ${node.number}`}</small>
            <span>{node.title}</span>
          </span>
          <span className="workspace-question-signals">
            {node.isDraft && <small className="workspace-question-draft">Не добавлен</small>}
            {!hasAvailableMaterial(node, removedBindingIds) && <CircleDashed size={14} aria-label="Нет материала" />}
            {hasActiveNote && <StickyNote size={14} aria-label="Есть пометка" />}
            {cardDraftNodeIds.includes(node.id) && <Layers size={14} aria-label="Есть черновик карточек" />}
          </span>
        </button>
      );

      return (
        <div className="workspace-question-node" key={node.id}>
          {isTextbook ? row : (
            <ContextMenu.Root>
              <ContextMenu.Trigger asChild>{row}</ContextMenu.Trigger>
              <ContextMenu.Portal>
                <ContextMenu.Content className="menu" aria-label={`Действия с вопросом: ${node.title}`}>
                  <ContextMenu.Item className="menu-item" onSelect={() => navigate(`/projects/${project.id}/program?node=${node.id}`)}><NotebookPen size={15} aria-hidden="true" />Изменить в списке вопросов</ContextMenu.Item>
                  <ContextMenu.Item className="menu-item" onSelect={() => { setSelectedNodeId(node.id); openTab("source"); }}><FileText size={15} aria-hidden="true" />Открыть материалы</ContextMenu.Item>
                  <ContextMenu.Item className="menu-item" onSelect={() => setProgramDialog({ questionId: node.id })}><Layers size={15} aria-hidden="true" />Открыть или создать карточки</ContextMenu.Item>
                  <ContextMenu.Item className="menu-item" onSelect={() => navigate(`/projects/${project.id}/program?node=${node.id}`)}><Plus size={15} aria-hidden="true" />Изменить структуру экзамена</ContextMenu.Item>
                </ContextMenu.Content>
              </ContextMenu.Portal>
            </ContextMenu.Root>
          )}
          {node.children?.length ? <div className="workspace-question-list is-nested">{renderNodeRows(node.children, depth + 1)}</div> : null}
        </div>
      );
    });
  }

  function renderProjectNav() {
    if (isTextbook) {
      return (
        <nav className="workspace-project-nav" aria-label="Разделы учебного проекта">
          <Tooltip label="Учебная конфигурация Материалов будет спроектирована отдельно" side="right"><button type="button" disabled><Files size={15} aria-hidden="true" /><span>Материалы</span><small>позже</small></button></Tooltip>
          <Link className="workspace-project-link" to={`/projects/${project.id}/program?mode=textbook`}><ListTree size={15} aria-hidden="true" /><span>Программа</span></Link>
          {project.lessonsEnabled && <Link className="workspace-project-link" to={`/projects/${project.id}/lessons`}><GraduationCap size={15} aria-hidden="true" /><span>Уроки</span><small>3</small></Link>}
          <Tooltip label="Учебная конфигурация Карточек будет спроектирована отдельно" side="right"><button type="button" disabled><Layers size={15} aria-hidden="true" /><span>Карточки</span><small>позже</small></button></Tooltip>
          <Link className="workspace-project-link" to={`/projects/${project.id}/settings`}><Settings size={15} aria-hidden="true" /><span>Настройки</span></Link>
        </nav>
      );
    }

    return (
      <nav className="workspace-project-nav" aria-label="Разделы проекта">
        <Link className="workspace-project-link" to={`/projects/${project.id}/materials`}><Files size={15} aria-hidden="true" /><span>Материалы</span><small>3</small></Link>
        <Link className="workspace-project-link" to={`/projects/${project.id}/program`}><ListTree size={15} aria-hidden="true" /><span>Вопросы экзамена</span><small>8</small></Link>
        {project.lessonsEnabled && <Link className="workspace-project-link" to={`/projects/${project.id}/lessons`}><GraduationCap size={15} aria-hidden="true" /><span>Уроки</span></Link>}
        {project.planEnabled && <Link className="workspace-project-link" to={`/projects/${project.id}/plan`}><CalendarDays size={15} aria-hidden="true" /><span>План подготовки</span><small>7 дней</small></Link>}
        <Link className="workspace-project-link" to={`/projects/${project.id}/cards`}><Layers size={15} aria-hidden="true" /><span>Карточки</span><small>12</small></Link>
        <Link className="workspace-project-link" to={`/projects/${project.id}/settings`}><Settings size={15} aria-hidden="true" /><span>Настройки</span></Link>
      </nav>
    );
  }

  const editorColumns = groups.map((_, index) => `${groupWeights[index] ?? 1}fr${index < groups.length - 1 ? " 10px" : ""}`).join(" ");
  const activeFilters = Object.values(filters).filter(Boolean).length;
  const deadline = project.deadlineDays ?? 0;
  const dialogNode = programDialog ? findNode(project.nodes, programDialog.questionId) : undefined;

  return (
    <div className={`project-workspace ${isTextbook ? "is-textbook" : "is-exam"} ${studioExpanded ? "is-studio-expanded" : "is-studio-collapsed"}`} style={{ "--workspace-tree-width": `${treeWidth}px` } as CSSProperties}>
      <aside className="workspace-tree-panel">
        <header className="workspace-tree-head">
          <div className={`workspace-tree-title ${isTextbook ? "is-textbook" : ""}`}>
            <Tooltip label="К проектам"><Link className="workspace-back-button" to="/projects" aria-label="К проектам"><ArrowLeft size={15} aria-hidden="true" /></Link></Tooltip>
            <strong>{project.name}</strong>
            {!isTextbook && <span className={`workspace-project-deadline is-${deadlineTone(deadline)}`} aria-label={`${deadline} дней до экзамена`}><b>{deadline}</b><small>дней</small></span>}
          </div>
        </header>

        <div className="workspace-tree-tools">
          <label className="workspace-tree-search">
            <Search size={15} aria-hidden="true" />
            <input type="search" aria-label={isTextbook ? "Поиск по темам" : "Поиск по вопросам"} placeholder={isTextbook ? "Найти тему" : "Найти вопрос"} value={query} onChange={(event) => setQuery(event.target.value)} />
            {query && <button type="button" onClick={() => setQuery("")} aria-label="Очистить поиск"><X size={14} aria-hidden="true" /></button>}
          </label>
          <Popover
            title={isTextbook ? "Показать темы" : "Показать вопросы"}
            side="bottom"
            align="end"
            trigger={<IconButton label="Фильтры" aria-pressed={activeFilters > 0}><Filter size={15} aria-hidden="true" /></IconButton>}
          >
            <div className="workspace-filter-list">
              {!isTextbook && <Checkbox label="Без эталонного ответа" checked={filters.noAnswer} onCheckedChange={(checked) => setFilters((current) => ({ ...current, noAnswer: checked }))} />}
              <Checkbox label="Без материала" checked={filters.noMaterial} onCheckedChange={(checked) => setFilters((current) => ({ ...current, noMaterial: checked }))} />
              {isTextbook && <Checkbox label="Не начаты" checked={filters.notStarted} onCheckedChange={(checked) => setFilters((current) => ({ ...current, notStarted: checked }))} />}
              <Checkbox label="С пометками" checked={filters.notes} onCheckedChange={(checked) => setFilters((current) => ({ ...current, notes: checked }))} />
            </div>
          </Popover>
        </div>

        {project.pass2Progress && (
          <Popover
            title="Фоновая задача"
            side="right"
            align="start"
            className="workspace-pass2-popover"
            trigger={<button type="button" className="workspace-pass2-summary"><CircleDashed size={14} aria-hidden="true" /><span>Проход 2</span><small>{project.pass2Progress.done} из {project.pass2Progress.total}</small></button>}
          >
            <TaskRow task={{ id: "textbook-pass2", kind: "pass2", subject: project.name, unit: "блок", done: project.pass2Progress.done, total: project.pass2Progress.total, etaMinutes: 9, state: "running" }} />
          </Popover>
        )}

        <nav className="workspace-question-tree" aria-label={isTextbook ? "Программа учебного проекта" : "Вопросы экзамена"}>
          {filteredNodes.length === 0 && <p className="workspace-tree-empty">По этим условиям {isTextbook ? "тем" : "вопросов"} нет.</p>}
          {filteredNodes.map((node) => {
            if (node.type !== "section") return <div key={node.id}>{renderNodeRows([node])}</div>;
            const open = query.trim() !== "" || expandedNodeIds.includes(node.id);
            return (
              <section className="workspace-tree-section" key={node.id}>
                <div className={`workspace-section-row ${selectedNode.id === node.id ? "is-active" : ""}`}>
                  <button type="button" className="workspace-section-toggle" aria-label={`${open ? "Свернуть" : "Развернуть"} раздел «${node.title}»`} aria-expanded={open} onClick={() => toggleNode(node.id)}>{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</button>
                  <button type="button" className="workspace-section-select" onClick={() => setSelectedNodeId(node.id)}><span>{node.number}. {node.title}</span></button>
                  <small>{flattenNodes(node.children ?? []).filter((child) => child.type !== "section").length}</small>
                </div>
                {open && <div className="workspace-question-list">{renderNodeRows(node.children ?? [])}</div>}
              </section>
            );
          })}
        </nav>

        {renderProjectNav()}
      </aside>

      <PanelResizeHandle className="workspace-tree-resize" label={`Изменить ширину дерева ${isTextbook ? "тем" : "вопросов"}`} value={treeWidth} min={260} max={460} onDelta={(delta) => setTreeWidth((current) => Math.min(460, Math.max(260, current + delta)))} onReset={() => setTreeWidth(320)} />

      <main className="workspace-main">
        <header className="workspace-question-bar">
          <div className="workspace-question-heading"><h1>{selectedNode.title}</h1></div>
          {selectedNode.type !== "section" && (
            <div className="workspace-question-actions">
              {!hasAvailableMaterial(selectedNode, removedBindingIds) && <div className={`workspace-material-notice ${isTextbook ? "is-textbook" : ""}`} role="status"><Info size={15} aria-hidden="true" /><span>{isTextbook ? "Нужно найти материал по теме" : "Добавьте материалы к вопросу"}</span></div>}
              <div className="workspace-question-nav" aria-label={`Переход между ${isTextbook ? "темами" : "вопросами"}`}>
                <IconButton label={isTextbook ? "Предыдущая тема" : "Предыдущий вопрос"} disabled={!hasNavigableSelection || selectedIndex <= 0} onClick={() => selectRelativeNode(-1)}><ChevronLeft size={15} aria-hidden="true" /></IconButton>
                <span>{hasNavigableSelection ? `${selectedIndex + 1} из ${navigableNodes.length}` : "Новый черновик"}</span>
                <IconButton label={isTextbook ? "Следующая тема" : "Следующий вопрос"} disabled={!hasNavigableSelection || selectedIndex >= navigableNodes.length - 1} onClick={() => selectRelativeNode(1)}><ChevronRight size={15} aria-hidden="true" /></IconButton>
              </div>
              {openMenu(activeGroupId)}
              <IconButton label="Разделить рабочую область" onClick={addGroup} disabled={groups.length >= 3}><PanelsTopLeft size={15} aria-hidden="true" /></IconButton>
              <Popover
                title={`Пометка к ${isTextbook ? "теме" : `вопросу ${selectedNode.number}`}`}
                side="bottom"
                align="end"
                className="workspace-note-popover"
                trigger={<IconButton label={`Пометка к ${isTextbook ? "теме" : "вопросу"}`} aria-pressed={Boolean((notes[selectedNode.id] ?? "").trim())}><StickyNote size={15} aria-hidden="true" /></IconButton>}
              >
                <textarea aria-label="Текст пометки" placeholder={isTextbook ? "Что важно не забыть по этой теме?" : "Что не забыть повторить по этому вопросу?"} value={notes[selectedNode.id] ?? ""} onChange={(event) => setNotes((current) => ({ ...current, [selectedNode.id]: event.target.value }))} />
                {!isTextbook && <Button variant="secondary" className={`workspace-repeat-button ${noteRepeats[selectedNode.id] ? "is-active" : ""}`.trim()} aria-pressed={noteRepeats[selectedNode.id] ?? false} onClick={() => setNoteRepeats((current) => ({ ...current, [selectedNode.id]: !current[selectedNode.id] }))}><RotateCcw size={15} aria-hidden="true" />Нужно повторить</Button>}
                <small className="workspace-note-saved">Сохраняется автоматически</small>
              </Popover>
              {isTextbook ? <Tooltip label="Сессия занятия будет спроектирована отдельно"><span><Button disabled>Начать занятие</Button></span></Tooltip> : <Button disabled>Проверить себя</Button>}
            </div>
          )}
        </header>

        {selectedNode.type === "section" ? renderSectionOverview(selectedNode) : (
          <div className="workspace-editor-grid" ref={editorGridRef} style={{ gridTemplateColumns: editorColumns }}>
            {groups.map((group, index) => {
              const activeTab = group.activeTab;
              return (
                <div key={group.id} className="workspace-editor-fragment">
                  <section className={`workspace-editor-group ${activeGroupId === group.id ? "is-active" : ""}`.trim()} aria-label={`Рабочая панель ${index + 1}`} onClick={() => setActiveGroupId(group.id)}>
                    <div className="workspace-tabbar">
                      <div className="workspace-tabs" role="tablist" aria-label={`Вкладки панели ${index + 1}`}>
                        {group.tabs.map((kind) => {
                          const TabIcon = TAB_ICONS[kind];
                          const label = tabLabel(kind, project.variant);
                          return (
                            <div className={`workspace-tab ${activeTab === kind ? "is-active" : ""}`.trim()} key={kind}>
                              <button type="button" role="tab" aria-selected={activeTab === kind} onClick={() => setGroups((current) => current.map((item) => item.id === group.id ? { ...item, activeTab: kind } : item))}><TabIcon size={14} aria-hidden="true" /><span>{label}</span></button>
                              <button type="button" className="workspace-tab-close" aria-label={`Закрыть вкладку «${label}»`} onClick={() => closeTab(group.id, kind)}><X size={13} aria-hidden="true" /></button>
                            </div>
                          );
                        })}
                      </div>
                      <div className="workspace-tabbar-actions">
                        {openMenu(group.id, true)}
                        {groups.length > 1 && group.tabs.length === 0 && <IconButton label="Закрыть пустую панель" onClick={() => closeGroup(group.id)}><PanelRightClose size={15} aria-hidden="true" /></IconButton>}
                      </div>
                    </div>
                    <div className="workspace-panel-content">
                      {activeTab ? renderTabContent(activeTab) : (
                        <div className="workspace-empty-panel"><PanelRightClose size={28} aria-hidden="true" /><h2>Панель пока пустая</h2><p>{isTextbook ? "Откройте здесь другой инструмент темы: конспект, историю или чат." : "Откройте здесь ответ, материал, свой текст или чат."}</p><div>{openMenu(group.id)}{groups.length > 1 && <Button variant="ghost" onClick={() => closeGroup(group.id)}>Закрыть панель</Button>}</div></div>
                      )}
                    </div>
                  </section>
                  {index < groups.length - 1 && <PanelResizeHandle className="workspace-panel-resize" label={`Изменить ширину панелей ${index + 1} и ${index + 2}`} value={(groupWeights[index] / (groupWeights[index] + groupWeights[index + 1])) * 100} min={20} max={80} onDelta={(delta) => resizeGroups(index, delta)} onReset={() => setGroupWeights(groups.map(() => 1))} />}
                </div>
              );
            })}
          </div>
        )}
      </main>

      <StudioPanel
        expanded={studioExpanded}
        onExpandedChange={setStudioExpanded}
        modelsEnabled={project.modelsEnabled}
        sourceCount={selectedNodeSources.filter((source) => source.available !== false).length}
        topicTitle={selectedNode.title}
      />

      <Dialog
        open={Boolean(programDialog && dialogNode)}
        onOpenChange={(open) => { if (!open) setProgramDialog(null); }}
        title="Карточки вопроса"
        description="Карточки останутся отдельным режимом, но черновик можно пометить уже сейчас."
        footer={<><Button variant="ghost" onClick={() => setProgramDialog(null)}>Отменить</Button><Button onClick={() => { if (programDialog) setCardDraftNodeIds((current) => current.includes(programDialog.questionId) ? current : [...current, programDialog.questionId]); setProgramDialog(null); }}>{cardDraftNodeIds.includes(programDialog?.questionId ?? "") ? "Черновик уже создан" : "Создать черновик"}</Button></>}
      >
        <p className="workspace-program-dialog-copy">{cardDraftNodeIds.includes(programDialog?.questionId ?? "") ? "Черновик карточек отмечен в дереве. Сам режим повторения будет спроектирован отдельно." : "После создания черновик будет отмечен у вопроса значком карточек."}</p>
      </Dialog>
    </div>
  );
}
