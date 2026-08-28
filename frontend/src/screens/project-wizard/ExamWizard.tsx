import { type ReactNode, useEffect, useRef, useState } from "react";
import { Brain, Calculator, CalendarDays, Check, ClipboardCheck, FileCheck2, FileText, Files, LibraryBig, ListChecks, Pencil, Sparkles, TicketCheck, Upload } from "lucide-react";
import {
  controlMaterialProcessing,
  createTextMaterial,
  detachMaterial,
  importCompositeExamDraftProgram,
  importExamDraftProgramFromMaterial,
  importMaterialReferenceAnswers,
  listMaterials,
  previewExamProgram,
  startMaterialProcessing,
  uploadMaterial,
  type ExamCompositeDraftImportResult,
  type ExamMaterialSlot,
  type LibraryMaterialRead,
  type MaterialPurpose,
  type MaterialRead,
} from "../../api/materials";
import {
  preflightPreparationEstimate,
  runPreparationEstimate,
  updateProgramNode,
  type ExamFormat,
  type GoalPassportWrite,
  type ModuleKey,
  type ProgramNodeRead,
  type ProjectDetail,
  type PreparationEstimateInput,
  type PreparationEstimatePreflightRead,
  type StartingLevel,
  type StudyFormat,
  type TargetOutcome,
} from "../../api/projects";
import { getAiSettings, isAiApiError, type AiSettingsRead } from "../../api/ai";
import type { WizardDraftController } from "../../hooks/useWizardDraft";
import { useProjectMaterials } from "../../hooks/useProjectMaterials";
import { Button, Card, Checkbox, Dialog, Field, IconButton, LoadingState, PageHead, RadioCards, SegmentedTabs, Tooltip } from "../../components/ui";
import type { RadioCardOption } from "../../components/ui";
import { AiFailureNotice, CostEstimate, LibraryMaterialPickerDialog } from "../../components/domain";
import { AiImportRepairDialog } from "../AiImportRepairDialog";
import {
  ExamMaterialUploadPanel,
  type ExamMaterialInputMode,
} from "./ExamMaterialUploadPanel";
import { ExamImportGuide } from "./ExamImportGuide";

interface SlotInput {
  selected: boolean;
  mode: ExamMaterialInputMode;
  text: string;
}

const EMPTY_SLOT: SlotInput = { selected: false, mode: "files", text: "" };

/** UI-выбор шага 1: не вводит новое значение `ExamFormat` — «combined»

 * разворачивается в «questions» или «questions_tasks» в зависимости от того,
 * выбран ли список задач (см. `trackFor`/`deriveCombinedFormat`).
 */
type WizardTrack = "combined" | "tickets" | "unknown";

function trackFor(format: ExamFormat | null): WizardTrack | null {
  if (format === "tickets") return "tickets";
  if (format === "unknown") return "unknown";
  if (format === "questions" || format === "questions_tasks") return "combined";
  return null;
}

interface ExamForm {
  format: ExamFormat | null;
  rawText: string;
  answersText: string;
  hasAnswers: boolean;
  hasTheory: boolean;
  primaryMode: ExamMaterialInputMode;
  answersMode: ExamMaterialInputMode;
  questionList: SlotInput;
  questionAnswers: SlotInput;
  taskList: SlotInput;
  taskAnswers: SlotInput;
  subject: string;
  deadline: string;
  examTime: string;
  expectedCount: string;
  startingLevel: StartingLevel;
  targetOutcome: TargetOutcome;
  studyFormat: StudyFormat;
  currentKnowledge: string;
  important: string;
  instructorRequirements: string;
  examProcedure: string;
  minutesPerDay: string;
  daysPerWeek: string;
  sessionMinutes: string;
}

const EMPTY_FORM: ExamForm = {
  format: null,
  rawText: "",
  answersText: "",
  hasAnswers: false,
  hasTheory: false,
  primaryMode: "files",
  answersMode: "files",
  questionList: EMPTY_SLOT,
  questionAnswers: EMPTY_SLOT,
  taskList: EMPTY_SLOT,
  taskAnswers: EMPTY_SLOT,
  subject: "",
  deadline: "",
  examTime: "",
  expectedCount: "",
  startingLevel: "familiar",
  targetOutcome: "application",
  studyFormat: "theory_and_practice",
  currentKnowledge: "",
  important: "",
  instructorRequirements: "",
  examProcedure: "",
  minutesPerDay: "45",
  daysPerWeek: "4",
  sessionMinutes: "45",
};

const FORMAT_OPTIONS: Array<RadioCardOption<WizardTrack>> = [
  { value: "combined", title: "Отдельные вопросы / задачи", description: "Общий список теоретических вопросов и/или задач без заранее собранных билетов.", icon: <ListChecks size={18} aria-hidden="true" /> },
  { value: "tickets", title: "Готовые билеты", description: "Состав каждого билета известен: вопросы, задачи или их комбинация.", icon: <TicketCheck size={18} aria-hidden="true" /> },
  { value: "unknown", title: "Точного списка пока нет", description: "Сохраним источники сейчас, а официальный список вы добавите позже.", icon: <LibraryBig size={18} aria-hidden="true" /> },
];

const STARTING_OPTIONS: Array<RadioCardOption<StartingLevel>> = [
  { value: "beginner", title: "Начинаю с нуля", description: "Тема почти незнакома" },
  { value: "familiar", title: "Что-то знаю", description: "Есть отдельные знакомые темы" },
  { value: "refreshing", title: "Повторяю забытое", description: "Раньше изучал, нужно восстановить" },
];

const OUTCOME_TABS: Array<{ value: TargetOutcome; label: string; tooltip: string }> = [
  { value: "awareness", label: "Ориентироваться", tooltip: "Узнавать основные темы и термины, понимать вопрос и давать короткий ответ по сути" },
  { value: "understanding", label: "Понимать", tooltip: "Объяснять определения и связи своими словами, приводить простой пример и отвечать на базовые уточнения" },
  { value: "application", label: "Уверенно отвечать", tooltip: "Давать полный ответ без конспекта, разбирать типовые задачи и уверенно отвечать на уточняющие вопросы" },
  { value: "mastery", label: "Владеть свободно", tooltip: "Связывать темы, решать нетиповые задачи, аргументировать ответ и выдерживать глубокий устный разбор" },
];

const STUDY_TABS: Array<{ value: StudyFormat; label: string }> = [
  { value: "theory", label: "Только теория" },
  { value: "theory_and_practice", label: "Теория и задачи" },
  { value: "practice", label: "Больше практики" },
];

const OUTCOME_SUMMARIES: Record<TargetOutcome, string> = {
  awareness: "Вы хотите ориентироваться в предмете.",
  understanding: "Вы хотите понимать предмет.",
  application: "Вы хотите уверенно отвечать.",
  mastery: "Вы хотите владеть материалом свободно.",
};

const STARTING_SUMMARIES: Record<StartingLevel, string> = {
  beginner: "начинаете с нуля.",
  familiar: "уже знаете отдельные темы.",
  refreshing: "повторяете забытое.",
};

const nullable = (value: string): string | null => value.trim() || null;
const positive = (value: string): number | null => {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : null;
};
const plural = (count: number, one: string, few: string, many: string): string => {
  const modulo100 = count % 100;
  const modulo10 = count % 10;
  if (modulo100 >= 11 && modulo100 <= 14) return many;
  if (modulo10 === 1) return one;
  if (modulo10 >= 2 && modulo10 <= 4) return few;
  return many;
};

function formatStudyMinutes(minutes: number) {
  if (minutes < 60) return `${minutes} мин`;
  const hours = minutes / 60;
  return `${Number.isInteger(hours) ? hours : hours.toFixed(1).replace(".", ",")} ч`;
}

function getDailyLoad(deadlineValue: string) {
  const deadline = deadlineValue ? new Date(`${deadlineValue}T00:00:00`) : null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const daysLeft = deadline ? Math.ceil((deadline.getTime() - today.getTime()) / 86_400_000) : null;

  if (!daysLeft || daysLeft <= 0) return { options: [120, 180, 240, 300, 360], hint: "Выберите реальный объём работы — дату экзамена можно добавить позже." };
  if (daysLeft <= 4) return { options: [240, 300, 360, 420, 480], hint: `До экзамена ${daysLeft} дн. Ориентир: 6 ч в день.` };
  if (daysLeft <= 7) return { options: [120, 180, 240, 300, 360], hint: `До экзамена ${daysLeft} дн. Ориентир: 4 ч в день.` };
  if (daysLeft <= 21) return { options: [90, 120, 180, 240, 300], hint: `До экзамена ${daysLeft} дн. Ориентир: 3 ч в день.` };
  return { options: [60, 90, 120, 150, 180], hint: `До экзамена ${daysLeft} дн. Ориентир: 2 ч в день.` };
}

function getExamCountdown(deadlineValue: string, examTime: string) {
  if (!deadlineValue) return null;
  if (!examTime) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const examDay = new Date(`${deadlineValue}T00:00:00`);
    const days = Math.ceil((examDay.getTime() - today.getTime()) / 86_400_000);
    if (days <= 0) return "Экзамен уже сегодня.";
    return `До экзамена ${days} ${plural(days, "день", "дня", "дней")}.`;
  }
  const totalHours = Math.ceil((new Date(`${deadlineValue}T${examTime}:00`).getTime() - Date.now()) / 3_600_000);
  if (totalHours <= 0) return "Экзамен уже сегодня.";
  const days = Math.floor(totalHours / 24);
  const hours = totalHours % 24;
  return `До экзамена ${days > 0 ? `${days} ${plural(days, "день", "дня", "дней")} ` : ""}${hours} ${plural(hours, "час", "часа", "часов")}.`;
}

function formatExamMoment(deadlineValue: string, examTime: string) {
  if (!deadlineValue) return null;
  const label = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric" })
    .format(new Date(`${deadlineValue}T00:00:00`));
  return examTime ? `${label}, ${examTime}` : label;
}

