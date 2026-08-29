import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import {
  ArrowLeft,
  BookOpen,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FileText,
  Filter,
  GraduationCap,
  History,
  ListTree,
  MessageSquare,
  NotebookPen,
  PanelRightClose,
  PanelsTopLeft,
  Plus,
  Search,
  Tag,
  Target,
  Unlink,
  X,
} from "lucide-react";
import type { BindingFragmentRead } from "../api/bindings";
import { listBindings, removeBinding, createBindings } from "../api/bindings";
import { materialFragmentAssetUrl } from "../api/materials";
import {
  answerAttachmentUrl,
  getCoverageMap,
  getReferenceAnswer,
  getProject,
  listAnswerAttachments,
  ProjectApiError,
  saveWorkspaceState,
  type CoverageMapRead,
  type ProgramNodeRead,
  type ProjectDetail,
  type ProjectRead,
  type ReferenceAnswerSlot,
  type ReferenceAnswerStatus,
  type ReferenceAnswerAttachment,
  type WorkspaceLayout,
  type WorkspaceTab,
} from "../api/projects";
import type { SearchHighlightRead, SearchResultRead } from "../api/search";
import { searchProjectMaterials } from "../api/search";
import {
  AnswerScanPages,
  answerScanGroups,
  PERSONAL_MARK_OPTIONS,
  PersonalMarkIcon,
  ProjectNav,
  QualityBadge,
  ReferenceAnswerBadge,
  referenceAnswerStatusLabel,
} from "../components/domain";
import {
  Button,
  ContextMenu,
  EmptyState,
  ErrorState,
  IconButton,
  LoadingState,
  Menu,
  PanelResizeHandle,
  SegmentedTabs,
  Tooltip,
} from "../components/ui";
import type { ContextMenuItem } from "../components/ui";
import { useBindings } from "../hooks/useBindings";
import {
  buildProgramTree,
  filterProgramTree,
  flattenProgramTree,
  type ProgramTreeNode,
} from "./programTree";
import { StudioPanel } from "./StudioPanel";
import { usePersonalMarks } from "../hooks/usePersonalMarks";
import { useAnswerViewMode } from "../hooks/useAnswerViewMode";
import { ExamChatPanel } from "./workspace/chat/ExamChatPanel";
import { AttemptHistory } from "./workspace/AttemptHistory";
import { ReferenceAnswerContent, type ReferenceAnswerMedia } from "./workspace/ReferenceAnswerContent";
import { attachmentImageLabel } from "./workspace/referenceAnswerMedia";

const DEFAULT_LAYOUT: WorkspaceLayout = {
  selected_node_id: null,
  expanded_node_ids: [],
  tree_width: 320,
  groups: [{ id: "main", tabs: [], active_tab: null }],
  group_weights: [1],
};

const STUDY_TYPES = new Set(["topic", "subpoint"]);

const TAB_ICONS = {
  answer: BookOpen,
  source: FileText,
  lesson: GraduationCap,
  conspect: NotebookPen,
  history: History,
  chat: MessageSquare,
  summary: ListTree,
} satisfies Record<WorkspaceTab, typeof BookOpen>;

function allowedTabs(project: Pick<ProjectRead, "workspace_variant" | "enabled_modules"> | null): WorkspaceTab[] {
  if (!project) return ["answer", "source"];
  const tabs: WorkspaceTab[] = project.workspace_variant === "exam"
    ? ["answer", "source", "conspect", "chat", "summary"]
    : ["source", "conspect", "history", "chat"];
  return project.enabled_modules.includes("lessons") ? [...tabs.slice(0, 2), "lesson", ...tabs.slice(2)] : tabs;
}

function tabLabel(tab: WorkspaceTab, textbook: boolean): string {
  if (tab === "source") return textbook ? "Источник" : "Материал";
  return {
    answer: "Ответ",
    lesson: "Урок",
    conspect: "Мой конспект",
    history: "История",
    chat: "Чат",
    summary: "Сводный конспект",
  }[tab];
}

