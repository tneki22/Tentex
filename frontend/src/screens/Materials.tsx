import {
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  FileImage,
  FileText,
  Globe,
  Files,
  Info,
  Link2,
  Maximize2,
  Minimize2,
  Pause,
  Play,
  Plus,
  RotateCcw,
  Search,
  Sparkles,
  Trash2,
  Undo2,
  Unlink,
  Upload,
  Video,
  Pencil,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import type { BindingFragmentRead } from "../api/bindings";
import { linkAnswersMaterial, listBindings } from "../api/bindings";
import {
  getMaterialPage,
  getMaterialCapabilities,
  materialFragmentAssetUrl,
  importMaterialReferenceAnswers,
  materialPageImageUrl,
  updateMaterialPageText,
} from "../api/materials";
import type {
  MaterialBlockRead,
  MaterialFragmentRead,
  MaterialPageRead,
  MaterialPurpose,
  MaterialRead,
  MaterialCapabilities,
  SourceRole,
} from "../api/materials";
import { getProject, undoProjectAction, type LatestUndoableAction, type ProjectDetail } from "../api/projects";
import { ProjectNav, QualityBadge, TaskRow } from "../components/domain";
import type { BackgroundTask } from "../components/domain";
import {
  Button,
  ConfirmDialog,
  Dialog,
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
import { useProjectMaterials } from "../hooks/useProjectMaterials";
import { buildProgramTree, filterProgramTree, flattenProgramTree, type ProgramTreeNode } from "./programTree";

const STUDY_NODE_TYPES = new Set(["topic", "subpoint"]);
const isStudyNode = (node: ProgramTreeNode): boolean =>
  STUDY_NODE_TYPES.has(node.node_type) && node.is_in_current_program && !node.is_archived;

const STATUS: Record<MaterialRead["status"], { label: string; tone: "neutral" | "info" | "warning" | "danger" | "success" }> = {
  ready_to_process: { label: "Готов к разбору", tone: "neutral" },
  queued: { label: "В очереди", tone: "info" },
  processing: { label: "Разбирается", tone: "info" },
  paused: { label: "На паузе", tone: "warning" },
  ready: { label: "Готов", tone: "success" },
  failed: { label: "Ошибка", tone: "danger" },
};

const PURPOSE: Record<MaterialPurpose, string> = {
  exam_structure: "Структура экзамена",
  reference_answers: "Эталонные ответы",
  study_source: "Учебный источник",
};

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / 1024 ** 2).toFixed(1)} МБ`;
}

function fileCountLabel(count: number): string {
  const mod100 = count % 100;
  const mod10 = count % 10;
  if (mod100 >= 11 && mod100 <= 14) return `${count} файлов`;
  if (mod10 === 1) return `${count} файл`;
  if (mod10 >= 2 && mod10 <= 4) return `${count} файла`;
  return `${count} файлов`;
}

function taskFor(material: MaterialRead): BackgroundTask | null {
  if (!material.task || material.task.state === "completed") return null;
  return {
    id: material.task.id,
    kind: "parse",
    subject: material.display_name,
    unit: "страниц",
    done: material.task.done,
    total: material.task.total,
    etaMinutes: null,
    state: material.task.state,
    error: material.task.error ?? undefined,
  };
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
}

function MaterialCatalog({
  projectId,
  project,
  materials,
  selectedId,
  query,
  onQuery,
  onAdd,
}: CatalogProps) {
  const textbook = project?.project.workspace_variant === "textbook";
  const visible = materials.filter((material) =>
    material.display_name.toLocaleLowerCase("ru").includes(query.toLocaleLowerCase("ru")));
  const examFiles = visible.filter((material) => material.purposes.some((purpose) =>
    purpose === "exam_structure" || purpose === "reference_answers"));
  const sources = visible.filter((material) => !examFiles.includes(material));

  const items = (group: MaterialRead[]) => group.map((material) => (
    <div
      className={`materials-catalog-item ${selectedId === material.id ? "is-active" : ""}`.trim()}
      key={material.id}
    >
      <Link to={`/projects/${projectId}/materials/${material.id}`}>
        <MaterialIcon material={material} />
        <span>
          <strong>{material.display_name}</strong>
          <small>{STATUS[material.status].label}</small>
        </span>
        {(material.status === "failed" || material.ocr_low_page_count > 0) && (
          <span className="materials-attention-dot tone-warning" />
        )}
      </Link>
    </div>
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
        <Link className={!selectedId ? "materials-catalog-overview is-active" : "materials-catalog-overview"} to={`/projects/${projectId}/materials`}>
          <Files size={15} />
          <span><strong>Все материалы</strong><small>{fileCountLabel(materials.length)}</small></span>
        </Link>
        {examFiles.length > 0 && <section><h2>Экзамен</h2>{items(examFiles)}</section>}
        {sources.length > 0 && <section><h2>Учебные источники</h2>{items(sources)}</section>}
      </nav>
      <ProjectNav
        projectId={projectId}
        active="materials"
        textbook={textbook}
        modules={project?.project.enabled_modules}
        counts={{ materials: materials.length }}
      />
    </aside>
  );
}

function MaterialOverview({
  materials,
  onOpen,
  onAdd,
}: {
  materials: MaterialRead[];
  onOpen: (id: string) => void;
  onAdd: () => void;
}) {
  return (
    <div className="materials-document-stage">
      <div className="materials-document-scroll">
        <div className="materials-overview">
          <header>
            <div>
              <p className="materials-kicker">Приоритет этапа 5</p>
              <h1>Материалы экзамена</h1>
              <p>Загрузите список вопросов, эталонные ответы и учебные источники.</p>
            </div>
            <Button onClick={onAdd}><Upload size={15} /> Добавить материал</Button>
          </header>
          {materials.length === 0 ? (
            <section className="materials-empty-state">
              <Files size={28} />
              <h2>Материалов пока нет</h2>
              <p>Начните с фотографии списка вопросов — быстрый OCR разберёт её в фоне.</p>
              <Button onClick={onAdd}>Выбрать файл</Button>
            </section>
          ) : (
            <div className="materials-overview-table" role="table" aria-label="Материалы проекта">
              <div className="materials-overview-row is-head" role="row">
                <span>Материал</span><span>Назначение</span><span>Страницы</span><span>Качество</span><span>Состояние</span>
              </div>
              {materials.map((material) => (
                <button
                  className="materials-overview-row"
                  type="button"
                  role="row"
                  key={material.id}
                  onClick={() => onOpen(material.id)}
                >
                  <strong>{material.display_name}</strong>
                  <span>{material.purposes.map((purpose) => PURPOSE[purpose]).join(", ")}</span>
                  <span>{material.page_count ?? "—"}</span>
                  <span>{material.ocr_low_page_count ? `${material.ocr_low_page_count} low` : "—"}</span>
                  <StatusBadge tone={STATUS[material.status].tone}>{STATUS[material.status].label}</StatusBadge>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function AddMaterialDialog({
  open,
  busy,
  answersMaterial,
  onOpenChange,
  onFile,
  onText,
  onExternal,
  onReplaceAnswers,
}: {
  open: boolean;
  busy: boolean;
  /** Уже загруженные эталонные ответы: второй такой файл проект не держит. */
  answersMaterial: MaterialRead | null;
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
  const [name, setName] = useState("Эталонные ответы.txt");
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
      title={textMode ? "Вставить эталонные ответы" : externalMode ? externalMode === "url" ? "Добавить веб-страницу" : "Добавить YouTube-транскрипт" : "Добавить материал"}
      description={textMode
        ? "Заголовок ответа должен точно совпадать с названием вопроса программы."
        : externalMode
          ? externalMode === "url" ? "Tentex сохранит локальный снимок читаемого текста и дату получения." : "Tentex сохранит субтитры с временными метками, а не видеопоток."
        : "Выберите назначение сейчас; изменить его можно будет позже."}
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
          <button type="button" disabled={busy} onClick={() => choose("reference", ["exam_structure"])}>
            <FileImage size={18} /><span><strong>Список вопросов</strong><small>PDF, фото или текст структуры экзамена</small></span><ChevronRight size={15} />
          </button>
          <button type="button" disabled={busy} onClick={() => chooseAnswers("file")}>
            <FileText size={18} />
            <span>
              <strong>Эталонные ответы</strong>
              <small>
                {answersMaterial
                  ? `Сейчас: ${answersMaterial.display_name}. Файл ответов один — можно заменить`
                  : "После разбора сам ляжет на вопросы по заголовкам"}
              </small>
            </span>
            <ChevronRight size={15} />
          </button>
          <button type="button" disabled={busy} onClick={() => choose("main", ["study_source"])}>
            <BookOpen size={18} /><span><strong>Учебный источник</strong><small>PDF, DOCX, TXT, MD или изображение</small></span><ChevronRight size={15} />
          </button>
          <button type="button" disabled={busy} onClick={() => chooseAnswers("text")}>
            <Plus size={18} /><span><strong>Вставить текст ответов</strong><small>Без создания отдельного файла вручную</small></span><ChevronRight size={15} />
          </button>
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
        title="Заменить файл эталонных ответов?"
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
          Сейчас эталонные ответы берутся из «{answersMaterial?.display_name}». Проект
          держит один такой файл: с прежнего снимется назначение, и он останется в
          материалах как учебный источник.
        </p>
        <p>Уже заполненные эталоны и привязки старого файла сохранятся.</p>
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
  viewMode,
  query,
  binding,
}: {
  projectId: string;
  material: MaterialRead;
  page: MaterialPageRead;
  viewMode: "original" | "text";
  query: string;
  binding: DocumentBindingProps;
}) {
  if (viewMode === "original" && (material.media_type === "application/pdf" || material.media_type.startsWith("image/"))) {
    return (
      <div className="materials-original-page">
        <div className="materials-original-canvas">
          <img src={materialPageImageUrl(projectId, material.id, page.page_number)} alt={`Страница ${page.page_number} файла ${material.display_name}`} />
          <div className="materials-bbox-layer" aria-hidden="true">
            {page.fragments.map((fragment) => <span key={fragment.id} style={{ left: `${fragment.bbox[0] * 100}%`, top: `${fragment.bbox[1] * 100}%`, width: `${(fragment.bbox[2] - fragment.bbox[0]) * 100}%`, height: `${(fragment.bbox[3] - fragment.bbox[1]) * 100}%` }} />)}
          </div>
        </div>
      </div>
    );
  }

  const blockById = new Map(page.blocks.map((block) => [block.id, block]));
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
  let previousBlockId: string | null = null;
  return (
    <div className={`materials-pages is-text ${page.quality === "ocr_low" ? "is-ocr-low" : ""}`.trim()}>
      <article className={`materials-page ${page.quality === "ocr_low" ? "is-ocr-low" : ""}`.trim()}>
        <header className="materials-page-head">
          <span>Страница {page.page_number}</span>
          <QualityBadge quality={page.quality} />
        </header>
        {page.fragments.map((fragment) => {
          const block = blockById.get(fragment.block_id);
          const isNewBlock = fragment.block_id !== previousBlockId;
          previousBlockId = fragment.block_id;
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

          return (
            <div className="materials-document-block-wrap" key={fragment.id}>
              {isNewBlock && bindingMode && block && (
                <div className="materials-block-actions">
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
              <section
                className={className}
                role={clickable ? "button" : undefined}
                tabIndex={clickable ? 0 : undefined}
                aria-pressed={clickable ? isActiveBound : undefined}
                onClick={clickable ? (event) => onFragmentActivate(fragment.id, { shiftKey: event.shiftKey }) : undefined}
                onKeyDown={clickable ? (event: ReactKeyboardEvent<HTMLElement>) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onFragmentActivate(fragment.id, { shiftKey: event.shiftKey });
                  }
                } : undefined}
              >
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
                <FragmentBody fragment={fragment} query={query} projectId={projectId} materialId={material.id} />
              </section>
            </div>
          );
        })}
        <footer>Фрагментов: {page.fragments.length}</footer>
      </article>
    </div>
  );
}

/**
 * Оформление исходника: заголовок остаётся заголовком, пункт списка получает
 * висячий отступ по своему уровню вложенности (маркер живёт в самом тексте —
 * так его видно и в поиске, и при копировании).
 */
function FragmentBody({
  fragment,
  query,
  projectId,
  materialId,
}: {
  fragment: MaterialFragmentRead;
  query: string;
  projectId: string;
  materialId: string;
}) {
  if (fragment.element_kind === "image" && fragment.has_asset) {
    return (
      <img
        className="materials-document-image"
        src={materialFragmentAssetUrl(projectId, materialId, fragment.id)}
        alt="Изображение из документа"
        loading="lazy"
      />
    );
  }
  if (fragment.element_kind === "heading") return <h2>{highlight(fragment.text, query)}</h2>;
  if (fragment.element_kind === "list") {
    return (
      <p
        className="materials-document-list-item"
        style={{ "--list-level": fragment.structure_level ?? 1 } as React.CSSProperties}
      >
        {highlight(fragment.text, query)}
      </p>
    );
  }
  return <p>{highlight(fragment.text, query)}</p>;
}

function highlight(text: string, query: string) {
  const needle = query.trim().toLocaleLowerCase("ru");
  if (!needle) return text;
  const index = text.toLocaleLowerCase("ru").indexOf(needle);
  if (index < 0) return text;
  return <>{text.slice(0, index)}<mark>{text.slice(index, index + needle.length)}</mark>{text.slice(index + needle.length)}</>;
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
  material,
  busy,
  onStart,
  onControl,
  onImport,
  onEdit,
  onReparse,
  onLinkAnswers,
  capabilities,
  notice,
  onDismissNotice,
}: {
  material: MaterialRead;
  busy: boolean;
  onStart: (mode: "fast" | "textbook") => void;
  onControl: (action: "pause" | "resume" | "retry") => void;
  onImport: () => void;
  onEdit: () => void;
  onReparse: () => void;
  onLinkAnswers: () => void;
  capabilities: MaterialCapabilities | null;
  notice: NoticeState | null;
  onDismissNotice: () => void;
}) {
  const task = taskFor(material);
  return (
    <div className="materials-inspector-content">
      <NoticeLine notice={notice} onDismiss={onDismissNotice} />
      {task && (
        <TaskRow
          task={task}
          onPause={() => onControl("pause")}
          onResume={() => onControl("resume")}
          onRetry={() => onControl("retry")}
        />
      )}
      {material.status === "ready_to_process" && <section className="materials-processing-section">
        <h3>Оценка обработки</h3>
        <p>{material.page_count ?? 1} стр. · OCR: {material.scan_page_count} · примерно {material.estimated_seconds ?? 1} сек. · локально, 0 ₽.</p>
        <Button disabled={busy} onClick={() => onStart("fast")}>Быстро · PP-OCRv5</Button>
        <Button variant="secondary" disabled={busy || !capabilities?.textbook_available} title={capabilities?.textbook_reason} onClick={() => onStart("textbook")}>Учебник · PaddleOCR-VL</Button>
        <Button variant="ghost" disabled title={capabilities?.cloud_reason}>Облако · этап 7</Button>
        <Button variant="ghost" disabled title={capabilities?.cloud_reason}>Максимум · этап 7</Button>
        <Button variant="ghost" disabled title={capabilities?.cloud_reason}>Эксперт · этап 7</Button>
      </section>}
      {material.status === "paused" && <Button disabled={busy} onClick={() => onControl("resume")}><Play size={14} /> Возобновить</Button>}
      {material.status === "processing" && <Button variant="secondary" disabled={busy} onClick={() => onControl("pause")}><Pause size={14} /> Поставить на паузу</Button>}
      {material.status === "failed" && <Button disabled={busy} onClick={() => onControl("retry")}><RotateCcw size={14} /> Повторить</Button>}
      {material.status === "ready" && material.purposes.includes("reference_answers") && (
        <section className="materials-processing-section">
          <h3>Эталонные ответы</h3>
          <p>
            Разделы этого файла ложатся на вопросы программы сами — по совпадению
            заголовка с формулировкой вопроса. Из тех же разделов заполняются эталоны.
          </p>
          <Button disabled={busy} onClick={onLinkAnswers}><Link2 size={14} /> Привязать заново</Button>
          <Button variant="ghost" disabled={busy} onClick={onImport}>Импортировать эталоны текстом</Button>
        </section>
      )}
      {material.status === "ready" && <Button variant="secondary" disabled={busy} onClick={onEdit}><Pencil size={14} />Исправить текст страницы</Button>}
      {material.status === "ready" && (
        <Tooltip label="Пересобрать страницы, списки и отступы текущим разбором">
          <Button variant="ghost" disabled={busy} onClick={onReparse}><RotateCcw size={14} /> Разобрать заново</Button>
        </Tooltip>
      )}
      {material.diagnostics.length > 0 && <section className="materials-processing-section"><h3>Диагностика</h3><ul>{material.diagnostics.map((item) => <li key={item}>{item === "formula_possible" ? "Возможны формулы — сверяйте с оригиналом" : item === "audio_transcription_required" ? "Нужна локальная транскрипция аудио" : item}</li>)}</ul>{material.ocr_low_page_count > 0 && <p>Есть страницы низкого качества. Проверьте оригинал или выберите следующий доступный режим.</p>}</section>}
      {material.error && <ErrorState title="Разбор остановился" message={material.error} />}
    </div>
  );
}

function FileTab({
  material,
  onRemove,
  notice,
  onDismissNotice,
}: {
  material: MaterialRead;
  onRemove: () => void;
  notice: NoticeState | null;
  onDismissNotice: () => void;
}) {
  return (
    <div className="materials-inspector-content">
      <NoticeLine notice={notice} onDismiss={onDismissNotice} />
      <dl className="materials-file-details">
        <div><dt>Файл</dt><dd>{material.original_name}</dd></div>
        <div><dt>Используется как</dt><dd>{material.purposes.map((purpose) => PURPOSE[purpose]).join(", ")}</dd></div>
        <div><dt>Размер</dt><dd>{sizeLabel(material.size_bytes)}</dd></div>
        <div><dt>Страницы</dt><dd>{material.page_count ?? "—"}</dd></div>
        <div><dt>Сканов</dt><dd>{material.scan_page_count}</dd></div>
        <div><dt>Плохо распознано</dt><dd>{material.ocr_low_page_count ? `${material.ocr_low_page_count} стр.` : "нет"}</dd></div>
      </dl>
      {material.source_url && <a className="materials-text-link" href={material.source_url} target="_blank" rel="noreferrer">Открыть исходную ссылку</a>}
      {material.outline.length > 0 && <details className="materials-outline"><summary>Оглавление · {material.outline.length}</summary><ol>{material.outline.map((item, index) => <li key={`${item.page}-${index}`} style={{ paddingInlineStart: `${Math.max(0, item.level - 1) * 12}px` }}><span>{item.title}</span><small>с. {item.page}</small></li>)}</ol></details>}
      <Button variant="ghost" className="materials-remove-button" onClick={onRemove}><Trash2 size={14} /> Убрать из проекта</Button>
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
  focusedFragmentId: string | null;
  onSelectBinding: (binding: BindingFragmentRead) => void;
  focusedFragment: MaterialFragmentRead | null;
  focusedFragmentBindings: BindingFragmentRead[];
  onBindFocusedToActive: () => void;
  onOpenPickerForFocused: () => void;
  onUnbind: (bindingId: string) => void;
}

function BindingsTab({
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
  focusedFragmentId,
  onSelectBinding,
  focusedFragment,
  focusedFragmentBindings,
  onBindFocusedToActive,
  onOpenPickerForFocused,
  onUnbind,
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

      <Tooltip label="Проход 2 привяжет остальное автоматически на этапе 8 — тогда же появится подтверждение перед отправкой данных">
        <Button variant="ghost" disabled>Сопоставить автоматически · этап 8</Button>
      </Tooltip>

      <NoticeLine notice={notice} onDismiss={onDismissNotice} />

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
                <strong>{binding.node_title}</strong>
                <small>{bindingPreview(binding.text)} · стр. {binding.page_number}</small>
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
            <QualityBadge quality={focusedFragment.quality} />
          </div>
          <p>{focusedFragment.text}</p>
          {focusedFragmentBindings.length > 0 && (
            <ul className="materials-fragment-questions">
              {focusedFragmentBindings.map((binding) => (
                <li key={binding.id}>
                  <span>{binding.node_title}</span>
                  <IconButton label={`Снять привязку к вопросу «${binding.node_title}»`} onClick={() => onUnbind(binding.id)}><Unlink size={13} /></IconButton>
                </li>
              ))}
            </ul>
          )}
          <div className="materials-button-stack">
            {activeNode && !alreadyBoundToActive && (
              <Button onClick={onBindFocusedToActive}><Link2 size={14} /> Привязать к выбранному вопросу</Button>
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

function MaterialInspector({
  material,
  activeTab,
  onTabChange,
  busy,
  notice,
  onStart,
  onControl,
  onImport,
  onRemove,
  onEdit,
  onReparse,
  onLinkAnswers,
  capabilities,
  bindingsProps,
  textbook,
  onDismissNotice,
}: {
  material: MaterialRead;
  activeTab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
  busy: boolean;
  notice: NoticeState | null;
  onStart: (mode: "fast" | "textbook") => void;
  onControl: (action: "pause" | "resume" | "retry") => void;
  onImport: () => void;
  onRemove: () => void;
  onEdit: () => void;
  onReparse: () => void;
  onLinkAnswers: () => void;
  capabilities: MaterialCapabilities | null;
  bindingsProps: BindingsTabProps;
  textbook: boolean;
  onDismissNotice: () => void;
}) {
  return (
    <aside className="materials-inspector" aria-label="Действия с материалом">
      <div className="materials-inspector-tabs" role="tablist" aria-label="Разделы инспектора">
        {(["bindings", "processing", "file"] as const).map((tab) => (
          <button type="button" role="tab" aria-selected={activeTab === tab} className={activeTab === tab ? "is-active" : ""} key={tab} onClick={() => onTabChange(tab)}>{TAB_LABELS[tab]}</button>
        ))}
      </div>
      <div className="materials-inspector-scroll">
        {activeTab === "bindings" && (
          textbook ? (
            <div className="materials-inspector-content">
              <NoticeLine notice={notice} onDismiss={onDismissNotice} />
              <p className="materials-muted">
                Привязки учебника к программе — отдельный раздел «Привязки», он появится
                после этапа 7 (эскиз — <code>SCREENS.md</code>). Ручная привязка фрагментов
                к вопросам в этой вкладке работает только в экзаменационном проекте.
              </p>
            </div>
          ) : <BindingsTab {...bindingsProps} />
        )}
        {activeTab === "processing" && (
          <ProcessingTab material={material} busy={busy} onStart={onStart} onControl={onControl} onImport={onImport} onEdit={onEdit} onReparse={onReparse} onLinkAnswers={onLinkAnswers} capabilities={capabilities} notice={notice} onDismissNotice={onDismissNotice} />
        )}
        {activeTab === "file" && <FileTab material={material} onRemove={onRemove} notice={notice} onDismissNotice={onDismissNotice} />}
      </div>
    </aside>
  );
}

function MaterialSurface() {
  const { projectId = "", materialId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const store = useProjectMaterials(projectId);
  const bindings = useBindings(projectId);
  const [query, setQuery] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [removeOpen, setRemoveOpen] = useState(false);
  const [reparseOpen, setReparseOpen] = useState(false);
  const [pageNumber, setPageNumber] = useState(1);
  const [page, setPage] = useState<MaterialPageRead | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"original" | "text">("text");
  const [notice, setNotice] = useState<NoticeState | null>(null);
  const [capabilities, setCapabilities] = useState<MaterialCapabilities | null>(null);
  const [documentQuery, setDocumentQuery] = useState("");
  /** «fit» — вписать страницу целиком: с ним документ открывается, а не с обрезанного 100%. */
  const [zoom, setZoom] = useState<number | "fit">("fit");
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const [fullscreen, setFullscreen] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const scrollObserver = useRef<ResizeObserver | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [editText, setEditText] = useState("");
  const [editBusy, setEditBusy] = useState(false);
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("bindings");
  const [bindingMode, setBindingMode] = useState(false);
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
  const hasOriginal = material?.media_type === "application/pdf"
    || material?.media_type.startsWith("image/");
  const textbook = project?.project.workspace_variant === "textbook";

  const treeResult = useMemo(() => {
    try { return buildProgramTree(project?.program.nodes ?? []); }
    catch { return []; }
  }, [project?.program.nodes]);
  const studyNodes = useMemo(() => flattenProgramTree(treeResult).filter(isStudyNode), [treeResult]);
  const activeNode = studyNodes.find((node) => node.id === activeNodeId) ?? null;
  const refreshBindingData = useCallback(() => setDataVersion((value) => value + 1), []);

  const pageCount = material?.page_count ?? 1;
  // Размеры листа заданы в layout.css (.materials-page): держим их синхронно,
  // иначе «вписать страницу» промахнётся.
  const fitZoom = useMemo(() => {
    if (viewport.width === 0 || viewport.height === 0) return 1;
    const byWidth = (viewport.width - 96) / 680;
    const byHeight = (viewport.height - 96) / 900;
    return Math.min(2, Math.max(0.5, Math.min(byWidth, byHeight)));
  }, [viewport]);
  // В режиме «Текст» лист тянется по ширине колонки, вписывать нечего:
  // там «по размеру» — это обычный масштаб, а зум меняет кегль.
  const effectiveZoom = zoom === "fit" ? (viewMode === "original" ? fitZoom : 1) : zoom;

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
      if (target !== current) scrollRef.current?.scrollTo({ top: 0 });
      return target;
    });
  }, [pageCount]);

  useEffect(() => {
    const controller = new AbortController();
    void getProject(projectId, controller.signal).then(setProject).catch(() => undefined);
    return () => controller.abort();
  }, [projectId]);

  useEffect(() => {
    const controller = new AbortController();
    void getMaterialCapabilities(controller.signal).then(setCapabilities).catch(() => undefined);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!material || material.status !== "ready") {
      setPage(null);
      return;
    }
    const controller = new AbortController();
    setPageError(null);
    void getMaterialPage(projectId, material.id, pageNumber, controller.signal)
      .then(setPage)
      .catch((caught) => {
        if (!controller.signal.aborted) setPageError(caught instanceof Error ? caught.message : "Страница не загрузилась");
      });
    return () => controller.abort();
  }, [material, pageNumber, projectId]);

  useEffect(() => {
    setSelectedFragmentIds([]);
    setLastClickedFragmentId(null);
  }, [material?.id, pageNumber]);

  useEffect(() => {
    setFocusedFragmentId(null);
  }, [material?.id]);

  useEffect(() => {
    const pageParam = Number(searchParams.get("page"));
    if (Number.isFinite(pageParam) && pageParam > 0) setPageNumber(pageParam);
    const focusParam = searchParams.get("focus");
    if (focusParam) {
      setFocusedFragmentId(focusParam);
      setInspectorTab("bindings");
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
      titles.set(binding.fragment_id, [...(titles.get(binding.fragment_id) ?? []), binding.node_title]);
    }
    return titles;
  }, [pageBindings]);
  const selectedFragmentIdSet = useMemo(() => new Set(selectedFragmentIds), [selectedFragmentIds]);
  const focusedFragment = page?.fragments.find((fragment) => fragment.id === focusedFragmentId) ?? null;
  const focusedFragmentBindings = useMemo(
    () => pageBindings.filter((binding) => binding.fragment_id === focusedFragmentId),
    [pageBindings, focusedFragmentId],
  );
  const fragmentsBound = bindings.summary.reduce((sum, item) => sum + item.fragment_count, 0);
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
    const created = await store.createExternal({ kind, url, source_role: "additional", purposes: ["study_source"] });
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

  async function linkAnswers() {
    if (!material) return;
    try {
      const result = await linkAnswersMaterial(projectId, material.id);
      refreshBindingData();
      void bindings.refreshSummary();
      const parts = [
        `Разделов привязано: ${result.linked_sections}`,
        `фрагментов: ${result.linked_fragments}`,
        `эталонов создано: ${result.created_answers}`,
      ];
      if (result.updated_answers) parts.push(`обновлено: ${result.updated_answers}`);
      if (result.kept_answers) parts.push(`оставлено своих: ${result.kept_answers}`);
      if (result.unmatched_headings.length) {
        parts.push(`не нашлось вопросов для ${result.unmatched_headings.length} заголовков`);
      }
      if (result.duplicate_headings.length) {
        parts.push(`формулировка повторяется в программе: ${result.duplicate_headings.length}`);
      }
      say(`${parts.join(", ")}.`, result.linked_sections > 0 ? "success" : "danger");
    } catch (caught) {
      say(caught instanceof Error ? caught.message : "Привязать не удалось", "danger");
    }
  }

  async function importAnswers() {
    if (!material) return;
    try {
      const result = await importMaterialReferenceAnswers(projectId, material.id);
      say(`Создано эталонов: ${result.created}; пропущено существующих: ${result.skipped_existing}.`, "success");
    } catch (caught) {
      say(caught instanceof Error ? caught.message : "Импорт не выполнен", "danger");
    }
  }

  if (store.loading) return <LoadingState label="Загружаем материалы" />;

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
      />
      <main className="materials-document-area">
        {store.error && <p className="materials-action-note" role="alert">{store.error}</p>}
        {!material ? (
          <MaterialOverview materials={store.materials} onOpen={(id) => navigate(`/projects/${projectId}/materials/${id}`)} onAdd={() => setAddOpen(true)} />
        ) : (
          <>
            <header className="materials-document-toolbar">
              <div className="materials-toolbar-slot" />
              <div className="materials-toolbar-tools">
                <Button disabled={!hasOriginal} variant={viewMode === "original" ? "secondary" : "ghost"} onClick={() => setViewMode("original")}>Оригинал</Button>
                <Button variant={viewMode === "text" ? "secondary" : "ghost"} onClick={() => setViewMode("text")}>Текст</Button>
                <div className="materials-page-tools">
                  <IconButton label="Предыдущая страница" disabled={pageNumber <= 1} onClick={() => goToPage(pageNumber - 1)}><ChevronLeft size={15} /></IconButton>
                  <span>{pageNumber} / {pageCount}</span>
                  <IconButton label="Следующая страница" disabled={pageNumber >= pageCount} onClick={() => goToPage(pageNumber + 1)}><ChevronRight size={15} /></IconButton>
                </div>
                <label className="materials-search-tools is-open"><Search size={14} /><span className="sr-only">Найти на странице</span><input type="search" value={documentQuery} onChange={(event) => setDocumentQuery(event.target.value)} placeholder="Найти на странице" /></label>
                <div className="materials-zoom-tools">
                  <IconButton label="Уменьшить" disabled={effectiveZoom <= 0.5} onClick={() => setZoom(Math.max(0.5, Number((effectiveZoom - 0.25).toFixed(2))))}><ZoomOut size={15} /></IconButton>
                  <Tooltip label={viewMode === "original" ? "Вписать страницу в окно" : "Вернуть обычный кегль"}>
                    <button
                      type="button"
                      className={`materials-zoom-readout ${zoom === "fit" ? "is-active" : ""}`.trim()}
                      onClick={() => setZoom("fit")}
                    >
                      {Math.round(effectiveZoom * 100)}%
                    </button>
                  </Tooltip>
                  <IconButton label="Увеличить" disabled={effectiveZoom >= 2} onClick={() => setZoom(Math.min(2, Number((effectiveZoom + 0.25).toFixed(2))))}><ZoomIn size={15} /></IconButton>
                </div>
                <Tooltip label={textbook ? "Привязки появятся после этапа 7 (учебник)" : "Режим привязки (B)"}>
                  <IconButton
                    label="Режим привязки"
                    aria-pressed={bindingMode && !textbook}
                    disabled={textbook}
                    onClick={() => setBindingMode((value) => !value)}
                  >
                    <Link2 size={15} />
                  </IconButton>
                </Tooltip>
                {!textbook && bindingMode && selectedFragmentIds.length > 0 && (
                  <span className="materials-selection-hint">Выбрано: {selectedFragmentIds.length} · <Kbd>Enter</Kbd> привязать</span>
                )}
              </div>
              <div className="materials-toolbar-end">
                <Tooltip label="Списки, отступы и абзацы уже расставляет разбор. Модель сможет переписать спорные места, когда на этапе 7 появится шлюз">
                  <IconButton label="Прибрать текст с ИИ · этап 7" disabled>
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
            <div className="materials-document-stage">
              {pageCount > 1 && (
                <>
                  <button
                    type="button"
                    className="materials-page-zone is-prev"
                    aria-label="Предыдущая страница"
                    disabled={pageNumber <= 1}
                    onClick={() => goToPage(pageNumber - 1)}
                  >
                    <ChevronLeft size={22} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className="materials-page-zone is-next"
                    aria-label="Следующая страница"
                    disabled={pageNumber >= pageCount}
                    onClick={() => goToPage(pageNumber + 1)}
                  >
                    <ChevronRight size={22} aria-hidden="true" />
                  </button>
                </>
              )}
              <div ref={attachScroll} className="materials-document-scroll" style={{ "--materials-zoom": effectiveZoom } as React.CSSProperties}>
                {material.status !== "ready" ? (
                  <div className="materials-processing-placeholder">
                    <StatusBadge tone={STATUS[material.status].tone}>{STATUS[material.status].label}</StatusBadge>
                    <h1>{material.display_name}</h1>
                    <p>Страница появится после завершения фонового разбора.</p>
                  </div>
                ) : pageError ? (
                  <div className="materials-document-center"><ErrorState message={pageError} /></div>
                ) : page
                  ? (
                    <DocumentView
                      projectId={projectId}
                      material={material}
                      page={page}
                      viewMode={viewMode}
                      query={documentQuery}
                      binding={{
                        bindingMode: bindingMode && !textbook,
                        activeNodeId,
                        boundFragmentIds,
                        activeNodeFragmentIds,
                        selectedFragmentIds: selectedFragmentIdSet,
                        onFragmentActivate: handleFragmentActivate,
                        onBindBlock: handleBindBlock,
                        onFragmentUnbind: handleFragmentUnbind,
                        fragmentBindingTitles,
                      }}
                    />
                  )
                  : <div className="materials-document-center"><LoadingState label="Открываем страницу" /></div>}
              </div>
            </div>
          </>
        )}
      </main>
      {material && (
        <MaterialInspector
          material={material}
          activeTab={inspectorTab}
          onTabChange={setInspectorTab}
          busy={store.busy}
          notice={notice}
          onStart={(mode) => void store.start(material.id, mode)}
          onControl={(action) => void store.control(material.id, action)}
          onImport={() => void importAnswers()}
          onRemove={() => setRemoveOpen(true)}
          onEdit={() => { if (page) { setEditText(page.text); setEditOpen(true); } }}
          onReparse={() => setReparseOpen(true)}
          onLinkAnswers={() => void linkAnswers()}
          capabilities={capabilities}
          textbook={Boolean(textbook)}
          onDismissNotice={() => setNotice(null)}
          bindingsProps={{
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
          }}
        />
      )}
      <NodePickerDialog
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        tree={treeResult}
        onSelect={handlePickNode}
      />
      <AddMaterialDialog
        open={addOpen}
        busy={store.busy}
        answersMaterial={answersMaterial}
        onOpenChange={setAddOpen}
        onFile={(file, role, purposes) => void addFile(file, role, purposes)}
        onText={(name, text) => void addText(name, text)}
        onExternal={(kind, url) => void addExternal(kind, url)}
        onReplaceAnswers={releaseAnswersMaterial}
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
      {material && (
        <ConfirmDialog
          open={reparseOpen}
          onOpenChange={setReparseOpen}
          title={`Разобрать «${material.display_name}» заново?`}
          confirmLabel="Разобрать заново"
          onConfirm={() => {
            void store.start(material.id, "fast");
            setInspectorTab("processing");
            say("Разбор запущен заново. Списки и отступы появятся после его окончания.", "info");
          }}
        >
          <p>
            Страницы соберутся текущим разбором: абзацы перестанут рваться по строкам,
            списки получат отступы. Исходный файл не меняется, эталонные ответы остаются.
          </p>
          <p>
            Привязки переедут на новые фрагменты по совпадению текста. Те, чей текст
            изменился, станут осиротевшими — их придётся поставить заново.
          </p>
        </ConfirmDialog>
      )}
      {material && (
        <ConfirmDialog
          open={removeOpen}
          onOpenChange={setRemoveOpen}
          title={`Убрать «${material.display_name}» из проекта?`}
          confirmLabel="Убрать материал"
          destructive
          onConfirm={() => {
            const removal = store.detach(material.id);
            if (removal) void removal.then(() => navigate(`/projects/${projectId}/materials`));
          }}
        >
          <p>Файл отвяжется от этого проекта. Эталоны, уже импортированные из него, сохранятся.</p>
        </ConfirmDialog>
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
