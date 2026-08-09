import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import {
  ArrowLeft,
  BookOpen,
  CircleDashed,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FileText,
  ListTree,
  PanelsTopLeft,
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
  PanelResizeHandle,
} from "../components/ui";
import {
  buildProgramTree,
  filterProgramTree,
  flattenProgramTree,
  type ProgramTreeNode,
} from "./programTree";

const DEFAULT_LAYOUT: WorkspaceLayout = {
  selected_node_id: null,
  expanded_node_ids: [],
  tree_width: 320,
  groups: [{ id: "main", tabs: ["answer", "source"], active_tab: "answer" }],
  group_weights: [1],
};

const STUDY_TYPES = new Set(["topic", "subpoint"]);

function isStudyNode(node: ProgramNodeRead): boolean {
  return STUDY_TYPES.has(node.node_type) && node.is_in_current_program && !node.is_archived;
}

function sanitizeLayout(
  source: WorkspaceLayout | undefined,
  nodes: ProgramNodeRead[],
  preferredNodeId: string | null,
): WorkspaceLayout {
  const currentIds = new Set(nodes.filter((node) => node.is_in_current_program && !node.is_archived).map((node) => node.id));
  const studyIds = new Set(nodes.filter(isStudyNode).map((node) => node.id));
  const firstStudyId = nodes.find(isStudyNode)?.id ?? null;
  const selected = preferredNodeId && studyIds.has(preferredNodeId)
    ? preferredNodeId
    : source?.selected_node_id && studyIds.has(source.selected_node_id)
      ? source.selected_node_id
      : firstStudyId;
  const groups = (source?.groups ?? DEFAULT_LAYOUT.groups).slice(0, 3).map((group, index) => {
    const tabs = group.tabs.filter((tab): tab is WorkspaceTab => tab === "answer" || tab === "source");
    const normalizedTabs = tabs.length ? [...new Set(tabs)] : ["answer" as WorkspaceTab];
    return {
      id: group.id || `panel-${index + 1}`,
      tabs: normalizedTabs,
      active_tab: group.active_tab && normalizedTabs.includes(group.active_tab) ? group.active_tab : normalizedTabs[0],
    };
  });
  return {
    selected_node_id: selected,
    expanded_node_ids: [...new Set(source?.expanded_node_ids ?? [])].filter((id) => currentIds.has(id)),
    tree_width: Math.min(460, Math.max(260, source?.tree_width ?? 320)),
    groups: groups.length ? groups : DEFAULT_LAYOUT.groups,
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
  const queueRef = useRef<Promise<void>>(Promise.resolve());
  const resizeReadyRef = useRef(false);

  async function load(signal?: AbortSignal) {
    setLoading(true);
    setLoadError(null);
    try {
      const next = await getProject(projectId, signal);
      const sanitized = sanitizeLayout(next.workspace_state?.layout, next.program.nodes, preferredTopic);
      setDetail(next);
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

  function persist(next: WorkspaceLayout) {
    setLayout(next);
    setSaveError("");
    queueRef.current = queueRef.current
      .then(async () => { await saveWorkspaceState(projectId, next); })
      .catch((error) => { setSaveError(error instanceof Error ? error.message : "Не удалось сохранить раскладку"); });
  }

  useEffect(() => {
    if (!detail) return;
    if (!resizeReadyRef.current) {
      resizeReadyRef.current = true;
      return;
    }
    const timer = window.setTimeout(() => {
      persist({ ...layout });
    }, 400);
    return () => window.clearTimeout(timer);
  }, [layout.tree_width]);

  const treeResult = useMemo(() => {
    try { return { tree: buildProgramTree(detail?.program.nodes ?? []), error: "" }; }
    catch (error) { return { tree: [], error: error instanceof Error ? error.message : "Некорректное дерево" }; }
  }, [detail?.program.nodes]);
  const flat = useMemo(() => flattenProgramTree(treeResult.tree), [treeResult.tree]);
  const studyNodes = flat.filter(isStudyNode);
  const selected = studyNodes.find((node) => node.id === layout.selected_node_id) ?? null;
  const selectedIndex = selected ? studyNodes.findIndex((node) => node.id === selected.id) : -1;
  const textbook = detail?.project.workspace_variant === "textbook";
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
    persist({ ...layout, selected_node_id: nodeId });
  }

  function toggleNode(nodeId: string) {
    const next = new Set(layout.expanded_node_ids);
    if (next.has(nodeId)) next.delete(nodeId); else next.add(nodeId);
    persist({ ...layout, expanded_node_ids: [...next] });
  }

  function selectRelative(offset: number) {
    const node = studyNodes[selectedIndex + offset];
    if (node) selectNode(node.id);
  }

  function setActiveTab(groupId: string, tab: WorkspaceTab) {
    persist({
      ...layout,
      groups: layout.groups.map((group) => group.id === groupId ? { ...group, active_tab: tab } : group),
    });
  }

  function addPanel() {
    if (layout.groups.length >= 3) return;
    const id = `panel-${Date.now()}`;
    persist({
      ...layout,
      groups: [...layout.groups, { id, tabs: ["answer", "source"], active_tab: "answer" }],
      group_weights: [...layout.group_weights, 1],
    });
  }

  function closePanel(groupId: string) {
    if (layout.groups.length === 1) return;
    const index = layout.groups.findIndex((group) => group.id === groupId);
    persist({
      ...layout,
      groups: layout.groups.filter((group) => group.id !== groupId),
      group_weights: layout.group_weights.filter((_, itemIndex) => itemIndex !== index),
    });
  }

  function answerPanel() {
    if (textbook) {
      return <div className="workspace-empty-panel"><FileText size={28} /><h2>Ответ пока не создан</h2><p>Учебные ответы появятся вместе со сценариями занятий.</p></div>;
    }
    if (answerLoading) return <LoadingState label="Загружаем эталон" />;
    if (answerError) return <ErrorState title="Эталон не загрузился" message={answerError} />;
    if (answerSlot?.answer?.is_active) {
      return (
        <article className="workspace-reference-answer">
          <header><ReferenceAnswerBadge status={answerSlot.status} /><span>{answerSlot.answer.origin_kind === "import" ? "Импортирован" : "Добавлен вручную"}{answerSlot.answer.source_label ? ` · Источник: ${answerSlot.answer.source_label}` : ""}</span></header>
          <div className="workspace-reference-text">{answerSlot.answer.text}</div>
          <Link to={`/projects/${projectId}/coverage-map?topic=${selected?.id ?? ""}`}>Открыть и изменить эталон</Link>
        </article>
      );
    }
    return <div className="workspace-empty-panel"><FileText size={28} /><h2>Эталонного ответа пока нет</h2><p>Добавьте его вручную или импортируйте общий текст с ответами.</p><Link className="secondary-button" to={`/projects/${projectId}/coverage-map?topic=${selected?.id ?? ""}`}>Добавить эталон</Link></div>;
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

  return (
    <div className={`project-workspace ${textbook ? "is-textbook" : "is-exam"}`} style={{ "--workspace-tree-width": `${layout.tree_width}px` } as CSSProperties}>
      <aside className="workspace-tree-panel">
        <header className="workspace-tree-head"><div className="workspace-tree-title"><Link className="workspace-back-button" to="/projects" aria-label="К проектам"><ArrowLeft size={15} /></Link><strong>{detail.project.name}</strong></div></header>
        <div className="workspace-tree-tools is-search-only"><label className="workspace-tree-search"><Search size={15} /><span className="sr-only">Поиск по программе</span><input type="search" aria-label={textbook ? "Поиск по темам" : "Поиск по вопросам"} placeholder={textbook ? "Найти тему" : "Найти вопрос"} value={query} onChange={(event) => setQuery(event.target.value)} />{query && <button type="button" onClick={() => setQuery("")} aria-label="Очистить поиск"><X size={14} /></button>}</label></div>
        <nav className="workspace-question-tree" aria-label={textbook ? "Программа" : "Вопросы экзамена"}>{filteredTree.length > 0 ? renderTree(filteredTree) : <p className="workspace-tree-empty">По запросу ничего не найдено.</p>}</nav>
        <nav className="workspace-project-nav" aria-label="Разделы проекта"><Link className="workspace-project-link" to={`/projects/${projectId}/program`}><ListTree size={15} /><span>{textbook ? "Программа" : "Вопросы экзамена"}</span></Link>{!textbook && <Link className="workspace-project-link" to={`/projects/${projectId}/coverage-map`}><Target size={15} /><span>Карта эталонов</span></Link>}<Link className="workspace-project-link" to={`/projects/${projectId}/settings`}><Settings size={15} /><span>Настройки</span></Link><span className="workspace-project-link is-disabled" title="Материалы появятся на этапе 5"><BookOpen size={15} /><span>Материалы · этап 5</span></span><span className="workspace-project-link is-disabled" title="Карточки и План появятся на этапе 9"><PanelsTopLeft size={15} /><span>План и карточки · этап 9</span></span></nav>
      </aside>

      <PanelResizeHandle
        className="workspace-tree-resize"
        label={`Изменить ширину дерева ${textbook ? "тем" : "вопросов"}`}
        value={layout.tree_width}
        min={260}
        max={460}
        onDelta={(delta) => setLayout((current) => ({ ...current, tree_width: Math.min(460, Math.max(260, current.tree_width + delta)) }))}
        onReset={() => setLayout((current) => ({ ...current, tree_width: 320 }))}
      />

      <main className="workspace-main">
        <header className="workspace-question-bar"><div className="workspace-question-heading"><h1>{selected.title}</h1></div><div className="workspace-question-actions"><div className="workspace-question-nav" aria-label="Переход между темами"><IconButton label="Предыдущая тема" disabled={selectedIndex <= 0} onClick={() => selectRelative(-1)}><ChevronLeft size={15} /></IconButton><span>{selectedIndex + 1} из {studyNodes.length}</span><IconButton label="Следующая тема" disabled={selectedIndex >= studyNodes.length - 1} onClick={() => selectRelative(1)}><ChevronRight size={15} /></IconButton></div><IconButton label="Разделить рабочую область" disabled={layout.groups.length >= 3} onClick={addPanel}><PanelsTopLeft size={15} /></IconButton></div></header>
        {saveError && <p className="inline-error" role="alert">{saveError}</p>}
        <div className="workspace-editor-grid" style={{ gridTemplateColumns: layout.group_weights.map((weight) => `${weight}fr`).join(" ") }}>
          {layout.groups.map((group, index) => <section className="workspace-editor-group" key={group.id} aria-label={`Рабочая панель ${index + 1}`}><div className="workspace-tabbar"><div className="workspace-tabs" role="tablist" aria-label={`Вкладки панели ${index + 1}`}>{group.tabs.map((tab) => <div className={`workspace-tab ${group.active_tab === tab ? "is-active" : ""}`.trim()} key={tab}><button type="button" role="tab" aria-selected={group.active_tab === tab} onClick={() => setActiveTab(group.id, tab)}>{tab === "answer" ? <FileText size={14} /> : <BookOpen size={14} />}<span>{tab === "answer" ? "Ответ" : textbook ? "Источник" : "Материал"}</span></button></div>)}</div>{layout.groups.length > 1 && <IconButton label="Закрыть панель" onClick={() => closePanel(group.id)}><X size={14} /></IconButton>}</div><div className="workspace-panel-content">{group.active_tab === "answer" ? answerPanel() : <div className="workspace-empty-panel"><BookOpen size={28} /><h2>{textbook ? "Источник ещё не добавлен" : "Материалов пока нет"}</h2><p>Загрузка и привязка материалов появятся на этапе 5.</p></div>}</div></section>)}
        </div>
      </main>
    </div>
  );
}
