import {
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  CreditCard,
  ChevronLeft,
  ChevronRight,
  FileImage,
  FileText,
  Globe,
  GripVertical,
  Files,
  Info,
  Link2,
  LibraryBig,
  ListTree,
  Maximize2,
  Minimize2,
  Plus,
  Search,
  ScanSearch,
  Sparkles,
  Trash2,
  Undo2,
  Unlink,
  Upload,
  Video,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { getBackgroundJob } from "../api/backgroundJobs";
import type { BindingFragmentRead, HeadingSuggestion, NodeBindingSummary } from "../api/bindings";
import { listBindings, resolveAnswersHeading } from "../api/bindings";
import {
  getMaterialPage,
  getLibraryMaterial,
  importMaterialReferenceAnswers,
  materialFragmentAssetUrl,
  searchLibraryMaterial,
  updateMaterialPageText,
} from "../api/materials";
import type {
  MaterialBlockRead,
  MaterialFragmentRead,
  MaterialPageRead,
  MaterialPurpose,
  MaterialRead,
  LibraryMaterialDetailRead,
  MaterialUpdateCommand,
  SourceRole,
} from "../api/materials";
import { getProject, undoProjectAction, type LatestUndoableAction, type ProjectDetail } from "../api/projects";
import {
  AnswerMatchStatus,
  AutoMatchDialog,
  LibraryMaterialPickerDialog,
  ProjectNav,
  QualityBadge,
  ResearchLaunchDialog,
} from "../components/domain";
import { usePendingReviewJob } from "../hooks/usePendingReviewJob";
import { useResearchStatus } from "../hooks/useResearchStatus";
import { RESEARCH_ACTION_LABEL, type ResearchState } from "../components/domain/researchStatus";
import { AnswersAiPlanDialog } from "./answers/AnswersAiPlanDialog";
import {
  Button,
  ConfirmDialog,
  ContextMenu,
  Dialog,
  EmptyState,
  ErrorState,
  IconButton,
  Kbd,
  LoadingState,
  SegmentedTabs,
  StatusBadge,
  Tooltip,
} from "../components/ui";
import { MetricList } from "../components/domain";
import { useBindings } from "../hooks/useBindings";
import { useConspectSummary } from "../hooks/useConspect";
import { useDocumentSearch } from "../hooks/useDocumentSearch";

// Прямой импорт файла, а не барреля components/domain: тянет Milkdown только
// когда реально открыт «Сводный конспект» (см. ProjectWorkspace.tsx).
const ConspectSummary = lazy(() =>
  import("../components/domain/ConspectSummary").then((module) => ({ default: module.ConspectSummary })),
);
import { useAnswerAutoMatch, type AnswerAutoMatchState } from "../hooks/useAnswerAutoMatch";
import { useProjectMaterials } from "../hooks/useProjectMaterials";
import { useViewerFullscreen } from "../hooks/useViewerFullscreen";
import { buildProgramTree, filterProgramTree, flattenProgramTree, type ProgramTreeNode } from "./programTree";
import { AiCleanupPanel } from "./AiCleanupPanel";
import { MaterialFileTab } from "./materials/MaterialFileTab";
import { materialMenuItems, type MaterialMenuActions } from "./materials/materialMenu";
import { materialRoleText, pagesSummary, parseModeShort, progressSuffix, topicsLabel } from "./materials/materialLabels";
import { ProjectFileUploadStatus } from "./materials/ProjectFileUploadStatus";
import { MaterialProcessingPanels } from "./materials/MaterialProcessingPanels";
import { MaterialsWebSearch, type MaterialsWebSearchHandle } from "./materials/MaterialsWebSearch";
import {
  DocumentSearchField,
  DocumentStage,
  getMaterialPresentation,
  MaterialSourceView,
  PageNumberInput,
  PdfOutline,
  StructuredPage,
  type MaterialViewMode,
} from "../components/domain/material-viewer";

const EMPTY_STRING_SET: Set<string> = new Set();
const EMPTY_TITLES_MAP: Map<string, string[]> = new Map();
// После этих границ в центре помещаются соответственно две читаемые половины
// и оглавление рядом с ними; меряем центр, а не всё окно с боковыми панелями.
const COMPARE_MIN_WIDTH = 760;
const INLINE_OUTLINE_MIN_WIDTH = 1080;

const STUDY_NODE_TYPES = new Set(["topic", "subpoint"]);
const isStudyNode = (node: ProgramTreeNode): boolean =>
  STUDY_NODE_TYPES.has(node.node_type) && node.is_in_current_program && !node.is_archived;

const STATUS: Record<MaterialRead["status"], { label: string; tone: "neutral" | "info" | "warning" | "danger" | "success" }> = {
  ready_to_process: { label: "Готов к разбору", tone: "neutral" },
  queued: { label: "В очереди", tone: "info" },
  processing: { label: "Разбирается", tone: "info" },
  paused: { label: "На паузе", tone: "warning" },
  needs_input: { label: "Нужны файлы", tone: "warning" },
  ready: { label: "Готов", tone: "success" },
  failed: { label: "Ошибка", tone: "danger" },
};

function fileCountLabel(count: number): string {
  const mod100 = count % 100;
  const mod10 = count % 10;
  if (mod100 >= 11 && mod100 <= 14) return `${count} файлов`;
  if (mod10 === 1) return `${count} файл`;
  if (mod10 >= 2 && mod10 <= 4) return `${count} файла`;
  return `${count} файлов`;
}

function MaterialIcon({ material }: { material: MaterialRead }) {
  if (material.media_type.startsWith("image/")) return <FileImage size={15} aria-hidden="true" />;
  return <FileText size={15} aria-hidden="true" />;
}

interface CatalogProps {
  projectId: string;
  project: ProjectDetail | null;
  materials: MaterialRead[];
  selectedId?: string;
  query: string;
  onQuery: (value: string) => void;
  onAdd: () => void;
  onChooseLibrary: () => void;
  hasConspects: boolean;
  conspectSummaryActive: boolean;
  menu: MaterialMenuActions;
}

function MaterialCatalog({
  projectId,
  project,
  materials,
  selectedId,
  query,
  onQuery,
  onAdd,
  onChooseLibrary,
  hasConspects,
  conspectSummaryActive,
  menu,
}: CatalogProps) {
  const textbook = project?.project.workspace_variant === "textbook";
  const visible = materials.filter((material) =>
    material.display_name.toLocaleLowerCase("ru").includes(query.toLocaleLowerCase("ru")));
  const examFiles = visible.filter((material) => material.purposes.some((purpose) =>
    purpose === "exam_structure" || purpose === "reference_answers"));
  const sources = visible.filter((material) => !examFiles.includes(material));
  const conspectQueryMatches = !query.trim()
    || "сводный конспект".includes(query.toLocaleLowerCase("ru").trim());

  const items = (group: MaterialRead[]) => group.map((material) => (
    <ContextMenu
      key={material.id}
      label={`Действия с «${material.display_name}»`}
      items={materialMenuItems(material, { index: materials.indexOf(material), total: materials.length }, menu)}
      trigger={<div
      className={`materials-catalog-item ${selectedId === material.id ? "is-active" : ""}`.trim()}
    >
      <Link to={`/projects/${projectId}/materials/${material.id}`}>
        <MaterialIcon material={material} />
        <span>
          <strong>{material.display_name}</strong>
          <small>{STATUS[material.status].label}</small>
        </span>
        {(material.status === "failed" || (material.parser_mode !== "fast" && material.ocr_low_page_count > 0)) && (
          <span className="materials-attention-dot tone-warning" />
        )}
      </Link>
    </div>}
    />
  ));

  return (
    <aside className="materials-catalog" aria-label="Каталог материалов">
      <header className="materials-catalog-head">
        <Tooltip label="Вернуться в рабочую область">
          <Link
            className="workspace-back-button"
            to={`/projects/${projectId}`}
            aria-label="Вернуться в рабочую область"
          >
            <ArrowLeft size={15} />
          </Link>
        </Tooltip>
        <strong>{project?.project.name ?? "Материалы"}</strong>
        <span />
      </header>
      <div className="materials-catalog-actions">
        <Button onClick={onAdd}><Plus size={15} /> Добавить</Button>
        <Button variant="secondary" onClick={onChooseLibrary}><LibraryBig size={15} /> Из Библиотеки</Button>
      </div>
      <label className="materials-catalog-search">
        <Search size={14} />
        <input
          type="search"
          value={query}
          onChange={(event) => onQuery(event.target.value)}
          placeholder="Найти файл"
          aria-label="Найти файл"
        />
      </label>
      <nav className="materials-catalog-list">
        <Link
          className={!selectedId && !conspectSummaryActive ? "materials-catalog-overview is-active" : "materials-catalog-overview"}
          to={`/projects/${projectId}/materials`}
        >
          <Files size={15} />
          <span><strong>Все материалы</strong><small>{fileCountLabel(materials.length)}</small></span>
        </Link>
        {examFiles.length > 0 && <section><h2>Экзамен</h2>{items(examFiles)}</section>}
        {sources.length > 0 && <section><h2>Учебные источники</h2>{items(sources)}</section>}
        {hasConspects && conspectQueryMatches && (
          <section>
            <h2>Конспекты</h2>
            <div className={`materials-catalog-item ${conspectSummaryActive ? "is-active" : ""}`.trim()}>
              <Link to={`/projects/${projectId}/materials?view=conspect-summary`}>
                <ListTree size={15} aria-hidden="true" />
                <span><strong>Сводный конспект</strong></span>
              </Link>
            </div>
          </section>
        )}
      </nav>
      {project && <ProjectNav
        projectId={projectId}
        active="materials"
        textbook={textbook}
        modules={project.project.enabled_modules}
        counts={{ materials: materials.length }}
      />}
    </aside>
  );
}

function MaterialOverview({
  materials,
  textbook,
  onOpen,
  onAdd,
  onChooseLibrary,
  onFindOnline,
  onResearch,
  onResearchProgress,
  research,
  webSearch,
  menu,
  onReorder,
}: {
  materials: MaterialRead[];
  textbook: boolean;
  /** Исследован ли материал: строка под кнопкой «Исследовать». */
  research: Map<string, ResearchState>;
  /** Идущее исследование смотрят в Покрытии: второй запуск туда не нужен. */
  onResearchProgress: () => void;
  menu: MaterialMenuActions;
  /** Новый порядок строк сверху вниз — он и есть приоритет источников. */
  onReorder: (materialIds: string[]) => void;
  onOpen: (id: string) => void;
  onAdd: () => void;
  onChooseLibrary: () => void;
  /** Раскрыть чат поиска в интернете для любого проекта. */
  onFindOnline?: () => void;
  onResearch: (id: string) => void;
  /** Блок «Поиск в интернете» под списком материалов. */
  webSearch?: ReactNode;
}) {
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [dropId, setDropId] = useState<string | null>(null);

  function drop(targetId: string) {
    const from = materials.findIndex((item) => item.id === draggedId);
    const to = materials.findIndex((item) => item.id === targetId);
    setDraggedId(null);
    setDropId(null);
    if (from < 0 || to < 0 || from === to) return;
    const ids = materials.map((item) => item.id);
    ids.splice(to, 0, ids.splice(from, 1)[0]);
    onReorder(ids);
  }

  return (
    <div className="materials-document-stage is-standalone">
      <div className="materials-document-scroll">
        <div className="materials-overview">
          <header>
            <div>
              <p className="materials-kicker">Источники проекта</p>
              <h1>{textbook ? "Материалы" : "Материалы экзамена"}</h1>
              <p>{textbook ? "Подготовьте текст, затем исследуйте содержание одного или нескольких источников." : "Учебники, конспекты и лекции, по которым идёт подготовка к экзамену."}</p>
            </div>
            <div className="material-entry-actions is-end">
              <Button onClick={onAdd}><Upload size={15} /> Добавить материал</Button>
              <Button variant="secondary" onClick={onChooseLibrary}><LibraryBig size={15} /> Из Библиотеки</Button>
              {onFindOnline && <Button variant="secondary" onClick={onFindOnline}><Globe size={15} /> Найти в интернете</Button>}
            </div>
          </header>
          {materials.length === 0 ? (
            <section className="materials-empty-state">
              <Files size={28} />
              <h2>Материалов пока нет</h2>
              <p>Добавьте учебник, конспект или справочник и подготовьте его текст.</p>
              <div className="material-entry-actions">
                <Button onClick={onAdd}>Выбрать файл</Button>
                <Button variant="secondary" onClick={onChooseLibrary}><LibraryBig size={15} /> Из Библиотеки</Button>
                {onFindOnline && <Button variant="secondary" onClick={onFindOnline}><Globe size={15} /> Найти в интернете</Button>}
              </div>
            </section>
          ) : (
            <div className="materials-overview-table" role="table" aria-label="Материалы проекта">
              <div className="materials-overview-row is-head" role="row">
                <span>Материал</span><span>Роль</span><span>Страницы</span><span>Разбор</span><span>Используется</span><span>Состояние</span><span>Действие</span>
              </div>
              {materials.map((material, index) => {
                const pages = pagesSummary(material);
                const parse = parseModeShort(material);
                const lowPages = material.parser_mode !== "fast" ? material.ocr_low_page_count : 0;
                return (
                  <ContextMenu
                    key={material.id}
                    label={`Действия с «${material.display_name}»`}
                    items={materialMenuItems(material, { index, total: materials.length }, menu)}
                    trigger={<div
                      className={[
                        "materials-overview-row",
                        draggedId === material.id ? "is-dragging" : "",
                        dropId === material.id && draggedId && draggedId !== material.id
                          ? materials.findIndex((item) => item.id === draggedId) < index ? "is-drop-after" : "is-drop-before"
                          : "",
                      ].filter(Boolean).join(" ")}
                      role="row"
                      onDragOver={(event) => {
                        if (!draggedId) return;
                        event.preventDefault();
                        if (dropId !== material.id) setDropId(material.id);
                      }}
                      onDrop={(event) => { event.preventDefault(); drop(material.id); }}
                    >
                      <span className="materials-overview-name">
                        <Tooltip label="Перетащите, чтобы изменить порядок">
                          <span
                            className="materials-drag-handle"
                            draggable
                            aria-hidden="true"
                            onDragStart={(event) => {
                              event.dataTransfer.effectAllowed = "move";
                              event.dataTransfer.setData("text/plain", material.id);
                              setDraggedId(material.id);
                            }}
                            onDragEnd={() => { setDraggedId(null); setDropId(null); }}
                          ><GripVertical size={14} /></span>
                        </Tooltip>
                        <button className="materials-overview-link" type="button" onClick={() => onOpen(material.id)}><strong>{material.display_name}</strong></button>
                      </span>
                      <span>{materialRoleText(material)}</span>
                      <span className="materials-overview-cell">
                        <span>{pages.value}</span>
                        {pages.note && <small>{pages.note}</small>}
                      </span>
                      <span className="materials-overview-cell">
                        <span title={parse?.model ?? undefined}>{parse ? parse.model ? `${parse.mode} · ${parse.model}` : parse.mode : "—"}</span>
                        {lowPages > 0 && <small className="is-warning">проверить: {lowPages} стр.</small>}
                      </span>
                      <span>{topicsLabel(material.used_by_topics)}</span>
                      <StatusBadge tone={STATUS[material.status].tone}>{STATUS[material.status].label}{progressSuffix(material)}</StatusBadge>
                      {textbook && material.status === "ready"
                        ? <ResearchCell
                          state={research.get(material.id)}
                          onResearch={() => onResearch(material.id)}
                          onProgress={onResearchProgress}
                        />
                        : <span>—</span>}
                    </div>}
                  />
                );
              })}
            </div>
          )}
          {webSearch}
        </div>
      </div>
    </div>
  );
}

/** Кнопка исследования и под ней — исследован ли файл и нужно ли повторить. */
function ResearchCell({
  state,
  onResearch,
  onProgress,
}: {
  state: ResearchState | undefined;
  onResearch: () => void;
  onProgress: () => void;
}) {
  const action = state?.action ?? "research";
  return (
    <span className="materials-research-cell">
      <Button variant="ghost" onClick={action === "progress" ? onProgress : onResearch}>
        <ScanSearch size={14} />{RESEARCH_ACTION_LABEL[action]}
      </Button>
      {state && (
        <small className={`materials-research-state is-${state.tone}`}>
          {state.label}{state.detail && <span> · {state.detail}</span>}
        </small>
      )}
    </span>
  );
}

function AddMaterialDialog({
  open,
  busy,
  uploadStatus,
  answersMaterial,
  allowExamPurposes = true,
  studyRole,
  onOpenChange,
  onFile,
  onText,
  onExternal,
  onReplaceAnswers,
}: {
  open: boolean;
  busy: boolean;
  uploadStatus: { name: string; progress: number } | null;
  /** Уже загруженные эталонные ответы: второй такой файл проект не держит. */
  answersMaterial: MaterialRead | null;
  allowExamPurposes?: boolean;
  /** Роль нового учебного источника: основной, пока основного в проекте нет. */
  studyRole: SourceRole;
  onOpenChange: (open: boolean) => void;
  onFile: (file: File, role: SourceRole, purposes: MaterialPurpose[]) => void;
  onText: (name: string, text: string) => void;
  onExternal: (kind: "url" | "youtube", url: string) => void;
  onReplaceAnswers: () => Promise<boolean>;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [selection, setSelection] = useState<{ role: SourceRole; purposes: MaterialPurpose[] }>({
    role: "additional",
    purposes: ["study_source"],
  });
  const [textMode, setTextMode] = useState(false);
  const [externalMode, setExternalMode] = useState<"url" | "youtube" | null>(null);
  const [externalUrl, setExternalUrl] = useState("");
  const [text, setText] = useState("");
  const [name, setName] = useState("Ответы.txt");
  const [replaceOpen, setReplaceOpen] = useState(false);
  const [pendingAnswers, setPendingAnswers] = useState<"file" | "text" | null>(null);

  function choose(role: SourceRole, purposes: MaterialPurpose[]) {
    setSelection({ role, purposes });
    input.current?.click();
  }

  /** Ответы уже есть — сначала спрашиваем про замену, потом открываем выбор файла. */
  function chooseAnswers(target: "file" | "text") {
    if (answersMaterial) {
      setPendingAnswers(target);
      setReplaceOpen(true);
      return;
    }
    if (target === "text") setTextMode(true);
    else choose("reference", ["reference_answers"]);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={textMode ? "Вставить ответы" : externalMode ? externalMode === "url" ? "Добавить веб-страницу" : "Добавить YouTube-транскрипт" : "Добавить материал"}
      description={textMode
        ? "Заголовок ответа должен точно совпадать с названием вопроса программы."
        : externalMode
          ? externalMode === "url" ? "Tentex сохранит локальный снимок читаемого текста и дату получения." : "Tentex сохранит субтитры с временными метками, а не видеопоток."
        : allowExamPurposes
          ? "Выберите назначение сейчас; изменить его можно будет позже."
          : "Роль и приоритет источника можно изменить позже — в меню по правой кнопке."}
      footer={textMode ? (
        <>
          <Button variant="ghost" onClick={() => setTextMode(false)}>Назад</Button>
          <Button disabled={busy || !text.trim()} onClick={() => onText(name, text)}>Добавить материал</Button>
        </>
      ) : externalMode ? <>
        <Button variant="ghost" onClick={() => setExternalMode(null)}>Назад</Button>
        <Button disabled={busy || !externalUrl.trim()} onClick={() => onExternal(externalMode, externalUrl)}>Добавить источник</Button>
      </> : <Button variant="ghost" onClick={() => onOpenChange(false)}>Закрыть</Button>}
    >
      <input
        ref={input}
        className="materials-file-input"
        type="file"
        tabIndex={-1}
        aria-hidden="true"
        accept=".pdf,.docx,.txt,.md,.jpg,.jpeg,.png,.mp3,.wav,.m4a,.ogg,.flac"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onFile(file, selection.role, selection.purposes);
          event.target.value = "";
        }}
      />
      {uploadStatus && <ProjectFileUploadStatus {...uploadStatus} />}
      {textMode ? (
        <div className="materials-text-form">
          <label>Название<input value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label>Текст<textarea value={text} onChange={(event) => setText(event.target.value)} placeholder={"1. Индексы\nПолный ответ..."} /></label>
        </div>
      ) : externalMode ? (
        <div className="materials-text-form">
          <label>Ссылка<input type="url" autoFocus value={externalUrl} onChange={(event) => setExternalUrl(event.target.value)} placeholder={externalMode === "url" ? "https://example.org/article" : "https://www.youtube.com/watch?v=…"} /></label>
        </div>
      ) : (
        <div className="materials-add-grid">
          {allowExamPurposes && <>
            <button type="button" disabled={busy} onClick={() => choose("reference", ["exam_structure"])}>
              <FileImage size={18} /><span><strong>Список вопросов</strong><small>PDF, фото или текст структуры экзамена</small></span><ChevronRight size={15} />
            </button>
            <button type="button" disabled={busy} onClick={() => chooseAnswers("file")}>
              <FileText size={18} />
              <span>
                <strong>Ответы</strong>
                <small>
                  {answersMaterial
                    ? `Сейчас: ${answersMaterial.display_name}. Файл ответов один — можно заменить`
                    : "После разбора сам ляжет на вопросы по заголовкам"}
                </small>
              </span>
              <ChevronRight size={15} />
            </button>
          </>}
          <button type="button" disabled={busy} onClick={() => choose(studyRole, ["study_source"])}>
            <BookOpen size={18} /><span><strong>Учебный источник</strong><small>PDF, DOCX, TXT, MD или изображение</small></span><ChevronRight size={15} />
          </button>
          {allowExamPurposes && <button type="button" disabled={busy} onClick={() => chooseAnswers("text")}>
            <Plus size={18} /><span><strong>Вставить текст ответов</strong><small>Без создания отдельного файла вручную</small></span><ChevronRight size={15} />
          </button>}
          <button type="button" disabled={busy} onClick={() => setExternalMode("url")}>
            <Globe size={18} /><span><strong>Веб-страница по URL</strong><small>Локальный снимок текста и исходная ссылка</small></span><ChevronRight size={15} />
          </button>
          <button type="button" disabled={busy} onClick={() => setExternalMode("youtube")}>
            <Video size={18} /><span><strong>Публичное YouTube-видео</strong><small>Субтитры с временными метками</small></span><ChevronRight size={15} />
          </button>
        </div>
      )}
      <ConfirmDialog
        open={replaceOpen}
        onOpenChange={setReplaceOpen}
        title="Заменить файл с ответами?"
        confirmLabel="Заменить"
        onConfirm={() => {
          const target = pendingAnswers;
          setPendingAnswers(null);
          void onReplaceAnswers().then((done) => {
            if (!done) return;
            if (target === "text") setTextMode(true);
            else choose("reference", ["reference_answers"]);
          });
        }}
      >
        <p>
          Сейчас ответы берутся из «{answersMaterial?.display_name}». Проект
          держит один такой файл: с прежнего снимется назначение, и он останется в
          материалах как учебный источник.
        </p>
        <p>Уже заполненные ответы и привязки старого файла сохранятся.</p>
      </ConfirmDialog>
    </Dialog>
  );
}

