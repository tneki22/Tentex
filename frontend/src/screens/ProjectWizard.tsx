import { useId, useState } from "react";
import type { ChangeEvent, DragEvent, ReactNode } from "react";
import { Link } from "react-router";
import { DEMO_PROJECT_ID } from "../app/screens";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  BookOpen,
  Brain,
  CalendarDays,
  Check,
  FileCheck2,
  FileText,
  GraduationCap,
  LibraryBig,
  ListChecks,
  Pencil,
  Sparkles,
  TicketCheck,
  UploadCloud,
  WandSparkles,
  X,
} from "lucide-react";
import {
  Button,
  Card,
  Checkbox,
  Field,
  IconButton,
  RadioCards,
  SegmentedTabs,
  StatusBadge,
} from "../components/ui";
import type { RadioCardOption } from "../components/ui";
import { TextbookWizard } from "./TextbookWizard";

type ExamFormat = "questions" | "questions_tasks" | "tickets" | "unknown";
type InputMode = "files" | "text";
type StartingMode = "preset" | "details";
type StartingLevel = "zero" | "partial" | "refresh";
type GoalLevel = "orient" | "understand" | "answer" | "master";
type StudyFormat = "theory" | "mixed" | "practice";
type UploadRole = "primary" | "answers" | "theory";

interface UploadFile {
  name: string;
  size: string;
  warning?: boolean;
}

interface ReviewItem {
  id: string;
  text: string;
  order?: number;
  kind?: "вопрос" | "задача";
  children?: ReviewItem[];
}

function savedContentMessage(format: ExamFormat, hasAnswers: boolean, hasMaterials: boolean) {
  if (format === "unknown") return "Материалы сохранены.";

  const content = format === "tickets"
    ? hasAnswers ? "Билеты и ответы" : "Билеты"
    : format === "questions_tasks"
      ? hasAnswers ? "Вопросы, задачи и ответы" : "Вопросы и задачи"
      : hasAnswers ? "Вопросы и ответы" : "Ваши вопросы";

  return `${content}${hasMaterials ? " и материалы" : ""} сохранены.`;
}

const FORMAT_OPTIONS: Array<RadioCardOption<ExamFormat>> = [
  {
    value: "questions",
    title: "Отдельные вопросы",
    description: "Общий список теоретических вопросов без заранее собранных билетов.",
    icon: <ListChecks size={18} aria-hidden="true" />,
  },
  {
    value: "questions_tasks",
    title: "Вопросы и задачи",
    description: "Теория и практические задания перечислены отдельно, без группировки.",
    icon: <FileCheck2 size={18} aria-hidden="true" />,
  },
  {
    value: "tickets",
    title: "Готовые билеты",
    description: "Состав каждого билета известен: вопросы, задачи или их комбинация.",
    icon: <TicketCheck size={18} aria-hidden="true" />,
  },
  {
    value: "unknown",
    title: "Точного списка пока нет",
    description: "Есть учебники или конспекты — сначала соберём предварительную программу.",
    icon: <LibraryBig size={18} aria-hidden="true" />,
  },
];

const STARTING_LEVELS: Array<RadioCardOption<StartingLevel>> = [
  { value: "zero", title: "Начинаю с нуля", description: "Тема почти незнакома" },
  { value: "partial", title: "Что-то знаю", description: "Есть отдельные знакомые темы" },
  { value: "refresh", title: "Повторяю забытое", description: "Раньше изучал, нужно восстановить" },
];

const GOAL_TABS: Array<{ value: GoalLevel; label: string }> = [
  { value: "orient", label: "Ориентироваться" },
  { value: "understand", label: "Понимать" },
  { value: "answer", label: "Уверенно отвечать" },
  { value: "master", label: "Владеть свободно" },
];

const GOAL_SUMMARIES: Record<GoalLevel, string> = {
  orient: "Вы хотите ориентироваться в предмете.",
  understand: "Вы хотите понимать предмет.",
  answer: "Вы хотите уверенно отвечать.",
  master: "Вы хотите владеть материалом свободно.",
};

const STARTING_SUMMARIES: Record<StartingLevel, string> = {
  zero: "начинаете с нуля — баклуши уже бить некогда.",
  partial: "что-то уже знаете — баклуши весь семестр вы всё-таки не били.",
  refresh: "повторяете забытое — осталось разбудить знания до экзамена.",
};

const STUDY_TABS: Array<{ value: StudyFormat; label: string }> = [
  { value: "theory", label: "Только теория" },
  { value: "mixed", label: "Теория и задачи" },
  { value: "practice", label: "Больше практики" },
];

const STEP_LABELS = ["Формат", "Материалы", "Загрузка", "Паспорт", "Проверка"];

const TRACKS = [
  {
    id: "exam",
    icon: GraduationCap,
    eyebrow: "До конкретной даты",
    title: "Подготовка к экзамену",
    description:
      "Есть вопросы, задачи, билеты или только учебные материалы. Соберём программу и распределим работу до экзамена.",
    need: "Список формулировок или материалы по предмету",
    result: "Структура экзамена, программа и понятный темп подготовки",
    available: true,
  },
  {
    id: "textbook",
    icon: BookOpen,
    eyebrow: "Источник + ваша цель",
    title: "Изучение по учебнику",
    description:
      "Есть учебник, методичка или курс и своя цель. Найдём в материалах нужные темы, предпосылки и связи.",
    need: "Один или несколько основных учебных материалов",
    result: "Программа под цель с привязкой к главам и честными пробелами",
    available: true,
  },
  {
    id: "free",
    icon: Sparkles,
    eyebrow: "От цели к программе",
    title: "Свободное изучение",
    description:
      "Есть цель, но нет обязательной программы или одного главного источника. Начнём с ориентира и дополним его по ходу.",
    need: "Цель и примерное представление о желаемом результате",
    result: "Гибкая программа, которую можно уточнять материалами",
    available: false,
  },
];