function getPreparationForecast(form: ExamForm, itemCount: number) {
  if (!form.deadline) return null;
  const deadline = new Date(`${form.deadline}T${form.examTime || "23:59"}:00`);
  const daysLeft = Math.max(1, Math.ceil((deadline.getTime() - Date.now()) / 86_400_000));
  const minutes = positive(form.minutesPerDay) ?? 0;
  const minutesPerItem = form.format === "tickets" ? 50 : form.format === "questions_tasks" ? 36 : 30;
  const startMultiplier: Record<StartingLevel, number> = { beginner: 1.35, familiar: 1, refreshing: 0.75 };
  const goalMultiplier: Record<TargetOutcome, number> = { awareness: 0.6, understanding: 0.8, application: 1, mastery: 1.25 };
  const practiceMultiplier = form.studyFormat === "practice" ? 1.1 : 1;
  const ratio = (daysLeft * minutes) / (Math.max(1, itemCount) * minutesPerItem * startMultiplier[form.startingLevel] * goalMultiplier[form.targetOutcome] * practiceMultiplier);

  if (ratio < 0.35) return { title: "будет очень тяжело", text: "времени заметно меньше, чем требует выбранная цель." };
  if (ratio < 0.7) return { title: "план напряжённый", text: "подготовиться можно, но пропуски быстро съедят запас времени." };
  if (ratio < 1.1) return { title: "шансы хорошие", text: "темп реалистичный, если заниматься регулярно." };
  return { title: "запаса достаточно", text: "времени хватает и на спокойное повторение перед экзаменом." };
}

function getMaterialOpinion(form: ExamForm) {
  if (form.format === "unknown") {
    return "Сохраним учебные материалы. Когда появится официальный список, вы добавите его и получите программу экзамена.";
  }
  if (trackFor(form.format) === "combined") {
    const hasStructure = form.questionList.selected || form.taskList.selected;
    const hasAnswers = form.questionAnswers.selected || form.taskAnswers.selected;
    if (!hasStructure) {
      return "Добавьте список вопросов или список задач — без него не из чего собрать программу.";
    }
    if (hasAnswers && form.hasTheory) {
      return "Отличный набор: готовые ответы и решения дадут основу для повторения, а учебные материалы помогут глубже разобраться и уточнить сложные темы.";
    }
    if (hasAnswers) {
      return "Отлично: у вас уже есть всё, чтобы повторять ответы и тренироваться по вопросам и задачам.";
    }
    if (form.hasTheory) {
      return "Учебные материалы помогут не только запомнить ответы, но и разобраться в темах глубже. Готовые ответы и решения можно добавить позже.";
    }
    return "Списка достаточно, чтобы создать программу и начать подготовку. Ответы, решения и учебные материалы можно добавить позже.";
  }
  if (form.hasAnswers && form.hasTheory) {
    return "Отличный набор: готовые ответы дадут основу для повторения, а учебные материалы помогут глубже разобраться и уточнить сложные темы.";
  }
  if (form.hasAnswers) {
    return "Отлично: у вас уже есть всё, чтобы повторять ответы и тренироваться по вопросам.";
  }
  if (form.hasTheory) {
    return "Учебные материалы помогут не только запомнить ответы, но и разобраться в темах глубже. Готовые ответы можно добавить позже.";
  }
  return "Списка вопросов достаточно, чтобы создать программу и начать подготовку. Ответы и учебные материалы можно добавить позже.";
}

function formatDetectedCounts(counts: { tickets: number; questions: number; tasks: number; subpoints?: number }) {
  return [
    counts.tickets > 0 ? `${counts.tickets} ${plural(counts.tickets, "билет", "билета", "билетов")}` : null,
    counts.questions > 0 ? `${counts.questions} ${plural(counts.questions, "вопрос", "вопроса", "вопросов")}` : null,
    counts.tasks > 0 ? `${counts.tasks} ${plural(counts.tasks, "задача", "задачи", "задач")}` : null,
    counts.subpoints ? `${counts.subpoints} ${plural(counts.subpoints, "подпункт", "подпункта", "подпунктов")}` : null,
  ].filter((value): value is string => value !== null).join(" · ");
}

type SlotKey = "questionList" | "questionAnswers" | "taskList" | "taskAnswers";

const SLOT_VALUE: Record<SlotKey, ExamMaterialSlot> = {
  questionList: "question_list",
  questionAnswers: "question_answers",
  taskList: "task_list",
  taskAnswers: "task_answers",
};

const SLOT_PURPOSE: Record<SlotKey, MaterialPurpose> = {
  questionList: "exam_structure",
  questionAnswers: "reference_answers",
  taskList: "exam_structure",
  taskAnswers: "reference_answers",
};

const SLOT_LABEL: Record<SlotKey, string> = {
  questionList: "список вопросов",
  questionAnswers: "готовые ответы на вопросы",
  taskList: "список задач",
  taskAnswers: "решения задач",
};

const SLOT_FILE_NAME: Record<SlotKey, string> = {
  questionList: "Список вопросов",
  questionAnswers: "Готовые ответы",
  taskList: "Список задач",
  taskAnswers: "Решения задач",
};

interface PreparationSuggestion {
  inputKey: string;
  minutesPerDay: number;
  studyDays: number;
  itemsPerDay: number;
  reviewDayReserved: boolean;
  rationale: string;
  cached: boolean;
}

function preparationInputKey(form: ExamForm, itemCount: number) {
  return JSON.stringify({
    deadline: form.deadline,
    examTime: form.examTime,
    itemCount,
    format: form.format,
    startingLevel: form.startingLevel,
    targetOutcome: form.targetOutcome,
    studyFormat: form.studyFormat,
    hasAnswers: form.hasAnswers,
    hasTheory: form.hasTheory,
  });
}

function restoredSuggestion(value: unknown): PreparationSuggestion | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<PreparationSuggestion>;
  return typeof candidate.inputKey === "string"
    && typeof candidate.minutesPerDay === "number"
    && typeof candidate.studyDays === "number"
    && typeof candidate.itemsPerDay === "number"
    && typeof candidate.reviewDayReserved === "boolean"
    && typeof candidate.rationale === "string"
    && typeof candidate.cached === "boolean"
    ? candidate as PreparationSuggestion
    : null;
}

function estimateUnavailableReason(
  settings: AiSettingsRead | null,
  settingsLoaded: boolean,
  form: ExamForm,
  itemCount: number,
) {
  if (!form.deadline) return "Сначала укажите дату экзамена";
  if (itemCount <= 0) return "Сначала укажите или загрузите вопросы и задачи";
  if (!settingsLoaded) return "Проверяем настройки внешних моделей";
  if (!settings?.external_models_enabled) return "Внешние модели выключены в Параметрах";
  const role = settings.roles.find((candidate) => candidate.role === "exam_preparation_estimate");
  if (!role?.enabled || !role.resolved_provider_id || !role.resolved_model) {
    return "Для этой функции не настроена текстовая модель";
  }
  const provider = settings.providers.find((candidate) => candidate.id === role.resolved_provider_id);
  if (!provider?.has_api_key) return "Для выбранного провайдера не сохранён API-ключ";
  return null;
}

interface ExamWizardProps {
  controller: WizardDraftController;
  requestedStep?: number;
  onStepChange?: (step: number) => void;
  onActivated?: (project: ProjectDetail, warning?: string) => void;
}