interface DocumentBindingProps {
  bindingMode: boolean;
  activeNodeId: string | null;
  boundFragmentIds: Set<string>;
  activeNodeFragmentIds: Set<string>;
  selectedFragmentIds: Set<string>;
  onFragmentActivate: (fragmentId: string, options: { shiftKey: boolean }) => void;
  onBindBlock: (block: MaterialBlockRead) => void;
  /** Разрыв связи прямо в тексте: у одной привязки снимает сразу, у нескольких открывает карточку. */
  onFragmentUnbind: (fragmentId: string) => void;
  fragmentBindingTitles: Map<string, string[]>;
}

function DocumentView({
  projectId,
  material,
  page,
  terms,
  binding,
}: {
  projectId: string;
  material: MaterialRead;
  page: MaterialPageRead;
  terms: string[];
  binding: DocumentBindingProps;
}) {
  const blockById = new Map(page.blocks.map((block) => [block.id, block]));
  const firstFragmentByBlock = new Set<string>();
  const seenBlocks = new Set<string>();
  for (const fragment of page.fragments) {
    if (!seenBlocks.has(fragment.block_id)) {
      seenBlocks.add(fragment.block_id);
      firstFragmentByBlock.add(fragment.id);
    }
  }
  const {
    bindingMode,
    activeNodeId,
    boundFragmentIds,
    activeNodeFragmentIds,
    selectedFragmentIds,
    onFragmentActivate,
    onBindBlock,
    onFragmentUnbind,
    fragmentBindingTitles,
  } = binding;
  return (
    <div className={`materials-pages is-text ${material.parser_mode !== "fast" && page.quality === "ocr_low" ? "is-ocr-low" : ""}`.trim()}>
      <StructuredPage
        showOcrReview={material.parser_mode !== "fast"}
        page={page}
        terms={terms}
        assetUrl={(fragmentId) => materialFragmentAssetUrl(projectId, material.id, fragmentId)}
        className={`materials-page materials-structured-page ${material.parser_mode !== "fast" && page.quality === "ocr_low" ? "is-ocr-low" : ""}`.trim()}
        fragmentProps={(fragment) => {
          const block = blockById.get(fragment.block_id);
          const isService = block?.block_class === "service";
          const isAnyBound = boundFragmentIds.has(fragment.id);
          const isActiveBound = activeNodeFragmentIds.has(fragment.id);
          const isSelected = selectedFragmentIds.has(fragment.id);
          const clickable = bindingMode && !isService;
          const className = [
            "materials-document-block",
            isService ? "is-note" : "",
            isAnyBound ? "is-bound" : "",
            isActiveBound ? "is-answer" : "",
            isSelected ? "is-selected" : "",
            clickable ? "is-bindable" : "",
          ].filter(Boolean).join(" ");

          return {
            className,
            role: clickable ? "button" : undefined,
            tabIndex: clickable ? 0 : undefined,
            "aria-pressed": clickable ? isActiveBound : undefined,
            onClick: clickable
              ? (event) => onFragmentActivate(fragment.id, { shiftKey: event.shiftKey })
              : undefined,
            onKeyDown: clickable
              ? (event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onFragmentActivate(fragment.id, { shiftKey: event.shiftKey });
                }
              }
              : undefined,
          };
        }}
        renderFragmentOverlay={(fragment) => {
          const block = blockById.get(fragment.block_id);
          const isService = block?.block_class === "service";
          const isAnyBound = boundFragmentIds.has(fragment.id);
          return (
            <>
              {firstFragmentByBlock.has(fragment.id) && bindingMode && block && (
                <div className="materials-block-actions" onClick={(event) => event.stopPropagation()}>
                  <Button
                    variant="ghost"
                    disabled={!activeNodeId}
                    onClick={() => onBindBlock(block)}
                    title={!activeNodeId ? "Сначала выберите активный вопрос" : undefined}
                  >
                    <Link2 size={13} /> {isService ? "Привязать всё равно" : "Привязать блок целиком"}
                  </Button>
                </div>
              )}
              {isAnyBound && (
                <button
                  type="button"
                  className="materials-fragment-pin"
                  title={`Снять привязку · ${(fragmentBindingTitles.get(fragment.id) ?? []).join(", ")}`}
                  aria-label={`Снять привязку фрагмента: ${(fragmentBindingTitles.get(fragment.id) ?? []).join(", ")}`}
                  onClick={(event) => { event.stopPropagation(); onFragmentUnbind(fragment.id); }}
                >
                  <Link2 size={12} aria-hidden="true" />
                  <Unlink size={12} aria-hidden="true" />
                </button>
              )}
            </>
          );
        }}
      />
    </div>
  );
}

