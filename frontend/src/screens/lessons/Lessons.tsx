import { Suspense, lazy, useCallback, useDeferredValue, useEffect, useMemo, useState, type CSSProperties } from "react";
import { ArrowLeft, FileDown, FileUp, FolderInput, GraduationCap, PanelRightClose, PanelRightOpen } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router";
import { createLessonFromSearch, createManualLesson, createQuickLesson, editLessonBlocks, getLesson, type FoundPage, type LessonBlockCommand } from "../../api/lessons";
import { getProject, ProjectApiError, type ProjectDetail } from "../../api/projects";
import { ProjectNav } from "../../components/domain/ProjectNav";
import { Button, EmptyState, ErrorState, IconButton, LoadingState, Menu, PanelResizeHandle } from "../../components/ui";
import { useLesson, useLessonsOverview } from "../../hooks/useLessons";
import { buildProgramTree, flattenProgramTree } from "../programTree";
import { LessonBuildDialog } from "./LessonBuildDialog";
import { LessonBulkTable } from "./LessonBulkTable";
import { LessonExportDialog } from "./LessonExportDialog";
import { LessonImportDialog } from "./LessonImportDialog";
import { insertPlacement, INSERT_AT_END, type LessonInsertPoint } from "./lessonBlocks";
import type { PanelTab } from "./LessonMaterialPanel";
import { LessonSectionOverview } from "./LessonSectionOverview";
import { LessonSourcesDialog } from "./LessonSourcesDialog";
import { LessonsTree } from "./LessonsTree";
import { LessonTopicPane } from "./LessonTopicPane";
import { errorText, isVisible, STUDY_TYPES } from "./lessonTree";

const LAYOUT_KEY = "tentex:lessons-layout";
const LessonMaterialPanel = lazy(() =>
  import("./LessonMaterialPanel").then((module) => ({ default: module.LessonMaterialPanel })),
);

interface LessonsLayout {
  tree: number;
  panel: number;
  panelOpen: boolean;
}

function readLayout(): LessonsLayout {
  const narrow = typeof window !== "undefined" && window.matchMedia?.("(max-width: 1100px)").matches;
  try {
    const stored = JSON.parse(window.localStorage.getItem(LAYOUT_KEY) ?? "null") as Partial<LessonsLayout> | null;
    return { tree: stored?.tree ?? 300, panel: stored?.panel ?? 360, panelOpen: narrow ? false : stored?.panelOpen ?? true };
  } catch {
    return { tree: 300, panel: 360, panelOpen: !narrow };
  }
}

const clamp = (value: number, min: number, max: number) => Math.round(Math.min(max, Math.max(min, value)));