export function ExamWizard({ controller, requestedStep, onStepChange, onActivated }: ExamWizardProps) {
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<ExamForm>(EMPTY_FORM);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [counts, setCounts] = useState({ tickets: 0, questions: 0, tasks: 0, subpoints: 0 });
  const [actionError, setActionError] = useState("");
  const [reviewRepairOpen, setReviewRepairOpen] = useState(false);
  const [libraryPurpose, setLibraryPurpose] = useState<MaterialPurpose | null>(null);
  const [librarySlot, setLibrarySlot] = useState<SlotKey | null>(null);
  const [aiSettings, setAiSettings] = useState<AiSettingsRead | null>(null);
  const [aiSettingsLoaded, setAiSettingsLoaded] = useState(false);
  const [estimatePending, setEstimatePending] = useState(false);
  const [estimateError, setEstimateError] = useState<unknown>(null);
  const [estimateConfirmation, setEstimateConfirmation] = useState<{
    preview: PreparationEstimatePreflightRead;
    input: PreparationEstimateInput;
  } | null>(null);
  const [preparationSuggestion, setPreparationSuggestion] = useState<PreparationSuggestion | null>(null);
  const initializedKey = useRef<string | null>(null);
  const projectMaterials = useProjectMaterials(controller.detail?.project.id);
  const programItemCount = (controller.detail?.program.nodes ?? []).filter((node) => node.node_type !== "section").length;

  useEffect(() => {
    const abort = new AbortController();
    void getAiSettings(abort.signal)
      .then(setAiSettings)
      .catch(() => setAiSettings(null))
      .finally(() => setAiSettingsLoaded(true));
    return () => abort.abort();
  }, []);

  useEffect(() => {
    if (controller.detail || controller.status !== "idle") return;
    void controller.ensureDraft().catch((error) => {
      setActionError(error instanceof Error ? error.message : "Не удалось создать черновик");
    });
  }, [controller.detail, controller.ensureDraft, controller.status]);

  useEffect(() => {
    const detail = controller.detail;
    const key = detail ? `${detail.project.id}:${controller.hydrationVersion}` : null;
    if (!detail || initializedKey.current === key) return;
    initializedKey.current = key;
    const state = detail.draft.state;
    const goal = detail.goal_passport;
    const restoredFormat = (state.exam_format as ExamFormat | undefined)
      ?? goal?.exam_format
      ?? null;
    const inputModes = state.input_modes && typeof state.input_modes === "object"
      ? state.input_modes as Record<string, unknown>
      : {};
    const restoredHasAnswers = state.has_answers === true;
    const restoredRawText = typeof state.raw_text === "string" ? state.raw_text : "";
    const restoredAnswersText = typeof state.answer_text === "string" ? state.answer_text : "";
    const restoredPrimaryMode: ExamMaterialInputMode = inputModes.primary === "text" ? "text" : "files";
    const restoredAnswersMode: ExamMaterialInputMode = inputModes.answers === "text" ? "text" : "files";
    const rawSlots = state.slots && typeof state.slots === "object"
      ? state.slots as Record<string, Partial<SlotInput>>
      : null;
    const restoreSlot = (key: string, legacyFallback: SlotInput): SlotInput => {
      const raw = rawSlots?.[key];
      if (!raw) return legacyFallback;
      return {
        selected: raw.selected === true,
        mode: raw.mode === "text" ? "text" : "files",
        text: typeof raw.text === "string" ? raw.text : "",
      };
    };
    // Старый черновик (`questions`/`questions_tasks`, ещё без `state.slots`):
    // прежний список занимает слот вопросов «как один legacy-вход», прежний
    // общий файл ответов — слот ответов на вопросы. Разделять не обязательно.
    const restoredWarnings = Array.isArray(state.warnings)
      ? state.warnings.filter((warning): warning is string => typeof warning === "string")
      : [];
    setStep(detail.draft.current_step);
    setWarnings(restoredWarnings);
    setPreparationSuggestion(restoredSuggestion(state.preparation_suggestion));
    setCounts({
      tickets: detail.program.nodes.filter((node) => node.exam_kind === "ticket").length,
      questions: detail.program.nodes.filter(
        (node) => node.exam_kind === "question" && node.node_type === "topic",
      ).length,
      tasks: detail.program.nodes.filter(
        (node) => node.exam_kind === "task" && node.node_type === "topic",
      ).length,
      subpoints: detail.program.nodes.filter((node) => node.node_type === "subpoint").length,
    });
    setForm({
      format: restoredFormat,
      rawText: restoredRawText,
      answersText: restoredAnswersText,
      hasAnswers: restoredHasAnswers,
      hasTheory: restoredFormat === "unknown" || state.has_theory === true,
      primaryMode: restoredPrimaryMode,
      answersMode: restoredAnswersMode,
      questionList: restoreSlot("question_list", {
        selected: trackFor(restoredFormat) === "combined",
        mode: restoredPrimaryMode,
        text: restoredRawText,
      }),
      questionAnswers: restoreSlot("question_answers", {
        selected: trackFor(restoredFormat) === "combined" && restoredHasAnswers,
        mode: restoredAnswersMode,
        text: restoredAnswersText,
      }),
      taskList: restoreSlot("task_list", EMPTY_SLOT),
      taskAnswers: restoreSlot("task_answers", EMPTY_SLOT),
      subject: goal?.subject ?? "",
      deadline: detail.project.deadline ?? "",
      examTime: goal?.exam_time?.slice(0, 5) ?? "",
      expectedCount: goal?.expected_item_count ? String(goal.expected_item_count) : "",
      startingLevel: goal?.starting_level ?? "familiar",
      targetOutcome: goal?.target_outcome ?? "application",
      studyFormat: goal?.study_format ?? "theory_and_practice",
      currentKnowledge: goal?.current_knowledge ?? "",
      important: goal?.important ?? "",
      instructorRequirements: goal?.instructor_requirements ?? "",
      examProcedure: goal?.exam_procedure ?? "",
      minutesPerDay: goal?.minutes_per_day ? String(goal.minutes_per_day) : "45",
      daysPerWeek: goal?.days_per_week ? String(goal.days_per_week) : "4",
      sessionMinutes: goal?.session_minutes ? String(goal.session_minutes) : "45",
    });
  }, [controller.detail, controller.hydrationVersion]);

  useEffect(() => {
    if (requestedStep !== undefined && requestedStep !== step) setStep(requestedStep);
  }, [requestedStep, step]);

  function changeStep(nextStep: number) {
    setStep(nextStep);
    onStepChange?.(nextStep);
  }

  function passport(): GoalPassportWrite {
    return {
      subject: nullable(form.subject),
      purpose: "exam",
      scope: "whole",
      starting_level: form.startingLevel,
      current_knowledge: nullable(form.currentKnowledge),
      target_outcome: form.targetOutcome,
      goal: form.subject.trim() ? `Подготовиться к экзамену по предмету «${form.subject.trim()}»` : null,
      success_criterion: form.format === "questions"
        ? "Уверенно воспроизвести и объяснить ответ на случайный вопрос без конспекта"
        : "Уверенно ответить на случайный вопрос и решить типовую задачу без конспекта",
      important: nullable(form.important),
      excluded: null,
      study_format: form.studyFormat,
      minutes_per_day: positive(form.minutesPerDay),
      days_per_week: positive(form.daysPerWeek),
      session_minutes: positive(form.sessionMinutes),
      exam_format: form.format,
      expected_item_count: positive(form.expectedCount),
      instructor_requirements: nullable(form.instructorRequirements),
      exam_time: nullable(form.examTime),
      exam_procedure: nullable(form.examProcedure),
    };
  }

  function command(nextStep: number, nextWarnings = warnings) {
    return {
      current_step: nextStep,
      max_completed_step: Math.max(nextStep, controller.detail?.draft.max_completed_step ?? 1),
      schema_version: 1,
      project: {
        name: form.subject.trim() ? `${form.subject.trim()} — экзамен` : null,
        description: null,
        icon: "database" as const,
        color: 2,
        deadline: nullable(form.deadline),
        enabled_modules: ["plan", "cards", "repetitions", "oral_answers"] as ModuleKey[],
      },
      goal_passport: passport(),
      state: {
        raw_text: form.rawText,
        answer_text: form.answersText,
        exam_format: form.format,
        has_answers: form.hasAnswers,
        has_theory: form.format === "unknown" || form.hasTheory,
        input_modes: { primary: form.primaryMode, answers: form.answersMode },
        slots: {
          question_list: form.questionList,
          question_answers: form.questionAnswers,
          task_list: form.taskList,
          task_answers: form.taskAnswers,
        },
        warnings: nextWarnings,
        preparation_suggestion: preparationSuggestion,
      },
    };
  }

  useEffect(() => {
    const key = controller.detail ? `${controller.detail.project.id}:${controller.hydrationVersion}` : null;
    if (!controller.detail || initializedKey.current !== key || controller.conflict) return;
    const timer = window.setTimeout(() => {
      void controller.queueSave(command(step)).catch(() => undefined);
    }, 400);
    return () => window.clearTimeout(timer);
  }, [form, preparationSuggestion, step, warnings]);

  useEffect(() => {
    if (!preparationSuggestion) return;
    const currentKey = preparationInputKey(form, positive(form.expectedCount) ?? programItemCount);
    if (preparationSuggestion.inputKey !== currentKey) {
      setPreparationSuggestion(null);
      setEstimateConfirmation(null);
    }
  }, [form, preparationSuggestion, programItemCount]);

  function preparationInput(): PreparationEstimateInput | null {
    const itemCount = positive(form.expectedCount) ?? programItemCount;
    if (!form.deadline || !form.format || itemCount <= 0) return null;
    return {
      exam_date: form.deadline,
      exam_time: nullable(form.examTime),
      item_count: itemCount,
      exam_format: form.format,
      starting_level: form.startingLevel,
      target_outcome: form.targetOutcome,
      study_format: form.studyFormat,
      has_answers: form.hasAnswers,
      has_theory: form.format === "unknown" || form.hasTheory,
    };
  }

  async function applyPreparationEstimate(
    preview: PreparationEstimatePreflightRead,
    input: PreparationEstimateInput,
    confirmed: boolean,
  ) {
    const projectId = controller.detail?.project.id;
    if (!projectId) return;
    setEstimatePending(true);
    setEstimateError(null);
    try {
      const result = await runPreparationEstimate(projectId, {
        ...input,
        expected_input_hash: preview.input_hash,
        confirmed,
      });
      setForm((current) => ({ ...current, minutesPerDay: String(result.minutes_per_day) }));
      setPreparationSuggestion({
        inputKey: preparationInputKey(form, input.item_count),
        minutesPerDay: result.minutes_per_day,
        studyDays: result.study_days,
        itemsPerDay: result.items_per_day,
        reviewDayReserved: result.review_day_reserved,
        rationale: result.rationale,
        cached: result.cached,
      });
      setEstimateConfirmation(null);
    } catch (error) {
      setEstimateError(error);
    } finally {
      setEstimatePending(false);
    }
  }

  async function suggestPreparationTime() {
    const projectId = controller.detail?.project.id;
    const input = preparationInput();
    if (!projectId || !input) return;
    setEstimatePending(true);
    setEstimateError(null);
    try {
      const preview = await preflightPreparationEstimate(projectId, input);
      if (preview.preflight.confirmation_required) {
        setEstimateConfirmation({ preview, input });
      } else {
        await applyPreparationEstimate(preview, input, false);
      }
    } catch (error) {
      setEstimateError(error);
    } finally {
      setEstimatePending(false);
    }
  }

  function changeMinutes(minutesPerDay: string) {
    setForm((current) => ({ ...current, minutesPerDay }));
  }

  async function go(nextStep: number) {
    setActionError("");
    try {
      await controller.queueSave(command(nextStep));
      changeStep(nextStep);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось сохранить шаг");
    }
  }

  const materialsFor = (purpose: MaterialPurpose) => projectMaterials.materials.filter(
    (material) => material.purposes.includes(purpose),
  );

  function openLibraryPicker(purpose: MaterialPurpose, slot?: SlotKey) {
    setLibraryPurpose(purpose);
    setLibrarySlot(slot ?? null);
  }

  async function addFiles(purpose: MaterialPurpose, files: File[]) {
    const draft = await controller.ensureDraft();
    const existingStudyCount = materialsFor("study_source").length;
    for (const [index, file] of files.entries()) {
      const sourceRole = purpose === "study_source" && existingStudyCount + index === 0
        ? "main"
        : purpose === "study_source" ? "additional" : "reference";
      const material = await uploadMaterial(draft.project.id, file, sourceRole, [purpose]);
      if (purpose === "exam_structure" && material.status === "ready_to_process") {
        await startMaterialProcessing(draft.project.id, material.id, "fast");
      }
    }
    await projectMaterials.refresh();
  }

  async function attachedLibraryMaterials(materials: LibraryMaterialRead[]) {
    const projectId = controller.detail?.project.id;
    if (!projectId || !libraryPurpose) return;
    if (libraryPurpose === "exam_structure") {
      for (const material of materials) {
        if (material.status === "ready_to_process") {
          await startMaterialProcessing(projectId, material.id, "fast");
        }
      }
    }
    await projectMaterials.refresh();
  }

  async function removeMaterial(material: MaterialRead) {
    const projectId = controller.detail?.project.id;
    if (!projectId) return;
    await detachMaterial(projectId, material.id);
    await projectMaterials.refresh();
  }

  async function retryMaterial(material: MaterialRead) {
    const projectId = controller.detail?.project.id;
    if (!projectId) return;
    await controlMaterialProcessing(projectId, material.id, "retry");
    await projectMaterials.refresh();
  }

  async function changeInputMode(
    role: "primary" | "answers",
    nextMode: ExamMaterialInputMode,
  ) {
    const currentMode = role === "primary" ? form.primaryMode : form.answersMode;
    if (currentMode === nextMode) return;
    const purpose = role === "primary" ? "exam_structure" : "reference_answers";
    const currentMaterials = materialsFor(purpose);
    const currentText = role === "primary" ? form.rawText : form.answersText;
    if (nextMode === "text" && currentMaterials.length > 0) {
      if (!window.confirm("Файл будет убран из проекта. Переключиться на вставку текста?")) return;
      await Promise.all(currentMaterials.map(removeMaterial));
    }
    if (nextMode === "files" && currentText.trim()) {
      if (!window.confirm("Вставленный текст будет очищен. Переключиться на файлы?")) return;
    }
    setForm((current) => ({
      ...current,
      primaryMode: role === "primary" ? nextMode : current.primaryMode,
      answersMode: role === "answers" ? nextMode : current.answersMode,
      rawText: role === "primary" && nextMode === "files" ? "" : current.rawText,
      answersText: role === "answers" && nextMode === "files" ? "" : current.answersText,
    }));
  }

  async function setOptionalMaterial(kind: "answers" | "theory", selected: boolean) {
    const purpose = kind === "answers" ? "reference_answers" : "study_source";
    const existing = materialsFor(purpose);
    if (!selected && existing.length > 0) {
      if (!window.confirm("Добавленные материалы будут убраны из проекта. Продолжить?")) return;
      await Promise.all(existing.map(removeMaterial));
    }
    setForm((current) => ({
      ...current,
      hasAnswers: kind === "answers" ? selected : current.hasAnswers,
      hasTheory: kind === "theory" ? selected : current.hasTheory,
      answersText: kind === "answers" && !selected ? "" : current.answersText,
    }));
  }

  /** Материалы конкретного слота. Единственный материал без слота считается
   * прежним объединённым/общим файлом старого черновика — так завершить его
   * можно без обязательного разделения (см. FR составного импорта). */
  function materialsForSlot(key: SlotKey): MaterialRead[] {
    const purpose = SLOT_PURPOSE[key];
    const slotValue = SLOT_VALUE[key];
    const exact = projectMaterials.materials.filter(
      (material) => material.purposes.includes(purpose) && material.exam_slot === slotValue,
    );
    if (exact.length > 0) return exact;
    if (key !== "questionList" && key !== "questionAnswers") return [];
    const unslotted = projectMaterials.materials.filter(
      (material) => material.purposes.includes(purpose) && !material.exam_slot,
    );
    return unslotted.length === 1 ? unslotted : [];
  }

  async function addSlotFiles(key: SlotKey, files: File[]) {
    const draft = await controller.ensureDraft();
    const purpose = SLOT_PURPOSE[key];
    const slotValue = SLOT_VALUE[key];
    for (const file of files) {
      const material = await uploadMaterial(draft.project.id, file, "reference", [purpose], slotValue);
      if (purpose === "exam_structure" && material.status === "ready_to_process") {
        await startMaterialProcessing(draft.project.id, material.id, "fast");
      }
    }
    await projectMaterials.refresh();
  }

  async function changeSlotMode(key: SlotKey, nextMode: ExamMaterialInputMode) {
    const slot = form[key];
    if (slot.mode === nextMode) return;
    const existing = materialsForSlot(key);
    if (nextMode === "text" && existing.length > 0) {
      if (!window.confirm("Файл будет убран из проекта. Переключиться на вставку текста?")) return;
      await Promise.all(existing.map(removeMaterial));
    }
    if (nextMode === "files" && slot.text.trim()) {
      if (!window.confirm("Вставленный текст будет очищен. Переключиться на файлы?")) return;
    }
    setForm((current) => ({
      ...current,
      [key]: { ...current[key], mode: nextMode, text: nextMode === "files" ? "" : current[key].text },
    }));
  }

  function slotText(key: SlotKey, text: string) {
    setForm((current) => ({ ...current, [key]: { ...current[key], text } }));
  }

  /** Список и его ответы связаны: снятие списка отключает и файл ответов —
   * мастер предупреждает об этом одним подтверждением на оба файла. */
  async function toggleListSlot(listKey: "questionList" | "taskList", selected: boolean) {
    const answersKey: SlotKey = listKey === "questionList" ? "questionAnswers" : "taskAnswers";
    const listMaterials = materialsForSlot(listKey);
    const answerMaterials = selected ? [] : materialsForSlot(answersKey);
    const toRemove = [...listMaterials, ...answerMaterials];
    if (!selected && toRemove.length > 0) {
      const noun = listKey === "questionList" ? "список вопросов и связанные с ним ответы" : "список задач и связанные с ним решения";
      if (!window.confirm(`Файл будет отключён от проекта (${noun}). Продолжить?`)) return;
    }
    if (!selected) await Promise.all(toRemove.map(removeMaterial));
    setForm((current) => {
      const next: ExamForm = {
        ...current,
        [listKey]: { ...current[listKey], selected, text: selected ? current[listKey].text : "" },
      };
      if (!selected) next[answersKey] = EMPTY_SLOT;
      if (listKey === "taskList") {
        next.format = selected ? "questions_tasks" : (next.questionList.selected ? "questions" : current.format);
      }
      next.hasAnswers = next.questionAnswers.selected || next.taskAnswers.selected;
      return next;
    });
  }

  async function toggleAnswersSlot(key: "questionAnswers" | "taskAnswers", selected: boolean) {
    const existing = materialsForSlot(key);
    if (!selected && existing.length > 0) {
      if (!window.confirm("Файл будет отключён от проекта. Продолжить?")) return;
      await Promise.all(existing.map(removeMaterial));
    }
    setForm((current) => {
      const next: ExamForm = {
        ...current,
        [key]: { ...current[key], selected, text: selected ? current[key].text : "" },
      };
      next.hasAnswers = next.questionAnswers.selected || next.taskAnswers.selected;
      return next;
    });
  }

  async function continueLegacyTrack() {
    const primaryMaterials = materialsFor("exam_structure");
    const answerMaterials = materialsFor("reference_answers");

    if (form.format !== "unknown") {
      if (form.primaryMode === "text") {
        if (!form.rawText.trim()) throw new Error("Вставьте список вопросов или выберите файл");
        const result = await controller.importExam(form.rawText, form.format as Exclude<ExamFormat, "unknown">);
        setWarnings(result.warnings);
        setCounts(result.counts);
      } else {
        const primary = primaryMaterials[0];
        if (!primary) throw new Error("Добавьте файл со списком вопросов или билетов");
        if (primary.status !== "ready") {
          throw new Error(primary.status === "failed"
            ? primary.error || "Не удалось разобрать файл вопросов"
            : "Дождитесь завершения быстрого разбора файла вопросов");
        }
        const preview = await previewExamProgram(controller.detail!.project.id, primary.id);
        await controller.enqueueProgramCommand((current) => importExamDraftProgramFromMaterial(
          current.project.id,
          primary.id,
          current.draft.revision,
          current.program.revision,
        ));
        setWarnings(preview.warnings);
        setCounts({ ...preview.counts, subpoints: preview.counts.subpoints ?? 0 });
      }
    }

    if (form.hasAnswers) {
      if (form.answersMode === "text") {
        if (!form.answersText.trim()) throw new Error("Вставьте готовые ответы или выберите файл");
        if (answerMaterials.length === 0) {
          await createTextMaterial(controller.detail!.project.id, {
            name: "Готовые ответы.txt",
            text: form.answersText,
            source_role: "reference",
            purposes: ["reference_answers"],
          });
        }
      } else if (answerMaterials.length === 0) {
        throw new Error("Добавьте файл с готовыми ответами");
      }
    }

    if ((form.format === "unknown" || form.hasTheory) && materialsFor("study_source").length === 0) {
      throw new Error("Добавьте хотя бы один учебный материал");
    }
  }

  async function continueCombinedTrack() {
    const projectId = controller.detail!.project.id;
    const listKeys: SlotKey[] = ["questionList", "questionAnswers", "taskList", "taskAnswers"];
    if (!form.questionList.selected && !form.taskList.selected) {
      throw new Error("Добавьте список вопросов или список задач");
    }

    // Материалы, создаваемые прямо здесь (вставленный текст), читаем из
    // возвращаемого значения запроса, а не из хука материалов: React ещё не
    // перерисовал компонент с новым состоянием внутри той же цепочки await,
    // поэтому `projectMaterials.materials` в этом вызове остаётся старым.
    const materialBySlot: Partial<Record<SlotKey, MaterialRead>> = {};
    for (const key of listKeys) {
      const slot = form[key];
      if (!slot.selected) continue;
      if (slot.mode === "text") {
        if (!slot.text.trim()) throw new Error(`Вставьте текст в раздел «${SLOT_LABEL[key]}» или выберите файл`);
        const existing = materialsForSlot(key)[0];
        if (existing) {
          materialBySlot[key] = existing;
          continue;
        }
        const material = await createTextMaterial(projectId, {
          name: `${SLOT_FILE_NAME[key]}.txt`,
          text: slot.text,
          source_role: "reference",
          purposes: [SLOT_PURPOSE[key]],
          exam_slot: SLOT_VALUE[key],
        });
        if (SLOT_PURPOSE[key] === "exam_structure" && material.status === "ready_to_process") {
          await startMaterialProcessing(projectId, material.id, "fast");
        }
        materialBySlot[key] = material;
      } else {
        const existing = materialsForSlot(key)[0];
        if (!existing) throw new Error(`Добавьте файл в раздел «${SLOT_LABEL[key]}»`);
        materialBySlot[key] = existing;
      }
    }

    // Быстрый разбор списков вопросов/задач может ещё идти — опрашиваем сервер
    // напрямую (не через хук) и ждём короткое время, прежде чем сдаться.
    for (const key of (["questionList", "taskList"] as const)) {
      let material = materialBySlot[key];
      if (!material) continue;
      for (let attempt = 0; attempt < 30 && material.status !== "ready" && material.status !== "failed"; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 400));
        const fresh = await listMaterials(projectId);
        material = fresh.find((item) => item.id === material!.id) ?? material;
      }
      materialBySlot[key] = material;
      if (material.status !== "ready") {
        throw new Error(material.status === "failed"
          ? material.error || `Не удалось разобрать файл: ${SLOT_LABEL[key]}`
          : `Дождитесь завершения быстрого разбора файла: ${SLOT_LABEL[key]}`);
      }
    }

    await projectMaterials.refresh();

    const questionMaterial = materialBySlot.questionList;
    const taskMaterial = materialBySlot.taskList;
    const isLegacyQuestionOnly = Boolean(questionMaterial && !questionMaterial.exam_slot && !taskMaterial);

    if (isLegacyQuestionOnly && questionMaterial) {
      // Старый черновик до этого слота: файл ещё не разделён на вопросы/задачи —
      // завершаем его прежним однослотовым импортом, как раньше.
      const preview = await previewExamProgram(controller.detail!.project.id, questionMaterial.id);
      await controller.enqueueProgramCommand((current) => importExamDraftProgramFromMaterial(
        current.project.id,
        questionMaterial.id,
        current.draft.revision,
        current.program.revision,
      ));
      setWarnings(preview.warnings);
      setCounts({ ...preview.counts, subpoints: preview.counts.subpoints ?? 0 });
    } else if (questionMaterial || taskMaterial) {
      let captured: Awaited<ReturnType<typeof importCompositeExamDraftProgram>> | null = null;
      await controller.enqueueProgramCommand(async (current) => {
        const result = await importCompositeExamDraftProgram(current.project.id, {
          expected_draft_revision: current.draft.revision,
          expected_program_revision: current.program.revision,
          question_material_id: questionMaterial?.id ?? null,
          task_material_id: taskMaterial?.id ?? null,
        });
        captured = result;
        return result.change;
      });
      if (captured) {
        const result = captured as ExamCompositeDraftImportResult;
        setWarnings(result.warnings);
        setCounts({ tickets: 0, ...result.counts });
      }
    }

    if (form.hasTheory && materialsFor("study_source").length === 0) {
      throw new Error("Добавьте хотя бы один учебный материал");
    }
  }

  async function continueFromUpload() {
    if (!form.format) return;
    setActionError("");
    try {
      await controller.queueSave(command(3));
      if (trackFor(form.format) === "combined") {
        await continueCombinedTrack();
      } else {
        await continueLegacyTrack();
      }
      await projectMaterials.refresh();
      await controller.queueSave(command(4));
      changeStep(4);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось подготовить материалы");
    }
  }

  async function activate() {
    setActionError("");
    try {
      await controller.queueSave(command(5));
      const project = await controller.activate();
      const projectId = project.project.id;
      const auxiliary = projectMaterials.materials.filter((material) =>
        material.purposes.some((purpose) => ["reference_answers", "study_source"].includes(purpose)),
      );
      const starts = auxiliary.map(async (material) => {
        if (material.status === "ready_to_process") {
          await startMaterialProcessing(projectId, material.id, "fast");
        } else if (material.status === "ready" && material.purposes.includes("reference_answers")) {
          await importMaterialReferenceAnswers(projectId, material.id);
        }
      });
      const results = await Promise.allSettled(starts);
      const failed = results.filter((result) => result.status === "rejected").length;
      onActivated?.(
        project,
        failed > 0
          ? `Проект создан, но не удалось запустить обработку ${failed} материалов. Продолжите её в разделе «Материалы».`
          : undefined,
      );
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось создать проект");
    }
  }

  if (controller.status === "loading") return <LoadingState label="Загружаем экзаменационный черновик" placement="page" />;

  const busy = controller.status === "saving";
  const studyCount = programItemCount;
  const repairNodes = (controller.detail?.program.nodes ?? [])
    .filter((node) => node.is_in_current_program && !node.is_archived && node.node_type !== "section");
  const expectedCount = positive(form.expectedCount);
  const countMismatch = expectedCount !== null && expectedCount !== studyCount;
  const dailyLoad = getDailyLoad(form.deadline);
  const examCountdown = getExamCountdown(form.deadline, form.examTime);
  const preparationForecast = getPreparationForecast(form, expectedCount ?? studyCount);
  const estimateDisabledReason = estimateUnavailableReason(aiSettings, aiSettingsLoaded, form, expectedCount ?? studyCount);

  return (
    <div className="wizard-flow">
      {(actionError || controller.error || projectMaterials.error) && <p className="inline-error" role="alert">{actionError || controller.error?.message || projectMaterials.error}</p>}
      {controller.conflict && <Card><h2>Черновик изменился в другой вкладке</h2><p>Загрузите серверную версию, чтобы не затереть изменения.</p><Button onClick={() => void controller.reload()}>Загрузить серверную версию</Button></Card>}

      {step === 1 && <section className="wizard-step"><PageHead eyebrow="Сначала — структура" title="Как устроен ваш экзамен?" /><p>Это определит, как Tentex сохранит формулировки и соберёт из них программу.</p><RadioCards label="Формат экзамена" value={trackFor(form.format)} options={FORMAT_OPTIONS} onChange={(track) => setForm((current) => ({ ...current, format: track === "combined" ? (current.taskList.selected ? "questions_tasks" : "questions") : track, hasTheory: track === "unknown" || current.hasTheory }))} className="wizard-format-options" />{form.format === "unknown" && <div className="wizard-context-note"><LibraryBig size={18} aria-hidden="true" /><span><b>Официальный список добавите позже</b>Сейчас сохраним учебные источники. Без прохода 1 предварительную программу по ним не выдумываем.</span></div>}<div className="wizard-actions"><Button disabled={busy || !form.format} onClick={() => void go(2)}>Продолжить</Button></div></section>}

      {step === 2 && (
        <section className="wizard-step">
          <PageHead eyebrow="Материалы" title="Что у вас уже есть?" />
          <p>{form.format === "unknown"
            ? "Раз точного списка нет, начнём с учебных материалов. Официальные вопросы можно будет добавить позже."
            : trackFor(form.format) === "combined"
              ? "Список вопросов и список задач независимы — принесите один из них или оба."
              : "Список вопросов или билетов уже считаем основой. Отметьте, есть ли что-то ещё."}</p>
          {trackFor(form.format) === "combined" ? (
            <div className="wizard-material-grid">
              <SelectableMaterial
                selected={form.questionList.selected}
                onChange={(selected) => void toggleListSlot("questionList", selected)}
                icon={<ListChecks size={22} aria-hidden="true" />}
                title="Список вопросов"
                description="Отдельный файл или вставленный текст с формулировками вопросов."
                action="Добавить список вопросов"
              />
              <SelectableMaterial
                selected={form.questionAnswers.selected}
                disabledReason={form.questionList.selected ? undefined : "Сначала добавьте список вопросов"}
                onChange={(selected) => void toggleAnswersSlot("questionAnswers", selected)}
                icon={<FileCheck2 size={22} aria-hidden="true" />}
                title="Готовые ответы на них"
                description="На все вопросы или только на часть — сопоставим после разбора."
                action="Добавить ответы"
              />
              <SelectableMaterial
                selected={form.taskList.selected}
                onChange={(selected) => void toggleListSlot("taskList", selected)}
                icon={<Calculator size={22} aria-hidden="true" />}
                title="Список задач"
                description="Отдельный файл или вставленный текст с формулировками задач."
                action="Добавить список задач"
              />
              <SelectableMaterial
                selected={form.taskAnswers.selected}
                disabledReason={form.taskList.selected ? undefined : "Сначала добавьте список задач"}
                onChange={(selected) => void toggleAnswersSlot("taskAnswers", selected)}
                icon={<ClipboardCheck size={22} aria-hidden="true" />}
                title="Решения / ответы к ним"
                description="На все задачи или только на часть — сопоставим после разбора."
                action="Добавить решения"
              />
              <SelectableMaterial
                wide
                selected={form.hasTheory}
                onChange={(selected) => void setOptionalMaterial("theory", selected)}
                icon={<Files size={22} aria-hidden="true" />}
                title="Учебные материалы"
                description="Учебники, методички, лекции, конспекты, статьи, веб-страницы и видеолекции по ссылке на YouTube. Файлы можно загрузить в мастере, остальные источники — выбрать из Библиотеки."
                action="Добавить материалы"
              />
            </div>
          ) : (
            <div className={`wizard-material-grid${form.format === "unknown" ? " has-one" : ""}`}>
              {form.format !== "unknown" && (
                <SelectableMaterial
                  selected
                  locked
                  icon={<ListChecks size={22} aria-hidden="true" />}
                  title="Билеты"
                  description="Главная структура экзамена — файл или вставленный текст."
                  action="Добавить список"
                />
              )}
              {form.format !== "unknown" && (
                <SelectableMaterial
                  selected={form.hasAnswers}
                  onChange={(selected) => void setOptionalMaterial("answers", selected)}
                  icon={<FileCheck2 size={22} aria-hidden="true" />}
                  title="Готовые ответы"
                  description="На все вопросы или только на часть — сопоставим после разбора."
                  action="Добавить ответы"
                />
              )}
              <SelectableMaterial
                wide
                selected={form.format === "unknown" || form.hasTheory}
                locked={form.format === "unknown"}
                onChange={(selected) => void setOptionalMaterial("theory", selected)}
                icon={<Files size={22} aria-hidden="true" />}
                title="Учебные материалы"
                description="Учебники, методички, лекции, конспекты, статьи, веб-страницы и видеолекции по ссылке на YouTube. Файлы можно загрузить в мастере, остальные источники — выбрать из Библиотеки."
                action="Добавить материалы"
              />
            </div>
          )}
          {trackFor(form.format) === "combined" && !form.questionList.selected && !form.taskList.selected && (
            <p className="inline-error" role="alert">Добавьте список вопросов или список задач</p>
          )}
          <div className="wizard-context-note is-hint">
            <Brain size={18} aria-hidden="true" />
            <span>{getMaterialOpinion(form)}</span>
          </div>
          {form.format === "unknown" && <p className="wizard-quiet-note">Если ваша цель — изучать конкретную методичку, удобнее соседний маршрут «Изучение по учебнику».</p>}
          <div className="wizard-actions">
            <Button variant="ghost" onClick={() => changeStep(1)}>Назад</Button>
            <Button
              disabled={trackFor(form.format) === "combined" && !form.questionList.selected && !form.taskList.selected}
              onClick={() => void go(3)}
            >
              Продолжить
            </Button>
          </div>
        </section>
      )}

      {step === 3 && (
        <section className="wizard-step">
          <PageHead
            eyebrow="Загрузка"
            title="Добавьте то, что у вас есть"
          />
          <p>Добавьте список вопросов, готовые ответы и дополнительные источники. Список разберём сразу; ответы и учебные материалы начнём обрабатывать после создания проекта.</p>
          {trackFor(form.format) === "combined" && <ExamImportGuide />}
          <div className="wizard-upload-stack">
            {trackFor(form.format) === "combined" ? (
              <>
                {form.questionList.selected && (
                  <ExamMaterialUploadPanel
                    icon={<ListChecks size={20} aria-hidden="true" />}
                    title="Список вопросов"
                    description="Главная структура — вопросы экзамена"
                    examSlot="question_list"
                    allowText
                    mode={form.questionList.mode}
                    onModeChange={(mode) => void changeSlotMode("questionList", mode)}
                    materials={materialsForSlot("questionList")}
                    text={form.questionList.text}
                    onTextChange={(text) => slotText("questionList", text)}
                    onFiles={(files) => addSlotFiles("questionList", files)}
                    onChooseLibrary={() => openLibraryPicker("exam_structure", "questionList")}
                    onRemove={removeMaterial}
                    onRetry={retryMaterial}
                  />
                )}
                {form.questionAnswers.selected && (
                  <ExamMaterialUploadPanel
                    icon={<FileCheck2 size={20} aria-hidden="true" />}
                    title="Готовые ответы на вопросы"
                    description="На все вопросы или только на часть"
                    examSlot="question_answers"
                    allowText
                    mode={form.questionAnswers.mode}
                    onModeChange={(mode) => void changeSlotMode("questionAnswers", mode)}
                    materials={materialsForSlot("questionAnswers")}
                    text={form.questionAnswers.text}
                    onTextChange={(text) => slotText("questionAnswers", text)}
                    onFiles={(files) => addSlotFiles("questionAnswers", files)}
                    onChooseLibrary={() => openLibraryPicker("reference_answers", "questionAnswers")}
                    onRemove={removeMaterial}
                    onRetry={retryMaterial}
                  />
                )}
                {form.taskList.selected && (
                  <ExamMaterialUploadPanel
                    icon={<Calculator size={20} aria-hidden="true" />}
                    title="Список задач"
                    description="Главная структура — задачи экзамена"
                    examSlot="task_list"
                    allowText
                    mode={form.taskList.mode}
                    onModeChange={(mode) => void changeSlotMode("taskList", mode)}
                    materials={materialsForSlot("taskList")}
                    text={form.taskList.text}
                    onTextChange={(text) => slotText("taskList", text)}
                    onFiles={(files) => addSlotFiles("taskList", files)}
                    onChooseLibrary={() => openLibraryPicker("exam_structure", "taskList")}
                    onRemove={removeMaterial}
                    onRetry={retryMaterial}
                  />
                )}
                {form.taskAnswers.selected && (
                  <ExamMaterialUploadPanel
                    icon={<ClipboardCheck size={20} aria-hidden="true" />}
                    title="Решения / ответы к задачам"
                    description="На все задачи или только на часть"
                    examSlot="task_answers"
                    allowText
                    mode={form.taskAnswers.mode}
                    onModeChange={(mode) => void changeSlotMode("taskAnswers", mode)}
                    materials={materialsForSlot("taskAnswers")}
                    text={form.taskAnswers.text}
                    onTextChange={(text) => slotText("taskAnswers", text)}
                    onFiles={(files) => addSlotFiles("taskAnswers", files)}
                    onChooseLibrary={() => openLibraryPicker("reference_answers", "taskAnswers")}
                    onRemove={removeMaterial}
                    onRetry={retryMaterial}
                  />
                )}
                {form.hasTheory && (
                  <ExamMaterialUploadPanel
                    icon={<LibraryBig size={20} aria-hidden="true" />}
                    title="Учебные материалы"
                    description="Источники для просмотра, поиска и ручной привязки"
                    mode="files"
                    onModeChange={() => undefined}
                    materials={materialsFor("study_source")}
                    multiple
                    text=""
                    onTextChange={() => undefined}
                    onFiles={(files) => addFiles("study_source", files)}
                    onChooseLibrary={() => openLibraryPicker("study_source")}
                    onRemove={removeMaterial}
                    onRetry={retryMaterial}
                  />
                )}
                {(counts.tickets > 0 || counts.questions > 0 || counts.tasks > 0 || warnings.length > 0) && (
                  <Card className="wizard-import-result" aria-live="polite">
                    <h2>Предварительный разбор</h2>
                    {formatDetectedCounts(counts) && <p>{formatDetectedCounts(counts)}</p>}
                    {warnings.map((warning) => <p className="inline-warning" key={warning}>{warning}</p>)}
                  </Card>
                )}
              </>
            ) : (
              <>
                {form.format !== "unknown" && (
                  <ExamMaterialUploadPanel
                    icon={form.format === "tickets" ? <TicketCheck size={20} aria-hidden="true" /> : <ListChecks size={20} aria-hidden="true" />}
                    title={form.format === "tickets" ? "Билеты" : "Вопросы и задачи"}
                    description="Главная структура экзамена"
                    allowText
                    mode={form.primaryMode}
                    onModeChange={(mode) => void changeInputMode("primary", mode)}
                    materials={materialsFor("exam_structure")}
                    text={form.rawText}
                    onTextChange={(rawText) => setForm((current) => ({ ...current, rawText }))}
                    onFiles={(files) => addFiles("exam_structure", files)}
                    onChooseLibrary={() => openLibraryPicker("exam_structure")}
                    onRemove={removeMaterial}
                    onRetry={retryMaterial}
                  />
                )}
                {(counts.tickets > 0 || counts.questions > 0 || counts.tasks > 0 || warnings.length > 0) && (
                  <Card className="wizard-import-result" aria-live="polite">
                    <h2>Предварительный разбор</h2>
                    {formatDetectedCounts(counts) && <p>{formatDetectedCounts(counts)}</p>}
                    {warnings.map((warning) => <p className="inline-warning" key={warning}>{warning}</p>)}
                  </Card>
                )}
                {form.hasAnswers && (
                  <ExamMaterialUploadPanel
                    icon={<FileCheck2 size={20} aria-hidden="true" />}
                    title="Готовые ответы"
                    description="На все формулировки или только на часть"
                    allowText
                    mode={form.answersMode}
                    onModeChange={(mode) => void changeInputMode("answers", mode)}
                    materials={materialsFor("reference_answers")}
                    text={form.answersText}
                    onTextChange={(answersText) => setForm((current) => ({ ...current, answersText }))}
                    onFiles={(files) => addFiles("reference_answers", files)}
                    onChooseLibrary={() => openLibraryPicker("reference_answers")}
                    onRemove={removeMaterial}
                    onRetry={retryMaterial}
                  />
                )}
                {(form.format === "unknown" || form.hasTheory) && (
                  <ExamMaterialUploadPanel
                    icon={<LibraryBig size={20} aria-hidden="true" />}
                    title="Учебные материалы"
                    description="Источники для просмотра, поиска и ручной привязки"
                    mode="files"
                    onModeChange={() => undefined}
                    materials={materialsFor("study_source")}
                    multiple
                    text=""
                    onTextChange={() => undefined}
                    onFiles={(files) => addFiles("study_source", files)}
                    onChooseLibrary={() => openLibraryPicker("study_source")}
                    onRemove={removeMaterial}
                    onRetry={retryMaterial}
                  />
                )}
              </>
            )}
          </div>

          <div className="wizard-actions">
            <Button variant="ghost" onClick={() => changeStep(2)}>Назад</Button>
            {trackFor(form.format) !== "combined" && form.format !== "unknown" && !form.hasAnswers && !form.hasTheory && <Button variant="secondary" disabled={busy} onClick={() => void go(4)}>
              Добавить вопросы позже
            </Button>}
            <Button disabled={busy || projectMaterials.loading} onClick={() => void continueFromUpload()}>
              <Upload size={15} aria-hidden="true" />Сохранить и продолжить
            </Button>
          </div>
        </section>
      )}

      {step === 4 && (
        <section className="wizard-step">
          <PageHead
            eyebrow="Паспорт цели"
            title="Настроим подготовку под вас"
          />
          <p>Эти ответы зададут глубину программы и реальный темп. Их можно будет изменить после создания проекта.</p>
          <div className="wizard-passport-grid">
            <Card className="wizard-form-card">
              <div className="wizard-form-card-head">
                <span><CalendarDays size={19} aria-hidden="true" /></span>
                <div><h2>Об экзамене</h2><p>Что именно предстоит и когда</p></div>
              </div>
              <div className="wizard-form-fields">
                <Field label="Название предмета" required>
                  <input value={form.subject} onChange={(event) => setForm((current) => ({ ...current, subject: event.target.value }))} placeholder="Например, Базы данных" />
                </Field>
                <div className="wizard-exam-meta-grid">
                  <Field label="Дата экзамена" hint={examCountdown ?? "Если уже известна"}>
                    <input type="date" value={form.deadline} onChange={(event) => setForm((current) => ({ ...current, deadline: event.target.value }))} />
                  </Field>
                  <Field label="Время экзамена" hint="Если уже известно">
                    <input type="time" value={form.examTime} onChange={(event) => setForm((current) => ({ ...current, examTime: event.target.value }))} />
                  </Field>
                  <Field label={form.format === "tickets" ? "Ожидается билетов" : form.format === "unknown" ? "Ожидается разделов" : "Кол-во вопросов"} hint={`Предварительно найдено: ${studyCount}`}>
                    <input min="1" type="number" value={form.expectedCount} onChange={(event) => setForm((current) => ({ ...current, expectedCount: event.target.value }))} />
                  </Field>
                </div>
                <Field label="Что особенно важно" hint="Необязательно: напишите, на что сделать упор или что можно пройти обзорно.">
                  <textarea rows={3} value={form.important} onChange={(event) => setForm((current) => ({ ...current, important: event.target.value }))} placeholder="Например: больше практики по SQL, обзорно пройти историю СУБД" />
                </Field>
                <Field label="Требования преподавателя" hint="Необязательно: строгость, любимые темы или типичные требования.">
                  <textarea rows={3} value={form.instructorRequirements} onChange={(event) => setForm((current) => ({ ...current, instructorRequirements: event.target.value }))} placeholder="Например: просит точные определения, любит уточняющие вопросы…" />
                </Field>
                <Field label="Как проходит экзамен" hint="Необязательно: что пишете, что отвечаете устно и как преподаватель проверяет ответ.">
                  <textarea rows={4} value={form.examProcedure} onChange={(event) => setForm((current) => ({ ...current, examProcedure: event.target.value }))} placeholder="Например: пишем ответы на билеты, затем преподаватель задаёт 1–2 дополнительных вопроса устно" />
                </Field>
              </div>
            </Card>

            <Card className="wizard-form-card">
              <div className="wizard-form-card-head">
                <span><Brain size={19} aria-hidden="true" /></span>
                <div><h2>О подготовке</h2><p>Откуда начинаем и куда хотим прийти</p></div>
              </div>
              <div className="wizard-form-fields">
                <div className="wizard-control-group">
                  <b>Стартовый уровень</b>
                  <RadioCards label="Стартовый уровень" value={form.startingLevel} options={STARTING_OPTIONS} onChange={(startingLevel) => setForm((current) => ({ ...current, startingLevel }))} className="wizard-starting-levels" />
                </div>
                <Field label="Что вы уже знаете" hint="Можно писать свободно: темы, навыки и пробелы.">
                  <textarea rows={5} value={form.currentKnowledge} onChange={(event) => setForm((current) => ({ ...current, currentKnowledge: event.target.value }))} placeholder="Например: помню основы SQL, но почти не знаю индексы и транзакции…" />
                </Field>
                <div className="wizard-control-group">
                  <b>Желаемый результат</b>
                  <SegmentedTabs className="wizard-outcome-tabs" label="Желаемый результат" value={form.targetOutcome} tabs={OUTCOME_TABS} onChange={(targetOutcome) => setForm((current) => ({ ...current, targetOutcome }))} />
                  <small>Чем выше уровень, тем больше практики и проверок понимания войдёт в программу.</small>
                </div>
                <div className="wizard-control-group">
                  <b>Формат подготовки</b>
                  <SegmentedTabs label="Формат подготовки" value={form.studyFormat} tabs={STUDY_TABS} onChange={(studyFormat) => setForm((current) => ({ ...current, studyFormat }))} />
                </div>
                <div className="wizard-control-group">
                  <b>Сколько времени вы реально готовы уделять в день</b>
                  <small>{dailyLoad.hint}</small>
                  <div className="wizard-minutes">
                    {dailyLoad.options.map((value) => (
                      <button type="button" key={value} className={positive(form.minutesPerDay) === value ? "is-selected" : ""} onClick={() => changeMinutes(String(value))}>
                        {formatStudyMinutes(value)}
                      </button>
                    ))}
                    <label>
                      <span className="wizard-visually-hidden">Своё время в минутах</span>
                      <input min="30" max="720" type="number" value={form.minutesPerDay} onChange={(event) => changeMinutes(event.target.value)} />
                      <small>мин</small>
                    </label>
                  </div>
                  <Tooltip label={estimateDisabledReason ?? "Внешняя модель учтёт срок, объём и выбранную глубину подготовки"} side="bottom">
                    <span
                      className="wizard-ai-estimate-trigger"
                      tabIndex={estimateDisabledReason ? 0 : -1}
                      aria-label={estimateDisabledReason ?? undefined}
                    >
                      <Button
                        variant="secondary"
                        disabled={estimatePending || estimateDisabledReason !== null}
                        onClick={() => void suggestPreparationTime()}
                      >
                        <Sparkles size={15} aria-hidden="true" />
                        {estimatePending ? "Оцениваем…" : "Предложить время подготовки"}
                      </Button>
                    </span>
                  </Tooltip>
                  {preparationSuggestion && (
                    <div className="wizard-ai-suggestion" aria-live="polite">
                      <b>{preparationSuggestion.minutesPerDay} минут в день</b>
                      <span>{preparationSuggestion.rationale}</span>
                      <small>
                        {preparationSuggestion.studyDays} {plural(preparationSuggestion.studyDays, "учебный день", "учебных дня", "учебных дней")}
                        {` · по ${preparationSuggestion.itemsPerDay} ${plural(preparationSuggestion.itemsPerDay, "элементу", "элемента", "элементов")} в день`}
                        {preparationSuggestion.reviewDayReserved ? " · последний день оставлен на отдых и повторение" : " · отдельный резервный день не помещается"}
                        {preparationSuggestion.cached ? " · из кэша" : ""}
                      </small>
                    </div>
                  )}
                  {estimateError !== null && (isAiApiError(estimateError)
                    ? <AiFailureNotice error={estimateError} manualAlternative="Можно оставить локальную оценку или указать время вручную." />
                    : <p className="inline-error" role="alert">{estimateError instanceof Error ? estimateError.message : "Не удалось получить оценку"}</p>)}
                  {preparationForecast && <small>При такой нагрузке <b>{preparationForecast.title}</b>: {preparationForecast.text}</small>}
                </div>
              </div>
            </Card>
          </div>
          <div className="wizard-actions">
            <Button variant="ghost" onClick={() => changeStep(3)}>Назад</Button>
            <Button disabled={busy || !form.subject.trim()} onClick={() => void go(5)}>Продолжить</Button>
          </div>
        </section>
      )}

      {step === 5 && (
        <section className="wizard-step">
          <PageHead eyebrow="Проверка" title="Всё готово к созданию" />
          <p>Проверьте формулировки и порядок вопросов. Если список выглядит не так, поправьте его прямо здесь до создания проекта.</p>
          <section className="wizard-review-summary">
            <div className="wizard-review-hero">
              <h2>
                <span>Вы готовитесь к экзамену по предмету</span>
                <strong>{form.subject || "Без названия"}</strong>
              </h2>
              <p className={`wizard-review-countdown${examCountdown ? "" : " is-muted"}`}>
                {examCountdown ?? "Дата экзамена пока не указана."}
              </p>
              <p className="wizard-review-lead">
                {OUTCOME_SUMMARIES[form.targetOutcome]} На подготовку — <b>{form.minutesPerDay || "—"} минут в день</b>.
              </p>
            </div>
            <dl className="wizard-review-facts">
              {formatExamMoment(form.deadline, form.examTime) && (
                <div>
                  <dt>Экзамен</dt>
                  <dd>{formatExamMoment(form.deadline, form.examTime)}</dd>
                </div>
              )}
              <div>
                <dt>Текущий уровень</dt>
                <dd>{form.currentKnowledge.trim() || STARTING_SUMMARIES[form.startingLevel]}</dd>
              </div>
              {form.important.trim() && (
                <div>
                  <dt>Что особенно важно</dt>
                  <dd>{form.important}</dd>
                </div>
              )}
              {form.instructorRequirements.trim() && (
                <div>
                  <dt>Требования преподавателя</dt>
                  <dd>{form.instructorRequirements}</dd>
                </div>
              )}
              {form.examProcedure.trim() && (
                <div>
                  <dt>Как проходит экзамен</dt>
                  <dd>{form.examProcedure}</dd>
                </div>
              )}
            </dl>
            {preparationForecast && (
              <p className="wizard-review-forecast">
                При такой нагрузке <b>{preparationForecast.title}</b>: {preparationForecast.text}
              </p>
            )}
          </section>

          <Card className="wizard-review-card wizard-structure-card">
            <div className="wizard-review-block-head">
              <div>
                <h3>{form.format === "tickets" ? "Билеты" : form.format === "unknown" ? "Официальный список" : "Вопросы и задачи"}</h3>
                {formatDetectedCounts(counts) && <p>{formatDetectedCounts(counts)}</p>}
              </div>
            </div>
            <ReviewProgramTree
              nodes={(controller.detail?.program.nodes ?? []).filter((node) => node.is_in_current_program && !node.is_archived)}
              onRename={(node, title) => {
                if (title === node.title) return;
                void controller.enqueueProgramCommand((current) => updateProgramNode(current.project.id, node.id, {
                  expected_program_revision: current.program.revision,
                  title,
                }));
              }}
            />
            {studyCount === 0 && (
              <Card className="wizard-import-result">
                <h2>Вопросы пока не добавлены</h2>
                <p>Проект можно создать сейчас, а официальный список загрузить позже в разделе «Вопросы экзамена».</p>
              </Card>
            )}
            {countMismatch && (
              <div className="wizard-warning-card">
                <span>!</span>
                <div><b>Количество отличается</b><p>Вы указали {expectedCount}, а предварительно найдено {studyCount}. Создать проект всё равно можно.</p></div>
                {repairNodes.length > 0 && <button type="button" onClick={() => setReviewRepairOpen(true)}><Sparkles size={13} aria-hidden="true" /> Исправить формулировки</button>}
              </div>
            )}
          </Card>

          {controller.detail && (
            <AiImportRepairDialog
              open={reviewRepairOpen}
              projectId={controller.detail.project.id}
              nodes={repairNodes}
              onOpenChange={setReviewRepairOpen}
              onApplied={(result) => { void controller.enqueueProgramCommand(async () => result); }}
            />
          )}

          <Card className="wizard-review-card wizard-sources-card">
            <h3>Источники</h3>
            <div className="wizard-source-list">
              {projectMaterials.materials.length > 0
                ? projectMaterials.materials.map((material) => (
                  <ReviewSource key={material.id} value={material.display_name} />
                ))
                : <ReviewSource value="Дополнительные источники не добавлены" />}
            </div>
          </Card>

          <section className="wizard-after-create">
            <h3>Что произойдёт после создания</h3>
            {form.format === "unknown" ? (
              <p>Проект создастся с пустой Программой, а учебные источники начнут обрабатываться в фоне. Когда появится официальный список, импортируйте его в разделе «Вопросы экзамена».</p>
            ) : (
              <>
                <p>Список вопросов уже сохранён в Программе.</p>
                {form.hasAnswers && <p>Файлы ответов автоматически пойдут в OCR, разбор и автопривязку. После создания откройте «Материалы → Ответы», проверьте распознанный текст и автоматические привязки, вручную исправив только неоднозначные.</p>}
                {!form.hasAnswers && <p>Готовые ответы можно добавить позже в разделе «Материалы → Ответы» и привязать к вопросам.</p>}
                {form.hasTheory && <p>Учебные источники начнут обрабатываться в фоне.</p>}
              </>
            )}
          </section>
          <div className="wizard-actions">
            <Button variant="ghost" onClick={() => changeStep(4)}>Назад</Button>
            <Button disabled={busy} onClick={() => void activate()}>Создать проект</Button>
          </div>
        </section>
      )}
      {controller.detail && libraryPurpose && (
        <LibraryMaterialPickerDialog
          open
          projectId={controller.detail.project.id}
          title={librarySlot
            ? `Выбрать «${SLOT_LABEL[librarySlot]}» из Библиотеки`
            : libraryPurpose === "exam_structure"
              ? "Выбрать список вопросов из Библиотеки"
              : libraryPurpose === "reference_answers"
                ? "Выбрать эталонные ответы из Библиотеки"
                : "Выбрать учебные материалы из Библиотеки"}
          purpose={libraryPurpose}
          examSlot={librarySlot ? SLOT_VALUE[librarySlot] : undefined}
          multiple={libraryPurpose === "study_source"}
          existingStudySourceCount={materialsFor("study_source").length}
          studyRoleMode="first-main"
          onOpenChange={(open) => { if (!open) { setLibraryPurpose(null); setLibrarySlot(null); } }}
          onAttached={attachedLibraryMaterials}
          onCreateNew={() => { setLibraryPurpose(null); setLibrarySlot(null); }}
        />
      )}
      <Dialog
        open={estimateConfirmation !== null}
        onOpenChange={(open) => { if (!open) setEstimateConfirmation(null); }}
        title="Подтвердить оценку времени"
        description="Модель получит только параметры экзамена и подготовки — без ваших свободных текстов."
        footer={estimateConfirmation && (
          <>
            <Button variant="ghost" disabled={estimatePending} onClick={() => setEstimateConfirmation(null)}>Отменить</Button>
            <Button
              disabled={estimatePending}
              onClick={() => void applyPreparationEstimate(estimateConfirmation.preview, estimateConfirmation.input, true)}
            >
              {estimatePending ? "Оцениваем…" : "Подтвердить и предложить"}
            </Button>
          </>
        )}
      >
        {estimateConfirmation && (
          <div className="wizard-ai-confirmation">
            <p>
              Модель: <b>{estimateConfirmation.preview.preflight.model_id}</b>. Планируется один вызов,
              до {estimateConfirmation.preview.preflight.estimated_input_tokens + estimateConfirmation.preview.preflight.estimated_output_tokens} токенов.
            </p>
            {estimateConfirmation.preview.preflight.estimated_cost_usd !== null ? (
              <CostEstimate
                calls={1}
                cost={Number(estimateConfirmation.preview.preflight.estimated_cost_usd)}
                minutes={1}
                pricesFrom={estimateConfirmation.preview.preflight.usd_rub_rate_date ?? "текущей настройки"}
                units={`${estimateConfirmation.preview.study_days} учебных дней`}
              />
            ) : <p className="wizard-quiet-note">Провайдер не сообщил цену модели, поэтому точную стоимость заранее показать нельзя.</p>}
          </div>
        )}
      </Dialog>
    </div>
  );
}

