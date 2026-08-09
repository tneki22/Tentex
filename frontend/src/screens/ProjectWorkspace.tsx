import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import {
  ArrowLeft,
  BookOpen,
  CalendarDays,
  CircleDashed,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FileText,
  Files,
  Filter,
  GraduationCap,
  History,
  Layers,
  ListTree,
  MessageSquare,
  NotebookPen,
  PanelRightClose,
  PanelsTopLeft,
  Plus,
  Search,
  Settings,
  Target,
  X,
} from "lucide-react";
import {
  getReferenceAnswer,
  getProject,
  ProjectApiError,
  saveWorkspaceState,
  type ProgramNodeRead,
  type ProjectDetail,
  type ProjectRead,
  type ReferenceAnswerSlot,
  type WorkspaceLayout,
  type WorkspaceTab,
} from "../api/projects";
import { ReferenceAnswerBadge } from "../components/domain";
import {
  Button,
  EmptyState,
  ErrorState,
  IconButton,
  LoadingState,
  Menu,
  PanelResizeHandle,
  Tooltip,
} from "../components/ui";
import {
  buildProgramTree,
  filterProgramTree,
  flattenProgramTree,
  type ProgramTreeNode,
} from "./programTree";
import { StudioPanel } from "./StudioPanel";

const DEFAULT_LAYOUT: WorkspaceLayout = {
  selected_node_id: null,
  expanded_node_ids: [],
  tree_width: 320,
  groups: [{ id: "main", tabs: ["answer", "source"], active_tab: "answer" }],
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

function isStudyNode(node: ProgramNodeRead): boolean {
  return STUDY_TYPES.has(node.node_type) && node.is_in_current_program && !node.is_archived;
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
  const fallbackTab = availableTabs[0] ?? "source";
  const groups = (source?.groups ?? DEFAULT_LAYOUT.groups).slice(0, 3).map((group, index) => {
    const tabs = group.tabs.filter((tab): tab is WorkspaceTab => availableTabs.includes(tab));
    const normalizedTabs = [...new Set(tabs)];
    const validTabs = normalizedTabs.length ? normalizedTabs : [fallbackTab];
    return {
      id: group.id || `panel-${index + 1}`,
      tabs: validTabs,
      active_tab: group.active_tab && validTabs.includes(group.active_tab) ? group.active_tab : validTabs[0],
    };
  });
  return {
    selected_node_id: selected,
    expanded_node_ids: [...new Set(source?.expanded_node_ids ?? visibleNodes.filter((node) => node.node_type === "section").map((node) => node.id))].filter((id) => currentIds.has(id)),
    tree_width: Math.min(460, Math.max(260, source?.tree_width ?? 320)),
    groups: groups.length ? groups : [{ id: "main", tabs: [fallbackTab], active_tab: fallbackTab }],
    group_weights: groups.map((_, index) => source?.group_weights[index] && source.group_weights[index] > 0 ? source.group_weights[index] : 1),
  };
}

export function ProjectWorkspace() {
  const { projectId = "" } = useParams();
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
  const [query, setQuery] = useState("");
  const [studioExpanded, setStudioExpanded] = useState(false);
  const [activeGroupId, setActiveGroupId] = useState(DEFAULT_LAYOUT.groups[0].id);
  const [pendingPanel, setPendingPanel] = useState<WorkspaceLayout["groups"][number] | null>(null);
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
      .catch((error) => { setSaveError(error instanceof Error ? error.message : "Не удалось сохранить раскладку"); });
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
    if (!layout.groups.some((group) => group.id === activeGroupId) && pendingPanel?.id !== activeGroupId) {
      setActiveGroupId(layout.groups[0]?.id ?? DEFAULT_LAYOUT.groups[0].id);
    }
  }, [activeGroupId, layout.groups, pendingPanel?.id]);

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
    if (pendingPanel?.id === groupId) {
      persist((current) => ({
        ...current,
        groups: [...current.groups, { ...pendingPanel, tabs: [tab], active_tab: tab }],
        group_weights: [...current.group_weights, 1],
      }));
      setPendingPanel(null);
      setActiveGroupId(groupId);
      return;
    }
    persist((current) => ({
      ...current,
      groups: current.groups.map((group) => group.id === groupId
        ? { ...group, tabs: group.tabs.includes(tab) ? group.tabs : [...group.tabs, tab], active_tab: tab }
        : group),
    }));
    setActiveGroupId(groupId);
  }

  function closeTab(groupId: string, tab: WorkspaceTab) {
    const current = layoutRef.current;
    const group = current.groups.find((item) => item.id === groupId);
    if (!group || (group.tabs.length === 1 && current.groups.length === 1)) return;
    if (group.tabs.length === 1 && group.tabs[0] === tab) {
      const index = current.groups.findIndex((item) => item.id === groupId);
      persist((latest) => ({
        ...latest,
        groups: latest.groups.filter((item) => item.id !== groupId),
        group_weights: latest.group_weights.filter((_, itemIndex) => itemIndex !== index),
      }));
      setPendingPanel({ id: groupId, tabs: [], active_tab: null });
      setActiveGroupId(groupId);
      return;
    }
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
    if (layout.groups.length + Number(Boolean(pendingPanel)) >= 3) return;
    const id = `panel-${Date.now()}`;
    setPendingPanel({ id, tabs: [], active_tab: null });
    setActiveGroupId(id);
  }

  function closePanel(groupId: string) {
    if (pendingPanel?.id === groupId) {
      setPendingPanel(null);
      setActiveGroupId(layout.groups.at(-1)?.id ?? DEFAULT_LAYOUT.groups[0].id);
      return;
    }
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
      chat: "Помощник будет подключён вместе со шлюзом моделей на этапе 7.",
      summary: "Сводный конспект появится после сохранения личных конспектов.",
    }[tab];
    return <div className="workspace-empty-copy"><TabIcon size={26} /><h2>{tabLabel(tab, Boolean(textbook))}</h2><p>{copy}</p>{tab === "chat" && <div className="workspace-chat-prompts"><Button variant="secondary" disabled>Объяснить проще</Button><Button variant="secondary" disabled>Проверить мой ответ</Button></div>}</div>;
  }

  function renderTabContent(tab: WorkspaceTab) {
    if (tab === "answer") return answerPanel();
    if (tab === "source") return <div className="workspace-empty-copy"><FileText size={26} /><h2>{textbook ? "Источник ещё не добавлен" : "Материалов пока нет"}</h2><p>Материалы и привязанные фрагменты появятся на этапе 5 и этапе 8.</p></div>;
    return renderTabStub(tab);
  }

  function openMenu(groupId: string, compact = false) {
    return <Menu label="Открыть в панели" trigger={compact ? <IconButton label="Открыть в этой панели"><Plus size={15} /></IconButton> : <Button variant="secondary"><Plus size={15} />Открыть<ChevronDown size={14} /></Button>} items={availableTabs.map((tab) => {
      const TabIcon = TAB_ICONS[tab];
      return { label: tabLabel(tab, Boolean(textbook)), icon: <TabIcon size={15} />, onSelect: () => openTab(tab, groupId) };
    })} />;
  }

  function answerPanel() {
    if (textbook) {
      return <div className="workspace-empty-panel"><FileText size={28} /><h2>Ответ пока не создан</h2><p>Учебные ответы появятся вместе со сценариями занятий.</p></div>;
    }
    if (answerLoading) return <LoadingState label="Загружаем эталон" />;
    if (answerError) return <ErrorState title="Эталон не загрузился" message={answerError} />;
    if (answerSlot?.answer?.is_active) {
      const answer = answerSlot.answer;
      const source = answer.source_label ? `Источник: ${answer.source_label}` : answer.origin_kind === "manual" ? "Добавлен вручную" : "Импортирован";
      const match = answer.match_method === "exact_title"
        ? `Сопоставлен по заголовку${answer.matched_title ? `: ${answer.matched_title}` : ""}`
        : "Сопоставлен вручную";
      return (
        <article className="workspace-reference-answer">
          <header><ReferenceAnswerBadge status={answerSlot.status} /><span>{source} · {match}</span></header>
          <h2>{selected?.title}</h2>
          <div className="workspace-reference-text">{answer.text}</div>
          <Link to={`/projects/${projectId}/coverage-map?topic=${selected?.id ?? ""}`}>Открыть и изменить эталон</Link>
        </article>
      );
    }
    return <div className="workspace-empty-copy"><BookOpen size={26} /><h2>Ответ пока не найден</h2><p>Добавьте эталон вручную или импортируйте общий текст с ответами.</p><Link className="secondary-button" to={`/projects/${projectId}/coverage-map?topic=${selected?.id ?? ""}`}>Открыть эталоны</Link></div>;
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
      return (
        <div className="workspace-question-node" key={node.id}>
          <button
            type="button"
            className={`workspace-question-row depth-${Math.min(Math.max(node.depth - 2, 0), 3)} ${selected?.id === node.id ? "is-active" : ""}`.trim()}
            onClick={() => selectNode(node.id)}
          >
            <span className="workspace-question-status" aria-label="Нет материала" />
            <span className="workspace-question-copy">
              <small>{textbook ? node.node_type === "subpoint" ? "Подпункт" : "Тема" : node.exam_kind === "task" ? "Задача" : "Вопрос"} {node.number}</small>
              <span>{node.title}</span>
            </span>
            <span className="workspace-question-signals"><CircleDashed size={14} aria-label="Нет материала" /></span>
          </button>
          {node.children.length > 0 && <div className="workspace-question-list is-nested">{renderTree(node.children)}</div>}
        </div>
      );
    });
  }

  if (loading) return <div className="screen"><LoadingState label="Загружаем рабочую область" /></div>;
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
  const modules = new Set(detail.project.enabled_modules);
  const editorGroups = pendingPanel ? [...layout.groups, pendingPanel] : layout.groups;
  const editorWeights = pendingPanel ? [...layout.group_weights, 1] : layout.group_weights;
  const editorColumns = editorGroups
    .map((_, index) => `${editorWeights[index] ?? 1}fr${index < editorGroups.length - 1 ? " 10px" : ""}`)
    .join(" ");

  return (
    <div className={`project-workspace ${textbook ? "is-textbook" : "is-exam"} ${studioExpanded ? "is-studio-expanded" : "is-studio-collapsed"}`} style={{ "--workspace-tree-width": `${layout.tree_width}px` } as CSSProperties}>
      <aside className="workspace-tree-panel">
        <header className="workspace-tree-head"><div className={`workspace-tree-title ${textbook ? "is-textbook" : ""}`}><Link className="workspace-back-button" to="/projects" aria-label="К проектам"><ArrowLeft size={15} /></Link><strong>{detail.project.name}</strong>{deadline !== null && <span className={`workspace-project-deadline is-${deadlineTone(deadline)}`} aria-label={deadline >= 0 ? `${deadline} дней до дедлайна` : `Дедлайн прошёл ${Math.abs(deadline)} дней назад`}><b>{deadline >= 0 ? deadline : Math.abs(deadline)}</b><small>{deadline >= 0 ? "дней" : "прошло"}</small></span>}</div></header>
        <div className="workspace-tree-tools"><label className="workspace-tree-search"><Search size={15} /><span className="sr-only">Поиск по программе</span><input type="search" aria-label={textbook ? "Поиск по темам" : "Поиск по вопросам"} placeholder={textbook ? "Найти тему" : "Найти вопрос"} value={query} onChange={(event) => setQuery(event.target.value)} />{query && <button type="button" onClick={() => setQuery("")} aria-label="Очистить поиск"><X size={14} /></button>}</label><Tooltip label="Фильтры появятся вместе с разбором материалов"><span><IconButton label="Фильтры" disabled><Filter size={15} /></IconButton></span></Tooltip></div>
        <nav className="workspace-question-tree" aria-label={textbook ? "Программа" : "Вопросы экзамена"}>{filteredTree.length > 0 ? renderTree(filteredTree) : <p className="workspace-tree-empty">По запросу ничего не найдено.</p>}</nav>
        <nav className="workspace-project-nav" aria-label="Разделы проекта"><Link className="workspace-project-link" to={`/projects/${projectId}/materials`}><Files size={15} /><span>Материалы</span></Link><Link className="workspace-project-link" to={`/projects/${projectId}/program`}><ListTree size={15} /><span>{textbook ? "Программа" : "Вопросы экзамена"}</span></Link>{!textbook && <Link className="workspace-project-link" to={`/projects/${projectId}/coverage-map`}><Target size={15} /><span>Карта эталонов</span></Link>}{modules.has("lessons") && <Link className="workspace-project-link" to={`/projects/${projectId}/lessons`}><GraduationCap size={15} /><span>Уроки</span></Link>}{modules.has("plan") && <Link className="workspace-project-link" to={`/projects/${projectId}/plan`}><CalendarDays size={15} /><span>План подготовки</span></Link>}{modules.has("cards") && <Link className="workspace-project-link" to={`/projects/${projectId}/cards`}><Layers size={15} /><span>Карточки</span></Link>}<Link className="workspace-project-link" to={`/projects/${projectId}/settings`}><Settings size={15} /><span>Настройки</span></Link></nav>
      </aside>

      <PanelResizeHandle
        className="workspace-tree-resize"
        label={`Изменить ширину дерева ${textbook ? "тем" : "вопросов"}`}
        value={layout.tree_width}
        min={260}
        max={460}
        onDelta={(delta) => updateLayout((current) => ({ ...current, tree_width: Math.min(460, Math.max(260, current.tree_width + delta)) }))}
        onReset={() => updateLayout((current) => ({ ...current, tree_width: 320 }))}
      />

      <main className="workspace-main">
        <header className="workspace-question-bar"><div className="workspace-question-heading"><h1>{selected.title}</h1></div><div className="workspace-question-actions"><div className={`workspace-material-notice ${textbook ? "is-textbook" : ""}`}><BookOpen size={15} /><span>{textbook ? "Материал появится после разбора" : "Материалы ещё не добавлены"}</span></div><div className="workspace-question-nav" aria-label="Переход между темами"><IconButton label="Предыдущая тема" disabled={selectedIndex <= 0} onClick={() => selectRelative(-1)}><ChevronLeft size={15} /></IconButton><span>{selectedIndex + 1} из {studyNodes.length}</span><IconButton label="Следующая тема" disabled={selectedIndex >= studyNodes.length - 1} onClick={() => selectRelative(1)}><ChevronRight size={15} /></IconButton></div>{openMenu(activeGroupId)}<IconButton label="Разделить рабочую область" disabled={editorGroups.length >= 3} onClick={addPanel}><PanelsTopLeft size={15} /></IconButton></div></header>
        {saveError && <p className="inline-error" role="alert">{saveError}</p>}
        <div className="workspace-editor-grid" ref={editorGridRef} style={{ gridTemplateColumns: editorColumns }}>
          {editorGroups.map((group, index) => {
            const canCloseTab = group.tabs.length > 1 || layout.groups.length > 1;
            return <div className="workspace-editor-fragment" key={group.id}><section className={`workspace-editor-group ${activeGroupId === group.id ? "is-active" : ""}`.trim()} aria-label={`Рабочая панель ${index + 1}`} onClick={() => setActiveGroupId(group.id)}><div className="workspace-tabbar"><div className="workspace-tabs" role="tablist" aria-label={`Вкладки панели ${index + 1}`}>{group.tabs.map((tab) => { const TabIcon = TAB_ICONS[tab]; const label = tabLabel(tab, Boolean(textbook)); const closeButton = <button type="button" className="workspace-tab-close" aria-label={`Закрыть вкладку «${label}»`} disabled={!canCloseTab} onClick={() => closeTab(group.id, tab)}><X size={13} /></button>; return <div className={`workspace-tab ${group.active_tab === tab ? "is-active" : ""}`.trim()} key={tab}><button type="button" role="tab" aria-selected={group.active_tab === tab} onClick={() => setActiveTab(group.id, tab)}><TabIcon size={14} /><span>{label}</span></button>{canCloseTab ? closeButton : <Tooltip label="В единственной панели должна остаться хотя бы одна вкладка"><span>{closeButton}</span></Tooltip>}</div>; })}</div><div className="workspace-tabbar-actions">{openMenu(group.id, true)}{editorGroups.length > 1 && group.tabs.length === 0 && <IconButton label="Закрыть пустую панель" onClick={() => closePanel(group.id)}><PanelRightClose size={15} /></IconButton>}</div></div><div className="workspace-panel-content">{group.active_tab ? renderTabContent(group.active_tab) : <div className="workspace-empty-panel"><PanelRightClose size={28} /><h2>Панель пока пустая</h2><p>{textbook ? "Откройте здесь другой инструмент темы: конспект, историю или чат." : "Откройте здесь ответ, материал, свой текст или чат."}</p><div>{openMenu(group.id)}{editorGroups.length > 1 && <Button variant="ghost" onClick={() => closePanel(group.id)}>Закрыть панель</Button>}</div></div>}</div></section>{index < layout.groups.length - 1 && <PanelResizeHandle className="workspace-panel-resize" label={`Изменить ширину панелей ${index + 1} и ${index + 2}`} value={((layout.group_weights[index] ?? 1) / ((layout.group_weights[index] ?? 1) + (layout.group_weights[index + 1] ?? 1))) * 100} min={20} max={80} onDelta={(delta) => resizePanels(index, delta)} onReset={() => updateLayout((current) => ({ ...current, group_weights: current.groups.map(() => 1) }))} />}</div>;
          })}
        </div>
      </main>
      <StudioPanel expanded={studioExpanded} onExpandedChange={setStudioExpanded} modelsEnabled={false} sourceCount={null} topicTitle={selected.title} />
    </div>
  );
}