/** Раздел «Уроки» — `/projects/:projectId/lessons?topic=&lesson=`. */
export function Lessons() {
  const { projectId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const [selection, setSelection] = useState<Set<string>>(new Set());
  const [layout, setLayout] = useState<LessonsLayout>(readLayout);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [rangesKey, setRangesKey] = useState(0);
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);
  const [insertPoint, setInsertPoint] = useState<LessonInsertPoint>(INSERT_AT_END);
  /** «Собрать урок с ИИ»: открытый диалог и, если сборка уже идёт, её задача. */
  const [build, setBuild] = useState<{ open: boolean; jobId: string | null }>({ open: false, jobId: null });
  /** Готовое предложение «Дополнить урок», открытое из «Фона». */
  const [proposalJobId, setProposalJobId] = useState<string | null>(null);
  /** Экспорт и импорт уроков — диалоги из меню в шапке раздела. */
  const [transfer, setTransfer] = useState<"export" | "import" | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    getProject(projectId, controller.signal).then(setDetail).catch((caught) => {
      if (!controller.signal.aborted) setError(caught);
    });
    return () => controller.abort();
  }, [projectId, attempt]);

  const available = Boolean(detail && detail.project.workspace_variant === "textbook" && detail.project.enabled_modules.includes("lessons"));
  const overview = useLessonsOverview(projectId, available);
  const lessons = useMemo(() => overview.data?.lessons ?? [], [overview.data]);

  // Дерево программы (сотни узлов у крупного учебника) рендерится в дереве
  // синхронно и надолго блокирует коммит — эффект загрузки обзора уроков
  // ждал бы того же кадра. useDeferredValue отпускает загрузку раньше дерева.
  const deferredNodes = useDeferredValue(detail?.program.nodes);
  const treeResult = useMemo(() => {
    try { return { tree: buildProgramTree(deferredNodes ?? []), error: "" }; }
    catch (caught) { return { tree: [], error: errorText(caught, "Программа повреждена") }; }
  }, [deferredNodes]);
  const flat = useMemo(() => flattenProgramTree(treeResult.tree).filter(isVisible), [treeResult.tree]);
  const studyNodes = useMemo(() => flat.filter((node) => STUDY_TYPES.has(node.node_type)), [flat]);

  const topicParam = searchParams.get("topic");
  const lessonParam = searchParams.get("lesson");
  const panelParam = searchParams.get("panel") === "search" ? "search" : undefined;
  const buildParam = searchParams.get("build") === "1";
  const jobParam = searchParams.get("job");
  const [panelTabRequest, setPanelTabRequest] = useState<{ tab: PanelTab; nonce: number } | null>(null);
  const active = flat.find((node) => node.id === topicParam) ?? flat.find((node) => STUDY_TYPES.has(node.node_type)) ?? flat[0] ?? null;
  const activeLessonId = lessonParam ?? lessons.find((item) => item.program_node_ids.includes(active?.id ?? "") && item.status !== "archived")?.id ?? null;
  const panelLesson = useLesson(projectId, activeLessonId);
  // Страницы открытого урока — для пометки «в уроке» в поиске и на страницах панели.
  const lessonPages = useMemo(() => {
    const keys = new Set<string>();
    for (const block of panelLesson.data?.blocks ?? []) {
      for (const ref of block.refs) {
        if (!ref.material_id || ref.role !== "content") continue;
        for (let page = ref.page_from; page <= ref.page_to; page += 1) keys.add(`${ref.material_id}#${page}`);
      }
    }
    return keys;
  }, [panelLesson.data]);

  // useLesson уже загружает урок при монтировании; повтор нужен только после правки.
  useEffect(() => { if (rangesKey > 0) panelLesson.refresh(); }, [rangesKey]); // eslint-disable-line react-hooks/exhaustive-deps

  /* Ссылка «Искать в материалах проекта» ведёт в поиск панели — скрытую панель
     она открывает, но сохранённую раскладку не трогает. */
  useEffect(() => {
    if (panelParam) setLayout((current) => (current.panelOpen ? current : { ...current, panelOpen: true }));
  }, [panelParam]);

  /* `?build=1` приходит из пустой вкладки «Урок», `?job=` — из панели «Фон».
     Оба открывают диалог один раз, после чего параметр снимается с адреса. */
  useEffect(() => {
    if (!buildParam && !jobParam) return;
    if (buildParam && !active) return;
    setBuild({ open: true, jobId: jobParam });
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.delete("build");
      next.delete("job");
      return next;
    }, { replace: true });
  }, [buildParam, jobParam, active, setSearchParams]);

  const updateLayout = useCallback((change: (current: LessonsLayout) => LessonsLayout) => {
    setLayout((current) => {
      const next = change(current);
      try { window.localStorage.setItem(LAYOUT_KEY, JSON.stringify(next)); } catch { /* только в памяти */ }
      return next;
    });
  }, []);

  function navigateTo(topicId: string, lessonId: string | null = null) {
    chooseBlock(null);
    const next = new URLSearchParams();
    next.set("topic", topicId);
    if (lessonId) next.set("lesson", lessonId);
    setSearchParams(next);
  }

  async function createLesson(materialIds?: string[]) {
    if (!active) return;
    setBusy(true);
    setActionError("");
    try {
      const result = await createQuickLesson(projectId, active.id, materialIds);
      setSourcesOpen(false);
      overview.refresh();
      setRangesKey((value) => value + 1);
      navigateTo(active.id, result.lesson.id);
    } catch (caught) {
      setActionError(errorText(caught, "Не удалось создать урок"));
    } finally {
      setBusy(false);
    }
  }

  async function createManual() {
    if (!active) return;
    setBusy(true);
    setActionError("");
    try {
      const result = await createManualLesson(projectId, active.id);
      overview.refresh();
      navigateTo(active.id, result.lesson.id);
    } catch (caught) {
      setActionError(errorText(caught, "Не удалось создать урок"));
    } finally { setBusy(false); }
  }

  /**
   * Добавление из правой панели: место вставки выбирается явно, а следующий
   * кусок встаёт за только что добавленным — подряд собранный урок сохраняет
   * порядок, в котором его собирали.
   */
  async function addFromPanel(command: Omit<LessonBlockCommand, "expected_revision">): Promise<boolean> {
    if (!activeLessonId) return false;
    setBusy(true);
    setActionError("");
    try {
      const current = await getLesson(projectId, activeLessonId);
      const result = await editLessonBlocks(projectId, activeLessonId, {
        ...command, ...insertPlacement(insertPoint, current.blocks),
        expected_revision: current.revision,
      });
      const known = new Set(current.blocks.map((block) => block.id));
      const added = result.lesson.blocks.find((block) => !known.has(block.id));
      if (added) chooseInsertPoint({ kind: "after", blockId: added.id });
      overview.refresh();
      setRangesKey((value) => value + 1);
      return true;
    } catch (caught) {
      setActionError(errorText(caught, "Не удалось добавить источник"));
      return false;
    } finally { setBusy(false); }
  }

  /** «Урок из найденного»: отмеченные в поиске страницы — новым черновиком или в конец урока. */
  async function addFound(pages: FoundPage[]): Promise<boolean> {
    if (!active || pages.length === 0) return false;
    setBusy(true);
    setActionError("");
    try {
      const current = activeLessonId ? await getLesson(projectId, activeLessonId) : null;
      const result = await createLessonFromSearch(projectId, {
        program_node_id: active.id,
        pages,
        ...(current ? { lesson_id: current.id, expected_revision: current.revision } : {}),
      });
      overview.refresh();
      setRangesKey((value) => value + 1);
      navigateTo(active.id, result.lesson.id);
      return true;
    } catch (caught) {
      setActionError(errorText(caught, "Не удалось собрать урок из найденного"));
      return false;
    } finally { setBusy(false); }
  }

  /** Готовый модельный черновик открывается в своей теме, даже если диалог звали из «Фона». */
  async function openBuilt(lessonId: string) {
    overview.refresh();
    setRangesKey((value) => value + 1);
    try {
      const lesson = await getLesson(projectId, lessonId);
      const topicId = lesson.topics[0]?.program_node_id ?? active?.id;
      if (topicId) navigateTo(topicId, lessonId);
    } catch (caught) {
      setActionError(errorText(caught, "Урок собран, но не открылся"));
    }
  }

  /** Выбранный блок и место вставки — одно и то же: выбор в уроке виден в панели и наоборот. */
  function chooseBlock(blockId: string | null) {
    setSelectedBlockId(blockId);
    setInsertPoint(blockId ? { kind: "after", blockId } : INSERT_AT_END);
  }

  function chooseInsertPoint(point: LessonInsertPoint) {
    setInsertPoint(point);
    setSelectedBlockId(point.kind === "after" ? point.blockId : null);
  }

  if (error) {
    const notFound = error instanceof ProjectApiError && error.status === 404;
    return <div className="screen screen-error-state"><ErrorState title={notFound ? "Проект не найден" : "Уроки не загрузились"} message={errorText(error, "Не удалось загрузить проект")} /><Button variant="secondary" onClick={() => setAttempt((value) => value + 1)}>Повторить</Button><Link className="secondary-button" to="/projects">К проектам</Link></div>;
  }
  if (!detail) return <div className="screen"><LoadingState label="Загружаем проект" placement="page" /></div>;

  const textbook = detail.project.workspace_variant === "textbook";
  if (!available) {
    return (
      <div className="program-screen">
        <aside className="project-side-panel">
          <header className="project-side-title"><Link className="workspace-back-button" to={`/projects/${projectId}`} aria-label="Вернуться в рабочую область"><ArrowLeft size={15} /></Link><strong>{detail.project.name}</strong></header>
          <ProjectNav projectId={projectId} active="lessons" textbook={textbook} modules={detail.project.enabled_modules} className="project-side-nav" />
        </aside>
        <main className="program-main">
          <EmptyState title="Уроки недоступны в этом проекте" icon={<GraduationCap size={28} />}>
            <p>{textbook ? "Раздел «Уроки» выключен в параметрах проекта." : "Уроки собираются из учебника: они есть только в учебниковом проекте. В экзаменационном проекте материал читается во вкладке «Источник»."}</p>
            <Link className="primary-button" to={`/projects/${projectId}`}>В рабочую область</Link>
          </EmptyState>
        </main>
      </div>
    );
  }

  const panelToggle = (
    <IconButton label={layout.panelOpen ? "Скрыть материал для урока" : "Показать материал для урока"} onClick={() => updateLayout((current) => ({ ...current, panelOpen: !current.panelOpen }))}>
      {layout.panelOpen ? <PanelRightClose size={15} /> : <PanelRightOpen size={15} />}
    </IconButton>
  );

  const selectedTopics = flat.filter((node) => selection.has(node.id));
  let center;
  let isTopicPane = false;
  if (treeResult.error) center = <ErrorState title="Программа повреждена" message={treeResult.error} />;
  else if (!active) {
    center = (
      <EmptyState title="Программа пока пуста" icon={<GraduationCap size={28} />}>
        <p>Уроки собираются по темам программы. Составьте её в разделе «Программа»: из оглавления, вручную или с ИИ.</p>
        <Link className="primary-button" to={`/projects/${projectId}/program`}>Открыть программу</Link>
      </EmptyState>
    );
  } else if (overview.error) {
    center = <><ErrorState message={errorText(overview.error, "Уроки не загрузились")} /><Button variant="secondary" onClick={overview.refresh}>Повторить</Button></>;
  } else if (!overview.data) center = <LoadingState label="Загружаем уроки" />;
  else if (selectedTopics.length > 0) {
    center = (
      <LessonBulkTable
        projectId={projectId}
        topics={selectedTopics}
        lessons={lessons}
        onClear={() => setSelection(new Set())}
        onChanged={() => { overview.refresh(); setRangesKey((value) => value + 1); }}
        onOpenLesson={(nodeId, lessonId) => { setSelection(new Set()); navigateTo(nodeId, lessonId); }}
      />
    );
  }
  else if (active.node_type === "section") {
    center = <LessonSectionOverview section={active} lessons={lessons} onOpenTopic={(id) => navigateTo(id)} onSelectTopics={(ids) => setSelection(new Set(ids))} />;
  } else {
    center = (
      <LessonTopicPane
        projectId={projectId}
        topic={active}
        studyNodes={studyNodes}
        lessons={lessons}
        lessonId={lessonParam}
        busy={busy}
        onSelectLesson={(id) => navigateTo(active.id, id)}
        onQuickLesson={() => void createLesson()}
        onFromSources={() => setSourcesOpen(true)}
        onManual={() => void createManual()}
        onBuildWithAi={() => setBuild({ open: true, jobId: null })}
        onChanged={() => { overview.refresh(); setRangesKey((value) => value + 1); }}
        refreshKey={rangesKey}
        selectedBlockId={selectedBlockId}
        onSelectBlock={chooseBlock}
        panelToggle={panelToggle}
        actionError={actionError}
        proposalJobId={proposalJobId}
        onFindInMaterials={() => {
          updateLayout((current) => (current.panelOpen ? current : { ...current, panelOpen: true }));
          setPanelTabRequest((current) => ({ tab: "search", nonce: (current?.nonce ?? 0) + 1 }));
        }}
      />
    );
    isTopicPane = true;
  }

  const columns = layout.panelOpen
    ? `${layout.tree}px 10px minmax(0, 1fr) 10px ${layout.panel}px`
    : `${layout.tree}px 10px minmax(0, 1fr)`;

  return (
    <div className="lessons-screen" style={{ gridTemplateColumns: columns } as CSSProperties}>
      <aside className="workspace-tree-panel lessons-tree-panel">
        <header className="workspace-tree-head">
          <div className="workspace-tree-title is-textbook has-actions">
            <Link className="workspace-back-button" to={`/projects/${projectId}${active ? `?topic=${active.id}` : ""}`} aria-label="Вернуться в рабочую область"><ArrowLeft size={15} /></Link>
            <strong>{detail.project.name}</strong>
            <Menu
              label="Экспорт и импорт уроков"
              tooltip="Экспорт и импорт уроков"
              trigger={<IconButton label="Экспорт и импорт уроков" hideNativeTitle><FolderInput size={15} /></IconButton>}
              items={[
                { label: "Экспорт уроков…", icon: <FileDown size={14} />, onSelect: () => setTransfer("export") },
                { label: "Импорт из файла…", icon: <FileUp size={14} />, onSelect: () => setTransfer("import") },
              ]}
            />
          </div>
        </header>
        <LessonsTree
          tree={treeResult.tree}
          lessons={lessons}
          activeNodeId={selectedTopics.length > 0 ? null : active?.id ?? null}
          selection={selection}
          onSelectNode={(id) => { setSelection(new Set()); navigateTo(id); }}
          onSelectionChange={setSelection}
        />
        <ProjectNav projectId={projectId} active="lessons" textbook={textbook} modules={detail.project.enabled_modules} />
      </aside>
      <PanelResizeHandle
        className="lessons-resize"
        label="Изменить ширину дерева тем"
        value={layout.tree}
        min={240}
        max={440}
        onDelta={(delta) => updateLayout((current) => ({ ...current, tree: clamp(current.tree + delta, 240, 440) }))}
        onReset={() => updateLayout((current) => ({ ...current, tree: 300 }))}
      />
      <main className="lessons-center">
        {!isTopicPane && (
          <div className="lessons-center-bar">
            {actionError && <p className="inline-error" role="alert">{actionError}</p>}
            {panelToggle}
          </div>
        )}
        {center}
      </main>
      {layout.panelOpen && (
        <>
          <PanelResizeHandle
            className="lessons-resize"
            label="Изменить ширину панели материала"
            value={layout.panel}
            /* Уже 320px четыре вкладки панели не помещаются в один ряд и начинают прокручиваться. */
            min={320}
            max={560}
            onDelta={(delta) => updateLayout((current) => ({ ...current, panel: clamp(current.panel - delta, 320, 560) }))}
            onReset={() => updateLayout((current) => ({ ...current, panel: 360 }))}
          />
          <aside className="lessons-panel">
            <Suspense fallback={<LoadingState label="Открываем материал" />}>
              <LessonMaterialPanel
                projectId={projectId}
                topic={selectedTopics.length > 0 ? null : active}
                busy={busy}
                refreshKey={rangesKey}
                onCreateFromRange={(materialId) => void createLesson([materialId])}
                lessonId={activeLessonId}
                lessonPages={lessonPages}
                blocks={panelLesson.data?.id === activeLessonId ? panelLesson.data.blocks : []}
                insertPoint={insertPoint}
                onInsertPointChange={chooseInsertPoint}
                onAdd={addFromPanel}
                onUseFound={addFound}
                initialTab={panelParam}
                tabRequest={panelTabRequest}
              />
            </Suspense>
          </aside>
        </>
      )}
      <LessonExportDialog
        projectId={projectId}
        open={transfer === "export"}
        onOpenChange={(open) => setTransfer(open ? "export" : null)}
        lessons={lessons}
        topics={studyNodes}
        currentLessonId={activeLessonId}
      />
      <LessonImportDialog
        projectId={projectId}
        open={transfer === "import"}
        onOpenChange={(open) => setTransfer(open ? "import" : null)}
        topics={studyNodes}
        onImported={() => { overview.refresh(); setRangesKey((value) => value + 1); }}
        onOpenLesson={(topicId, lessonId) => navigateTo(topicId, lessonId)}
      />
      {active && (build.jobId || active.node_type !== "section") && (
        <LessonBuildDialog
          open={build.open}
          onOpenChange={(open) => setBuild((current) => ({ open, jobId: open ? current.jobId : null }))}
          projectId={projectId}
          topic={active}
          jobId={build.jobId}
          onBuilt={(lessonId) => void openBuilt(lessonId)}
          onProposal={(jobId, lessonId) => { setProposalJobId(jobId); void openBuilt(lessonId); }}
        />
      )}
      {active && active.node_type !== "section" && (
        <LessonSourcesDialog
          projectId={projectId}
          nodeId={active.id}
          topicTitle={active.title}
          open={sourcesOpen}
          busy={busy}
          onOpenChange={setSourcesOpen}
          onCreate={(ids) => void createLesson(ids)}
        />
      )}
    </div>
  );
}