function NodePickerDialog({
  open,
  onOpenChange,
  tree,
  onSelect,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tree: ProgramTreeNode[];
  onSelect: (node: ProgramTreeNode) => void;
}) {
  const [query, setQuery] = useState("");
  useEffect(() => { if (open) setQuery(""); }, [open]);
  const filtered = useMemo(() => flattenProgramTree(filterProgramTree(tree, query)).filter(isStudyNode), [tree, query]);

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Выбрать вопрос"
      description="Поиск по формулировке или прокрутите список программы."
    >
      <label className="materials-catalog-search">
        <Search size={14} />
        <input
          autoFocus
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Найти вопрос"
          aria-label="Найти вопрос"
        />
      </label>
      <div className="materials-node-picker-list" role="listbox" aria-label="Вопросы программы">
        {filtered.length ? filtered.map((node) => (
          <button
            type="button"
            role="option"
            aria-selected={false}
            key={node.id}
            style={{ paddingInlineStart: `${12 + Math.max(0, node.depth - 1) * 14}px` }}
            onClick={() => { onSelect(node); onOpenChange(false); }}
          >
            <small>{node.number}</small>
            <span>{node.title}</span>
          </button>
        )) : <p className="materials-list-empty">Ничего не найдено.</p>}
      </div>
    </Dialog>
  );
}

type InspectorTab = "bindings" | "processing" | "file";
const TAB_LABELS: Record<InspectorTab, string> = {
  bindings: "Привязки",
  processing: "Обработка",
  file: "Файл",
};

function ProcessingTab({
  projectId,
  material,
  page,
  libraryLink,
  onEdit,
  onCleanup,
  onChanged,
  onError,
  notice,
  onDismissNotice,
}: {
  projectId: string;
  material: MaterialRead;
  /** Текущая страница проекта: по ней панель включает правку и подтверждение OCR. */
  page: MaterialPageRead | null;
  /** Библиотека остаётся домом для сравнения версий, скачивания и удаления файла. */
  libraryLink: string;
  onEdit: () => void;
  onCleanup: () => void;
  onChanged: () => void;
  onError: (message: string) => void;
  notice: NoticeState | null;
  onDismissNotice: () => void;
}) {
  return (
    <div className="materials-inspector-content">
      <NoticeLine notice={notice} onDismiss={onDismissNotice} />
      <MaterialProcessingPanels
        projectId={projectId}
        materialId={material.id}
        page={page}
        onEditPage={onEdit}
        onCleanupPage={onCleanup}
        onChanged={onChanged}
        onError={onError}
      />
      <p className="materials-muted">
        Сравнение версий, скачивание исходника и удаление файла из установки — в{" "}
        <Link className="materials-text-link" to={libraryLink}>Библиотеке</Link>.
        Изменения здесь общие для всех проектов с этим файлом.
      </p>
    </div>
  );
}

type NoticeTone = "info" | "success" | "danger";

interface NoticeState {
  text: string;
  tone: NoticeTone;
  /** Показывается прямо в строке статуса: отменять действие удобнее там, где о нём сообщили. */
  undo?: () => void;
}

const NOTICE_ICON: Record<NoticeTone, typeof Info> = {
  info: Info,
  success: CheckCircle2,
  danger: AlertTriangle,
};

function NoticeLine({ notice, onDismiss }: { notice: NoticeState | null; onDismiss: () => void }) {
  if (!notice) return null;
  const Icon = NOTICE_ICON[notice.tone];
  return (
    <div className={`materials-status-line is-${notice.tone}`} role="status">
      <Icon size={16} aria-hidden="true" />
      <p>{notice.text}</p>
      {notice.undo && (
        <button type="button" className="materials-status-undo" onClick={notice.undo}>
          <Undo2 size={13} aria-hidden="true" /> Отменить
        </button>
      )}
      <IconButton label="Скрыть сообщение" onClick={onDismiss}><X size={13} /></IconButton>
    </div>
  );
}

/** Строка списка привязок иначе показывает одно и то же название вопроса
    несколько раз подряд (заголовок, тело, источник — разные фрагменты одного
    ответа) и выглядит как дубль. Превью фрагмента различает их на взгляд. */
function bindingPreview(text: string, max = 44): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
}

const MECHANISM_LABEL: Record<BindingFragmentRead["mechanism"], string> = {
  manual: "вручную",
  search: "из поиска",
  answers_file: "из файла ответов",
  pass_two: "проход 2",
};

interface BindingsTabProps {
  projectId: string;
  activeNode: ProgramTreeNode | null;
  studyNodeCount: number;
  onOpenPicker: () => void;
  onPrevNode: () => void;
  onNextNode: () => void;
  fragmentsBound: number;
  questionsWithMaterial: number;
  questionsWithoutMaterial: number;
  notice: NoticeState | null;
  onDismissNotice: () => void;
  bindingMode: boolean;
  onToggleBindingMode: () => void;
  selectedCount: number;
  onBindSelection: () => void;
  onClearSelection: () => void;
  bindingScope: "page" | "document";
  onBindingScopeChange: (scope: "page" | "document") => void;
  pageBindingCount: number;
  documentBindingCount: number;
  listedBindings: BindingFragmentRead[];
  nodeNumberById: Map<string, string>;
  focusedFragmentId: string | null;
  onSelectBinding: (binding: BindingFragmentRead) => void;
  focusedFragment: MaterialFragmentRead | null;
  focusedFragmentBindings: BindingFragmentRead[];
  onBindFocusedToActive: () => void;
  onOpenPickerForFocused: () => void;
  onUnbind: (bindingId: string) => void;
  onRemoveAllInScope: () => void;
  headingSuggestions: HeadingSuggestion[];
  onResolveHeading: (blockId: string, nodeId: string) => void;
  /** Файл эталонных ответов, разбор завершён — режим «по заголовкам» применим. */
  canAutoMatch: boolean;
  onOpenAutoMatch: () => void;
  answerMatchState: AnswerAutoMatchState;
  answerMatchRunning: boolean;
  onRetryAutoMatch: () => void;
  onDismissAutoMatch: () => void;
}

/** «5. Реляционная модель…» — номер узла программы, если он известен. */
function nodeLabel(nodeNumberById: Map<string, string>, node: { program_node_id: string; node_title: string }): string {
  const number = nodeNumberById.get(node.program_node_id);
  return number ? `${number}. ${node.node_title}` : node.node_title;
}