function SelectableMaterial({
  wide = false,
  selected,
  locked = false,
  disabledReason,
  onChange,
  icon,
  title,
  description,
  action,
}: {
  wide?: boolean;
  selected: boolean;
  locked?: boolean;
  /** Карточка недоступна, пока не выполнено условие (например, не выбран список
   * вопросов) — текст объясняет, что нужно сделать сначала, вместо чекбокса. */
  disabledReason?: string;
  onChange?: (value: boolean) => void;
  icon: ReactNode;
  title: string;
  description: string;
  action: string;
}) {
  const unavailable = Boolean(disabledReason) && !selected;
  return (
    <div className={`wizard-material-card${selected ? " is-selected" : ""}${wide ? " is-wide" : ""}${unavailable ? " is-unavailable" : ""}`}>
      <button
        type="button"
        disabled={locked || unavailable}
        aria-pressed={selected}
        onClick={() => onChange?.(!selected)}
      >
        <span className="wizard-material-icon">{icon}</span>
        <span>
          <b>{title}</b>
          <small>{unavailable ? disabledReason : description}</small>
        </span>
      </button>
      {!unavailable && (
        <Checkbox
          checked={selected}
          disabled={locked}
          onCheckedChange={(value) => onChange?.(value)}
          label={action}
        />
      )}
    </div>
  );
}