function daysUntil(deadline: string | null): number | null {
  if (!deadline) return null;
  const date = new Date(deadline);
  if (Number.isNaN(date.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  date.setHours(0, 0, 0, 0);
  return Math.ceil((date.getTime() - today.getTime()) / 86_400_000);
}

function deadlineTone(days: number): "success" | "warning" | "danger" {
  if (days < 4) return "danger";
  if (days <= 7) return "warning";
  return "success";
}

function answerDotClass(status: ReferenceAnswerStatus | undefined): string {
  if (status === "needs_review") return "is-answer-needs-review";
  if (status === "auto_matched") return "is-answer-auto";
  if (status === "confirmed" || status === "manual") return "is-answer-present";
  return "";
}

function isStudyNode(node: ProgramNodeRead): boolean {
  return STUDY_TYPES.has(node.node_type) && node.is_in_current_program && !node.is_archived;
}

function renderHighlighted(text: string, highlights: SearchHighlightRead[]): ReactNode {
  if (highlights.length === 0) return text;
  const sorted = [...highlights].sort((left, right) => left.start - right.start);
  const nodes: ReactNode[] = [];
  let cursor = 0;
  sorted.forEach((range, index) => {
    if (range.start > cursor) nodes.push(text.slice(cursor, range.start));
    nodes.push(<mark key={index}>{text.slice(range.start, range.end)}</mark>);
    cursor = Math.max(cursor, range.end);
  });
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

function sanitizeLayout(
  source: WorkspaceLayout | undefined,
  nodes: ProgramNodeRead[],
  preferredNodeId: string | null,
  availableTabs: WorkspaceTab[],
): WorkspaceLayout {
  const visibleNodes = nodes.filter((node) => node.is_in_current_program && !node.is_archived);
  const currentIds = new Set(visibleNodes.map((node) => node.id));
  const studyIds = new Set(nodes.filter(isStudyNode).map((node) => node.id));
  const firstStudyId = nodes.find(isStudyNode)?.id ?? null;
  const selected = preferredNodeId && studyIds.has(preferredNodeId)
    ? preferredNodeId
    : source?.selected_node_id && studyIds.has(source.selected_node_id)
      ? source.selected_node_id
      : firstStudyId;
  const groups = (source?.groups ?? DEFAULT_LAYOUT.groups).slice(0, 3).map((group, index) => {
    const tabs = group.tabs.filter((tab): tab is WorkspaceTab => availableTabs.includes(tab));
    const validTabs = [...new Set(tabs)];
    return {
      id: group.id || `panel-${index + 1}`,
      tabs: validTabs,
      active_tab: group.active_tab && validTabs.includes(group.active_tab) ? group.active_tab : validTabs[0] ?? null,
    };
  });
  return {
    selected_node_id: selected,
    expanded_node_ids: [...new Set(source?.expanded_node_ids ?? visibleNodes.filter((node) => node.node_type === "section").map((node) => node.id))].filter((id) => currentIds.has(id)),
    tree_width: Math.round(Math.min(460, Math.max(260, source?.tree_width ?? 320))),
    groups: groups.length ? groups : DEFAULT_LAYOUT.groups,
    group_weights: groups.map((_, index) => source?.group_weights[index] && source.group_weights[index] > 0 ? source.group_weights[index] : 1),
  };
}

export function ProjectWorkspace() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const preferredTopic = searchParams.get("topic");
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [layout, setLayout] = useState<WorkspaceLayout>(DEFAULT_LAYOUT);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [saveError, setSaveError] = useState("");
  const [answerSlot, setAnswerSlot] = useState<ReferenceAnswerSlot | null>(null);
  const [answerLoading, setAnswerLoading] = useState(false);
  const [answerError, setAnswerError] = useState("");
  const [answerAttachments, setAnswerAttachments] = useState<ReferenceAnswerAttachment[]>([]);
  const [attemptsReloadKey, setAttemptsReloadKey] = useState(0);
  const [coverage, setCoverage] = useState<CoverageMapRead | null>(null);
  const [query, setQuery] = useState("");
  const [studioExpanded, setStudioExpanded] = useState(false);
  const [activeGroupId, setActiveGroupId] = useState(DEFAULT_LAYOUT.groups[0].id);
  const { marks, setMark } = usePersonalMarks(projectId);
  const { mode: answerViewMode, setMode: setAnswerViewMode } = useAnswerViewMode(projectId);
  const bindings = useBindings(projectId);
  const [sourceBindings, setSourceBindings] = useState<BindingFragmentRead[]>([]);
  const [sourceBindingsLoading, setSourceBindingsLoading] = useState(false);
  const [sourceQuery, setSourceQuery] = useState("");
  const [sourceResults, setSourceResults] = useState<SearchResultRead[]>([]);
  const [sourceSearching, setSourceSearching] = useState(false);
  const [sourceSearched, setSourceSearched] = useState(false);
  const [sourceBusy, setSourceBusy] = useState(false);
  const [sourceNotice, setSourceNotice] = useState("");
  const sourceSearchInput = useRef<HTMLInputElement>(null);
  const queueRef = useRef<Promise<void>>(Promise.resolve());
  const resizeReadyRef = useRef(false);
  const layoutRef = useRef<WorkspaceLayout>(DEFAULT_LAYOUT);
  const editorGridRef = useRef<HTMLDivElement>(null);

  async function load(signal?: AbortSignal) {
    setLoading(true);
    setLoadError(null);
    try {
      const next = await getProject(projectId, signal);
      const sanitized = sanitizeLayout(next.workspace_state?.layout, next.program.nodes, preferredTopic, allowedTabs(next.project));
      setDetail(next);
      layoutRef.current = sanitized;
      setLayout(sanitized);
      resizeReadyRef.current = false;
      if (JSON.stringify(sanitized) !== JSON.stringify(next.workspace_state?.layout)) {
        await saveWorkspaceState(projectId, sanitized);
      }
      if (next.project.workspace_variant === "exam") {
        getCoverageMap(projectId, signal).then(setCoverage).catch(() => undefined);
      } else {
        setCoverage(null);
      }
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

  function updateLayout(nextOrUpdater: WorkspaceLayout | ((current: WorkspaceLayout) => WorkspaceLayout)) {
    const next = typeof nextOrUpdater === "function" ? nextOrUpdater(layoutRef.current) : nextOrUpdater;
    layoutRef.current = next;
    setLayout(next);
    return next;
  }

  function enqueueSave(next: WorkspaceLayout) {
    setSaveError("");
    queueRef.current = queueRef.current
      .then(async () => { await saveWorkspaceState(projectId, next); })
      .catch(() => { setSaveError("Не удалось сохранить рабочую область. Попробуйте ещё раз."); });
  }

  function persist(nextOrUpdater: WorkspaceLayout | ((current: WorkspaceLayout) => WorkspaceLayout)) {
    enqueueSave(updateLayout(nextOrUpdater));
  }

  useEffect(() => {
    if (!detail) return;
    if (!resizeReadyRef.current) {
      resizeReadyRef.current = true;
      return;
    }
    const resizeFields = { tree_width: layout.tree_width, group_weights: layout.group_weights };
    const timer = window.setTimeout(() => {
      const latest = layoutRef.current;
      enqueueSave({ ...latest, ...resizeFields });
    }, 400);
    return () => window.clearTimeout(timer);
  }, [layout.group_weights, layout.tree_width]);

  useEffect(() => {
    if (!layout.groups.some((group) => group.id === activeGroupId)) {
      setActiveGroupId(layout.groups[0]?.id ?? DEFAULT_LAYOUT.groups[0].id);
    }
  }, [activeGroupId, layout.groups]);

  const treeResult = useMemo(() => {
    try { return { tree: buildProgramTree(detail?.program.nodes ?? []), error: "" }; }
    catch (error) { return { tree: [], error: error instanceof Error ? error.message : "Некорректное дерево" }; }
  }, [detail?.program.nodes]);
  const flat = useMemo(() => flattenProgramTree(treeResult.tree), [treeResult.tree]);
  const studyNodes = flat.filter(isStudyNode);
  const selected = studyNodes.find((node) => node.id === layout.selected_node_id) ?? null;
  const selectedIndex = selected ? studyNodes.findIndex((node) => node.id === selected.id) : -1;
  const textbook = detail?.project.workspace_variant === "textbook";
  const availableTabs = allowedTabs(detail?.project ?? null);
  const filteredTree = useMemo(() => filterProgramTree(treeResult.tree, query), [treeResult.tree, query]);
  const answerStatusByNode = useMemo(() => {
    const map = new Map<string, ReferenceAnswerStatus>();
    for (const row of coverage?.rows ?? []) {
      if (row.answer_status) map.set(row.node_id, row.answer_status);
    }
    return map;
  }, [coverage]);

  useEffect(() => {
    if (!selected || textbook !== false) {
      setAnswerSlot(null);
      setAnswerError("");
      return;
    }
    const controller = new AbortController();
    setAnswerLoading(true);
    setAnswerSlot(null);
    setAnswerError("");
    getReferenceAnswer(projectId, selected.id, controller.signal)
      .then(setAnswerSlot)
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setAnswerError(error instanceof Error ? error.message : "Не удалось загрузить эталон");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setAnswerLoading(false);
      });
    return () => controller.abort();
  }, [projectId, selected?.id, textbook]);

  useEffect(() => {
    if (!selected || textbook !== false) {
      setAnswerAttachments([]);
      return;
    }
    const controller = new AbortController();
    setAnswerAttachments([]);
    listAnswerAttachments(projectId, selected.id, controller.signal)
      .then(setAnswerAttachments)
      .catch(() => undefined);
    return () => controller.abort();
  }, [projectId, selected?.id, textbook]);

  useEffect(() => {
    if (!selected || textbook) {
      setSourceBindings([]);
      setSourceResults([]);
      setSourceSearched(false);
      return;
    }
    setSourceQuery(selected.title);
    setSourceResults([]);
    setSourceSearched(false);
    setSourceNotice("");
    setSourceBindings([]);
    const controller = new AbortController();
    setSourceBindingsLoading(true);
    listBindings(projectId, { nodeId: selected.id }, controller.signal)
      .then(setSourceBindings)
      .catch(() => undefined)
      .finally(() => { if (!controller.signal.aborted) setSourceBindingsLoading(false); });
    return () => controller.abort();
  }, [projectId, selected?.id, textbook]);

  async function runSourceSearch() {
    if (!selected || !sourceQuery.trim()) return;
    setSourceSearching(true);
    setSourceNotice("");
    try {
      const results = await searchProjectMaterials(projectId, sourceQuery, { nodeId: selected.id });
      setSourceResults(results);
      setSourceSearched(true);
    } catch (caught) {
      setSourceNotice(caught instanceof Error ? caught.message : "Поиск не выполнен");
    } finally {
      setSourceSearching(false);
    }
  }

  async function bindSourceCandidate(result: SearchResultRead) {
    if (!selected) return;
    setSourceBusy(true);
    try {
      const created = await createBindings(projectId, {
        program_node_id: selected.id,
        fragment_ids: result.fragment_ids,
        mechanism: "search",
      });
      setSourceBindings((current) => [
        ...current,
        ...created.bindings.filter((binding) => !current.some((existing) => existing.id === binding.id)),
      ]);
      setSourceResults((current) => current.map((item) => item === result ? { ...item, already_bound: true } : item));
      setSourceNotice("Фрагмент привязан.");
      void bindings.refreshSummary();
    } catch (caught) {
      setSourceNotice(caught instanceof Error ? caught.message : "Не удалось привязать фрагмент");
    } finally {
      setSourceBusy(false);
    }
  }

  async function unbindSourceBinding(bindingId: string) {
    setSourceBusy(true);
    try {
      await removeBinding(projectId, bindingId);
      setSourceBindings((current) => current.filter((binding) => binding.id !== bindingId));
      setSourceResults((current) => current.map((item) => item.fragment_ids.includes(
        sourceBindings.find((binding) => binding.id === bindingId)?.fragment_id ?? "",
      ) ? { ...item, already_bound: false } : item));
      setSourceNotice("Привязка снята.");
      void bindings.refreshSummary();
    } catch (caught) {
      setSourceNotice(caught instanceof Error ? caught.message : "Не удалось снять привязку");
    } finally {
      setSourceBusy(false);
    }
  }

  function selectNode(nodeId: string) {
    persist((current) => ({ ...current, selected_node_id: nodeId }));
  }

  function toggleNode(nodeId: string) {
    persist((current) => {
      const next = new Set(current.expanded_node_ids);
      if (next.has(nodeId)) next.delete(nodeId); else next.add(nodeId);
      return { ...current, expanded_node_ids: [...next] };
    });
  }

  function selectRelative(offset: number) {
    const node = studyNodes[selectedIndex + offset];
    if (node) selectNode(node.id);
  }

  function setActiveTab(groupId: string, tab: WorkspaceTab) {
    persist((current) => ({
      ...current,
      groups: current.groups.map((group) => group.id === groupId ? { ...group, active_tab: tab } : group),
    }));
    setActiveGroupId(groupId);
  }

  function openTab(tab: WorkspaceTab, groupId = activeGroupId) {
    if (!availableTabs.includes(tab)) return;
    persist((current) => ({
      ...current,
      groups: current.groups.map((group) => group.id === groupId
        ? { ...group, tabs: group.tabs.includes(tab) ? group.tabs : [...group.tabs, tab], active_tab: tab }
        : group),
    }));
    setActiveGroupId(groupId);
  }

  function closeTab(groupId: string, tab: WorkspaceTab) {
    persist((latest) => ({
      ...latest,
      groups: latest.groups.map((group) => {
        if (group.id !== groupId) return group;
        const tabs = group.tabs.filter((item) => item !== tab);
        return { ...group, tabs, active_tab: group.active_tab === tab ? tabs.at(-1) ?? null : group.active_tab };
      }),
    }));
  }

  function addPanel() {
    if (layoutRef.current.groups.length >= 3) return;
    const id = `panel-${Date.now()}`;
    persist((current) => ({
      ...current,
      groups: [...current.groups, { id, tabs: [], active_tab: null }],
      group_weights: [...current.group_weights, 1],
    }));
    setActiveGroupId(id);
  }

  function closePanel(groupId: string) {
    const current = layoutRef.current;
    if (current.groups.length === 1) return;
    const index = current.groups.findIndex((group) => group.id === groupId);
    const groups = current.groups.filter((group) => group.id !== groupId);
    persist((latest) => ({
      ...latest,
      groups: latest.groups.filter((group) => group.id !== groupId),
      group_weights: latest.group_weights.filter((_, itemIndex) => itemIndex !== index),
    }));
    if (activeGroupId === groupId) setActiveGroupId(groups[Math.min(index, groups.length - 1)]?.id ?? DEFAULT_LAYOUT.groups[0].id);
  }

  function resizePanels(leftIndex: number, deltaPixels: number) {
    const width = editorGridRef.current?.clientWidth ?? 1;
    updateLayout((current) => ({
      ...current,
      group_weights: current.group_weights.map((weight, index, weights) => {
        if (index !== leftIndex && index !== leftIndex + 1) return weight;
        const pairTotal = (weights[leftIndex] ?? 1) + (weights[leftIndex + 1] ?? 1);
        const minWeight = Math.min(0.55, pairTotal / 2);
        const total = weights.reduce((sum, item) => sum + item, 0);
        const left = Math.min(
          pairTotal - minWeight,
          Math.max(minWeight, (weights[leftIndex] ?? 1) + (deltaPixels / width) * total),
        );
        return index === leftIndex ? left : pairTotal - left;
      }),
    }));
  }

  function renderTabStub(tab: Exclude<WorkspaceTab, "answer" | "source">) {
    const TabIcon = TAB_ICONS[tab];
    const copy = {
      lesson: "Уроки пока доступны только в прототипном разделе.",
      conspect: "Личный конспект пока не подключён к хранилищу.",
      history: "История появится после первых учебных активностей.",
      chat: "Учебниковый чат появится в своей вертикали.",
      summary: "Сводный конспект появится после сохранения личных конспектов.",
    }[tab];
    return <div className="workspace-empty-copy"><TabIcon size={26} /><h2>{tabLabel(tab, Boolean(textbook))}</h2><p>{copy}</p></div>;
  }

  function renderTabContent(tab: WorkspaceTab) {
    if (tab === "answer") return answerPanel();
    if (tab === "source") return sourcePanel();
    if (tab === "chat" && !textbook && projectId) {
      return (
        <ExamChatPanel
          projectId={projectId}
          node={selected}
          onAttemptsChanged={() => setAttemptsReloadKey((value) => value + 1)}
        />
      );
    }
    return renderTabStub(tab);
  }

  function openMenu(groupId: string, compact = false) {
    return <Menu label="Открыть в рабочей зоне" trigger={compact ? <IconButton label="Открыть в этой рабочей зоне"><Plus size={15} /></IconButton> : <Button variant="secondary"><Plus size={15} />Открыть<ChevronDown size={14} /></Button>} items={availableTabs.map((tab) => {
      const TabIcon = TAB_ICONS[tab];
      return { label: tabLabel(tab, Boolean(textbook)), icon: <TabIcon size={15} />, onSelect: () => openTab(tab, groupId) };
    })} />;
  }

  function answerPanel() {
    if (textbook) {
      return <div className="workspace-empty-panel"><FileText size={28} /><h2>Ответ пока не создан</h2><p>Учебные ответы появятся вместе со сценариями занятий.</p></div>;
    }
    if (!selected) {
      return <div className="workspace-empty-copy"><BookOpen size={26} /><h2>Выберите вопрос</h2><p>Эталон и история попыток появятся после выбора вопроса слева.</p></div>;
    }
    let referenceContent: ReactNode;
    if (answerLoading) referenceContent = <LoadingState label="Загружаем эталон" />;
    else if (answerError) referenceContent = <ErrorState title="Эталон не загрузился" message={answerError} />;
    else if (answerSlot?.answer?.is_active) {
      const answer = answerSlot.answer;
      const source = answer.source_label ? `Источник: ${answer.source_label}` : answer.origin_kind === "manual" ? "Добавлен вручную" : "Импортирован";
      const match = answer.match_method === "exact_title"
        ? `Сопоставлен по заголовку${answer.matched_title ? `: ${answer.matched_title}` : ""}`
        : "Сопоставлен вручную";
      const media: ReferenceAnswerMedia[] = [
        ...sourceBindings
          .filter((binding) => ["image", "table"].includes(binding.element_kind))
          .map((binding) => ({
            kind: "image" as const,
            source: "binding" as const,
            materialId: binding.material_id,
            label: binding.asset_label,
            url: materialFragmentAssetUrl(projectId, binding.material_id, binding.fragment_id),
            alt: `Изображение из «${binding.material_name}», стр. ${binding.page_number}`,
          })),
        ...answerAttachments.map((attachment) => ({
          kind: attachment.media_type.startsWith("image/") ? "image" as const : "file" as const,
          source: "attachment" as const,
          label: attachment.media_type.startsWith("image/")
            ? attachmentImageLabel(attachment.file_name, attachment.id)
            : attachment.file_name,
          url: answerAttachmentUrl(projectId, attachment.id),
          alt: attachment.file_name,
        })),
      ];
      const linkedSourceGroups = answerScanGroups(answer, sourceBindings);
      referenceContent = (
        <article className="workspace-reference-answer">
          <header><ReferenceAnswerBadge status={answerSlot.status} /><span>{source} · {match}</span></header>
          <h2>{selected.title}</h2>
          <SegmentedTabs
            className="workspace-reference-mode"
            label="Как показывать ответ"
            value={answerViewMode}
            onChange={setAnswerViewMode}
            tabs={[
              { value: "text", label: "Текст" },
              {
                value: "scans",
                label: "Страницы",
                disabled: linkedSourceGroups.length === 0,
                tooltip: linkedSourceGroups.length === 0
                  ? "У этого ответа нет страниц в документе: он вписан вручную или импортирован текстом"
                  : undefined,
              },
            ]}
          />
          {answerViewMode === "scans" && linkedSourceGroups.length > 0 ? (
            <AnswerScanPages projectId={projectId} groups={linkedSourceGroups} compact />
          ) : answer.source_only ? (
            <div className="workspace-reference-text">
              Ответ находится в источнике. Текстовая проверка недоступна.
            </div>
          ) : (
            <ReferenceAnswerContent
              text={answer.text}
              media={media}
              sourceMaterialId={answer.source_material_id}
            />
          )}
          <Link to={`/projects/${projectId}/coverage-map?topic=${selected.id}`}>Открыть и изменить эталон</Link>
        </article>
      );
    } else if (sourceBindings.length > 0) {
      referenceContent = (
        <div className="workspace-empty-copy is-answer-reference">
          <BookOpen size={26} />
          <h2>Для вопроса есть связанные материалы, но нет эталонного ответа</h2>
          <p>Откройте «Ответы», чтобы создать или сопоставить эталон.</p>
          <Link className="secondary-button" to={`/projects/${projectId}/coverage-map?topic=${selected.id}`}>Открыть ответы</Link>
        </div>
      );
    } else {
      referenceContent = (
        <div className="workspace-empty-copy is-answer-reference">
          <BookOpen size={26} />
          <h2>Ответ пока не найден</h2>
          <p>Добавьте эталон вручную или импортируйте общий текст с ответами.</p>
          <Link className="secondary-button" to={`/projects/${projectId}/coverage-map?topic=${selected.id}`}>Открыть эталоны</Link>
        </div>
      );
    }
    return (
      <div className="workspace-answer-tab">
        {referenceContent}
        <AttemptHistory
          projectId={projectId}
          nodeId={selected.id}
          refreshKey={attemptsReloadKey}
        />
      </div>
    );
  }

  function sourcePanel() {
    if (textbook) {
      return <div className="workspace-empty-copy"><FileText size={26} /><h2>Источник ещё не добавлен</h2><p>Привязка учебника к программе — отдельный раздел «Привязки», появится на этапе 7.</p></div>;
    }
    if (!selected) {
      return <div className="workspace-empty-copy"><FileText size={26} /><h2>Выберите тему</h2><p>Материал появится после выбора темы слева.</p></div>;
    }
    return (
      <div className="workspace-source-tab">
        {sourceNotice && <p className="workspace-source-tab-notice" role="status">{sourceNotice}</p>}
        {sourceBindingsLoading ? <LoadingState label="Загружаем привязки" /> : sourceBindings.length > 0 ? (
          <ul className="workspace-source-tab-list">
            {sourceBindings.map((binding) => (
              <li key={binding.id}>
                <Link to={`/projects/${projectId}/materials/${binding.material_id}?page=${binding.page_number}&focus=${binding.fragment_id}`}>
                  <p>{binding.text.length > 160 ? `${binding.text.slice(0, 160)}…` : binding.text}</p>
                  <small>{binding.material_name} · стр. {binding.page_number}</small>
                </Link>
                <QualityBadge quality={binding.quality} />
                <IconButton
                  label="Это не по теме"
                  disabled={sourceBusy}
                  onClick={() => void unbindSourceBinding(binding.id)}
                >
                  <Unlink size={14} />
                </IconButton>
              </li>
            ))}
          </ul>
        ) : (
          <div className="workspace-empty-copy">
            <FileText size={26} />
            <h2>Для этого вопроса материал ещё не привязан</h2>
            <p>Найдите подходящий фрагмент в материалах проекта или откройте Материалы, чтобы привязать вручную.</p>
            <div className="workspace-source-tab-empty-actions">
              <Button onClick={() => sourceSearchInput.current?.focus()}>Найти в материалах</Button>
              <Link className="secondary-button" to={`/projects/${projectId}/materials`}>Открыть материалы</Link>
            </div>
          </div>
        )}
        <form
          className="workspace-source-tab-search"
          onSubmit={(event) => { event.preventDefault(); void runSourceSearch(); }}
        >
          <label>
            <Search size={14} />
            <input
              ref={sourceSearchInput}
              type="search"
              value={sourceQuery}
              onChange={(event) => setSourceQuery(event.target.value)}
              placeholder="Найти в материалах проекта"
              aria-label="Найти в материалах проекта"
            />
          </label>
          <Button type="submit" disabled={sourceSearching || !sourceQuery.trim()}>Найти</Button>
        </form>
        {sourceSearching && <LoadingState label="Ищем" />}
        {sourceSearched && !sourceSearching && (
          sourceResults.length > 0 ? (
            <ul className="workspace-source-tab-results">
              {sourceResults.map((result) => {
                const alreadyBound = result.already_bound
                  || sourceBindings.some((binding) => result.fragment_ids.includes(binding.fragment_id));
                return (
                  <li key={result.fragment_ids.join(",")}>
                    <p>{renderHighlighted(result.text, result.highlights)}</p>
                    <small>
                      {result.material_name} · стр. {result.page_from === result.page_to ? result.page_from : `${result.page_from}–${result.page_to}`}
                    </small>
                    <QualityBadge quality={result.quality} />
                    <Button
                      variant="secondary"
                      disabled={alreadyBound || sourceBusy}
                      onClick={() => void bindSourceCandidate(result)}
                    >
                      {alreadyBound ? "Уже привязано" : "Привязать"}
                    </Button>
                  </li>
                );
              })}
            </ul>
          ) : <p className="workspace-list-empty">Ничего не найдено.</p>
        )}
      </div>
    );
  }

  function renderTree(nodes: ProgramTreeNode[]): ReactNode {
    return nodes.map((node) => {
      if (!node.is_in_current_program || node.is_archived) return null;
      const open = Boolean(query.trim()) || layout.expanded_node_ids.includes(node.id);
      if (node.node_type === "section") {
        return (
          <section className="workspace-tree-section" key={node.id}>
            <div className="workspace-section-row">
              <button type="button" className="workspace-section-toggle" aria-expanded={open} aria-label={open ? `Свернуть раздел «${node.title}»` : `Раскрыть раздел «${node.title}»`} onClick={() => toggleNode(node.id)}>{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</button>
              <span className="workspace-section-select"><span>{node.number}. {node.title}</span></span>
              <small>{flattenProgramTree(node.children).filter(isStudyNode).length}</small>
            </div>
            {open && <div className="workspace-question-list">{renderTree(node.children)}</div>}
          </section>
        );
      }
      const answerStatus = textbook ? undefined : answerStatusByNode.get(node.id) ?? "missing";
      const mark = marks[node.id];
      const row = (
        <button
          type="button"
          className={`workspace-question-row depth-${Math.min(Math.max(node.depth - 2, 0), 3)} ${selected?.id === node.id ? "is-active" : ""}`.trim()}
          onClick={() => selectNode(node.id)}
        >
          {answerStatus ? (
            <Tooltip label={referenceAnswerStatusLabel(answerStatus)}>
              <span className={`workspace-question-status ${answerDotClass(answerStatus)}`.trim()} aria-label={referenceAnswerStatusLabel(answerStatus)} />
            </Tooltip>
          ) : <span className="workspace-question-status" />}
          <span className="workspace-question-copy">
            <small>{textbook ? node.node_type === "subpoint" ? "Подпункт" : "Тема" : node.exam_kind === "task" ? "Задача" : "Вопрос"} {node.number}</small>
            <span>{node.title}</span>
          </span>
          <span className="workspace-question-signals">{mark && <PersonalMarkIcon mark={mark} />}</span>
        </button>
      );
      return (
        <div className="workspace-question-node" key={node.id}>
          <ContextMenu label={`Действия с «${node.title}»`} trigger={row} items={questionMenuItems(node)} />
          {node.children.length > 0 && <div className="workspace-question-list is-nested">{renderTree(node.children)}</div>}
        </div>
      );
    });
  }

  function questionMenuItems(node: ProgramTreeNode): ContextMenuItem[] {
    return [
      {
        label: "Открыть в Программе",
        icon: <ListTree size={14} />,
        onSelect: () => navigate(`/projects/${projectId}/program?topic=${node.id}`),
      },
      ...(!textbook ? [{
        label: "Открыть в Ответах",
        icon: <Target size={14} />,
        onSelect: () => navigate(`/projects/${projectId}/coverage-map?topic=${node.id}`),
      }] : []),
      {
        label: "Пометить",
        icon: <Tag size={14} />,
        items: [
          ...PERSONAL_MARK_OPTIONS.map((option) => ({
            label: option.label,
            icon: <option.icon size={14} />,
            onSelect: () => setMark(node.id, option.value),
          })),
          {
            label: "Без пометки",
            icon: <X size={14} />,
            disabled: !marks[node.id],
            onSelect: () => setMark(node.id, null),
          },
        ],
      },
    ];
  }

  if (loading) return <div className="screen"><LoadingState label="Загружаем рабочую область" placement="page" /></div>;
  if (loadError) {
    const notFound = loadError instanceof ProjectApiError && loadError.status === 404;
    return <div className="screen"><ErrorState title={notFound ? "Проект не найден" : undefined} message={notFound ? "Проверьте адрес или вернитесь к списку проектов." : loadError instanceof Error ? loadError.message : "Не удалось загрузить проект"} /><Button onClick={() => void load()}>Повторить загрузку</Button><Link className="secondary-button" to="/projects">К проектам</Link></div>;
  }
  if (!detail) return null;
  if (treeResult.error) return <div className="screen"><ErrorState title="Программа повреждена" message={treeResult.error} /></div>;

  if (!selected) {
    return <div className="screen"><EmptyState title="В программе нет тем для изучения"><p>Добавьте тему или верните её в текущую программу.</p><Link className="primary-button" to={`/projects/${projectId}/program`}>Открыть программу</Link></EmptyState></div>;
  }

  const deadline = daysUntil(detail.project.deadline);
  const editorGroups = layout.groups;
  const editorWeights = layout.group_weights;
  const editorColumns = editorGroups
    .map((_, index) => `${editorWeights[index] ?? 1}fr${index < editorGroups.length - 1 ? " 10px" : ""}`)
    .join(" ");

  return (
    <div className={`project-workspace ${textbook ? "is-textbook" : "is-exam"} ${studioExpanded ? "is-studio-expanded" : "is-studio-collapsed"}`} style={{ "--workspace-tree-width": `${layout.tree_width}px` } as CSSProperties}>
      <aside className="workspace-tree-panel">
        <header className="workspace-tree-head"><div className={`workspace-tree-title ${textbook ? "is-textbook" : ""}`}><Link className="workspace-back-button" to="/projects" aria-label="К проектам"><ArrowLeft size={15} /></Link><strong>{detail.project.name}</strong>{deadline !== null && <span className={`workspace-project-deadline is-${deadlineTone(deadline)}`} aria-label={deadline >= 0 ? `${deadline} дней до дедлайна` : `Дедлайн прошёл ${Math.abs(deadline)} дней назад`}><b>{deadline >= 0 ? deadline : Math.abs(deadline)}</b><small>{deadline >= 0 ? "дней" : "прошло"}</small></span>}</div></header>
        <div className="workspace-tree-tools"><label className="workspace-tree-search"><Search size={15} /><span className="sr-only">{textbook ? "Поиск по темам" : "Поиск по вопросам"}</span><input type="search" placeholder={textbook ? "Найти тему" : "Найти вопрос"} value={query} onChange={(event) => setQuery(event.target.value)} />{query && <button type="button" onClick={() => setQuery("")} aria-label="Очистить поиск"><X size={14} /></button>}</label><Tooltip label="Фильтры появятся вместе с разбором материалов"><span><IconButton label="Фильтры" disabled><Filter size={15} /></IconButton></span></Tooltip></div>
        <nav className="workspace-question-tree" aria-label={textbook ? "Программа" : "Вопросы экзамена"}>{filteredTree.length > 0 ? renderTree(filteredTree) : <p className="workspace-tree-empty">По запросу ничего не найдено.</p>}</nav>
        <ProjectNav projectId={projectId} textbook={textbook} modules={detail.project.enabled_modules} />
      </aside>

      <PanelResizeHandle
        className="workspace-tree-resize"
        label={`Изменить ширину дерева ${textbook ? "тем" : "вопросов"}`}
        value={layout.tree_width}
        min={260}
        max={460}
        onDelta={(delta) => updateLayout((current) => ({ ...current, tree_width: Math.round(Math.min(460, Math.max(260, current.tree_width + delta))) }))}
        onReset={() => updateLayout((current) => ({ ...current, tree_width: 320 }))}
      />

      <main className="workspace-main">
        <header className="workspace-question-bar"><div className="workspace-question-heading"><h1>{selected.title}</h1></div><div className="workspace-question-actions">{(textbook || (!sourceBindingsLoading && sourceBindings.length === 0)) && <div className={`workspace-material-notice ${textbook ? "is-textbook" : ""}`}><BookOpen size={15} /><span>{textbook ? "Материал появится после разбора" : "Ответы ещё не добавлены"}</span></div>}<div className="workspace-question-nav" aria-label="Переход между темами"><IconButton label="Предыдущая тема" disabled={selectedIndex <= 0} onClick={() => selectRelative(-1)}><ChevronLeft size={15} /></IconButton><span>{selectedIndex + 1} из {studyNodes.length}</span><IconButton label="Следующая тема" disabled={selectedIndex >= studyNodes.length - 1} onClick={() => selectRelative(1)}><ChevronRight size={15} /></IconButton></div><IconButton label="Разделить рабочую область" disabled={editorGroups.length >= 3} onClick={addPanel}><PanelsTopLeft size={15} /></IconButton></div></header>
        <div className="workspace-save-status" aria-live="polite">{saveError && <p className="inline-error" role="alert">{saveError}</p>}</div>
        <div className="workspace-editor-grid" ref={editorGridRef} style={{ gridTemplateColumns: editorColumns }}>
          {editorGroups.map((group, index) => {
            return <div className="workspace-editor-fragment" key={group.id}><section className={`workspace-editor-group ${activeGroupId === group.id ? "is-active" : ""}`.trim()} aria-label={`Рабочая зона ${index + 1}`} onClick={() => setActiveGroupId(group.id)}><div className="workspace-tabbar"><div className="workspace-tabs" role="tablist" aria-label={`Вкладки рабочей зоны ${index + 1}`}>{group.tabs.map((tab) => { const TabIcon = TAB_ICONS[tab]; const label = tabLabel(tab, Boolean(textbook)); return <div className={`workspace-tab ${group.active_tab === tab ? "is-active" : ""}`.trim()} key={tab}><button type="button" role="tab" aria-selected={group.active_tab === tab} onClick={() => setActiveTab(group.id, tab)}><TabIcon size={14} /><span>{label}</span></button><button type="button" className="workspace-tab-close" aria-label={`Закрыть вкладку «${label}»`} onClick={() => closeTab(group.id, tab)}><X size={13} /></button></div>; })}</div><div className="workspace-tabbar-actions">{openMenu(group.id, true)}{editorGroups.length > 1 && group.tabs.length === 0 && <IconButton label="Закрыть пустую рабочую зону" onClick={() => closePanel(group.id)}><PanelRightClose size={15} /></IconButton>}</div></div><div className="workspace-panel-content">{group.active_tab ? renderTabContent(group.active_tab) : <div className="workspace-empty-panel"><Plus size={28} /><h2>Рабочая зона пока пустая</h2><p>{textbook ? "Откройте здесь источник, конспект, историю или чат." : "Откройте здесь ответ, материал, конспект или чат."}</p><div>{openMenu(group.id)}{editorGroups.length > 1 && <Button variant="ghost" onClick={() => closePanel(group.id)}>Закрыть зону</Button>}</div></div>}</div></section>{index < editorGroups.length - 1 && <PanelResizeHandle className="workspace-panel-resize" label={`Изменить ширину рабочих зон ${index + 1} и ${index + 2}`} value={((layout.group_weights[index] ?? 1) / ((layout.group_weights[index] ?? 1) + (layout.group_weights[index + 1] ?? 1))) * 100} min={20} max={80} onDelta={(delta) => resizePanels(index, delta)} onReset={() => updateLayout((current) => ({ ...current, group_weights: current.groups.map(() => 1) }))} />}</div>;
          })}
        </div>
      </main>
      <StudioPanel expanded={studioExpanded} onExpandedChange={setStudioExpanded} modelsEnabled={false} sourceCount={null} topicTitle={selected.title} />
    </div>
  );
}