function BindingsTab({
  projectId,
  activeNode,
  studyNodeCount,
  onOpenPicker,
  onPrevNode,
  onNextNode,
  fragmentsBound,
  questionsWithMaterial,
  questionsWithoutMaterial,
  notice,
  onDismissNotice,
  bindingMode,
  onToggleBindingMode,
  selectedCount,
  onBindSelection,
  onClearSelection,
  bindingScope,
  onBindingScopeChange,
  pageBindingCount,
  documentBindingCount,
  listedBindings,
  nodeNumberById,
  focusedFragmentId,
  onSelectBinding,
  focusedFragment,
  focusedFragmentBindings,
  onBindFocusedToActive,
  onOpenPickerForFocused,
  onUnbind,
  onRemoveAllInScope,
  headingSuggestions,
  onResolveHeading,
  canAutoMatch,
  onOpenAutoMatch,
  answerMatchState,
  answerMatchRunning,
  onRetryAutoMatch,
  onDismissAutoMatch,
}: BindingsTabProps) {
  const alreadyBoundToActive = activeNode
    ? focusedFragmentBindings.some((binding) => binding.program_node_id === activeNode.id)
    : false;
  const noQuestions = studyNodeCount === 0;

  return (
    <div className="materials-inspector-content">
      <MetricList
        layout="row"
        metrics={[
          { label: "Привязано", value: String(fragmentsBound) },
          { label: "С материалом", value: String(questionsWithMaterial) },
          { label: "Без материала", value: String(questionsWithoutMaterial) },
        ]}
      />

      {canAutoMatch ? (
        <Button variant="secondary" disabled={answerMatchRunning} onClick={onOpenAutoMatch}>
          <Sparkles size={14} /> Сопоставить автоматически
        </Button>
      ) : (
        <Tooltip label="Автопривязка материала к темам появится на этапе 8 (проход 2) — тогда же появится подтверждение перед отправкой данных">
          <Button variant="ghost" disabled>Сопоставить автоматически · этап 8</Button>
        </Tooltip>
      )}

      <AnswerMatchStatus
        state={answerMatchState}
        onRetry={onRetryAutoMatch}
        onDismiss={onDismissAutoMatch}
        compact
      />

      <NoticeLine notice={notice} onDismiss={onDismissNotice} />

      {headingSuggestions.length > 0 && (
        <section className="materials-suggestions" aria-label="Заголовки без вопроса">
          <header>
            <b>Не нашли вопрос · {headingSuggestions.length}</b>
            <small>
              Заголовок разошёлся с формулировкой сильнее, чем можно решить без вас.
              Выбор запомнится: повторная привязка файла его не потеряет.
            </small>
          </header>
          {headingSuggestions.map((suggestion) => (
            <article className="materials-suggestion" key={suggestion.anchor_fragment_id}>
              <b className="materials-suggestion-heading">{suggestion.heading}</b>
              <small className="materials-suggestion-preview">
                стр. {suggestion.page_from}
                {suggestion.preview ? ` · ${bindingPreview(suggestion.preview, 90)}` : ""}
              </small>
              <div className="materials-suggestion-actions">
                {suggestion.candidates.map((candidate) => (
                  <Button
                    key={candidate.node_id}
                    variant="secondary"
                    onClick={() => onResolveHeading(suggestion.anchor_fragment_id, candidate.node_id)}
                  >
                    <Link2 size={13} />
                    {nodeNumberById.get(candidate.node_id)
                      ? `${nodeNumberById.get(candidate.node_id)}. ${candidate.node_title}`
                      : candidate.node_title}
                  </Button>
                ))}
                <Button
                  variant="ghost"
                  disabled={!activeNode}
                  onClick={() => activeNode && onResolveHeading(suggestion.anchor_fragment_id, activeNode.id)}
                >
                  {activeNode ? `К вопросу ${activeNode.number}` : "Выберите вопрос ниже"}
                </Button>
              </div>
            </article>
          ))}
        </section>
      )}

      <div className="materials-active-node">
        <small className="materials-active-node-label">Привязываем к вопросу:</small>
        <button
          type="button"
          className="materials-active-node-pick"
          disabled={noQuestions}
          onClick={onOpenPicker}
        >
          {activeNode
            ? `${activeNode.number}. ${activeNode.title}`
            : noQuestions ? "В программе нет вопросов" : "Выберите вопрос"}
        </button>
        <div className="materials-active-node-steps">
          <button type="button" aria-label="Предыдущий вопрос" disabled={noQuestions} onClick={onPrevNode}>
            <ChevronLeft size={16} aria-hidden="true" />
          </button>
          <button type="button" aria-label="Следующий вопрос" disabled={noQuestions} onClick={onNextNode}>
            <ChevronRight size={16} aria-hidden="true" />
          </button>
        </div>
      </div>

      {activeNode && (
        bindingMode ? (
          <div className="materials-bind-hint">
            <p>
              Кликайте по абзацам документа — они привяжутся к этому вопросу.
              Повторный клик снимает привязку, <Kbd>Shift</Kbd> выделяет диапазон.
            </p>
            {selectedCount > 0 && (
              <div className="materials-button-stack">
                <Button onClick={onBindSelection}><Link2 size={14} /> Привязать выделенное · {selectedCount}</Button>
                <Button variant="ghost" onClick={onClearSelection}>Снять выделение</Button>
              </div>
            )}
          </div>
        ) : (
          <Button variant="secondary" onClick={onToggleBindingMode}>
            <Link2 size={14} /> Включить режим привязки
          </Button>
        )
      )}

      <div className="materials-binding-scope">
        <SegmentedTabs
          label="Какие привязки показывать"
          value={bindingScope}
          tabs={[
            { value: "page", label: `На странице · ${pageBindingCount}` },
            { value: "document", label: `Во всём файле · ${documentBindingCount}` },
          ]}
          onChange={onBindingScopeChange}
        />
        <div className="materials-binding-toolbar">
          <Button
            variant="ghost"
            className="materials-binding-remove-all"
            disabled={listedBindings.length === 0}
            onClick={onRemoveAllInScope}
          >
            <Trash2 size={13} />
            {bindingScope === "page" ? "Удалить все на странице" : "Удалить все в документе"} · {listedBindings.length}
          </Button>
        </div>
        <div className="materials-binding-list" aria-label="Привязки этого файла">
          {listedBindings.length ? listedBindings.map((binding) => (
            <div
              className={`materials-binding-row ${binding.fragment_id === focusedFragmentId ? "is-active" : ""}`.trim()}
              key={binding.id}
            >
              <span className={`materials-binding-line is-${binding.status}`} />
              <button
                type="button"
                title={`${binding.text} · ${MECHANISM_LABEL[binding.mechanism]}`}
                onClick={() => onSelectBinding(binding)}
              >
                <span className="materials-binding-row-question">
                  <b>Вопрос:</b> {nodeLabel(nodeNumberById, binding)}
                </span>
                <span className="materials-binding-row-fragment">
                  <b>Фрагмент:</b> {bindingPreview(binding.text)} · стр. {binding.page_number}
                </span>
              </button>
              <IconButton
                label={`Снять привязку к вопросу «${binding.node_title}»`}
                onClick={() => onUnbind(binding.id)}
              >
                <Unlink size={13} />
              </IconButton>
            </div>
          )) : (
            <p className="materials-list-empty">
              {bindingScope === "page"
                ? "На этой странице привязок нет."
                : "В этом файле ещё нет привязок."}
            </p>
          )}
        </div>
      </div>

      {focusedFragment && (
        <section className="materials-selection-card">
          <div className="materials-selection-head">
            <h3>Выбранный фрагмент</h3>
            <QualityBadge quality={focusedFragment.quality} showReview={focusedFragment.recognition_source !== "ocr"} />
          </div>
          <p>{focusedFragment.text}</p>
          {focusedFragmentBindings.length > 0 && (
            <ul className="materials-fragment-questions">
              {focusedFragmentBindings.map((binding) => (
                <li key={binding.id}>
                  <span>{nodeLabel(nodeNumberById, binding)}</span>
                  <IconButton label={`Снять привязку к вопросу «${binding.node_title}»`} onClick={() => onUnbind(binding.id)}><Unlink size={13} /></IconButton>
                </li>
              ))}
            </ul>
          )}
          <div className="materials-button-stack">
            <Link className="primary-button" to={`/projects/${projectId}/cards?mode=creation&path=fragment&fragment=${focusedFragment.id}`}>
              <CreditCard size={14} /> В карточку
            </Link>
            {activeNode && !alreadyBoundToActive && (
              <Button variant="secondary" onClick={onBindFocusedToActive}><Link2 size={14} /> Привязать к выбранному вопросу</Button>
            )}
            <Button variant="secondary" onClick={onOpenPickerForFocused}>
              {focusedFragmentBindings.length > 0 ? "Привязать ещё к одному вопросу" : "Привязать к другому вопросу"}
            </Button>
          </div>
        </section>
      )}
    </div>
  );
}

interface ExamStructureBindingsTabProps {
  studyNodes: ProgramTreeNode[];
  summary: NodeBindingSummary[];
  fragmentsBound: number;
  questionsWithMaterial: number;
  questionsWithoutMaterial: number;
  notice: NoticeState | null;
  onDismissNotice: () => void;
}

/** Файл со списком вопросов сам по себе — привязывать его абзацы к вопросам
    программы бессмысленно (см. §«Поиск: файл вопросов исключён»). Вместо
    режима привязки — честный список: какие вопросы уже получили материал
    из других файлов, без разбора по фрагментам. */
function ExamStructureBindingsTab({
  studyNodes,
  summary,
  fragmentsBound,
  questionsWithMaterial,
  questionsWithoutMaterial,
  notice,
  onDismissNotice,
}: ExamStructureBindingsTabProps) {
  const summaryByNode = useMemo(
    () => new Map(summary.map((item) => [item.program_node_id, item])),
    [summary],
  );
  return (
    <div className="materials-inspector-content">
      <MetricList
        layout="row"
        metrics={[
          { label: "Привязано", value: String(fragmentsBound) },
          { label: "С материалом", value: String(questionsWithMaterial) },
          { label: "Без материала", value: String(questionsWithoutMaterial) },
        ]}
      />
      <NoticeLine notice={notice} onDismiss={onDismissNotice} />
      <p className="materials-muted">
        Это файл со списком вопросов — привязывать его фрагменты к темам по
        отдельности не имеет смысла. Ниже видно, какие вопросы уже получили
        материал из других файлов.
      </p>
      <div className="materials-examnode-list" role="list" aria-label="Вопросы программы и материал по ним">
        {studyNodes.length ? studyNodes.map((node) => {
          const bound = summaryByNode.get(node.id);
          return (
            <div
              className="materials-examnode-row"
              role="listitem"
              key={node.id}
              style={{ paddingInlineStart: `${12 + Math.max(0, node.depth - 1) * 14}px` }}
            >
              <small>{node.number}</small>
              <span>{node.title}</span>
              {bound?.content_fragment_count
                ? <StatusBadge tone="success">{bound.content_fragment_count} содерж. фрагм. · {bound.content_material_count} ф.</StatusBadge>
                : <span className="materials-examnode-empty">Без материала</span>}
            </div>
          );
        }) : <p className="materials-list-empty">В программе нет вопросов.</p>}
      </div>
    </div>
  );
}

function MaterialInspector({
  projectId,
  material,
  activeTab,
  onTabChange,
  busy,
  notice,
  libraryLink,
  page,
  onRemove,
  onEdit,
  onCleanup,
  onChanged,
  onError,
  answersMaterial,
  allowPurposeChoice,
  order,
  onSaveFile,
  bindingsProps,
  examStructureProps,
  textbook,
  isExamStructureFile,
  onDismissNotice,
}: {
  projectId: string;
  material: MaterialRead;
  activeTab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
  busy: boolean;
  notice: NoticeState | null;
  libraryLink: string;
  page: MaterialPageRead | null;
  onRemove: () => void;
  onEdit: () => void;
  onCleanup: () => void;
  onChanged: () => void;
  onError: (message: string) => void;
  answersMaterial: MaterialRead | null;
  allowPurposeChoice: boolean;
  order: { position: number; total: number } | null;
  onSaveFile: (command: MaterialUpdateCommand) => Promise<MaterialRead | null>;
  bindingsProps: BindingsTabProps;
  examStructureProps: ExamStructureBindingsTabProps;
  textbook: boolean;
  isExamStructureFile: boolean;
  onDismissNotice: () => void;
}) {
  return (
    <aside className="materials-inspector" aria-label="Действия с материалом">
      <div className="materials-inspector-tabs" role="tablist" aria-label="Разделы инспектора">
        {(textbook ? (["processing", "file"] as const) : (["bindings", "processing", "file"] as const)).map((tab) => (
          <button type="button" role="tab" aria-selected={activeTab === tab} className={activeTab === tab ? "is-active" : ""} key={tab} onClick={() => onTabChange(tab)}>{TAB_LABELS[tab]}</button>
        ))}
      </div>
      <div className="materials-inspector-scroll">
        {activeTab === "bindings" && (
          isExamStructureFile ? <ExamStructureBindingsTab {...examStructureProps} /> : <BindingsTab {...bindingsProps} />
        )}
        {activeTab === "processing" && (
          <ProcessingTab projectId={projectId} material={material} page={page} libraryLink={libraryLink} onEdit={onEdit} onCleanup={onCleanup} onChanged={onChanged} onError={onError} notice={notice} onDismissNotice={onDismissNotice} />
        )}
        {activeTab === "file" && (
          <div className="materials-inspector-content">
            <NoticeLine notice={notice} onDismiss={onDismissNotice} />
            <MaterialFileTab
              material={material}
              answersMaterial={answersMaterial}
              allowPurposeChoice={allowPurposeChoice}
              order={order}
              busy={busy}
              onSave={onSaveFile}
              onRemove={onRemove}
            />
          </div>
        )}
      </div>
    </aside>
  );
}