function ReviewProgramTree({
  nodes,
  onRename,
}: {
  nodes: ProgramNodeRead[];
  onRename: (node: ProgramNodeRead, title: string) => void;
}) {
  const ids = new Set(nodes.map((node) => node.id));
  const childrenByParent = new Map<string | null, ProgramNodeRead[]>();
  for (const node of nodes) {
    const parentId = node.parent_id && ids.has(node.parent_id) ? node.parent_id : null;
    const siblings = childrenByParent.get(parentId) ?? [];
    siblings.push(node);
    childrenByParent.set(parentId, siblings);
  }
  for (const siblings of childrenByParent.values()) siblings.sort((left, right) => left.sort_order - right.sort_order);

  function renderNodes(parentId: string | null) {
    return (childrenByParent.get(parentId) ?? []).map((node, index) => {
      const children = childrenByParent.get(node.id) ?? [];
      return (
        <li key={node.id} className={node.exam_kind === "ticket" ? "is-ticket" : ""}>
          <div className="wizard-review-row">
            <span className="wizard-review-number">{index + 1}</span>
            {node.exam_kind && <span className="wizard-review-kind">{node.exam_kind === "task" ? "задача" : node.exam_kind === "question" ? "вопрос" : "билет"}</span>}
            <EditableProgramNodeText node={node} onSave={onRename} />
          </div>
          {children.length > 0 && <ol>{renderNodes(node.id)}</ol>}
        </li>
      );
    });
  }

  return <ol className="wizard-review-list">{renderNodes(null)}</ol>;
}

function EditableProgramNodeText({ node, onSave }: { node: ProgramNodeRead; onSave: (node: ProgramNodeRead, title: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(node.title);

  function save() {
    const title = draft.trim();
    if (title) onSave(node, title);
    else setDraft(node.title);
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
              setDraft(node.title);
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
      <span>{node.title}</span>
      <IconButton label="Редактировать формулировку" onClick={() => { setDraft(node.title); setEditing(true); }}>
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