const DEMO_FILES: Record<UploadRole, UploadFile[]> = {
  primary: [
    { name: "voprosy-k-ekzamenu.pdf", size: "1,8 МБ" },
  ],
  answers: [
    { name: "otvety-po-bazam-dannyh.docx", size: "824 КБ" },
  ],
  theory: [
    {
      name: "konspekt-lekciy-scan.pdf",
      size: "12,4 МБ",
      warning: true,
    },
  ],
};

const REVIEW_ITEMS: Record<ExamFormat, ReviewItem[]> = {
  questions: [
    { id: "q-1", text: "Понятие базы данных. Основные свойства СУБД" },
    { id: "q-2", text: "Реляционная модель данных и её компоненты" },
    { id: "q-3", text: "Функциональные зависимости. Нормальные формы" },
    { id: "q-4", text: "Архитектура СУБД" },
    { id: "q-5", text: "Транзакции и свойства ACID" },
    { id: "q-6", text: "Индексы и способы организации доступа к данным" },
  ],
  questions_tasks: [
    { id: "qt-1", kind: "вопрос", text: "Транзакции и свойства ACID" },
    { id: "qt-2", kind: "задача", text: "Построить план выполнения SQL-запроса" },
    { id: "qt-3", kind: "вопрос", text: "Уровни изоляции транзакций" },
    { id: "qt-4", kind: "задача", text: "Нормализовать отношение до третьей нормальной формы" },
    { id: "qt-5", kind: "вопрос", text: "Индексы и их влияние на выполнение запросов" },
    { id: "qt-6", kind: "задача", text: "Составить SQL-запрос с группировкой" },
  ],
  tickets: [
    {
      id: "ticket-1",
      text: "Билет № 1",
      children: [
        { id: "ticket-1-1", kind: "вопрос", text: "Реляционная модель данных" },
        { id: "ticket-1-2", kind: "вопрос", text: "Нормализация до третьей нормальной формы" },
        { id: "ticket-1-3", kind: "задача", text: "Составить SQL-запрос" },
      ],
    },
    {
      id: "ticket-2",
      text: "Билет № 2",
      children: [
        { id: "ticket-2-1", kind: "вопрос", text: "Архитектура СУБД" },
        { id: "ticket-2-2", kind: "вопрос", text: "Транзакции и журналирование" },
      ],
    },
    {
      id: "ticket-3",
      text: "Билет № 3",
      children: [
        { id: "ticket-3-1", kind: "вопрос", text: "Функциональные зависимости" },
        { id: "ticket-3-2", kind: "задача", text: "Найти ключи отношения" },
      ],
    },
    {
      id: "ticket-4",
      text: "Билет № 4",
      children: [
        { id: "ticket-4-1", kind: "вопрос", text: "Уровни изоляции транзакций" },
        { id: "ticket-4-2", kind: "задача", text: "Разобрать взаимную блокировку" },
      ],
    },
    {
      id: "ticket-5",
      text: "Билет № 5",
      children: [
        { id: "ticket-5-1", kind: "вопрос", text: "Индексы и планы выполнения" },
        { id: "ticket-5-2", kind: "задача", text: "Выбрать индекс для запроса" },
      ],
    },
  ],
  unknown: [
    { id: "section-1", text: "Введение в базы данных" },
    { id: "section-2", text: "Реляционная модель" },
    { id: "section-3", text: "Проектирование и нормализация" },
    { id: "section-4", text: "Язык SQL" },
    { id: "section-5", text: "Транзакции" },
    { id: "section-6", text: "Физическая организация данных" },
  ],
};

function formatFileSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace(".", ",")} МБ`;
}

function formatStudyMinutes(minutes: number) {
  if (minutes < 60) return `${minutes} мин`;
  const hours = minutes / 60;
  return `${Number.isInteger(hours) ? hours : hours.toFixed(1).replace(".", ",")} ч`;
}

function getDailyLoad(examDate: string) {
  const deadline = examDate ? new Date(`${examDate}T00:00:00`) : null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const daysLeft = deadline ? Math.ceil((deadline.getTime() - today.getTime()) / 86_400_000) : null;

  if (!daysLeft || daysLeft <= 0) {
    return { options: [120, 180, 240, 300, 360], recommended: 180, hint: "Выберите реальный объём работы — дату экзамена можно добавить позже." };
  }

  if (daysLeft <= 4) {
    return { options: [240, 300, 360, 420, 480], recommended: 360, hint: `До экзамена ${daysLeft} дн. Ориентир: 6 ч в день.` };
  }

  if (daysLeft <= 7) {
    return { options: [120, 180, 240, 300, 360], recommended: 240, hint: `До экзамена ${daysLeft} дн. Ориентир: 4 ч в день.` };
  }

  if (daysLeft <= 21) {
    return { options: [90, 120, 180, 240, 300], recommended: 180, hint: `До экзамена ${daysLeft} дн. Ориентир: 3 ч в день.` };
  }

  return { options: [60, 90, 120, 150, 180], recommended: 120, hint: `До экзамена ${daysLeft} дн. Ориентир: 2 ч в день.` };
}

function pluralizeRu(value: number, one: string, few: string, many: string) {
  const lastTwo = value % 100;
  const last = value % 10;
  if (lastTwo >= 11 && lastTwo <= 14) return many;
  if (last === 1) return one;
  if (last >= 2 && last <= 4) return few;
  return many;
}

function getExamCountdown(examDate: string) {
  if (!examDate) return null;

  const deadline = new Date(`${examDate}T00:00:00`);
  const totalHours = Math.ceil((deadline.getTime() - Date.now()) / 3_600_000);
  if (totalHours <= 0) return { prefix: "Экзамен уже ", parts: ["сегодня"], tone: "danger" as const };

  const days = Math.floor(totalHours / 24);
  const hours = totalHours % 24;
  return {
    prefix: "Он через ",
    parts: [
      days > 0 ? `${days} ${pluralizeRu(days, "день", "дня", "дней")}` : null,
      `${hours} ${pluralizeRu(hours, "час", "часа", "часов")}`,
    ].filter((part): part is string => Boolean(part)),
    tone: totalHours < 72 ? "danger" as const : totalHours < 168 ? "warning" as const : "accent" as const,
  };
}

function getPreparationForecast({
  format,
  itemCount,
  examDate,
  minutes,
  startingLevel,
  startingMode,
  goalLevel,
  studyFormat,
}: {
  format: ExamFormat;
  itemCount: number;
  examDate: string;
  minutes: number;
  startingLevel: StartingLevel;
  startingMode: StartingMode;
  goalLevel: GoalLevel;
  studyFormat: StudyFormat;
}) {
  const deadline = examDate ? new Date(`${examDate}T00:00:00`) : null;
  const daysLeft = deadline ? Math.max(1, Math.ceil((deadline.getTime() - Date.now()) / 86_400_000)) : 14;
  const minutesPerItem = format === "tickets" ? 50 : format === "unknown" ? 60 : format === "questions_tasks" ? 36 : 30;
  const startMultiplier = startingMode === "details"
    ? 1
    : { zero: 1.35, partial: 1, refresh: 0.75 }[startingLevel];
  const goalMultiplier = { orient: 0.6, understand: 0.8, answer: 1, master: 1.25 }[goalLevel];
  const practiceMultiplier = studyFormat === "practice" ? 1.1 : 1;
  const ratio = (daysLeft * minutes) / (itemCount * minutesPerItem * startMultiplier * goalMultiplier * practiceMultiplier);

  // ponytail: временная логическая оценка для прототипа; заменить отдельным LLM-запросом, когда появится персональное планирование.
  if (ratio < 0.35) return { title: "будет очень тяжело", text: "времени заметно меньше, чем требует выбранная цель. Нужен больший темп или более скромный результат." };
  if (ratio < 0.7) return { title: "план напряжённый", text: "подготовиться можно, но пропуски быстро съедят запас времени." };
  if (ratio < 1.1) return { title: "шансы хорошие", text: "темп реалистичный, если заниматься регулярно и не откладывать сложные темы." };
  return { title: "запаса достаточно", text: "времени хватает и на основную подготовку, и на спокойное повторение перед экзаменом." };
}

interface UploadPanelProps {
  role: UploadRole;
  icon: ReactNode;
  title: string;
  description: string;
  allowText?: boolean;
  mode: InputMode;
  onModeChange: (mode: InputMode) => void;
  files: UploadFile[];
  onFilesChange: (files: UploadFile[]) => void;
  text: string;
  onTextChange: (text: string) => void;
}

function UploadPanel({
  role,
  icon,
  title,
  description,
  allowText = false,
  mode,
  onModeChange,
  files,
  onFilesChange,
  text,
  onTextChange,
}: UploadPanelProps) {
  const inputId = useId();

  function addFiles(fileList: FileList | null) {
    if (!fileList) return;
    const added = Array.from(fileList).map((file) => ({
      name: file.name,
      size: formatFileSize(file.size),
    }));
    onFilesChange([...files, ...added]);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    addFiles(event.dataTransfer.files);
  }

  return (
    <Card className="wizard-upload-panel">
      <div className="wizard-upload-head">
        <span className="wizard-upload-icon">{icon}</span>
        <span>
          <strong>{title}</strong>
          <small>{description}</small>
        </span>
        {allowText && (
          <SegmentedTabs
            label={`Способ добавления: ${title}`}
            value={mode}
            onChange={onModeChange}
            tabs={[
              { value: "files", label: "Файлы" },
              { value: "text", label: "Вставить текст" },
            ]}
          />
        )}
      </div>

      {mode === "files" || !allowText ? (
        <>
          <div
            className="wizard-dropzone"
            onDragOver={(event) => event.preventDefault()}
            onDrop={onDrop}
          >
            <UploadCloud size={24} aria-hidden="true" />
            <span>
              <b>Перетащите файлы сюда</b>
              <small>PDF, DOCX, TXT, MD или изображения — до 100 МБ и 500 страниц</small>
            </span>
            <label className="secondary-button" htmlFor={inputId}>Выбрать файлы</label>
            <input
              id={inputId}
              className="wizard-file-input"
              type="file"
              multiple
              onChange={(event: ChangeEvent<HTMLInputElement>) => addFiles(event.currentTarget.files)}
            />
          </div>

          {files.length === 0 ? (
            <button
              type="button"
              className="wizard-demo-link"
              onClick={() => onFilesChange(DEMO_FILES[role])}
            >
              <WandSparkles size={15} aria-hidden="true" />
              Показать на демо-файле
            </button>
          ) : (
            <div className="wizard-file-list">
              {files.map((file, index) => (
                <div className="wizard-file-row" key={`${file.name}-${index}`}>
                  <span className="wizard-file-type"><FileText size={16} aria-hidden="true" /></span>
                  <span className="wizard-file-name">
                    <b>{file.name}</b>
                    <small>{file.size}</small>
                  </span>
                  <button
                    type="button"
                    className="wizard-remove-file"
                    aria-label={`Убрать ${file.name}`}
                    onClick={() => onFilesChange(files.filter((_, itemIndex) => itemIndex !== index))}
                  >
                    <X size={16} aria-hidden="true" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="wizard-paste-area">
          <textarea
            rows={8}
            value={text}
            onChange={(event) => onTextChange(event.target.value)}
            placeholder={
              role === "answers"
                ? "1. Ответ: база данных — это…\n\n2. Ответ: реляционная модель…"
                : "1. Понятие базы данных.\n2. Реляционная модель данных.\n3. Нормальные формы…"
            }
          />
          {!text && (
            <button
              type="button"
              className="wizard-demo-link"
              onClick={() => onTextChange(
                role === "answers"
                  ? "1. База данных — организованная совокупность данных…\n\n2. Реляционная модель представляет данные в виде отношений…"
                  : "1. Понятие базы данных. Основные свойства СУБД\n2. Реляционная модель данных\n3. Функциональные зависимости и нормальные формы",
              )}
            >
              <WandSparkles size={15} aria-hidden="true" />
              Вставить пример
            </button>
          )}
        </div>
      )}

    </Card>
  );
}

export function ProjectWizard() {
  const [selectedTrack, setSelectedTrack] = useState<"exam" | "textbook" | null>(null);
  const [step, setStep] = useState(0);
  const [maxStep, setMaxStep] = useState(0);
  const [created, setCreated] = useState(false);
  const [format, setFormat] = useState<ExamFormat | null>(null);
  const [hasAnswers, setHasAnswers] = useState(false);
  const [hasTheory, setHasTheory] = useState(false);
  const [inputModes, setInputModes] = useState<Record<"primary" | "answers", InputMode>>({
    primary: "files",
    answers: "files",
  });
  const [files, setFiles] = useState<Record<UploadRole, UploadFile[]>>({
    primary: [],
    answers: [],
    theory: [],
  });
  const [texts, setTexts] = useState({ primary: "", answers: "" });
  const [subject, setSubject] = useState("Базы данных");
  const [examDate, setExamDate] = useState("2026-12-18");
  const [expectedCount, setExpectedCount] = useState("64");
  const [focus, setFocus] = useState("");
  const [teacherNotes, setTeacherNotes] = useState(
    "Строгий к определениям и уточняющим вопросам. Ценит примеры и понимание связей между темами.",
  );
  const [startingMode, setStartingMode] = useState<StartingMode>("preset");
  const [startingLevel, setStartingLevel] = useState<StartingLevel>("partial");
  const [startingNotes, setStartingNotes] = useState(
    "Помню основы SQL и нормализацию, но путаюсь в транзакциях и индексах.",
  );
  const [goalLevel, setGoalLevel] = useState<GoalLevel>("answer");
  const [studyFormat, setStudyFormat] = useState<StudyFormat>("mixed");
  const [minutes, setMinutes] = useState(120);
  const [reviewExpanded, setReviewExpanded] = useState(false);
  const [reviewDescending, setReviewDescending] = useState(false);
  const [reviewEdits, setReviewEdits] = useState<Record<string, string>>({});

  const detected = format === "tickets"
    ? { main: 30, label: "30 билетов, внутри 68 вопросов и 8 задач" }
    : format === "questions_tasks"
      ? { main: 64, label: "52 вопроса и 12 задач" }
      : format === "unknown"
        ? { main: 11, label: "11 предварительных разделов" }
        : { main: 64, label: "64 вопроса" };

  const formatTitle = FORMAT_OPTIONS.find((option) => option.value === format)?.title ?? "Экзамен";
  const expectedMismatch = Boolean(expectedCount) && Number(expectedCount) !== detected.main;
  const dailyLoad = getDailyLoad(examDate);
  const reviewItems = REVIEW_ITEMS[format ?? "questions"].map((item, index) => ({ ...item, order: index + 1 }));
  if (reviewDescending) reviewItems.reverse();
  const visibleReviewItems = reviewExpanded ? reviewItems : reviewItems.slice(0, 3);
  const examCountdown = getExamCountdown(examDate);
  const structureTitle = format === "tickets"
    ? "Билеты"
    : format === "unknown"
      ? "Предварительная структура"
      : format === "questions_tasks"
        ? "Вопросы и задачи"
        : "Вопросы";
  const sourceNames = [
    ...(format !== "unknown"
      ? files.primary.length > 0
        ? files.primary.map((file) => file.name)
        : ["Вставленный список формулировок"]
      : []),
    ...(hasAnswers
      ? files.answers.length > 0
        ? files.answers.map((file) => file.name)
        : ["Вставленные готовые ответы"]
      : []),
    ...(hasTheory ? files.theory.map((file) => file.name) : []),
  ];
  const savedMessage = savedContentMessage(format ?? "questions", hasAnswers, hasTheory);
  const preparationForecast = getPreparationForecast({
    format: format ?? "questions",
    itemCount: detected.main,
    examDate,
    minutes,
    startingLevel,
    startingMode,
    goalLevel,
    studyFormat,
  });
  function go(nextStep: number) {
    setStep(nextStep);
    setMaxStep((current) => Math.max(current, nextStep));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function selectFormat(next: ExamFormat) {
    setFormat(next);
    if (next === "unknown") {
      setHasAnswers(false);
      setHasTheory(true);
      setExpectedCount("11");
    } else {
      setExpectedCount(next === "tickets" ? "30" : "64");
      if (next === "questions_tasks" || next === "tickets") setStudyFormat("mixed");
    }
  }

  function updateExamDate(nextDate: string) {
    const previousOptions = getDailyLoad(examDate).options;
    setExamDate(nextDate);
    setMinutes((current) => previousOptions.includes(current) ? getDailyLoad(nextDate).recommended : current);
  }

  const primaryReady = format === "unknown"
    || files.primary.length > 0
    || texts.primary.trim().length > 0;
  const answersReady = !hasAnswers
    || files.answers.length > 0
    || texts.answers.trim().length > 0;
  const theoryReady = !hasTheory || files.theory.length > 0;
  const uploadReady = primaryReady && answersReady && theoryReady;

  if (selectedTrack === "textbook") {
    return <TextbookWizard onBackToTracks={() => {
      setSelectedTrack(null);
      setStep(0);
      setMaxStep(0);
    }} />;
  }

  if (created) {
    return (
      <div className="project-wizard is-success">
        <div className="wizard-success-card">
          <h1>Создан проект: {subject}</h1>
          <p>{savedMessage}</p>
          <p className="wizard-success-next">Следующий шаг — открыть проект, проверить программу и начать готовиться, время не ждёт!</p>
          <div className="wizard-success-actions">
            <Link className="primary-button" to={`/projects/${DEMO_PROJECT_ID}`}>Открыть проект</Link>
            <Button variant="ghost" onClick={() => setCreated(false)}>Вернуться к проверке</Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="project-wizard">
      <header className="wizard-topbar">
        <Link className="wizard-back-projects" to="/projects">
          <ArrowLeft size={16} aria-hidden="true" />
          <span>К проектам</span>
        </Link>
        <span className="wizard-brand"><Sparkles size={17} aria-hidden="true" />Tentex</span>
        {step > 0 ? (
          <span className="wizard-step-caption">Экзамен — шаг {step} из 5</span>
        ) : (
          <span className="wizard-step-caption">Мастер проектов</span>
        )}
      </header>

      {step > 0 && (
        <nav className="wizard-progress" aria-label="Шаги создания проекта">
          <span className="wizard-progress-line" aria-hidden="true">
            <i style={{ width: `${((step - 1) / 4) * 100}%` }} />
          </span>
          {STEP_LABELS.map((label, index) => {
            const itemStep = index + 1;
            const available = itemStep <= maxStep;
            return (
              <button
                type="button"
                key={label}
                className={`${itemStep === step ? "is-current" : ""} ${itemStep < step ? "is-complete" : ""}`.trim()}
                disabled={!available}
                aria-current={itemStep === step ? "step" : undefined}
                aria-label={`${itemStep}. ${label}`}
                onClick={() => go(itemStep)}
              >
                <span>{itemStep < step ? <Check size={13} strokeWidth={3} /> : itemStep}</span>
                <small>{label}</small>
              </button>
            );
          })}
        </nav>
      )}

      <main className={`wizard-main ${step === 0 ? "is-landing" : ""}`.trim()}>
        <div className="wizard-step" key={step}>
          {step === 0 && (
            <>
              <div className="wizard-hero">
                <h1>Как вы хотите<br />учиться?</h1>
                <p>
                  Расскажите, к чему готовитесь и что у вас уже есть. Tentex поможет собрать программу и следующий шаг.
                </p>
              </div>
              <div className="wizard-track-grid">
                {TRACKS.map((track) => {
                  const Icon = track.icon;
                  return (
                    <button
                      type="button"
                      className={`wizard-track-card ${track.available ? "is-available" : "is-soon"}`}
                      key={track.id}
                      aria-disabled={!track.available}
                      onClick={() => {
                        if (!track.available) return;
                        if (track.id === "textbook") {
                          setSelectedTrack("textbook");
                          return;
                        }
                        setSelectedTrack("exam");
                        go(1);
                      }}
                    >
                      <span className="wizard-track-top">
                        <span className="wizard-track-icon"><Icon size={24} aria-hidden="true" /></span>
                        {!track.available && <StatusBadge>скоро</StatusBadge>}
                      </span>
                      <small className="wizard-track-eyebrow">{track.eyebrow}</small>
                      <h2>{track.title}</h2>
                      <p>{track.description}</p>
                      <span className="wizard-track-details">
                        <span><b>Что понадобится</b>{track.need}</span>
                        <span><b>Что получится</b>{track.result}</span>
                      </span>
                      <span className="wizard-track-action">
                        {track.available ? "Выбрать этот путь" : "Добавим в следующей версии"}
                        {track.available && <ArrowRight size={16} aria-hidden="true" />}
                      </span>
                    </button>
                  );
                })}
              </div>
            </>
          )}

          {step === 1 && (
            <WizardSection
              eyebrow="Сначала — структура"
              title="Как устроен ваш экзамен?"
              description="Это определит, как Tentex сохранит формулировки и соберёт из них программу. Ничего вручную группировать не придётся."
            >
              <RadioCards
                label="Формат экзамена"
                value={format}
                options={FORMAT_OPTIONS}
                onChange={selectFormat}
                className="wizard-format-options"
              />
              {format === "tickets" && (
                <div className="wizard-context-note">
                  <TicketCheck size={18} aria-hidden="true" />
                  <span><b>Сохраним вложенность</b>Билет останется группой, а вопросы и задачи внутри станут отдельными пунктами программы.</span>
                </div>
              )}
              {format === "questions_tasks" && (
                <div className="wizard-context-note">
                  <ListChecks size={18} aria-hidden="true" />
                  <span><b>Без искусственных билетов</b>Вопросы и задачи останутся двумя типами элементов общего списка.</span>
                </div>
              )}
              <WizardActions onBack={() => go(0)} onNext={() => go(2)} nextDisabled={!format} />
            </WizardSection>
          )}

          {step === 2 && (
            <WizardSection
              eyebrow="Материалы"
              title="Что у вас уже есть?"
              description={format === "unknown"
                ? "Раз точного списка нет, начнём с учебных материалов. Официальные вопросы можно будет добавить в проект позже."
                : `Список «${formatTitle.toLowerCase()}» уже считаем основой. Отметьте, есть ли что-то ещё.`}
            >
              {format === "unknown" ? (
                <div className="wizard-material-grid has-one">
                  <SelectableMaterial
                    selected
                    locked
                    icon={<LibraryBig size={22} aria-hidden="true" />}
                    title="Учебные материалы"
                    description="Учебники, методички, лекции или конспекты — один или несколько файлов."
                  />
                </div>
              ) : (
                <div className="wizard-material-grid">
                  <SelectableMaterial
                    selected={hasAnswers}
                    onChange={setHasAnswers}
                    icon={<FileCheck2 size={22} aria-hidden="true" />}
                    title="Готовые ответы"
                    description="Полные ответы есть на все вопросы или только на часть — сопоставим сами."
                  />
                  <SelectableMaterial
                    selected={hasTheory}
                    onChange={setHasTheory}
                    icon={<LibraryBig size={22} aria-hidden="true" />}
                    title="Учебные материалы"
                    description="Учебники, методички, лекции или конспекты с теорией по предмету."
                  />
                </div>
              )}
              {!hasAnswers && !hasTheory && format !== "unknown" && (
                <div className="wizard-quiet-note">
                  Это нормально: продолжим только со списком. Ответы и источники можно добавить позже.
                </div>
              )}
              <WizardActions onBack={() => go(1)} onNext={() => go(3)} />
            </WizardSection>
          )}

          {step === 3 && format && (
            <WizardSection
              eyebrow="Загрузка"
              title="Добавьте то, что у вас есть"
              description="Формат и нумерация могут быть любыми. Сейчас покажем только быстрый предварительный разбор — тяжёлая обработка начнётся после создания проекта."
              wide
            >
              <div className="wizard-upload-stack">
                {format !== "unknown" && (
                  <UploadPanel
                    role="primary"
                    icon={format === "tickets" ? <TicketCheck size={20} /> : <ListChecks size={20} />}
                    title={format === "tickets" ? "Билеты" : "Вопросы и задачи"}
                    description="Главная структура экзамена"
                    allowText
                    mode={inputModes.primary}
                    onModeChange={(mode) => setInputModes((current) => ({ ...current, primary: mode }))}
                    files={files.primary}
                    onFilesChange={(next) => setFiles((current) => ({ ...current, primary: next }))}
                    text={texts.primary}
                    onTextChange={(text) => setTexts((current) => ({ ...current, primary: text }))}
                  />
                )}
                {hasAnswers && (
                  <UploadPanel
                    role="answers"
                    icon={<FileCheck2 size={20} />}
                    title="Готовые ответы"
                    description="На все формулировки или только на часть"
                    allowText
                    mode={inputModes.answers}
                    onModeChange={(mode) => setInputModes((current) => ({ ...current, answers: mode }))}
                    files={files.answers}
                    onFilesChange={(next) => setFiles((current) => ({ ...current, answers: next }))}
                    text={texts.answers}
                    onTextChange={(text) => setTexts((current) => ({ ...current, answers: text }))}
                  />
                )}
                {hasTheory && (
                  <UploadPanel
                    role="theory"
                    icon={<LibraryBig size={20} />}
                    title="Учебные материалы"
                    description="Источники теории для программы и будущих ответов"
                    mode="files"
                    onModeChange={() => undefined}
                    files={files.theory}
                    onFilesChange={(next) => setFiles((current) => ({ ...current, theory: next }))}
                    text=""
                    onTextChange={() => undefined}
                  />
                )}
              </div>
              {!uploadReady && (
                <div className="wizard-required-note">Добавьте данные во все выбранные блоки, чтобы продолжить.</div>
              )}
              <WizardActions onBack={() => go(2)} onNext={() => go(4)} nextDisabled={!uploadReady} />
            </WizardSection>
          )}

          {step === 4 && (
            <WizardSection
              eyebrow="Паспорт цели"
              title="Настроим подготовку под вас"
              description="Эти ответы зададут глубину программы и реальный темп. Их можно будет изменить после создания проекта."
              wide
            >
              <div className="wizard-passport-grid">
                <Card className="wizard-form-card">
                  <div className="wizard-form-card-head">
                    <span><CalendarDays size={19} aria-hidden="true" /></span>
                    <div><h2>Об экзамене</h2><p>Что именно предстоит и когда</p></div>
                  </div>
                  <div className="wizard-form-fields">
                    <Field label="Название предмета" required>
                      <input value={subject} onChange={(event) => setSubject(event.target.value)} placeholder="Например, Базы данных" />
                    </Field>
                    <div className="wizard-field-pair">
                      <Field label="Дата экзамена" hint="Если уже известна">
                        <input type="date" value={examDate} onChange={(event) => updateExamDate(event.target.value)} />
                      </Field>
                      <Field
                        label={format === "tickets" ? "Ожидается билетов" : format === "unknown" ? "Ожидается разделов" : "Ожидается элементов"}
                        hint={`Предварительно найдено: ${detected.main}`}
                      >
                        <input min="1" type="number" value={expectedCount} onChange={(event) => setExpectedCount(event.target.value)} />
                      </Field>
                    </div>
                    <Field label="Особый фокус" hint="Необязательно: напишите, что особенно важно или можно пропустить.">
                      <textarea rows={3} value={focus} onChange={(event) => setFocus(event.target.value)} placeholder="Например: больше практики по SQL, обзорно пройти историю СУБД" />
                    </Field>
                    <Field
                      label="О преподавателе"
                      hint="Необязательно: напишите о строгости, любимых темах или типичных придирках. Эта информация пойдёт в контекст для модели."
                    >
                      <textarea
                        rows={4}
                        value={teacherNotes}
                        onChange={(event) => setTeacherNotes(event.target.value)}
                        placeholder="Например: просит точные определения, любит задавать уточняющие вопросы…"
                      />
                    </Field>
                  </div>
                </Card>

                <Card className="wizard-form-card">
                  <div className="wizard-form-card-head">
                    <span><Brain size={19} aria-hidden="true" /></span>
                    <div><h2>О подготовке</h2><p>Откуда начинаем и куда хотим прийти</p></div>
                  </div>
                  <div className="wizard-form-fields">
                    <div className="wizard-inline-label">
                      <b>Стартовый уровень</b>
                      <SegmentedTabs
                        label="Как указать стартовый уровень"
                        value={startingMode}
                        onChange={setStartingMode}
                        tabs={[
                          { value: "preset", label: "Быстрый выбор" },
                          { value: "details", label: "Описать знания" },
                        ]}
                      />
                    </div>
                    {startingMode === "preset" ? (
                      <RadioCards
                        label="Стартовый уровень"
                        value={startingLevel}
                        options={STARTING_LEVELS}
                        onChange={setStartingLevel}
                        className="wizard-starting-levels"
                      />
                    ) : (
                      <Field
                        label="Что вы уже знаете"
                        hint="Можно писать свободно: темы, навыки, пробелы — модель разберёт описание"
                      >
                        <textarea
                          rows={5}
                          value={startingNotes}
                          onChange={(event) => setStartingNotes(event.target.value)}
                          placeholder="Например: помню основы SQL, но почти не знаю индексы и транзакции…"
                        />
                      </Field>
                    )}
                    <div className="wizard-control-group">
                      <b>Желаемый результат</b>
                      <SegmentedTabs label="Желаемый результат" value={goalLevel} tabs={GOAL_TABS} onChange={setGoalLevel} />
                      <small>Чем выше уровень, тем больше практики и проверок понимания войдёт в программу.</small>
                    </div>
                    <div className="wizard-control-group">
                      <b>Формат подготовки</b>
                      <SegmentedTabs label="Формат подготовки" value={studyFormat} tabs={STUDY_TABS} onChange={setStudyFormat} />
                    </div>
                    <div className="wizard-control-group">
                      <b>Сколько времени в день уделять</b>
                      <small>{dailyLoad.hint}</small>
                      <div className="wizard-minutes">
                        {dailyLoad.options.map((value) => (
                          <button
                            type="button"
                            key={value}
                            className={minutes === value ? "is-selected" : ""}
                            onClick={() => setMinutes(value)}
                          >
                            {formatStudyMinutes(value)}
                          </button>
                        ))}
                        <label>
                          <span className="wizard-visually-hidden">Свое время в минутах</span>
                          <input min="30" max="720" type="number" value={minutes} onChange={(event) => setMinutes(Number(event.target.value))} />
                          <small>мин</small>
                        </label>
                      </div>
                    </div>
                  </div>
                </Card>
              </div>
              <WizardActions onBack={() => go(3)} onNext={() => go(5)} nextDisabled={!subject.trim()} />
            </WizardSection>
          )}

          {step === 5 && format && (
            <WizardSection
              eyebrow="Проверка"
              title="Всё готово к созданию"
              description="Проверьте вопросы/билеты и заполненную информацию об экзамене, затем проект можно будет создать."
              wide
            >
              <section className="wizard-review-summary">
                <h2>
                  <span>Вы готовитесь к экзамену по предмету:</span>
                  <strong>{subject}</strong>
                </h2>
                <p className={`wizard-review-countdown is-${examCountdown?.tone ?? "muted"}`}>
                  {examCountdown ? (
                    <>{examCountdown.prefix}{examCountdown.parts.map((part, index) => <b key={part}>{part}{index < examCountdown.parts.length - 1 ? " " : ""}</b>)}</>
                  ) : "Дата экзамена пока не указана."}
                </p>
                <div className="wizard-review-story">
                  <p className="wizard-review-goal">{GOAL_SUMMARIES[goalLevel]}</p>
                  <p>На подготовку — <b>{minutes} минут в день</b>.</p>
                  <p className="wizard-review-personal"><b>Текущий уровень:</b> {startingMode === "details" && startingNotes.trim() ? startingNotes : STARTING_SUMMARIES[startingLevel]}</p>
                  {focus && <p className="wizard-review-personal"><b>Особый фокус:</b> {focus}</p>}
                  {teacherNotes && <p className="wizard-review-personal"><b>О преподавателе:</b> {teacherNotes}</p>}
                  <p className="wizard-review-personal">Системе кажется, что <b>{preparationForecast.title}</b>: {preparationForecast.text}</p>
                </div>
              </section>

              <Card className="wizard-review-card wizard-structure-card">
                <div className="wizard-review-block-head">
                  <div>
                    <h3>{structureTitle}</h3>
                    <p>{detected.label}</p>
                  </div>
                  <Button
                    variant="ghost"
                    onClick={() => setReviewDescending((current) => !current)}
                    aria-label={reviewDescending ? "Сортировать по возрастанию" : "Сортировать по убыванию"}
                  >
                    {reviewDescending ? <ArrowUp size={15} aria-hidden="true" /> : <ArrowDown size={15} aria-hidden="true" />}
                    {reviewDescending ? "По убыванию" : "По возрастанию"}
                  </Button>
                </div>
                <ReviewStructure
                  items={visibleReviewItems}
                  edits={reviewEdits}
                  onEdit={(id, value) => setReviewEdits((current) => ({ ...current, [id]: value }))}
                />
                {reviewItems.length > 3 && (
                  <Button
                    variant="ghost"
                    className="wizard-review-expand"
                    onClick={() => setReviewExpanded((current) => !current)}
                    aria-expanded={reviewExpanded}
                  >
                    {reviewExpanded ? "Свернуть список" : `Показать ещё ${reviewItems.length - 3}`}
                    {reviewExpanded ? <ArrowUp size={15} aria-hidden="true" /> : <ArrowDown size={15} aria-hidden="true" />}
                  </Button>
                )}
                {expectedMismatch && (
                  <div className="wizard-warning-card">
                    <span>!</span>
                    <div><b>Количество отличается</b><p>Вы указали {expectedCount}, а предварительно найдено {detected.main}. Создать проект всё равно можно.</p></div>
                    <button type="button" onClick={() => go(4)}>Проверить</button>
                  </div>
                )}
              </Card>

              <Card className="wizard-review-card wizard-sources-card">
                <h3>Источники</h3>
                <div className="wizard-source-list">
                  {sourceNames.map((name) => <ReviewSource key={name} value={name} />)}
                </div>
              </Card>

              <section className="wizard-after-create">
                <h3>Что произойдёт после создания</h3>
                <p>Структура экзамена импортируется в проект, и всё будет готово к подготовке.</p>
              </section>
              <WizardActions
                onBack={() => go(4)}
                onNext={() => setCreated(true)}
                nextLabel="Создать проект"
                nextIcon={<Sparkles size={16} aria-hidden="true" />}
                secondaryLabel="Вернуться к файлам"
                onSecondary={() => go(3)}
              />
            </WizardSection>
          )}
        </div>
      </main>
    </div>
  );
}

function WizardSection({
  eyebrow,
  title,
  description,
  wide = false,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <section className={`wizard-section ${wide ? "is-wide" : ""}`.trim()}>
      <div className="wizard-section-head">
        <span>{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {children}
    </section>
  );
}

function WizardActions({
  onBack,
  onNext,
  nextDisabled = false,
  nextLabel = "Продолжить",
  nextIcon = <ArrowRight size={16} aria-hidden="true" />,
  secondaryLabel,
  onSecondary,
}: {
  onBack: () => void;
  onNext: () => void;
  nextDisabled?: boolean;
  nextLabel?: string;
  nextIcon?: ReactNode;
  secondaryLabel?: string;
  onSecondary?: () => void;
}) {
  return (
    <div className="wizard-actions">
      <Button variant="ghost" onClick={onBack}><ArrowLeft size={16} aria-hidden="true" />Назад</Button>
      <span className="wizard-actions-spacer" />
      {secondaryLabel && <Button variant="secondary" onClick={onSecondary}>{secondaryLabel}</Button>}
      <Button onClick={onNext} disabled={nextDisabled}>{nextLabel}{nextIcon}</Button>
    </div>
  );
}

function SelectableMaterial({
  selected,
  locked = false,
  onChange,
  icon,
  title,
  description,
}: {
  selected: boolean;
  locked?: boolean;
  onChange?: (value: boolean) => void;
  icon: ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className={`wizard-material-card ${selected ? "is-selected" : ""}`.trim()}>
      <button type="button" disabled={locked} onClick={() => onChange?.(!selected)}>
        <span className="wizard-material-icon">{icon}</span>
        <span><b>{title}</b><small>{description}</small></span>
      </button>
      <Checkbox checked={selected} disabled={locked} onCheckedChange={(value) => onChange?.(value)} label={locked ? "Обязательно для этого пути" : selected ? "Добавим на следующем шаге" : "Выбрать"} />
    </div>
  );
}

function ReviewStructure({
  items,
  edits,
  onEdit,
}: {
  items: ReviewItem[];
  edits: Record<string, string>;
  onEdit: (id: string, value: string) => void;
}) {
  return (
    <ol className="wizard-review-list">
      {items.map((item) => (
        <li key={item.id} className={item.children ? "is-ticket" : ""}>
          <div className="wizard-review-row">
            <span className="wizard-review-number">{item.order}</span>
            {item.kind && <span className="wizard-review-kind">{item.kind}</span>}
            <EditableReviewText id={item.id} text={edits[item.id] ?? item.text} onEdit={onEdit} />
          </div>
          {item.children && (
            <ol>
              {item.children.map((child, index) => (
                <li key={child.id}>
                  <div className="wizard-review-row">
                    <span className="wizard-review-number">{index + 1}</span>
                    {child.kind && <span className="wizard-review-kind">{child.kind}</span>}
                    <EditableReviewText id={child.id} text={edits[child.id] ?? child.text} onEdit={onEdit} />
                  </div>
                </li>
              ))}
            </ol>
          )}
        </li>
      ))}
    </ol>
  );
}

function EditableReviewText({ id, text, onEdit }: { id: string; text: string; onEdit: (id: string, value: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(text);

  function save() {
    const next = draft.trim();
    if (next) onEdit(id, next);
    else setDraft(text);
    setEditing(false);
  }

  if (editing) {
    return (
      <div className="wizard-review-edit">
        <input
          autoFocus
          value={draft}
          aria-label="Формулировка"
          onChange={(event) => setDraft(event.target.value)}
          onBlur={save}
          onKeyDown={(event) => {
            if (event.key === "Enter") save();
            if (event.key === "Escape") {
              setDraft(text);
              setEditing(false);
            }
          }}
        />
        <IconButton label="Сохранить формулировку" onMouseDown={(event) => event.preventDefault()} onClick={save}>
          <Check size={15} aria-hidden="true" />
        </IconButton>
      </div>
    );
  }

  return (
    <div className="wizard-review-text">
      <span>{text}</span>
      <IconButton
        label="Редактировать формулировку"
        onClick={() => {
          setDraft(text);
          setEditing(true);
        }}
      >
        <Pencil size={15} aria-hidden="true" />
      </IconButton>
    </div>
  );
}

function ReviewSource({ value }: { value: string }) {
  return (
    <div className="wizard-source-row">
      <FileText size={16} aria-hidden="true" />
      <span>{value}</span>
    </div>
  );
}