function MaterialSurface() {
  const { projectId = "", materialId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const store = useProjectMaterials(projectId);
  const bindings = useBindings(projectId);
  const [query, setQuery] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<MaterialRead | null>(null);
  const [renameTarget, setRenameTarget] = useState<{ material: MaterialRead; value: string } | null>(null);
  const [autoMatchOpen, setAutoMatchOpen] = useState(false);
  const [aiPlanOpen, setAiPlanOpen] = useState(false);
  const webSearch = useRef<MaterialsWebSearchHandle>(null);
  // Разметка ответов моделью досчиталась в фоне и ждёт человека — открываем
  // диалог с готовым планом сразу, без поиска нужной кнопки на экране.
  const answersReviewJob = usePendingReviewJob(
    "ai_answer_sections",
    { projectId, materialId },
    Boolean(materialId),
  );
  const [pageNumber, setPageNumber] = useState(1);
  const [page, setPage] = useState<MaterialPageRead | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<MaterialViewMode>("source");
  const [libraryDetail, setLibraryDetail] = useState<LibraryMaterialDetailRead | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [documentWidth, setDocumentWidth] = useState(0);
  const documentObserver = useRef<ResizeObserver | null>(null);
  const [inlineOutlineOpen, setInlineOutlineOpen] = useState(true);
  const [overlayOutlineOpen, setOverlayOutlineOpen] = useState(false);
  const [notice, setNotice] = useState<NoticeState | null>(null);
  /** «fit» — вписать страницу целиком: с ним документ открывается, а не с обрезанного 100%. */
  const [zoom, setZoom] = useState<number | "fit">("fit");
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const { fullscreen, setFullscreen } = useViewerFullscreen();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const textScrollRef = useRef<HTMLDivElement | null>(null);
  const scrollObserver = useRef<ResizeObserver | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [editText, setEditText] = useState("");
  const [editBusy, setEditBusy] = useState(false);
  const [cleanupOpen, setCleanupOpen] = useState(false);
  const requestedCleanupJob = searchParams.get("job");
  useEffect(() => {
    if (!requestedCleanupJob || !materialId) return;
    const controller = new AbortController();
    void getBackgroundJob(requestedCleanupJob, controller.signal).then((job) => {
      if (controller.signal.aborted || job.kind !== "ai_cleanup"
        || job.material_id !== materialId || job.project_id !== projectId
        || !job.page_number) return;
      setPageNumber(job.page_number);
      setCleanupOpen(true);
    }).catch(() => undefined);
    return () => controller.abort();
  }, [requestedCleanupJob, materialId, projectId]);
  const [researchOpen, setResearchOpen] = useState(false);
  const [researchMaterialIds, setResearchMaterialIds] = useState<string[]>([]);
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("bindings");
  const [bindingMode, setBindingMode] = useState(false);
  /** Заголовки файла ответов без уверенного вопроса — живут до перехода на другой файл. */
  const [answersSuggestions, setAnswersSuggestions] = useState<
    { materialId: string; items: HeadingSuggestion[] } | null
  >(null);
  const [activeNodeId, setActiveNodeId] = useState<string | null>(null);
  const [bindingScope, setBindingScope] = useState<"page" | "document">("document");
  const [selectedFragmentIds, setSelectedFragmentIds] = useState<string[]>([]);
  const [lastClickedFragmentId, setLastClickedFragmentId] = useState<string | null>(null);
  const [focusedFragmentId, setFocusedFragmentId] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerTarget, setPickerTarget] = useState<"active" | "fragment">("active");
  const [pageBindings, setPageBindings] = useState<BindingFragmentRead[]>([]);
  const [documentBindings, setDocumentBindings] = useState<BindingFragmentRead[]>([]);
  const [lastUndoableAction, setLastUndoableAction] = useState<LatestUndoableAction | null>(null);
  const [dataVersion, setDataVersion] = useState(0);
  const material = store.materials.find((item) => item.id === materialId);
  const answersMaterial = store.materials.find(
    (item) => item.purposes.includes("reference_answers"),
  ) ?? null;
  const presentation = material ? getMaterialPresentation(material.presentation_kind) : null;
  const viewerDetail = libraryDetail && material && libraryDetail.id === material.id
    ? { ...libraryDetail, display_name: material.display_name }
    : null;
  const hasOriginal = material?.presentation_kind === "pdf"
    || material?.presentation_kind === "image"
    || material?.presentation_kind === "typst";
  const hasSource = Boolean(material && material.presentation_kind !== "audio" && material.presentation_kind !== "youtube");
  const compareAvailable = Boolean(viewerDetail?.capabilities.can_compare) && documentWidth >= COMPARE_MIN_WIDTH;
  const outlineAvailable = viewMode !== "compare" && Boolean(presentation?.supportsOutline && viewerDetail?.outline.length);
  const inlineOutline = outlineAvailable && documentWidth >= INLINE_OUTLINE_MIN_WIDTH && inlineOutlineOpen;
  const overlayOutline = outlineAvailable && documentWidth < INLINE_OUTLINE_MIN_WIDTH && overlayOutlineOpen;
  const showOutline = inlineOutline || overlayOutline;
  const textbook = project?.project.workspace_variant === "textbook";
  // Новая версия текста делает прежнее исследование устаревшим: состояние перечитывается.
  const research = useResearchStatus(
    projectId,
    Boolean(textbook) && !material,
    store.materials.map((item) => `${item.id}:${item.status}`).join(","),
  );
  // Вопросы и ответы бывают только в учебниковом шаблоне; экзамен и свободное
  // изучение держат одни учебные источники (решение 27.09.2026 в SCREENS.md).
  const allowExamPurposes = project?.project.template_key === "textbook";
  // Основной источник у проекта один: первый учебный источник становится
  // основным, следующие — дополнительными, как в мастере проекта.
  const newStudyRole: SourceRole = store.materials.some((item) =>
    item.purposes.includes("study_source") && item.source_role === "main") ? "additional" : "main";
  // Ручные привязки — инструмент экзамена: в учебнике и свободном изучении
  // вкладки нет, и инспектор открывается на «Обработке».
  const visibleInspectorTab: InspectorTab = textbook && inspectorTab === "bindings" ? "processing" : inspectorTab;
  const conspectSummary = useConspectSummary(projectId);
  const hasConspects = !textbook && conspectSummary.entries.length > 0;
  const conspectSummaryActive = !textbook && searchParams.get("view") === "conspect-summary";
  // Список вопросов сам себя не привязывает: у него нет фрагментов, которые
  // имело бы смысл сопоставлять с темами программы (см. пояснение к вкладке).
  const isExamStructureFile = material?.purposes.includes("exam_structure") ?? false;
  const documentBindingEnabled = !textbook && !isExamStructureFile;

  useEffect(() => {
    setViewMode(hasOriginal ? "source" : "text");
    setInlineOutlineOpen(true);
    setOverlayOutlineOpen(false);
  }, [hasOriginal, material?.id]);

  useEffect(() => {
    if (!material) {
      setLibraryDetail(null);
      setDetailError(null);
      return;
    }
    const controller = new AbortController();
    setLibraryDetail(null);
    setDetailError(null);
    void getLibraryMaterial(material.id, controller.signal)
      .then(setLibraryDetail)
      .catch((caught) => {
        if (!controller.signal.aborted) setDetailError(caught instanceof Error ? caught.message : "Не удалось открыть исходник");
      });
    return () => controller.abort();
  }, [material?.id, material?.active_parse_revision]);

  const attachDocumentArea = useCallback((node: HTMLElement | null) => {
    documentObserver.current?.disconnect();
    if (!node) return;
    const measure = () => setDocumentWidth(node.clientWidth);
    measure();
    documentObserver.current = new ResizeObserver(measure);
    documentObserver.current.observe(node);
  }, []);

  // Сбрасываем оверлей только при переходе из широкого режима в узкий: любое
  // колебание ширины (например, полоса прокрутки на другой странице) не должно его закрывать.
  const wasWideOutline = useRef(false);
  useEffect(() => {
    const wide = documentWidth >= INLINE_OUTLINE_MIN_WIDTH;
    if (!wide && wasWideOutline.current) setOverlayOutlineOpen(false);
    wasWideOutline.current = wide;
  }, [documentWidth]);

  useEffect(() => {
    if (documentWidth < COMPARE_MIN_WIDTH && viewMode === "compare") setViewMode("source");
  }, [documentWidth, viewMode]);

  useEffect(() => { if (answersReviewJob) setAiPlanOpen(true); }, [answersReviewJob]);
  // «Найти в интернете» у темы ведёт сюда с `?search=1&topic=…`: блок раскрывается
  // и встаёт по центру, даже если экран уже был открыт.
  const searchRequested = searchParams.get("search") === "1";
  const searchTopicId = searchParams.get("topic");
  useEffect(() => {
    if (searchRequested && project) webSearch.current?.reveal();
  }, [searchRequested, searchTopicId, project]);

  const treeResult = useMemo(() => {
    try { return buildProgramTree(project?.program.nodes ?? []); }
    catch { return []; }
  }, [project?.program.nodes]);
  const studyNodes = useMemo(() => flattenProgramTree(treeResult).filter(isStudyNode), [treeResult]);
  const activeNode = studyNodes.find((node) => node.id === activeNodeId) ?? null;
  const nodeNumberById = useMemo(() => new Map(studyNodes.map((node) => [node.id, node.number])), [studyNodes]);
  const refreshBindingData = useCallback(() => setDataVersion((value) => value + 1), []);
  const answerMatch = useAnswerAutoMatch(
    projectId,
    material?.id ?? null,
    async (result) => {
      refreshBindingData();
      await bindings.refreshSummary();
      setAnswersSuggestions({ materialId: material?.id ?? "", items: result.suggestions });
      if (result.suggestions.length) setInspectorTab("bindings");
    },
  );

  const pageCount = material?.page_count ?? 1;
  const displayedPage = page?.page_number === pageNumber ? page : null;
  // Замеряется именно половина исходника: оглавление и текст не должны
  // участвовать в вычислении масштаба листа.
  const fitZoom = useMemo(() => {
    if (viewport.width === 0 || viewport.height === 0) return 1;
    const aspect = displayedPage && displayedPage.width > 0 ? displayedPage.height / displayedPage.width : 900 / 680;
    const byWidth = (viewport.width - 48) / 680;
    const byHeight = (viewport.height - 48) / (680 * aspect);
    return Math.min(2, Math.max(0.1, Math.min(byWidth, byHeight)));
  }, [viewport, displayedPage?.width, displayedPage?.height]);
  // В режиме «Текст» лист тянется по ширине колонки, вписывать нечего:
  // там «по размеру» — это обычный масштаб, а зум меняет кегль.
  const sourceZoom = zoom === "fit" ? fitZoom : zoom;
  const textZoom = zoom === "fit" ? 1 : zoom;
  const effectiveZoom = viewMode === "text" ? textZoom : sourceZoom;

  /* Ref-колбэк, а не эффект: область прокрутки появляется позже материала,
     и эффект по materialId её уже не застаёт. Меряем сразу при появлении узла,
     ResizeObserver дальше ловит смену ширины панелей. */
  const measureScroll = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    const box = node.getBoundingClientRect();
    setViewport((current) => (
      current.width === box.width && current.height === box.height
        ? current
        : { width: box.width, height: box.height }
    ));
  }, []);

  const attachScroll = useCallback((node: HTMLDivElement | null) => {
    scrollObserver.current?.disconnect();
    scrollRef.current = node;
    if (!node) return;
    measureScroll();
    const observer = new ResizeObserver(measureScroll);
    observer.observe(node);
    scrollObserver.current = observer;
  }, [measureScroll]);

  useEffect(() => {
    window.addEventListener("resize", measureScroll);
    return () => window.removeEventListener("resize", measureScroll);
  }, [measureScroll]);

  useEffect(measureScroll, [measureScroll, fullscreen, material?.id, page?.id]);

  const goToPage = useCallback((next: number) => {
    setPageNumber((current) => {
      const target = Math.min(Math.max(1, next), Math.max(1, pageCount));
      if (target !== current) {
        scrollRef.current?.scrollTo({ top: 0 });
        textScrollRef.current?.scrollTo({ top: 0 });
      }
      return target;
    });
  }, [pageCount]);

  // Поиск идёт по всему материалу через тот же FTS5, что и в Библиотеке:
  // ручка `/api/materials/{id}/search` про проект ничего не знает.
  const searchProvider = useCallback(async (value: string, signal: AbortSignal) => {
    if (!material) return [];
    const result = await searchLibraryMaterial(material.id, value, { signal });
    return result.hits.map((hit) => ({
      fragmentId: hit.fragment_id,
      pageNumber: hit.page_number,
      text: hit.text,
      blockTitle: hit.block_title,
      matchedForms: hit.matched_forms,
    }));
  }, [material]);
  const search = useDocumentSearch(searchProvider);

  useEffect(() => {
    if (!search.current) return;
    if (search.current.pageNumber !== pageNumber) goToPage(search.current.pageNumber);
    // Страница успевает смениться и отрисоваться раньше, чем ищется якорь.
    const timer = window.setTimeout(() => {
      document
        .getElementById(`fragment-${search.current?.fragmentId}`)
        ?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 120);
    return () => window.clearTimeout(timer);
    // Перепрыгивать надо на смену совпадения, а не на каждый рендер страницы.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search.current?.fragmentId, search.current?.pageNumber]);

  useEffect(() => {
    const controller = new AbortController();
    void getProject(projectId, controller.signal).then(setProject).catch(() => undefined);
    return () => controller.abort();
  }, [projectId]);

  useEffect(() => {
    const taskId = material?.status === "ready" ? undefined : material?.task?.id;
    if (!material || (material.status !== "ready" && !taskId)) {
      setPage(null);
      setPageError(null);
      return;
    }
    const controller = new AbortController();
    setPageError(null);
    void getMaterialPage(projectId, material.id, pageNumber, controller.signal, taskId)
      .then(setPage)
      .catch((caught) => {
        if (controller.signal.aborted) return;
        if (material.status !== "ready") {
          setPage(null);
          setPageError(null);
          return;
        }
        setPageError(caught instanceof Error ? caught.message : "Страница не загрузилась");
      });
    return () => controller.abort();
  }, [
    material?.id,
    material?.status,
    material?.active_parse_revision,
    material?.task?.id,
    material?.task?.done,
    pageNumber,
    projectId,
  ]);

  useEffect(() => {
    setSelectedFragmentIds([]);
    setLastClickedFragmentId(null);
  }, [material?.id, pageNumber]);

  useEffect(() => {
    setFocusedFragmentId(null);
  }, [material?.id]);

  useEffect(() => {
    // Без сброса здесь pageNumber остаётся от прошлого материала: переход
    // со страницы 6 одного файла на однострочное фото запрашивал бы у бэкенда
    // несуществующую страницу 6 и получал 404 «Страница не найдена».
    const pageParam = Number(searchParams.get("page"));
    setPageNumber(Number.isFinite(pageParam) && pageParam > 0 ? pageParam : 1);
    const focusParam = searchParams.get("focus");
    if (focusParam) {
      setFocusedFragmentId(focusParam);
      setInspectorTab("bindings");
    }
    // `node` приходит из предпросмотра источника в Рабочей области: там вопрос
    // уже выбран, и переспрашивать его здесь незачем. Режим привязки включается
    // сразу — иначе клики по абзацам молча ничего не делают.
    const nodeParam = searchParams.get("node");
    if (nodeParam) {
      setActiveNodeId(nodeParam);
      setInspectorTab("bindings");
      setBindingMode(true);
    }
    // Параметры читаются один раз при переходе на материал, дальше страницами
    // управляет сам экран — эффект не должен реагировать на их изменения.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [materialId]);

  useEffect(() => {
    if (!material || !page) { setPageBindings([]); return; }
    const controller = new AbortController();
    listBindings(projectId, { materialId: material.id, page: page.page_number }, controller.signal)
      .then(setPageBindings)
      .catch(() => undefined);
    return () => controller.abort();
  }, [projectId, material?.id, page?.page_number, dataVersion]);

  useEffect(() => {
    if (!material) { setDocumentBindings([]); return; }
    const controller = new AbortController();
    listBindings(projectId, { materialId: material.id }, controller.signal)
      .then(setDocumentBindings)
      .catch(() => undefined);
    return () => controller.abort();
  }, [projectId, material?.id, dataVersion]);

  const boundFragmentIds = useMemo(() => new Set(pageBindings.map((binding) => binding.fragment_id)), [pageBindings]);
  const activeNodeFragmentIds = useMemo(
    () => new Set(pageBindings.filter((binding) => binding.program_node_id === activeNodeId).map((binding) => binding.fragment_id)),
    [pageBindings, activeNodeId],
  );
  const fragmentBindingTitles = useMemo(() => {
    const titles = new Map<string, string[]>();
    for (const binding of pageBindings) {
      const label = nodeLabel(nodeNumberById, binding);
      titles.set(binding.fragment_id, [...(titles.get(binding.fragment_id) ?? []), label]);
    }
    return titles;
  }, [pageBindings, nodeNumberById]);
  const selectedFragmentIdSet = useMemo(() => new Set(selectedFragmentIds), [selectedFragmentIds]);
  const focusedFragment = page?.fragments.find((fragment) => fragment.id === focusedFragmentId) ?? null;
  const focusedFragmentBindings = useMemo(
    () => pageBindings.filter((binding) => binding.fragment_id === focusedFragmentId),
    [pageBindings, focusedFragmentId],
  );
  const fragmentsBound = bindings.summary.reduce((sum, item) => sum + item.content_fragment_count, 0);
  const questionsWithMaterial = bindings.summary.length;
  const questionsWithoutMaterial = Math.max(0, studyNodes.length - questionsWithMaterial);

  const say = useCallback((text: string, tone: NoticeTone = "info", undo?: () => void) => {
    setNotice({ text, tone, undo });
  }, []);

  /** Отмена через общий журнал: он один знает, какие привязки реально созданы,
      а какие уже были — повторная привязка идемпотентна и ничего не создаёт. */
  async function undoAction(sequence: number, doneText: string) {
    try {
      await undoProjectAction(projectId, sequence);
      setLastUndoableAction(null);
      refreshBindingData();
      void bindings.refreshSummary();
      say(doneText, "info");
    } catch (caught) {
      say(caught instanceof Error ? caught.message : "Не удалось отменить действие", "danger");
    }
  }

  async function bindFragmentsToNode(nodeId: string, fragmentIds: string[]) {
    const result = await bindings.bind({ program_node_id: nodeId, fragment_ids: fragmentIds, mechanism: "manual" });
    if (result) {
      setLastUndoableAction(result.latest_undoable_action);
      refreshBindingData();
      const sequence = result.latest_undoable_action?.sequence;
      say(
        fragmentIds.length > 1 ? `Привязано фрагментов: ${fragmentIds.length}.` : "Фрагмент привязан.",
        "success",
        sequence === undefined ? undefined : () => void undoAction(sequence, "Привязка отменена."),
      );
    } else if (bindings.error) {
      say(bindings.error, "danger");
    }
    return result;
  }

  async function bindBlockToNode(nodeId: string, block: MaterialBlockRead) {
    const result = await bindings.bind({ program_node_id: nodeId, block_id: block.id, mechanism: "manual" });
    if (result) {
      setLastUndoableAction(result.latest_undoable_action);
      refreshBindingData();
      const sequence = result.latest_undoable_action?.sequence;
      say(
        `Блок «${block.title ?? "без заголовка"}» привязан целиком: ${result.bindings.length} фрагм.`,
        "success",
        sequence === undefined ? undefined : () => void undoAction(sequence, "Привязка блока отменена."),
      );
    } else if (bindings.error) {
      say(bindings.error, "danger");
    }
  }

  async function unbindOne(bindingId: string) {
    const result = await bindings.unbind(bindingId);
    if (result) {
      setLastUndoableAction(result.latest_undoable_action);
      refreshBindingData();
      say("Привязка снята.", "info", () => void restoreOne(bindingId));
    } else if (bindings.error) {
      say(bindings.error, "danger");
    }
  }

  async function restoreOne(bindingId: string) {
    const result = await bindings.restore(bindingId);
    if (result) {
      setLastUndoableAction(result.latest_undoable_action);
      refreshBindingData();
      say("Привязка возвращена.", "success");
    } else if (bindings.error) {
      say(bindings.error, "danger");
    }
  }

  async function removeAllInScope() {
    if (!material) return;
    const count = bindingScope === "page" ? pageBindings.length : documentBindings.length;
    if (count === 0) return;
    const targetPage = bindingScope === "page" ? page?.page_number : undefined;
    const result = await bindings.removeAllForMaterial(material.id, targetPage);
    if (result) {
      setLastUndoableAction(result.latest_undoable_action);
      refreshBindingData();
      const sequence = result.latest_undoable_action?.sequence;
      say(
        `Привязок снято: ${result.bindings.length}.`,
        "info",
        sequence === undefined ? undefined : () => void undoAction(sequence, "Массовое снятие отменено."),
      );
    } else if (bindings.error) {
      say(bindings.error, "danger");
    }
  }

  /** Разрыв связи из текста: одну привязку снимаем сразу, несколько — показываем карточку с выбором. */
  function handleFragmentUnbind(fragmentId: string) {
    const own = pageBindings.filter((binding) => binding.fragment_id === fragmentId);
    if (own.length === 1) {
      void unbindOne(own[0].id);
      return;
    }
    setFocusedFragmentId(fragmentId);
    setInspectorTab("bindings");
    say(`Фрагмент привязан к нескольким вопросам — выберите, какую связь снять.`, "info");
  }

  async function undoLastBindingAction() {
    if (!lastUndoableAction) return;
    try {
      await undoProjectAction(projectId, lastUndoableAction.sequence);
      setLastUndoableAction(null);
      refreshBindingData();
      say("Последнее действие с привязками отменено.", "info");
    } catch (caught) {
      say(caught instanceof Error ? caught.message : "Не удалось отменить действие", "danger");
    }
  }

  function handleFragmentActivate(fragmentId: string, options: { shiftKey: boolean }) {
    setFocusedFragmentId(fragmentId);
    if (options.shiftKey && lastClickedFragmentId && page) {
      const ids = page.fragments.map((fragment) => fragment.id);
      const from = ids.indexOf(lastClickedFragmentId);
      const to = ids.indexOf(fragmentId);
      if (from >= 0 && to >= 0) {
        const [start, end] = from < to ? [from, to] : [to, from];
        setSelectedFragmentIds(ids.slice(start, end + 1));
        return;
      }
    }
    setLastClickedFragmentId(fragmentId);
    setSelectedFragmentIds([]);
    if (!activeNodeId) return;
    const existing = pageBindings.find((binding) => binding.fragment_id === fragmentId && binding.program_node_id === activeNodeId);
    if (existing) void unbindOne(existing.id);
    else void bindFragmentsToNode(activeNodeId, [fragmentId]);
  }

  function handleBindSelection() {
    if (!activeNodeId || selectedFragmentIds.length === 0) return;
    const ids = selectedFragmentIds;
    setSelectedFragmentIds([]);
    void bindFragmentsToNode(activeNodeId, ids);
  }

  function handleBindBlock(block: MaterialBlockRead) {
    if (!activeNodeId) return;
    void bindBlockToNode(activeNodeId, block);
  }

  function stepActiveNode(offset: number) {
    if (studyNodes.length === 0) return;
    const index = activeNodeId ? studyNodes.findIndex((node) => node.id === activeNodeId) : -1;
    const next = studyNodes[(index + offset + studyNodes.length) % studyNodes.length];
    if (next) setActiveNodeId(next.id);
  }

  function handlePickNode(node: ProgramTreeNode) {
    if (pickerTarget === "active") {
      setActiveNodeId(node.id);
      // Вопрос выбирают, чтобы к нему привязывать, — включаем режим сразу,
      // иначе клики по абзацам молча ничего не делают.
      setBindingMode(true);
      return;
    }
    if (focusedFragmentId) void bindFragmentsToNode(node.id, [focusedFragmentId]);
  }

  useEffect(() => {
    function isTypingTarget(target: EventTarget | null): boolean {
      if (!(target instanceof HTMLElement)) return false;
      return target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (!material || !page || isTypingTarget(event.target)) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === "z") {
        event.preventDefault();
        void undoLastBindingAction();
        return;
      }
      if (event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented) return;
      switch (event.key) {
        case "ArrowLeft":
        case "PageUp":
          event.preventDefault();
          goToPage(pageNumber - 1);
          return;
        case "ArrowRight":
        case "PageDown":
          event.preventDefault();
          goToPage(pageNumber + 1);
          return;
        case "Home":
          event.preventDefault();
          goToPage(1);
          return;
        case "End":
          event.preventDefault();
          goToPage(pageCount);
          return;
        case "f":
        case "F":
        case "а":
        case "А":
          event.preventDefault();
          setFullscreen((value) => !value);
          return;
        case "b":
        case "B":
        case "и":
        case "И":
          event.preventDefault();
          setBindingMode((value) => !value);
          return;
        default:
          break;
      }
      if (event.key === "Escape" && fullscreen) {
        event.preventDefault();
        setFullscreen(false);
        return;
      }
      if (!bindingMode) return;
      if (event.key === "Enter") {
        event.preventDefault();
        handleBindSelection();
      } else if (event.key === "Escape") {
        event.preventDefault();
        if (selectedFragmentIds.length > 0) setSelectedFragmentIds([]);
        else setBindingMode(false);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [material, page, bindingMode, selectedFragmentIds, activeNodeId, lastUndoableAction, pageNumber, pageCount, fullscreen, goToPage]);

  async function addFile(file: File, role: SourceRole, purposes: MaterialPurpose[]) {
    const created = await store.upload(file, role, purposes);
    if (!created) return;
    setAddOpen(false);
    navigate(`/projects/${projectId}/materials/${created.id}`);
  }

  async function addText(name: string, text: string) {
    const created = await store.createText({
      name,
      text,
      source_role: "reference",
      purposes: ["reference_answers"],
    });
    if (!created) return;
    setAddOpen(false);
    navigate(`/projects/${projectId}/materials/${created.id}`);
  }

  async function addExternal(kind: "url" | "youtube", url: string) {
    const created = await store.createExternal({ kind, url, source_role: newStudyRole, purposes: ["study_source"] });
    if (!created) return;
    setAddOpen(false);
    navigate(`/projects/${projectId}/materials/${created.id}`);
  }

  async function savePageText() {
    if (!material || !page || !editText.trim()) return;
    setEditBusy(true);
    try {
      const updated = await updateMaterialPageText(projectId, material.id, page.page_number, editText);
      setPage(updated.page);
      setEditOpen(false);
      if (updated.orphaned_binding_ids.length > 0) {
        say(
          `Текст сохранён новой ревизией. Привязок перенесено: ${updated.transferred_bindings}, `
            + `осиротело: ${updated.orphaned_binding_ids.length}.`,
          "danger",
        );
      } else {
        say("Текст страницы сохранён новой ревизией; исходный файл не изменён.", "success");
      }
      refreshBindingData();
      await store.refresh();
    } catch (caught) {
      say(caught instanceof Error ? caught.message : "Не удалось сохранить исправление", "danger");
    } finally {
      setEditBusy(false);
    }
  }

  async function reloadCurrentPage() {
    if (!material) return;
    const updated = await getMaterialPage(projectId, material.id, pageNumber);
    setPage(updated);
    await store.refresh();
  }

  /** Снять назначение «эталонные ответы» со старого файла: он остаётся учебным источником. */
  async function releaseAnswersMaterial(): Promise<boolean> {
    if (!answersMaterial) return true;
    const rest = answersMaterial.purposes.filter((purpose) => purpose !== "reference_answers");
    const updated = await store.update(answersMaterial.id, {
      purposes: rest.length ? rest : ["study_source"],
    });
    if (!updated) {
      say(store.error ?? "Не удалось освободить прежний файл ответов", "danger");
      return false;
    }
    return true;
  }

  /** Пользователь указал вопрос для заголовка, который система не опознала. */
  async function resolveHeading(anchorFragmentId: string, nodeId: string) {
    if (!material) return;
    try {
      const result = await resolveAnswersHeading(projectId, material.id, {
        anchorFragmentId,
        programNodeId: nodeId,
      });
      setAnswersSuggestions((current) => current && ({
        materialId: current.materialId,
        items: current.items.filter((item) => item.anchor_fragment_id !== anchorFragmentId),
      }));
      refreshBindingData();
      void bindings.refreshSummary();
      say(
        result.created_answers
          ? "Раздел привязан, ответ заполнен. Решение запомнено — повторная привязка его не потеряет."
          : "Раздел привязан; ответ у вопроса уже был и не тронут.",
        "success",
      );
    } catch (caught) {
      say(caught instanceof Error ? caught.message : "Не удалось привязать раздел", "danger");
    }
  }

  async function importAnswers() {
    if (!material) return;
    try {
      const result = await importMaterialReferenceAnswers(projectId, material.id);
      say(`Создано ответов: ${result.created}; пропущено существующих: ${result.skipped_existing}.`, "success");
    } catch (caught) {
      say(caught instanceof Error ? caught.message : "Импорт не выполнен", "danger");
    }
  }

  async function saveFileSettings(command: MaterialUpdateCommand) {
    if (!material) return null;
    const updated = await store.update(material.id, command);
    if (updated) {
      say("Настройки файла сохранены.", "success");
      return updated;
    }
    say("Не удалось сохранить настройки файла.", "danger");
    return null;
  }

  function openMaterial(target: MaterialRead, tab?: InspectorTab) {
    if (tab) setInspectorTab(tab);
    navigate(`/projects/${projectId}/materials/${target.id}`);
  }

  async function updateFromMenu(target: MaterialRead, command: MaterialUpdateCommand, done: string) {
    const updated = await store.update(target.id, command);
    say(updated ? done : store.error ?? "Не удалось изменить материал", updated ? "success" : "danger");
  }

  function submitRename() {
    if (!renameTarget?.value.trim()) return;
    const { material: target, value } = renameTarget;
    setRenameTarget(null);
    void updateFromMenu(target, { display_name: value.trim() }, "Название в проекте изменено.");
  }

  const menuActions: MaterialMenuActions = {
    onOpen: (target) => openMaterial(target),
    onOpenLibrary: (target) => navigate(`/library/${target.id}?returnTo=${encodeURIComponent(
      `/projects/${projectId}/materials${materialId ? `/${materialId}` : ""}`,
    )}`),
    onResearch: textbook ? (target) => { setResearchMaterialIds([target.id]); setResearchOpen(true); } : undefined,
    onProcess: (target) => openMaterial(target, "processing"),
    onRole: (target, role) => void updateFromMenu(target, { source_role: role }, `Роль «${target.display_name}» изменена.`),
    onMove: (target, offset) => {
      const ids = store.materials.map((item) => item.id);
      const from = ids.indexOf(target.id);
      const to = from + offset;
      if (from < 0 || to < 0 || to >= ids.length) return;
      ids.splice(to, 0, ids.splice(from, 1)[0]);
      void store.reorder(ids);
    },
    onRename: (target) => setRenameTarget({ material: target, value: target.display_name }),
    onRemove: setRemoveTarget,
  };

  const libraryLink = material
    ? `/library/${material.id}?returnTo=${encodeURIComponent(
      `/projects/${projectId}/materials/${material.id}?page=${pageNumber}`
        + (focusedFragmentId ? `&focus=${focusedFragmentId}` : ""),
    )}`
    : "/library";

  if (store.loading) return <LoadingState label="Загружаем материалы" placement="page" />;

  return (
    <div
      className={`project-materials ${material ? "has-material-inspector" : ""} ${fullscreen ? "is-fullscreen" : ""}`.trim()}
      style={{
        "--materials-catalog-width": "280px",
        "--materials-catalog-handle": "0px",
        "--materials-inspector-width": material ? "356px" : "0px",
        "--materials-inspector-handle": "0px",
      } as React.CSSProperties}
    >
      <MaterialCatalog
        projectId={projectId}
        project={project}
        materials={store.materials}
        selectedId={materialId}
        query={query}
        onQuery={setQuery}
        onAdd={() => setAddOpen(true)}
        onChooseLibrary={() => setLibraryOpen(true)}
        hasConspects={hasConspects}
        conspectSummaryActive={conspectSummaryActive}
        menu={menuActions}
      />
      <main className="materials-document-area" ref={attachDocumentArea}>
        {store.error && <p className="materials-action-note" role="alert">{store.error}</p>}
        {conspectSummaryActive ? (
          <div className="materials-conspect-summary">
            {conspectSummary.loading ? (
              <LoadingState label="Загружаем сводный конспект" />
            ) : hasConspects ? (
              <Suspense fallback={<LoadingState label="Загружаем сводный конспект" />}>
                <ConspectSummary projectId={projectId} />
              </Suspense>
            ) : (
              <EmptyState title="Конспектов пока нет">
                <p>Сводный конспект появится, как только сохранится личный конспект темы.</p>
                <Link className="secondary-button" to={`/projects/${projectId}`}>Вернуться в рабочую область</Link>
              </EmptyState>
            )}
          </div>
        ) : !material ? (
          <MaterialOverview
            materials={store.materials}
            textbook={Boolean(textbook)}
            onOpen={(id) => navigate(`/projects/${projectId}/materials/${id}`)}
            onAdd={() => setAddOpen(true)}
            onChooseLibrary={() => setLibraryOpen(true)}
            onFindOnline={() => webSearch.current?.reveal()}
            onResearch={(id) => { setResearchMaterialIds([id]); setResearchOpen(true); }}
            onResearchProgress={() => navigate(`/projects/${projectId}/coverage`)}
            research={research}
            menu={menuActions}
            onReorder={(ids) => void store.reorder(ids)}
            webSearch={project ? (
              <MaterialsWebSearch
                ref={webSearch}
                projectId={projectId}
                nodes={project.program.nodes}
                variant={project.project.template_key}
                initialTopicId={searchTopicId}
              />
            ) : null}
          />
        ) : (
          <>
            <header className="materials-document-toolbar">
              <div className="materials-toolbar-slot" />
              <div className="materials-toolbar-tools">
                <SegmentedTabs
                  className="materials-view-mode-tabs"
                  label="Что показать"
                  value={viewMode}
                  tabs={[
                    ...(compareAvailable ? [{ value: "compare" as const, label: "Сравнение" }] : []),
                    ...(hasSource ? [{ value: "source" as const, label: presentation?.sourceLabel ?? "Оригинал" }] : []),
                    { value: "text" as const, label: "Текст" },
                  ]}
                  onChange={setViewMode}
                />
                <div className="materials-page-tools">
                  <IconButton label="Предыдущая страница" disabled={pageNumber <= 1} onClick={() => goToPage(pageNumber - 1)}><ChevronLeft size={15} /></IconButton>
                  <PageNumberInput page={pageNumber} pageCount={pageCount} onPageChange={goToPage} />
                  <IconButton label="Следующая страница" disabled={pageNumber >= pageCount} onClick={() => goToPage(pageNumber + 1)}><ChevronRight size={15} /></IconButton>
                </div>
                <DocumentSearchField
                  query={search.query}
                  matchLabel={search.label}
                  searching={search.loading}
                  onQueryChange={search.setQuery}
                  onQuerySubmit={search.step}
                />
                {(presentation?.supportsZoom || viewMode === "text") && <div className="materials-zoom-tools">
                  <IconButton label="Уменьшить" disabled={effectiveZoom <= 0.5} onClick={() => setZoom(Math.max(0.5, Number((effectiveZoom - 0.25).toFixed(2))))}><ZoomOut size={15} /></IconButton>
                  <Tooltip label={viewMode === "text" ? "Вернуть обычный кегль" : "Вписать страницу в окно"}>
                    <button
                      type="button"
                      className={`materials-zoom-readout ${zoom === "fit" ? "is-active" : ""}`.trim()}
                      onClick={() => setZoom("fit")}
                    >
                      {Math.round(effectiveZoom * 100)}%
                    </button>
                  </Tooltip>
                  <IconButton label="Увеличить" disabled={effectiveZoom >= 2} onClick={() => setZoom(Math.min(2, Number((effectiveZoom + 0.25).toFixed(2))))}><ZoomIn size={15} /></IconButton>
                </div>}
                {/* Ручная привязка к вопросам — инструмент экзамена; в учебнике кнопки нет. */}
                {!textbook && <Tooltip label={isExamStructureFile ? "Список вопросов не привязывается по фрагментам" : "Режим привязки (B)"}>
                  <IconButton
                    label="Режим привязки"
                    aria-pressed={bindingMode && documentBindingEnabled}
                    disabled={!documentBindingEnabled}
                    onClick={() => setBindingMode((value) => !value)}
                  >
                    <Link2 size={15} />
                  </IconButton>
                </Tooltip>}
                {documentBindingEnabled && bindingMode && selectedFragmentIds.length > 0 && (
                  <span className="materials-selection-hint">Выбрано: {selectedFragmentIds.length} · <Kbd>Enter</Kbd> привязать</span>
                )}
              </div>
              <div className="materials-toolbar-end">
                {outlineAvailable && <Tooltip label={showOutline ? "Скрыть оглавление" : "Показать оглавление"}>
                  <IconButton
                    label="Оглавление"
                    aria-pressed={showOutline}
                    onClick={() => {
                      if (documentWidth >= INLINE_OUTLINE_MIN_WIDTH) setInlineOutlineOpen((value) => !value);
                      else setOverlayOutlineOpen((value) => !value);
                    }}
                  ><ListTree size={15} /></IconButton>
                </Tooltip>}
                <Tooltip label={!page ? "Текст страницы станет доступен после разбора" : !(page.markdown || page.text).trim() ? "На странице нет текста для уборки" : "Предложить исправление оформления и спорных мест"}>
                  <IconButton label="Прибрать текст с ИИ" disabled={!page || !(page.markdown || page.text).trim()} onClick={() => setCleanupOpen(true)}>
                    <Sparkles size={15} />
                  </IconButton>
                </Tooltip>
                <Tooltip label={fullscreen ? "Выйти из полного экрана (F или Esc)" : "Открыть на весь экран (F)"}>
                  <IconButton
                    label={fullscreen ? "Выйти из полного экрана" : "Открыть на весь экран"}
                    aria-pressed={fullscreen}
                    onClick={() => setFullscreen((value) => !value)}
                  >
                    {fullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
                  </IconButton>
                </Tooltip>
              </div>
            </header>
            <div className={`materials-document-stage ${inlineOutline ? "has-outline" : ""} ${overlayOutline ? "has-overlay-outline" : ""}`.trim()}>
              {showOutline && viewerDetail && (
                <PdfOutline
                  outline={viewerDetail.outline}
                  outlineSource={viewerDetail.outline_source}
                  page={pageNumber}
                  pageCount={pageCount}
                  pageStates={viewerDetail.page_states}
                  showOcrReview={viewerDetail.parser_mode !== "fast"}
                  storageKey={material.id}
                  // Оглавление остаётся открытым и поверх документа: страницы листают подряд,
                  // закрывать панель после каждого перехода значило бы открывать её заново.
                  onPageChange={goToPage}
                />
              )}
              <DocumentStage
                mode={viewMode}
                storageKey={material.id}
                sourceLabel={presentation?.sourceLabel ?? "Исходник"}
                textLabel={presentation?.textLabel ?? "Текст"}
                canPrevPage={pageNumber > 1}
                canNextPage={pageNumber < pageCount}
                onPrevPage={pageCount > 1 ? () => goToPage(pageNumber - 1) : undefined}
                onNextPage={pageCount > 1 ? () => goToPage(pageNumber + 1) : undefined}
                source={viewerDetail ? (
                  <MaterialSourceView
                    material={viewerDetail}
                    page={displayedPage}
                    pageNumber={pageNumber}
                    revision={null}
                    terms={search.forms}
                    zoom={sourceZoom}
                    showRegions
                    focusedFragmentId={focusedFragmentId}
                    currentTime={0}
                    onTimeUpdate={() => undefined}
                    flow="paged"
                    pageCount={pageCount}
                    pageAspect={displayedPage && displayedPage.width > 0 ? displayedPage.height / displayedPage.width : 900 / 680}
                    scrollRef={attachScroll}
                  />
                ) : (
                  <div className="materials-document-center">
                    {detailError ? <ErrorState message={detailError} /> : <LoadingState label="Открываем исходник" />}
                  </div>
                )}
                text={
                  <div ref={textScrollRef} className="materials-document-scroll is-project-text" style={{ "--materials-zoom": textZoom } as React.CSSProperties}>
                    {pageError ? (
                      <div className="materials-document-center"><ErrorState message={pageError} /></div>
                    ) : displayedPage ? (
                      <DocumentView
                        projectId={projectId}
                        material={material}
                        page={displayedPage}
                        terms={search.forms}
                        binding={{
                          bindingMode: bindingMode && documentBindingEnabled,
                          activeNodeId: documentBindingEnabled ? activeNodeId : null,
                          boundFragmentIds: documentBindingEnabled ? boundFragmentIds : EMPTY_STRING_SET,
                          activeNodeFragmentIds: documentBindingEnabled ? activeNodeFragmentIds : EMPTY_STRING_SET,
                          selectedFragmentIds: documentBindingEnabled ? selectedFragmentIdSet : EMPTY_STRING_SET,
                          onFragmentActivate: handleFragmentActivate,
                          onBindBlock: handleBindBlock,
                          onFragmentUnbind: handleFragmentUnbind,
                          fragmentBindingTitles: documentBindingEnabled ? fragmentBindingTitles : EMPTY_TITLES_MAP,
                        }}
                      />
                    ) : material.status !== "ready" ? (
                      <div className="materials-processing-placeholder">
                        <StatusBadge tone={STATUS[material.status].tone}>{STATUS[material.status].label}</StatusBadge>
                        <h1>{material.display_name}</h1>
                        <p>{material.status === "ready_to_process"
                          ? "Текст ещё не подготовлен: запустите разбор на вкладке «Обработка»."
                          : "Страница ещё обрабатывается. Готовые страницы появляются здесь по мере разбора."}</p>
                      </div>
                    ) : <div className="materials-document-center"><LoadingState label="Открываем страницу" /></div>}
                  </div>
                }
              />
            </div>
          </>
        )}
      </main>
      {material && (
        <MaterialInspector
          projectId={projectId}
          material={material}
          activeTab={visibleInspectorTab}
          onTabChange={setInspectorTab}
          busy={store.busy}
          notice={notice}
          libraryLink={libraryLink}
          page={page}
          onRemove={() => setRemoveTarget(material)}
          onEdit={() => { if (page) { setEditText(page.text); setEditOpen(true); } }}
          onCleanup={() => setCleanupOpen(true)}
          onChanged={() => { void store.refresh(); refreshBindingData(); }}
          onError={(message) => say(message, "danger")}
          answersMaterial={answersMaterial}
          allowPurposeChoice={allowExamPurposes}
          order={{ position: store.materials.indexOf(material) + 1, total: store.materials.length }}
          onSaveFile={saveFileSettings}
          textbook={Boolean(textbook)}
          isExamStructureFile={isExamStructureFile}
          onDismissNotice={() => setNotice(null)}
          examStructureProps={{
            studyNodes,
            summary: bindings.summary,
            fragmentsBound,
            questionsWithMaterial,
            questionsWithoutMaterial,
            notice,
            onDismissNotice: () => setNotice(null),
          }}
          bindingsProps={{
            projectId,
            activeNode,
            studyNodeCount: studyNodes.length,
            onOpenPicker: () => { setPickerTarget("active"); setPickerOpen(true); },
            onPrevNode: () => stepActiveNode(-1),
            onNextNode: () => stepActiveNode(1),
            fragmentsBound,
            questionsWithMaterial,
            questionsWithoutMaterial,
            notice,
            onDismissNotice: () => setNotice(null),
            bindingMode,
            onToggleBindingMode: () => setBindingMode((value) => !value),
            selectedCount: selectedFragmentIds.length,
            onBindSelection: handleBindSelection,
            onClearSelection: () => setSelectedFragmentIds([]),
            bindingScope,
            onBindingScopeChange: setBindingScope,
            pageBindingCount: pageBindings.length,
            documentBindingCount: documentBindings.length,
            listedBindings: bindingScope === "page" ? pageBindings : documentBindings,
            nodeNumberById,
            focusedFragmentId,
            onSelectBinding: (binding) => {
              setFocusedFragmentId(binding.fragment_id);
              if (binding.page_number !== pageNumber) setPageNumber(binding.page_number);
            },
            focusedFragment,
            focusedFragmentBindings,
            onBindFocusedToActive: () => {
              if (activeNodeId && focusedFragmentId) void bindFragmentsToNode(activeNodeId, [focusedFragmentId]);
            },
            onOpenPickerForFocused: () => { setPickerTarget("fragment"); setPickerOpen(true); },
            onUnbind: (bindingId) => void unbindOne(bindingId),
            onRemoveAllInScope: () => void removeAllInScope(),
            headingSuggestions:
              answersSuggestions?.materialId === material.id ? answersSuggestions.items : [],
            onResolveHeading: (blockId, nodeId) => void resolveHeading(blockId, nodeId),
            canAutoMatch: material.status === "ready" && material.purposes.includes("reference_answers"),
            onOpenAutoMatch: () => setAutoMatchOpen(true),
            answerMatchState: answerMatch.state,
            answerMatchRunning: answerMatch.isRunning,
            onRetryAutoMatch: () => void answerMatch.run(),
            onDismissAutoMatch: answerMatch.dismiss,
          }}
        />
      )}
      <NodePickerDialog
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        tree={treeResult}
        onSelect={handlePickNode}
      />
      <AutoMatchDialog
        open={autoMatchOpen}
        onOpenChange={setAutoMatchOpen}
        onRunHeadings={() => void answerMatch.run()}
        onRunAi={() => setAiPlanOpen(true)}
        onImportText={() => void importAnswers()}
      />
      {material && (
        <AnswersAiPlanDialog
          open={aiPlanOpen}
          projectId={projectId}
          materialId={material.id}
          nodeNumberById={nodeNumberById}
          onOpenChange={setAiPlanOpen}
          onApplied={(result) => {
            refreshBindingData();
            void bindings.refreshSummary();
            setAnswersSuggestions({ materialId: material.id, items: result.suggestions });
            if (result.suggestions.length) setInspectorTab("bindings");
          }}
        />
      )}
      <AddMaterialDialog
        open={addOpen}
        busy={store.busy}
        uploadStatus={store.uploadStatus}
        answersMaterial={answersMaterial}
        allowExamPurposes={allowExamPurposes}
        studyRole={newStudyRole}
        onOpenChange={setAddOpen}
        onFile={(file, role, purposes) => void addFile(file, role, purposes)}
        onText={(name, text) => void addText(name, text)}
        onExternal={(kind, url) => void addExternal(kind, url)}
        onReplaceAnswers={releaseAnswersMaterial}
      />
      <LibraryMaterialPickerDialog
        open={libraryOpen}
        projectId={projectId}
        title="Выбрать материалы из Библиотеки"
        multiple
        allowPurposeSelection
        allowExamPurposes={allowExamPurposes}
        existingStudySourceCount={store.materials.filter((item) => item.purposes.includes("study_source")).length}
        defaultStudyRole={newStudyRole}
        answersMaterial={answersMaterial}
        onReplaceAnswers={releaseAnswersMaterial}
        onOpenChange={setLibraryOpen}
        onAttached={async (selected) => {
          await store.refresh();
          const first = selected[0];
          if (first) navigate(`/projects/${projectId}/materials/${first.id}`);
        }}
        onCreateNew={() => {
          setLibraryOpen(false);
          setAddOpen(true);
        }}
      />
      <Dialog
        open={editOpen}
        onOpenChange={setEditOpen}
        title={`Исправить текст страницы ${page?.page_number ?? ""}`}
        description="Исправление создаст новую ревизию фрагментов и блоков. Исходный файл останется без изменений."
        footer={<><Button variant="ghost" onClick={() => setEditOpen(false)}>Отменить</Button><Button disabled={editBusy || !editText.trim()} onClick={() => void savePageText()}>Сохранить исправление</Button></>}
      >
        <label className="materials-page-editor">Текст страницы<textarea autoFocus value={editText} onChange={(event) => setEditText(event.target.value)} /></label>
      </Dialog>
      {material && page && (
        <AiCleanupPanel
          open={cleanupOpen && (!requestedCleanupJob || page.page_number === pageNumber)}
          projectId={projectId}
          material={material}
          page={page}
          onOpenChange={(open) => {
            setCleanupOpen(open);
            if (!open && requestedCleanupJob) {
              const next = new URLSearchParams(searchParams);
              next.delete("job");
              setSearchParams(next, { replace: true });
            }
          }}
          initialJobId={requestedCleanupJob}
          onManualEdit={() => {
            setEditText(page.markdown || page.text);
            setEditOpen(true);
          }}
          onReload={reloadCurrentPage}
          onApplied={(result, undo) => {
            setPage(result.page);
            refreshBindingData();
            void store.refresh();
            say("Текст страницы обновлён новой ревизией.", "success", () => {
              void updateMaterialPageText(
                projectId,
                material.id,
                page.page_number,
                undo.originalText,
                { revision: undo.appliedRevision, sourceHash: undo.appliedSourceHash },
              ).then((restored) => {
                setPage(restored.page);
                refreshBindingData();
                void store.refresh();
                say("Применение отменено: исходный снимок сохранён новой ревизией.", "info");
              }).catch((caught) => {
                say(caught instanceof Error ? caught.message : "Не удалось отменить применение", "danger");
              });
            });
          }}
        />
      )}
      <ConfirmDialog
        open={removeTarget !== null}
        onOpenChange={(open) => { if (!open) setRemoveTarget(null); }}
        title={`Убрать «${removeTarget?.display_name ?? ""}» из проекта?`}
        confirmLabel="Убрать материал"
        destructive
        onConfirm={() => {
          if (!removeTarget) return;
          const removedId = removeTarget.id;
          const removal = store.detach(removedId);
          // Открытый материал исчез из проекта — к списку; другой убирается на месте.
          if (removal && removedId === materialId) void removal.then(() => navigate(`/projects/${projectId}/materials`));
        }}
      >
        <p>
          Файл отвяжется от этого проекта и останется в Библиотеке.
          {allowExamPurposes ? " Ответы, уже импортированные из него, сохранятся." : ""}
        </p>
      </ConfirmDialog>
      <Dialog
        open={renameTarget !== null}
        onOpenChange={(open) => { if (!open) setRenameTarget(null); }}
        title="Переименовать в проекте"
        description="Название меняется только здесь; в Библиотеке и других проектах у файла останется своё."
        footer={<>
          <Button variant="ghost" onClick={() => setRenameTarget(null)}>Отменить</Button>
          <Button disabled={!renameTarget?.value.trim() || store.busy} onClick={submitRename}>Сохранить</Button>
        </>}
      >
        <form className="materials-text-form" onSubmit={(event) => { event.preventDefault(); submitRename(); }}>
          <label>Название<input
            autoFocus
            value={renameTarget?.value ?? ""}
            onChange={(event) => setRenameTarget((current) => current && { ...current, value: event.target.value })}
          /></label>
        </form>
      </Dialog>
      {textbook && (
        <ResearchLaunchDialog
          open={researchOpen}
          projectId={projectId}
          initialMaterialIds={researchMaterialIds}
          onOpenChange={setResearchOpen}
          onStarted={() => navigate(`/projects/${projectId}/coverage`)}
        />
      )}
    </div>
  );
}

export function Materials() {
  return <MaterialSurface />;
}

export function SourceViewer() {
  return <MaterialSurface />;
}
