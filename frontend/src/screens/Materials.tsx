import {
  AlignJustify,
  ArrowLeft,
  BookOpen,
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleCheck,
  Download,
  ExternalLink,
  File,
  FileImage,
  Files,
  FileText,
  Filter,
  Inbox,
  Layers,
  Library,
  Link as LinkIcon,
  ListTree,
  Maximize2,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Pencil,
  Plus,
  RefreshCw,
  ScanText,
  Search,
  Settings,
  SlidersHorizontal,
  Trash2,
  Undo2,
  Unlink,
  Upload,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import {
  Button,
  Checkbox,
  ConfirmDialog,
  Dialog,
  IconButton,
  Menu,
  PanelResizeHandle,
  Popover,
  SegmentedTabs,
  StatusBadge,
  Tooltip,
} from "../components/ui";
import {
  CostEstimate,
  MachineMark,
  OfflineNotice,
  QualityBadge,
  TaskRow,
} from "../components/domain";
import type { BackgroundTask, PageQuality } from "../components/domain";

type MaterialKind = "overview" | "summary" | "answers" | "source" | "scan";
type ViewMode = "original" | "text";
type InspectorTab = "questions" | "answers" | "bindings" | "processing" | "file";
type AnswerStatus = "confirmed" | "machine" | "review" | "missing" | "manual";
type BindingStatus = "confirmed" | "machine" | "manual" | "removed";

interface DemoBlock {
  id: string;
  kind: "heading" | "paragraph" | "note";
  text: string;
  answerId?: string;
  bindingId?: string;
}

interface DemoPage {
  number: number;
  eyebrow: string;
  title: string;
  blocks: DemoBlock[];
  quality: PageQuality;
}

interface DemoMaterial {
  id: string;
  kind: MaterialKind;
  name: string;
  originalName: string;
  roles: string[];
  sourceType?: string;
  fileType: string;
  size: string;
  totalPages: number;
  quality: PageQuality;
  status: string;
  statusTone: "neutral" | "success" | "warning" | "info";
  pages: DemoPage[];
  defaultTab: InspectorTab | null;
  added: string;
}

interface DemoAnswer {
  id: string;
  number: number;
  title: string;
  status: AnswerStatus;
  page: number | null;
  excerpt: string;
  origin: string;
}

interface DemoBinding {
  id: string;
  question: string;
  page: number;
  fragment: string;
  status: BindingStatus;
  quality: PageQuality;
  position: number;
}

type SummaryTone = "info" | "success" | "warning" | "danger" | "neutral";

interface SummaryMetric {
  label: string;
  value: number;
  tone: SummaryTone;
}

const ANSWERS: DemoAnswer[] = [
  {
    id: "transactions",
    number: 21,
    title: "Понятие транзакции. Свойства ACID",
    status: "machine",
    page: 11,
    excerpt: "Транзакция — логически неделимая последовательность операций с данными. Её свойства описываются акронимом ACID.",
    origin: "Ответы по базам данных.pdf — стр. 11",
  },
  {
    id: "isolation",
    number: 22,
    title: "Уровни изоляции транзакций",
    status: "confirmed",
    page: 12,
    excerpt: "Стандарт SQL выделяет уровни Read Uncommitted, Read Committed, Repeatable Read и Serializable.",
    origin: "Ответы по базам данных.pdf — стр. 12",
  },
  {
    id: "locking",
    number: 23,
    title: "Блокировки и взаимоблокировки",
    status: "review",
    page: 13,
    excerpt: "Блокировка ограничивает конкурентный доступ к объекту базы данных до завершения критической операции.",
    origin: "Формулировка вопроса изменена после импорта",
  },
  {
    id: "recovery",
    number: 24,
    title: "Журнализация и восстановление",
    status: "missing",
    page: null,
    excerpt: "",
    origin: "Эталон пока не добавлен",
  },
];

const BINDINGS: DemoBinding[] = [
  {
    id: "acid",
    question: "Понятие транзакции. Свойства ACID",
    page: 47,
    fragment: "Атомарность, согласованность, изоляция и долговечность образуют набор гарантий ACID.",
    status: "machine",
    quality: "native",
    position: 34,
  },
  {
    id: "isolation-levels",
    question: "Уровни изоляции транзакций",
    page: 47,
    fragment: "Чем слабее уровень изоляции, тем больше аномалий конкурентного выполнения допускает система.",
    status: "confirmed",
    quality: "native",
    position: 39,
  },
  {
    id: "deadlocks",
    question: "Блокировки и взаимоблокировки",
    page: 48,
    fragment: "Цикл ожидания блокировок приводит к взаимоблокировке; СУБД выбирает одну транзакцию жертвой.",
    status: "manual",
    quality: "native",
    position: 73,
  },
];

const MATERIALS: DemoMaterial[] = [
  {
    id: "overview",
    kind: "overview",
    name: "Все материалы",
    originalName: "",
    roles: [],
    fileType: "",
    size: "",
    totalPages: 0,
    quality: "native",
    status: "3 файла",
    statusTone: "neutral",
    pages: [],
    defaultTab: null,
    added: "",
  },
  {
    id: "summary",
    kind: "summary",
    name: "Эталоны проекта",
    originalName: "",
    roles: ["Сводка"],
    fileType: "",
    size: "",
    totalPages: 0,
    quality: "native",
    status: "24 из 28",
    statusTone: "neutral",
    pages: [],
    defaultTab: "answers",
    added: "",
  },
  {
    id: "answers",
    kind: "answers",
    name: "Ответы по базам данных.pdf",
    originalName: "БД_ответы_2026_final.pdf",
    roles: ["Структура экзамена", "Эталонные ответы"],
    fileType: "PDF",
    size: "2,8 МБ",
    totalPages: 36,
    quality: "native",
    status: "2 проверить",
    statusTone: "warning",
    defaultTab: "answers",
    added: "28.07.2026",
    pages: [
      {
        number: 11,
        eyebrow: "Раздел 4 — Транзакции",
        title: "21. Понятие транзакции. Свойства ACID",
        quality: "native",
        blocks: [
          { id: "a11-1", kind: "paragraph", answerId: "transactions", text: "Транзакция — логически неделимая последовательность операций с данными, переводящая базу из одного согласованного состояния в другое." },
          { id: "a11-2", kind: "paragraph", answerId: "transactions", text: "Атомарность означает выполнение всех операций транзакции или ни одной. Согласованность сохраняет ограничения базы, изоляция скрывает промежуточные результаты, долговечность гарантирует сохранение подтверждённых изменений." },
          { id: "a11-note", kind: "note", text: "Важно назвать все четыре свойства и кратко объяснить каждое." },
        ],
      },
      {
        number: 12,
        eyebrow: "Раздел 4 — Транзакции",
        title: "22. Уровни изоляции транзакций",
        quality: "native",
        blocks: [
          { id: "a12-1", kind: "paragraph", answerId: "isolation", text: "Стандарт SQL выделяет уровни Read Uncommitted, Read Committed, Repeatable Read и Serializable." },
          { id: "a12-2", kind: "paragraph", answerId: "isolation", text: "Усиление уровня устраняет грязное чтение, неповторяемое чтение и фантомы, но уменьшает доступный параллелизм." },
        ],
      },
      {
        number: 13,
        eyebrow: "Раздел 4 — Транзакции",
        title: "23. Блокировки и взаимоблокировки",
        quality: "native",
        blocks: [
          { id: "a13-1", kind: "paragraph", answerId: "locking", text: "Блокировки бывают разделяемыми и исключительными. Совместимость режимов определяет, какие операции могут выполняться параллельно." },
          { id: "a13-2", kind: "paragraph", answerId: "locking", text: "Взаимоблокировка возникает, когда транзакции образуют цикл ожидания ресурсов. СУБД обнаруживает цикл и откатывает одну из транзакций." },
        ],
      },
    ],
  },
  {
    id: "source",
    kind: "source",
    name: "Методические указания.pdf",
    originalName: "МУ_Базы_данных.pdf",
    roles: ["Учебный источник"],
    sourceType: "Методичка",
    fileType: "PDF",
    size: "8,4 МБ",
    totalPages: 113,
    quality: "native",
    status: "4 проверить",
    statusTone: "info",
    defaultTab: "bindings",
    added: "29.07.2026",
    pages: [
      {
        number: 46,
        eyebrow: "Глава 5 — Управление транзакциями",
        title: "5.1. Понятие транзакции",
        quality: "native",
        blocks: [
          { id: "s46-1", kind: "paragraph", text: "Транзакция объединяет несколько операций чтения и записи в одну единицу обработки. Границы задаются командами начала, подтверждения и отката." },
          { id: "s46-2", kind: "paragraph", text: "До подтверждения изменения могут быть отменены. После подтверждения система обязана восстановить их даже после сбоя." },
        ],
      },
      {
        number: 47,
        eyebrow: "Глава 5 — Управление транзакциями",
        title: "5.2. Гарантии ACID и изоляция",
        quality: "native",
        blocks: [
          { id: "s47-1", kind: "paragraph", bindingId: "acid", text: "Атомарность, согласованность, изоляция и долговечность образуют набор гарантий ACID. Они описывают поведение транзакции при конкуренции и сбоях." },
          { id: "s47-2", kind: "paragraph", bindingId: "isolation-levels", text: "Чем слабее уровень изоляции, тем больше аномалий конкурентного выполнения допускает система. Выбор уровня является компромиссом между строгостью и пропускной способностью." },
          { id: "s47-note", kind: "note", text: "Пример с двумя переводами между счетами показывает нарушение изоляции." },
        ],
      },
      {
        number: 48,
        eyebrow: "Глава 5 — Управление транзакциями",
        title: "5.3. Блокировки",
        quality: "native",
        blocks: [
          { id: "s48-1", kind: "paragraph", text: "Двухфазный протокол разделяет получение и освобождение блокировок. Строгий вариант удерживает блокировки записи до завершения транзакции." },
          { id: "s48-2", kind: "paragraph", bindingId: "deadlocks", text: "Цикл ожидания блокировок приводит к взаимоблокировке; СУБД выбирает одну транзакцию жертвой, откатывает её и освобождает ресурсы." },
        ],
      },
    ],
  },
  {
    id: "scan",
    kind: "scan",
    name: "Фото страницы 47.jpg",
    originalName: "IMG_20260729_184105.jpg",
    roles: ["Учебный источник"],
    sourceType: "Дополнительный материал",
    fileType: "JPG",
    size: "4,1 МБ",
    totalPages: 1,
    quality: "ocr_low",
    status: "OCR низкого качества",
    statusTone: "warning",
    defaultTab: "processing",
    added: "29.07.2026",
    pages: [
      {
        number: 1,
        eyebrow: "Фотография страницы",
        title: "Журнализация изменений",
        quality: "ocr_low",
        blocks: [
          { id: "o1", kind: "paragraph", text: "Журнап предназна4ен для фиксации изменений до того, как изменённые страницы будут записаны на диск." },
          { id: "o2", kind: "paragraph", text: "Правипо WAL требует сначала записать журнальную запись, а затем соответствующую страницу базы данных." },
          { id: "o3", kind: "note", text: "Уверенность распознавания 61% — сверьте текст с фотографией." },
        ],
      },
    ],
  },
];

const ANSWER_LABELS: Record<AnswerStatus, { label: string; tone: "success" | "info" | "warning" | "neutral" }> = {
  confirmed: { label: "подтверждён", tone: "success" },
  machine: { label: "автоматически", tone: "info" },
  review: { label: "проверить", tone: "warning" },
  missing: { label: "нет ответа", tone: "neutral" },
  manual: { label: "вручную", tone: "neutral" },
};

const TAB_LABELS: Record<InspectorTab, string> = {
  questions: "Вопросы",
  answers: "Ответы",
  bindings: "Привязки",
  processing: "Обработка",
  file: "Файл",
};

function tabsFor(material: DemoMaterial): InspectorTab[] {
  if (material.kind === "overview") return [];
  if (material.kind === "summary") return ["answers"];
  if (material.kind === "answers") return ["questions", "answers", "processing", "file"];
  if (material.kind === "source") return ["bindings", "processing", "file"];
  return ["processing", "file"];
}

function iconFor(material: DemoMaterial) {
  if (material.kind === "overview") return Files;
  if (material.kind === "summary") return BookOpen;
  if (material.kind === "scan") return FileImage;
  return FileText;
}

function highlightText(text: string, query: string): ReactNode {
  const normalized = query.trim().toLocaleLowerCase("ru");
  if (!normalized) return text;
  const index = text.toLocaleLowerCase("ru").indexOf(normalized);
  if (index < 0) return text;
  return (
    <>
      {text.slice(0, index)}
      <mark>{text.slice(index, index + normalized.length)}</mark>
      {text.slice(index + normalized.length)}
    </>
  );
}

function SummaryTable({ label, metrics }: { label: string; metrics: SummaryMetric[] }) {
  return (
    <dl className="materials-summary-table" aria-label={label}>
      {metrics.map((metric) => (
        <div className={`is-${metric.tone}`} key={metric.label}>
          <dt>{metric.label}</dt>
          <dd>{metric.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Materials() {
  const { projectId = "demo" } = useParams();
  const [selectedId, setSelectedId] = useState("answers");
  const [viewMode, setViewMode] = useState<ViewMode>("original");
  const [activeTab, setActiveTab] = useState<InspectorTab>("answers");
  const [page, setPage] = useState(11);
  const [zoom, setZoom] = useState(100);
  const [markersVisible, setMarkersVisible] = useState(true);
  const [catalogOpen, setCatalogOpen] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [focusMode, setFocusMode] = useState(false);
  const [catalogWidth, setCatalogWidth] = useState(280);
  const [inspectorWidth, setInspectorWidth] = useState(356);
  const [fileQuery, setFileQuery] = useState("");
  const [documentQuery, setDocumentQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [selectedAnswerId, setSelectedAnswerId] = useState("transactions");
  const [selectedBindingId, setSelectedBindingId] = useState("acid");
  const [answers, setAnswers] = useState(ANSWERS);
  const [bindings, setBindings] = useState(BINDINGS);
  const [bindingScope, setBindingScope] = useState<"page" | "document">("document");
  const [notice, setNotice] = useState("Выберите строку справа или фрагмент в документе.");
  const [addOpen, setAddOpen] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [costOpen, setCostOpen] = useState(false);
  const [rolesOpen, setRolesOpen] = useState(false);
  const [removeOpen, setRemoveOpen] = useState(false);
  const [manualText, setManualText] = useState("");
  const [scanTaskState, setScanTaskState] = useState<BackgroundTask["state"]>("paused");
  const [filters, setFilters] = useState({ attention: false, processing: false, lowOcr: false });

  const selected = MATERIALS.find((material) => material.id === selectedId) ?? MATERIALS[2];
  const selectedAnswer = answers.find((answer) => answer.id === selectedAnswerId) ?? answers[0];
  const selectedBinding = bindings.find((binding) => binding.id === selectedBindingId) ?? bindings[0];
  const availableTabs = tabsFor(selected);
  const pages = selected.pages;
  const currentPageIndex = Math.max(0, pages.findIndex((candidate) => candidate.number === page));
  const currentPage = pages[currentPageIndex] ?? pages[0];
  const filteredBindings = bindingScope === "page"
    ? bindings.filter((binding) => binding.page === page)
    : bindings;
  const visibleMaterials = MATERIALS.filter((material) => material.name.toLocaleLowerCase("ru").includes(fileQuery.toLocaleLowerCase("ru")));
  const activeFilters = Object.values(filters).filter(Boolean).length;
  const searchMatches = selected.pages.flatMap((candidate) => candidate.blocks)
    .filter((block) => documentQuery.trim() && block.text.toLocaleLowerCase("ru").includes(documentQuery.trim().toLocaleLowerCase("ru"))).length;

  const rootStyle = {
    "--materials-catalog-width": `${catalogOpen && !focusMode ? catalogWidth : 0}px`,
    "--materials-catalog-handle": catalogOpen && !focusMode ? "10px" : "0px",
    "--materials-inspector-width": `${inspectorOpen && !focusMode ? inspectorWidth : 0}px`,
    "--materials-inspector-handle": inspectorOpen && !focusMode ? "10px" : "0px",
    "--materials-zoom": zoom / 100,
  } as CSSProperties;

  function selectMaterial(material: DemoMaterial) {
    setSelectedId(material.id);
    setViewMode(material.kind === "scan" ? "text" : "original");
    setPage(material.pages[0]?.number ?? 1);
    setActiveTab(material.defaultTab ?? "file");
    setInspectorOpen(material.kind !== "overview");
    setDocumentQuery("");
    setNotice(material.kind === "overview" ? "Выберите файл из каталога." : "Файл открыт. Действия зависят от выбранной вкладки.");
  }

  function goToPage(nextPage: number) {
    setPage(nextPage);
    requestAnimationFrame(() => document.getElementById(`materials-page-${selected.id}-${nextPage}`)?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  function selectBinding(bindingId: string) {
    const binding = bindings.find((candidate) => candidate.id === bindingId);
    if (!binding) return;
    setSelectedBindingId(binding.id);
    setActiveTab("bindings");
    setInspectorOpen(true);
    goToPage(binding.page);
    setNotice(`Выбран фрагмент на странице ${binding.page}.`);
  }

  function selectAnswer(answerId: string) {
    const answer = answers.find((candidate) => candidate.id === answerId);
    if (!answer) return;
    setSelectedAnswerId(answer.id);
    if (answer.page !== null && selected.kind === "answers") goToPage(answer.page);
  }

  function setStubNotice(action: string) {
    setNotice(`${action} — в макете показана точка входа; данные не отправляются на сервер.`);
  }

  function renderOverview() {
    return (
      <div className="materials-overview">
        <header>
          <div>
            <p className="materials-kicker">Базы данных — экзамен</p>
            <h1>Все материалы</h1>
            <p>Три файла, 150 страниц. Файл ответов и два учебных источника.</p>
          </div>
          <Button onClick={() => setAddOpen(true)}><Plus size={15} /> Добавить материал</Button>
        </header>
        <div className="materials-overview-table" role="table" aria-label="Материалы проекта">
          <div className="materials-overview-row is-head" role="row">
            <span>Файл</span><span>Роль</span><span>Обработка</span><span>Качество</span><span>Результат</span>
          </div>
          {MATERIALS.filter((material) => !["overview", "summary"].includes(material.kind)).map((material) => (
            <button className="materials-overview-row" type="button" role="row" key={material.id} onClick={() => selectMaterial(material)}>
              <strong>{material.name}</strong>
              <span>{material.roles[0]}</span>
              <span>{material.kind === "scan" ? "на паузе" : "готов"}</span>
              <QualityBadge quality={material.quality} />
              <span>{material.status}</span>
            </button>
          ))}
        </div>
      </div>
    );
  }

  function renderSummaryDocument() {
    return (
      <div className="materials-summary-document">
        <header>
          <p className="materials-kicker">Эталоны проекта</p>
          <h1>Базы данных — экзамен</h1>
          <span>28 вопросов. Ответы собраны из файлов и ручного ввода.</span>
        </header>
        {answers.filter((answer) => answer.status !== "missing").map((answer) => (
          <button type="button" key={answer.id} className={selectedAnswerId === answer.id ? "is-active" : ""} onClick={() => selectAnswer(answer.id)}>
            <small>Вопрос {answer.number}</small>
            <strong>{answer.title}</strong>
            <p>{answer.excerpt}</p>
          </button>
        ))}
      </div>
    );
  }

  function renderDocument() {
    if (selected.kind === "overview") return renderOverview();
    if (selected.kind === "summary") return renderSummaryDocument();

    return (
      <div className={`materials-pages is-${viewMode}`}>
        {pages.map((documentPage) => (
          <article
            className={`materials-page ${documentPage.quality === "ocr_low" ? "is-ocr-low" : ""}`.trim()}
            id={`materials-page-${selected.id}-${documentPage.number}`}
            key={documentPage.number}
            aria-label={`Страница ${documentPage.number}`}
          >
            <header className="materials-page-head">
              <span>{documentPage.eyebrow}</span>
              <QualityBadge quality={documentPage.quality} />
            </header>
            <h2>{documentPage.title}</h2>
            {documentPage.blocks.map((block) => {
              const binding = block.bindingId ? bindings.find((candidate) => candidate.id === block.bindingId) : null;
              const isSelectedBinding = Boolean(binding && binding.id === selectedBindingId);
              const isSelectedAnswer = Boolean(block.answerId && block.answerId === selectedAnswerId);
              const className = [
                "materials-document-block",
                block.kind === "note" ? "is-note" : "",
                binding ? "is-bound" : "",
                binding?.status === "machine" ? "is-machine" : "",
                binding?.status === "removed" ? "is-removed" : "",
                isSelectedBinding || isSelectedAnswer ? "is-selected" : "",
                block.answerId ? "is-answer" : "",
              ].filter(Boolean).join(" ");

              return (
                <div
                  className={className}
                  key={block.id}
                  role={binding || block.answerId ? "button" : undefined}
                  tabIndex={binding || block.answerId ? 0 : undefined}
                  onClick={() => binding ? selectBinding(binding.id) : block.answerId ? selectAnswer(block.answerId) : undefined}
                  onKeyDown={(event) => {
                    if ((event.key === "Enter" || event.key === " ") && (binding || block.answerId)) {
                      event.preventDefault();
                      if (binding) selectBinding(binding.id);
                      else if (block.answerId) selectAnswer(block.answerId);
                    }
                  }}
                >
                  {binding && binding.status !== "removed" && (
                    <span className="materials-fragment-pin" aria-label={`Связан с вопросом: ${binding.question}`}>
                      <LinkIcon size={12} />
                    </span>
                  )}
                  <p>{highlightText(block.text, documentQuery)}</p>
                </div>
              );
            })}
            <footer>— {documentPage.number} —</footer>
          </article>
        ))}
      </div>
    );
  }

  function renderQuestionsTab() {
    return (
      <div className="materials-inspector-content">
        <SummaryTable
          label="Сводка вопросов"
          metrics={[
            { label: "Вопросы", value: 28, tone: "info" },
            { label: "В Программе", value: 24, tone: "success" },
            { label: "Новые", value: 2, tone: "neutral" },
            { label: "Проверить", value: 2, tone: "warning" },
          ]}
        />
        <Button onClick={() => setStubNotice("Сверка со списком вопросов завершена: найдено четыре изменения")}>Сверить со списком вопросов</Button>
        <div className="materials-compact-list">
          {answers.map((answer) => (
            <button type="button" key={answer.id} onClick={() => selectAnswer(answer.id)}>
              <span>{answer.number}</span>
              <strong>{answer.title}</strong>
              {answer.status === "review" ? <StatusBadge tone="warning">проверить</StatusBadge> : <StatusBadge tone="neutral">в программе</StatusBadge>}
            </button>
          ))}
        </div>
        <div className="materials-button-row">
          <Button variant="secondary" onClick={() => setStubNotice("Открыт диф импорта")}>Открыть диф</Button>
          <Link className="text-button" to={`/projects/${projectId}/program`}>Открыть вопросы экзамена</Link>
        </div>
        <Button variant="ghost" onClick={() => setStubNotice("Повторное извлечение поставлено в очередь")}><RefreshCw size={14} /> Повторить извлечение</Button>
      </div>
    );
  }

  function renderAnswersTab() {
    const state = ANSWER_LABELS[selectedAnswer.status];
    return (
      <div className="materials-inspector-content">
        <SummaryTable
          label="Сводка эталонных ответов"
          metrics={[
            { label: "Вопросы", value: 28, tone: "info" },
            { label: "Сопоставлено", value: 24, tone: "success" },
            { label: "Проверить", value: 2, tone: "warning" },
            { label: "Без ответа", value: 2, tone: "danger" },
          ]}
        />
        <div className="materials-filter-chips" aria-label="Фильтр эталонов">
          <button type="button" className="is-active">Все</button>
          <button type="button">Проверить</button>
          <button type="button">Без ответа</button>
        </div>
        <div className="materials-answer-list" aria-label="Вопросы и эталоны">
          {answers.map((answer) => {
            const label = ANSWER_LABELS[answer.status];
            return (
              <button type="button" className={answer.id === selectedAnswer.id ? "is-active" : ""} key={answer.id} onClick={() => selectAnswer(answer.id)}>
                <span>{answer.number}</span>
                <span><strong>{answer.title}</strong><small>{label.label}</small></span>
              </button>
            );
          })}
        </div>
        <section className="materials-selection-card">
          <div className="materials-selection-head">
            <StatusBadge tone={state.tone}>{state.label}</StatusBadge>
            {selectedAnswer.status === "machine" && <MachineMark origin="сопоставлено локально" />}
          </div>
          <h3>{selectedAnswer.title}</h3>
          {selectedAnswer.excerpt ? <p>{selectedAnswer.excerpt}</p> : <p className="materials-muted">Эталон для этого вопроса пока не добавлен.</p>}
          <small>{selectedAnswer.origin}</small>
          <div className="materials-button-stack">
            {selectedAnswer.status === "machine" && (
              <Button onClick={() => {
                setAnswers((current) => current.map((answer) => answer.id === selectedAnswer.id ? { ...answer, status: "confirmed" } : answer));
                setNotice("Сопоставление эталона подтверждено.");
              }}><Check size={14} /> Подтвердить</Button>
            )}
            {selectedAnswer.status === "missing" ? (
              <>
                <Button onClick={() => setManualOpen(true)}><Pencil size={14} /> Добавить вручную</Button>
                <Button variant="secondary" onClick={() => setNotice("Выделите фрагмент ответа в центральном документе.")}>Выбрать из документа</Button>
              </>
            ) : (
              <>
                <Button variant="secondary" onClick={() => setNotice("Выберите новый фрагмент в документе или добавьте текст вручную.")}>Изменить фрагмент</Button>
                <Button variant="ghost" onClick={() => setManualOpen(true)}>Дополнить вручную</Button>
              </>
            )}
            <Link className="materials-text-link" to={`/projects/${projectId}`}>Открыть в Рабочей области <ExternalLink size={13} /></Link>
          </div>
        </section>
      </div>
    );
  }

  function renderBindingsTab() {
    const visible = selectedBinding.status !== "removed";
    return (
      <div className="materials-inspector-content">
        <SummaryTable
          label="Сводка привязок"
          metrics={[
            { label: "Блоки", value: 63, tone: "info" },
            { label: "Отнесено", value: 48, tone: "success" },
            { label: "Проверить", value: 4, tone: "warning" },
            { label: "Вне Программы", value: 11, tone: "neutral" },
          ]}
        />
        <Button onClick={() => setCostOpen(true)}>Сопоставить с вопросами</Button>
        <SegmentedTabs
          label="Область списка привязок"
          value={bindingScope}
          tabs={[{ value: "page", label: "Страница" }, { value: "document", label: "Документ" }]}
          onChange={setBindingScope}
        />
        <div className="materials-binding-list" aria-label="Привязки документа">
          {filteredBindings.length ? filteredBindings.map((binding) => (
            <button type="button" className={binding.id === selectedBinding.id ? "is-active" : ""} key={binding.id} onClick={() => selectBinding(binding.id)}>
              <span className={`materials-binding-line is-${binding.status}`} />
              <span><strong>{binding.question}</strong><small>стр. {binding.page} — {binding.status === "machine" ? "машинная" : binding.status === "manual" ? "ручная" : binding.status === "removed" ? "снята" : "подтверждена"}</small></span>
            </button>
          )) : <p className="materials-list-empty">На этой странице привязок нет.</p>}
        </div>
        <section className="materials-selection-card">
          <div className="materials-selection-head">
            <QualityBadge quality={selectedBinding.quality} />
            {selectedBinding.status === "machine" && <MachineMark origin="проход 2" onUndo={() => setStubNotice("Машинная привязка отменена")} />}
          </div>
          <h3>{selectedBinding.question}</h3>
          <p>{selectedBinding.fragment}</p>
          <div className="materials-provenance">
            <span>Страница {selectedBinding.page}</span>
            <span>Фрагмент → страница → файл</span>
          </div>
          {visible ? (
            <div className="materials-button-stack">
              {selectedBinding.status === "machine" && (
                <Button onClick={() => {
                  setBindings((current) => current.map((binding) => binding.id === selectedBinding.id ? { ...binding, status: "confirmed" } : binding));
                  setNotice("Машинная привязка подтверждена.");
                }}><Check size={14} /> Подтвердить</Button>
              )}
              <Button variant="secondary" onClick={() => setNotice("Справа открыт выбор другого вопроса для фрагмента.")}><LinkIcon size={14} /> Изменить привязку</Button>
              <Button variant="ghost" onClick={() => setNotice("Фрагмент можно связать с несколькими вопросами.")}>Привязать ещё к вопросу</Button>
              <Button variant="ghost" onClick={() => {
                setBindings((current) => current.map((binding) => binding.id === selectedBinding.id ? { ...binding, status: "removed" } : binding));
                setNotice("Привязка снята. Действие можно отменить.");
              }}><Unlink size={14} /> Это не по теме</Button>
            </div>
          ) : (
            <Button variant="secondary" onClick={() => {
              setBindings((current) => current.map((binding) => binding.id === selectedBinding.id ? { ...binding, status: "machine" } : binding));
              setNotice("Снятие привязки отменено.");
            }}><Undo2 size={14} /> Отменить снятие</Button>
          )}
        </section>
        <div className="materials-button-row">
          <Button variant="ghost" onClick={() => setStubNotice("Открыта очередь предложений")}>Очередь предложений</Button>
          <Button variant="ghost" onClick={() => setStubNotice("Открыто Неразобранное")}>Неразобранное</Button>
        </div>
      </div>
    );
  }

  function renderProcessingTab() {
    const task: BackgroundTask = {
      id: "ocr-photo",
      kind: "ocr",
      subject: selected.name,
      unit: "страниц",
      done: scanTaskState === "running" ? 0 : 0,
      total: 1,
      etaMinutes: scanTaskState === "running" ? 1 : null,
      state: scanTaskState,
    };

    return (
      <div className="materials-inspector-content">
        <SummaryTable
          label="Сводка обработки"
          metrics={selected.kind === "scan"
            ? [
                { label: "Страницы", value: 1, tone: "info" },
                { label: "Готово", value: 0, tone: "success" },
                { label: "OCR low", value: 1, tone: "warning" },
              ]
            : [
                { label: "Страницы", value: selected.totalPages, tone: "info" },
                { label: "Готово", value: selected.totalPages, tone: "success" },
                { label: "OCR low", value: 0, tone: "warning" },
              ]}
        />
        {selected.kind === "scan" ? (
          <TaskRow
            task={task}
            onPause={() => setScanTaskState("paused")}
            onResume={() => setScanTaskState("running")}
            onRetry={() => setScanTaskState("running")}
          />
        ) : (
          <ol className="materials-pipeline">
            {[
              "Проверка файла",
              "Извлечение структуры",
              "Извлечение текста",
              "Разбиение на блоки",
              "Индексирование",
            ].map((step) => <li key={step}><CircleCheck size={14} /> {step}</li>)}
          </ol>
        )}
        <section className="materials-processing-section">
          <div>
            <h3>Распознавание</h3>
            <QualityBadge quality={selected.quality} count={selected.kind === "scan" ? 1 : selected.totalPages} />
          </div>
          <p>{selected.kind === "scan" ? "Русский + английский — уверенность 61%. Сверьте текст с фотографией." : "Текстовый слой найден. OCR для этих страниц не требуется."}</p>
          <div className="materials-button-stack">
            <Button onClick={() => {
              setScanTaskState("running");
              setNotice("Повторный OCR поставлен в очередь.");
            }}><ScanText size={14} /> {selected.kind === "scan" ? "Повторить OCR страницы" : "Выполнить OCR выбранных страниц"}</Button>
            <Button variant="secondary" onClick={() => setStubNotice("Открыт выбор страниц для OCR")}>Выбрать страницы</Button>
            <Button variant="ghost" onClick={() => setNotice("Исправление текста продолжится в полноэкранном Просмотрщике.")}><Pencil size={14} /> Исправить текст</Button>
          </div>
        </section>
        {selected.kind === "scan" && (
          <OfflineNotice reason="disabled" alternative="OCR, исправление текста и локальный индекс продолжают работать." />
        )}
        <Button variant="ghost" onClick={() => setStubNotice("Индекс будет перестроен после подтверждения")}>Перестроить индекс</Button>
      </div>
    );
  }

  function renderFileTab() {
    return (
      <div className="materials-inspector-content">
        <dl className="materials-file-details">
          <div><dt>Название</dt><dd>{selected.name}</dd></div>
          <div><dt>Исходный файл</dt><dd>{selected.originalName}</dd></div>
          <div><dt>Формат</dt><dd>{selected.fileType}</dd></div>
          <div><dt>Размер</dt><dd>{selected.size}</dd></div>
          <div><dt>Страницы</dt><dd>{selected.totalPages}</dd></div>
          <div><dt>Добавлен</dt><dd>{selected.added}</dd></div>
          <div><dt>Использование</dt><dd>1 проект</dd></div>
        </dl>
        <section className="materials-role-list">
          <h3>Роли в проекте</h3>
          {selected.roles.map((role) => <StatusBadge key={role} tone="neutral">{role}</StatusBadge>)}
          {selected.sourceType && <StatusBadge tone="info">{selected.sourceType}</StatusBadge>}
          <Button variant="secondary" onClick={() => setRolesOpen(true)}><SlidersHorizontal size={14} /> Изменить роли</Button>
        </section>
        <div className="materials-button-stack">
          <Button variant="secondary" onClick={() => setStubNotice("Оригинал открыт системным приложением")}><ExternalLink size={14} /> Открыть оригинал</Button>
          <Button variant="ghost" onClick={() => setStubNotice("Копия подготовлена к скачиванию")}><Download size={14} /> Скачать копию</Button>
          <Button variant="ghost" onClick={() => setStubNotice("Базовый разбор поставлен в очередь")}><RefreshCw size={14} /> Повторить базовый разбор</Button>
          <Button variant="ghost" className="materials-remove-button" onClick={() => setRemoveOpen(true)}><Trash2 size={14} /> Убрать из проекта</Button>
        </div>
      </div>
    );
  }

  function renderInspector() {
    if (activeTab === "questions") return renderQuestionsTab();
    if (activeTab === "answers") return renderAnswersTab();
    if (activeTab === "bindings") return renderBindingsTab();
    if (activeTab === "processing") return renderProcessingTab();
    return renderFileTab();
  }

  const scanGroup = visibleMaterials.filter((material) => material.kind === "scan");
  const sourceGroup = visibleMaterials.filter((material) => material.kind === "source");
  const answerGroup = visibleMaterials.filter((material) => material.kind === "answers");

  function renderCatalogItem(material: DemoMaterial) {
    const Icon = iconFor(material);
    const active = selected.id === material.id;
    return (
      <div className={`materials-catalog-item ${active ? "is-active" : ""}`.trim()} key={material.id}>
        <button type="button" onClick={() => selectMaterial(material)}>
          <Icon size={15} aria-hidden="true" />
          <span><strong>{material.name}</strong><small>{material.status}</small></span>
          {material.statusTone !== "neutral" && <span className={`materials-attention-dot tone-${material.statusTone}`} />}
        </button>
        {!(["overview", "summary"].includes(material.kind)) && (
          <Menu
            label={`Действия с ${material.name}`}
            trigger={<IconButton label={`Действия с ${material.name}`}><MoreHorizontal size={14} /></IconButton>}
            items={[
              { label: "Изменить название", icon: <Pencil size={14} />, onSelect: () => setStubNotice("Открыто переименование файла") },
              { label: "Изменить роли", icon: <SlidersHorizontal size={14} />, onSelect: () => setRolesOpen(true) },
              { label: "Открыть оригинал", icon: <ExternalLink size={14} />, onSelect: () => setStubNotice("Оригинал открыт") },
              { label: "Повторить обработку", icon: <RefreshCw size={14} />, onSelect: () => setStubNotice("Повторная обработка поставлена в очередь") },
              { label: "Убрать из проекта", icon: <Trash2 size={14} />, destructive: true, onSelect: () => setRemoveOpen(true) },
            ]}
          />
        )}
      </div>
    );
  }

  return (
    <div className={`project-materials ${focusMode ? "is-focus-mode" : ""}`.trim()} style={rootStyle}>
      {catalogOpen && !focusMode && <aside className="materials-catalog" aria-label="Каталог материалов">
        <header className="materials-catalog-head">
          <Tooltip label="Вернуться в рабочую область">
            <Link className="workspace-back-button" to={`/projects/${projectId}`} aria-label="Вернуться в рабочую область"><ArrowLeft size={15} /></Link>
          </Tooltip>
          <strong>Базы данных — экзамен</strong>
          <IconButton label="Свернуть каталог" onClick={() => setCatalogOpen(false)}><PanelLeftClose size={15} /></IconButton>
        </header>
        <div className="materials-catalog-actions">
          <Button onClick={() => setAddOpen(true)}><Plus size={15} /> Добавить</Button>
          <Popover
            title="Показать материалы"
            side="bottom"
            align="end"
            trigger={<IconButton label="Фильтры каталога" aria-pressed={activeFilters > 0}><Filter size={15} /></IconButton>}
          >
            <div className="workspace-filter-list">
              <Checkbox label="Требуют внимания" checked={filters.attention} onCheckedChange={(value) => setFilters((current) => ({ ...current, attention: value }))} />
              <Checkbox label="Обрабатываются" checked={filters.processing} onCheckedChange={(value) => setFilters((current) => ({ ...current, processing: value }))} />
              <Checkbox label="Низкое качество OCR" checked={filters.lowOcr} onCheckedChange={(value) => setFilters((current) => ({ ...current, lowOcr: value }))} />
            </div>
          </Popover>
        </div>
        <label className="materials-catalog-search">
          <Search size={14} />
          <input type="search" value={fileQuery} onChange={(event) => setFileQuery(event.target.value)} placeholder="Найти файл" aria-label="Найти файл" />
          {fileQuery && <button type="button" aria-label="Очистить поиск" onClick={() => setFileQuery("")}><X size={13} /></button>}
        </label>
        <nav className="materials-catalog-list">
          {visibleMaterials.filter((material) => ["overview", "summary"].includes(material.kind)).map(renderCatalogItem)}
          {answerGroup.length > 0 && <section><h2>Вопросы и ответы</h2>{answerGroup.map(renderCatalogItem)}</section>}
          {sourceGroup.length + scanGroup.length > 0 && <section><h2>Учебные источники</h2>{sourceGroup.map(renderCatalogItem)}{scanGroup.map(renderCatalogItem)}</section>}
        </nav>
        <nav className="materials-project-nav" aria-label="Разделы проекта">
          <span className="is-active"><Files size={14} /><span>Материалы</span><small>3</small></span>
          <Link to={`/projects/${projectId}/program`}><ListTree size={14} /><span>Вопросы экзамена</span></Link>
          <Link to={`/projects/${projectId}/plan`}><CalendarDays size={14} /><span>План подготовки</span></Link>
          <button type="button" disabled><Layers size={14} /><span>Карточки</span></button>
          <button type="button" disabled><Settings size={14} /><span>Настройки</span></button>
        </nav>
      </aside>}

      {catalogOpen && !focusMode && (
        <PanelResizeHandle className="materials-catalog-resize" label="Изменить ширину каталога" value={catalogWidth} min={240} max={360} onDelta={(delta) => setCatalogWidth((current) => Math.min(360, Math.max(240, current + delta)))} onReset={() => setCatalogWidth(280)} />
      )}

      <main className="materials-document-area">
        {selected.kind !== "overview" && (
          <header className="materials-document-toolbar">
            <div className="materials-toolbar-slot">
              {!catalogOpen && !focusMode && <IconButton label="Открыть каталог" onClick={() => setCatalogOpen(true)}><PanelLeftOpen size={15} /></IconButton>}
            </div>
            <div className="materials-toolbar-tools">
              {!(["summary"].includes(selected.kind)) && (
                <div className="materials-view-mode" role="group" aria-label="Режим документа">
                  <IconButton className={viewMode === "original" ? "is-active" : ""} label="Показать оригинал" aria-pressed={viewMode === "original"} onClick={() => setViewMode("original")}><File size={15} /></IconButton>
                  <IconButton className={viewMode === "text" ? "is-active" : ""} label="Показать распознанный текст" aria-pressed={viewMode === "text"} onClick={() => setViewMode("text")}><FileText size={15} /></IconButton>
                </div>
              )}
              <div className="materials-page-tools" aria-label="Навигация по документу">
              <Popover
                title="Оглавление"
                side="bottom"
                align="start"
                className="materials-outline-popover"
                trigger={<IconButton label="Оглавление"><AlignJustify size={15} /></IconButton>}
              >
                <nav className="materials-outline" aria-label="Оглавление документа">
                  {pages.map((documentPage) => (
                    <button
                      className={documentPage.number === page ? "is-active" : ""}
                      type="button"
                      key={documentPage.number}
                      onClick={() => goToPage(documentPage.number)}
                    >
                      <span>Стр. {documentPage.number}</span>
                      <strong>{documentPage.title}</strong>
                    </button>
                  ))}
                </nav>
              </Popover>
              <IconButton label="Предыдущая страница" disabled={currentPageIndex <= 0} onClick={() => goToPage(pages[currentPageIndex - 1]?.number ?? page)}><ChevronLeft size={15} /></IconButton>
              <span>{currentPage?.number ?? 1} / {selected.totalPages || 1}</span>
              <IconButton label="Следующая страница" disabled={currentPageIndex >= pages.length - 1} onClick={() => goToPage(pages[currentPageIndex + 1]?.number ?? page)}><ChevronRight size={15} /></IconButton>
              </div>
              <div className="materials-zoom-tools" aria-label="Масштаб">
              <IconButton label="Уменьшить масштаб" onClick={() => setZoom((current) => Math.max(70, current - 10))}><ZoomOut size={15} /></IconButton>
              <span>{zoom}%</span>
              <IconButton label="Увеличить масштаб" onClick={() => setZoom((current) => Math.min(150, current + 10))}><ZoomIn size={15} /></IconButton>
              <Tooltip label="По ширине"><IconButton label="По ширине" onClick={() => setZoom(92)}><Maximize2 size={14} /></IconButton></Tooltip>
              </div>
              <div className={`materials-search-tools ${searchOpen ? "is-open" : ""}`.trim()}>
              {searchOpen && <input autoFocus type="search" value={documentQuery} onChange={(event) => setDocumentQuery(event.target.value)} placeholder="Поиск в документе" aria-label="Поиск в документе" />}
              {searchOpen && <small>{documentQuery ? `${searchMatches} найдено` : ""}</small>}
              <IconButton label={searchOpen ? "Закрыть поиск" : "Поиск в документе"} onClick={() => {
                setSearchOpen((current) => !current);
                if (searchOpen) setDocumentQuery("");
              }}>{searchOpen ? <X size={15} /> : <Search size={15} />}</IconButton>
              </div>
              <div className="materials-toolbar-end">
              {selected.kind === "source" && <IconButton label="Показывать метки привязок" aria-pressed={markersVisible} onClick={() => setMarkersVisible((current) => !current)}>{markersVisible ? <LinkIcon size={15} /> : <Unlink size={15} />}</IconButton>}
              <IconButton label={focusMode ? "Вернуть панели" : "Документ на весь экран"} aria-pressed={focusMode} onClick={() => setFocusMode((current) => !current)}><Maximize2 size={15} /></IconButton>
              {!focusMode && <IconButton label={inspectorOpen ? "Свернуть правую панель" : "Открыть правую панель"} onClick={() => setInspectorOpen((current) => !current)}>{inspectorOpen ? <PanelRightClose size={15} /> : <PanelRightOpen size={15} />}</IconButton>}
              </div>
            </div>
            <div className="materials-toolbar-slot" aria-hidden="true" />
          </header>
        )}
        <div className={`materials-document-stage ${selected.kind === "source" && markersVisible ? "has-marker-rail" : ""}`.trim()}>
          <div className="materials-document-scroll" onScroll={(event) => {
            const scroller = event.currentTarget;
            const ratio = scroller.scrollTop / Math.max(1, scroller.scrollHeight - scroller.clientHeight);
            const index = Math.min(pages.length - 1, Math.max(0, Math.round(ratio * Math.max(0, pages.length - 1))));
            if (pages[index]) setPage(pages[index].number);
          }}>
            {renderDocument()}
          </div>
          {selected.kind === "source" && markersVisible && (
            <nav className="materials-marker-rail" aria-label="Метки документа">
              {bindings.filter((binding) => binding.status !== "removed").map((binding) => (
                <Tooltip key={binding.id} label={`Стр. ${binding.page} — ${binding.question}`} side="left">
                  <button type="button" className={`is-${binding.status} ${binding.id === selectedBinding.id ? "is-active" : ""}`.trim()} style={{ top: `${binding.position}%` }} onClick={() => selectBinding(binding.id)} aria-label={`Страница ${binding.page}: ${binding.question}`} />
                </Tooltip>
              ))}
              <Tooltip label="Стр. 91 — низкое качество OCR" side="left"><button type="button" className="is-ocr" style={{ top: "86%" }} onClick={() => setStubNotice("Открыта страница 91 с низким качеством OCR")} aria-label="Страница 91: низкое качество OCR" /></Tooltip>
            </nav>
          )}
        </div>
      </main>

      {inspectorOpen && !focusMode && (
        <PanelResizeHandle className="materials-inspector-resize" label="Изменить ширину правой панели" value={inspectorWidth} min={320} max={440} onDelta={(delta) => setInspectorWidth((current) => Math.min(440, Math.max(320, current - delta)))} onReset={() => setInspectorWidth(356)} />
      )}

      {inspectorOpen && !focusMode && <aside className="materials-inspector" aria-label="Действия с материалом">
        <header className="materials-inspector-head">
          <div>
            <strong>{selected.kind === "overview" ? "Материалы" : TAB_LABELS[activeTab]}</strong>
            <small>{selected.kind === "overview" ? "Сводка проекта" : `Страница ${page}`}</small>
          </div>
        </header>
        {availableTabs.length > 1 && (
          <div className="materials-inspector-tabs" role="tablist" aria-label="Разделы инспектора">
            {availableTabs.map((tab) => (
              <button type="button" role="tab" aria-selected={activeTab === tab} className={activeTab === tab ? "is-active" : ""} key={tab} onClick={() => setActiveTab(tab)}>{TAB_LABELS[tab]}</button>
            ))}
          </div>
        )}
        <p className="materials-action-note" role="status">{notice}</p>
        <div className="materials-inspector-scroll">{selected.kind !== "overview" && renderInspector()}</div>
      </aside>}

      <Dialog
        open={addOpen}
        onOpenChange={setAddOpen}
        title="Добавить материал"
        description="Выберите источник. На этапе макета действие показывает будущий вход, но не загружает данные."
        footer={<Button variant="ghost" onClick={() => setAddOpen(false)}>Закрыть</Button>}
      >
        <div className="materials-add-grid">
          {[
            { label: "Загрузить файл", hint: "PDF, DOCX, TXT, MD, JPG или PNG", icon: Upload },
            { label: "Вставить текст", hint: "Вопросы, ответы или собственный материал", icon: FileText },
            { label: "Выбрать из Библиотеки", hint: "Подключить уже обработанный файл", icon: Library },
            { label: "Взять из Инбокса", hint: "Документ, фото или текст из бота", icon: Inbox },
            { label: "Добавить по URL", hint: "Сохранить веб-страницу локально", icon: LinkIcon },
          ].map((option) => (
            <button type="button" key={option.label} onClick={() => {
              setStubNotice(option.label);
              setAddOpen(false);
            }}><option.icon size={17} /><span><strong>{option.label}</strong><small>{option.hint}</small></span><ChevronRight size={15} /></button>
          ))}
        </div>
      </Dialog>

      <Dialog
        open={manualOpen}
        onOpenChange={setManualOpen}
        title={`Эталон к вопросу ${selectedAnswer.number}`}
        description={selectedAnswer.title}
        footer={(
          <>
            <Button variant="ghost" onClick={() => setManualOpen(false)}>Отменить</Button>
            <Button onClick={() => {
              setAnswers((current) => current.map((answer) => answer.id === selectedAnswer.id ? { ...answer, status: "manual", excerpt: manualText || "Ручной эталонный ответ." , origin: "Введён вручную" } : answer));
              setNotice("Ручной эталон сохранён с пометкой происхождения.");
              setManualOpen(false);
            }}>Сохранить эталон</Button>
          </>
        )}
      >
        <textarea className="materials-manual-answer" value={manualText} onChange={(event) => setManualText(event.target.value)} placeholder="Введите полный эталонный ответ" aria-label="Эталонный ответ" />
        <p className="materials-dialog-note">Ответ сохранится без файла-источника и будет явно помечен как введённый вручную.</p>
      </Dialog>

      <Dialog
        open={costOpen}
        onOpenChange={setCostOpen}
        title="Сопоставить материал с вопросами?"
        description="Проход 2 рассмотрит каждый новый содержательный блок ровно один раз."
        footer={(
          <>
            <Button variant="ghost" onClick={() => setCostOpen(false)}>Отменить</Button>
            <Button onClick={() => {
              setNotice("Сопоставление запущено: обработано 0 блоков из 63.");
              setCostOpen(false);
            }}>Запустить сопоставление</Button>
          </>
        )}
      >
        <CostEstimate calls={9} cost={0.18} minutes={3} pricesFrom="01.08.2026" units="63 новых блока" />
        <ul className="consequences">
          <li>Во внешнюю модель уйдут тексты 63 блоков и формулировки 28 вопросов.</li>
          <li>Файл целиком и изображения страниц не отправляются.</li>
          <li>Однозначные решения будут помечены машинными, спорные попадут в очередь.</li>
        </ul>
      </Dialog>

      <Dialog
        open={rolesOpen}
        onOpenChange={setRolesOpen}
        title="Роли файла в проекте"
        description="Роли влияют на доступные способы разбора, но не запускают их без подтверждения."
        footer={(
          <>
            <Button variant="ghost" onClick={() => setRolesOpen(false)}>Отменить</Button>
            <Button onClick={() => {
              setNotice("Роли сохранены. Базовый разбор повторять не требуется.");
              setRolesOpen(false);
            }}>Сохранить роли</Button>
          </>
        )}
      >
        <div className="materials-role-dialog">
          <Checkbox label="Структура экзамена" checked={selected.roles.includes("Структура экзамена")} onCheckedChange={() => undefined} />
          <Checkbox label="Эталонные ответы" checked={selected.roles.includes("Эталонные ответы")} onCheckedChange={() => undefined} />
          <Checkbox label="Учебный источник" checked={selected.roles.includes("Учебный источник")} onCheckedChange={() => undefined} />
        </div>
      </Dialog>

      <ConfirmDialog
        open={removeOpen}
        onOpenChange={setRemoveOpen}
        title={`Убрать «${selected.name}» из проекта?`}
        confirmLabel="Убрать из проекта"
        destructive
        onConfirm={() => setNotice("Материал отключён в макете. Общий файл остаётся в Библиотеке.")}
      >
        <p className="dialog-lead">Общий файл останется в Библиотеке. В проекте изменится:</p>
        <ul className="consequences">
          <li>{selected.kind === "answers" ? "24 эталонных ответа потеряют файл-источник" : "3 вопроса потеряют привязанные фрагменты"}</li>
          <li>Ручные ответы и вопросы Программы сохранятся.</li>
          <li>Статусы затронутых вопросов будут пересчитаны.</li>
        </ul>
      </ConfirmDialog>
    </div>
  );
}
