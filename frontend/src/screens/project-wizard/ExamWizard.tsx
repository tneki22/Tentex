import { type ReactNode, useEffect, useRef, useState } from "react";
import { Brain, CalendarDays, Check, FileCheck2, FileText, Files, LibraryBig, ListChecks, Pencil, Sparkles, TicketCheck, Upload } from "lucide-react";
import {
  controlMaterialProcessing,
  createTextMaterial,
  detachMaterial,
  importExamDraftProgramFromMaterial,
  importMaterialReferenceAnswers,
  previewExamProgram,
  startMaterialProcessing,
  uploadMaterial,
  type LibraryMaterialRead,
  type MaterialPurpose,
  type MaterialRead,
} from "../../api/materials";
import {
  updateProgramNode,
  type ExamFormat,
  type GoalPassportWrite,
  type ModuleKey,
  type ProgramNodeRead,
  type ProjectDetail,
  type StartingLevel,
  type StudyFormat,
  type TargetOutcome,
} from "../../api/projects";
import type { WizardDraftController } from "../../hooks/useWizardDraft";
import { useProjectMaterials } from "../../hooks/useProjectMaterials";
import { Button, Card, Checkbox, Field, IconButton, LoadingState, PageHead, RadioCards, SegmentedTabs } from "../../components/ui";
import type { RadioCardOption } from "../../components/ui";
import { LibraryMaterialPickerDialog } from "../../components/domain";
import { AiImportRepairDialog } from "../AiImportRepairDialog";
import {
  ExamMaterialUploadPanel,
  type ExamMaterialInputMode,
} from "./ExamMaterialUploadPanel";

interface ExamForm {
  format: ExamFormat | null;
  rawText: string;
  answersText: string;
  hasAnswers: boolean;
  hasTheory: boolean;
  primaryMode: ExamMaterialInputMode;
  answersMode: ExamMaterialInputMode;
  subject: string;
  deadline: string;
  expectedCount: string;
  startingLevel: StartingLevel;
  targetOutcome: TargetOutcome;
  studyFormat: StudyFormat;
  currentKnowledge: string;
  important: string;
  instructorRequirements: string;
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
  subject: "",
  deadline: "",
  expectedCount: "",
  startingLevel: "familiar",
  targetOutcome: "application",
  studyFormat: "theory_and_practice",
  currentKnowledge: "",
  important: "",
  instructorRequirements: "",
  minutesPerDay: "45",
  daysPerWeek: "4",
  sessionMinutes: "45",
};

const FORMAT_OPTIONS: Array<RadioCardOption<ExamFormat>> = [
  { value: "questions", title: "Отдельные вопросы", description: "Общий список теоретических вопросов без заранее собранных билетов.", icon: <ListChecks size={18} aria-hidden="true" /> },
  { value: "questions_tasks", title: "Вопросы и задачи", description: "Теория и практические задания перечислены отдельно, без группировки.", icon: <FileCheck2 size={18} aria-hidden="true" /> },
  { value: "tickets", title: "Готовые билеты", description: "Состав каждого билета известен: вопросы, задачи или их комбинация.", icon: <TicketCheck size={18} aria-hidden="true" /> },
  { value: "unknown", title: "Точного списка пока нет", description: "Сохраним источники сейчас, а официальный список вы добавите позже.", icon: <LibraryBig size={18} aria-hidden="true" /> },
];

const STARTING_OPTIONS: Array<RadioCardOption<StartingLevel>> = [
  { value: "beginner", title: "Начинаю с нуля", description: "Тема почти незнакома" },
  { value: "familiar", title: "Что-то знаю", description: "Есть отдельные знакомые темы" },
  { value: "refreshing", title: "Повторяю забытое", description: "Раньше изучал, нужно восстановить" },
];

const OUTCOME_TABS: Array<{ value: TargetOutcome; label: string }> = [
  { value: "awareness", label: "Ориентироваться" },
  { value: "understanding", label: "Понимать" },
  { value: "application", label: "Уверенно отвечать" },
  { value: "mastery", label: "Владеть свободно" },
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

function getExamCountdown(deadlineValue: string) {
  if (!deadlineValue) return null;
  const totalHours = Math.ceil((new Date(`${deadlineValue}T00:00:00`).getTime() - Date.now()) / 3_600_000);
  if (totalHours <= 0) return "Экзамен уже сегодня.";
  const days = Math.floor(totalHours / 24);
  const hours = totalHours % 24;
  return `До экзамена ${days > 0 ? `${days} ${plural(days, "день", "дня", "дней")} ` : ""}${hours} ${plural(hours, "час", "часа", "часов")}.`;
}

function getPreparationForecast(form: ExamForm, itemCount: number) {
  const deadline = form.deadline ? new Date(`${form.deadline}T00:00:00`) : null;
  const daysLeft = deadline ? Math.max(1, Math.ceil((deadline.getTime() - Date.now()) / 86_400_000)) : 14;
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
    return "Создадим пустую экзаменационную программу и сохраним источники. Официальный список можно добавить позже.";
  }
  if (form.hasAnswers && form.hasTheory) {
    return "Система отдельно разберёт структуру, эталоны и учебные источники и разложит их по назначению.";
  }
  if (form.hasAnswers) {
    return "Лучший маршрут для тренировки: вопросы станут программой, а готовые ответы — эталонами.";
  }
  if (form.hasTheory) {
    return "Программа будет готова сразу. Источники сохранятся для просмотра, поиска и ручной привязки.";
  }
  return "Списка достаточно для создания программы. Ответы и источники можно добавить позже.";
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
  const [counts, setCounts] = useState({ tickets: 0, questions: 0, tasks: 0 });
  const [actionError, setActionError] = useState("");
  const [reviewRepairOpen, setReviewRepairOpen] = useState(false);
  const [libraryPurpose, setLibraryPurpose] = useState<MaterialPurpose | null>(null);
  const initializedKey = useRef<string | null>(null);
  const projectMaterials = useProjectMaterials(controller.detail?.project.id);

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
    const restoredWarnings = Array.isArray(state.warnings)
      ? state.warnings.filter((warning): warning is string => typeof warning === "string")
      : [];
    setStep(detail.draft.current_step);
    setWarnings(restoredWarnings);
    setCounts({
      tickets: detail.program.nodes.filter((node) => node.exam_kind === "ticket").length,
      questions: detail.program.nodes.filter((node) => node.exam_kind === "question").length,
      tasks: detail.program.nodes.filter((node) => node.exam_kind === "task").length,
    });
    setForm({
      format: restoredFormat,
      rawText: typeof state.raw_text === "string" ? state.raw_text : "",
      answersText: typeof state.answer_text === "string" ? state.answer_text : "",
      hasAnswers: state.has_answers === true,
      hasTheory: restoredFormat === "unknown" || state.has_theory === true,
      primaryMode: inputModes.primary === "text" ? "text" : "files",
      answersMode: inputModes.answers === "text" ? "text" : "files",
      subject: goal?.subject ?? "",
      deadline: detail.project.deadline ?? "",
      expectedCount: goal?.expected_item_count ? String(goal.expected_item_count) : "",
      startingLevel: goal?.starting_level ?? "familiar",
      targetOutcome: goal?.target_outcome ?? "application",
      studyFormat: goal?.study_format ?? "theory_and_practice",
      currentKnowledge: goal?.current_knowledge ?? "",
      important: goal?.important ?? "",
      instructorRequirements: goal?.instructor_requirements ?? "",
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
        warnings: nextWarnings,
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
  }, [form, step, warnings]);

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

  async function continueFromUpload() {
    if (!form.format) return;
    setActionError("");
    try {
      await controller.queueSave(command(3));
      const primaryMaterials = materialsFor("exam_structure");
      const answerMaterials = materialsFor("reference_answers");
      const theoryMaterials = materialsFor("study_source");

      if (form.format !== "unknown") {
        if (form.primaryMode === "text") {
          if (!form.rawText.trim()) throw new Error("Вставьте список вопросов или выберите файл");
          const result = await controller.importExam(form.rawText, form.format);
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
          setCounts(preview.counts);
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

      if ((form.format === "unknown" || form.hasTheory) && theoryMaterials.length === 0) {
        throw new Error("Добавьте хотя бы один учебный материал");
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
  const studyCount = (controller.detail?.program.nodes ?? []).filter((node) => node.node_type !== "section").length;
  const repairNodes = (controller.detail?.program.nodes ?? [])
    .filter((node) => node.is_in_current_program && !node.is_archived && node.node_type !== "section");
  const expectedCount = positive(form.expectedCount);
  const countMismatch = expectedCount !== null && expectedCount !== studyCount;
  const dailyLoad = getDailyLoad(form.deadline);
  const examCountdown = getExamCountdown(form.deadline);
  const preparationForecast = getPreparationForecast(form, expectedCount ?? studyCount);

  return (
    <div className="wizard-flow">
      {(actionError || controller.error || projectMaterials.error) && <p className="inline-error" role="alert">{actionError || controller.error?.message || projectMaterials.error}</p>}
      {controller.conflict && <Card><h2>Черновик изменился в другой вкладке</h2><p>Загрузите серверную версию, чтобы не затереть изменения.</p><Button onClick={() => void controller.reload()}>Загрузить серверную версию</Button></Card>}

      {step === 1 && <section className="wizard-step"><PageHead eyebrow="Сначала — структура" title="Как устроен ваш экзамен?" /><p>Это определит, как Tentex сохранит формулировки и соберёт из них программу.</p><RadioCards label="Формат экзамена" value={form.format} options={FORMAT_OPTIONS} onChange={(format) => setForm((current) => ({ ...current, format, hasTheory: format === "unknown" || current.hasTheory }))} className="wizard-format-options" />{form.format === "unknown" && <div className="wizard-context-note"><LibraryBig size={18} aria-hidden="true" /><span><b>Официальный список добавите позже</b>Сейчас сохраним учебные источники. Без прохода 1 предварительную программу по ним не выдумываем.</span></div>}<div className="wizard-actions"><Button disabled={busy || !form.format} onClick={() => void go(2)}>Продолжить</Button></div></section>}

      {step === 2 && (
        <section className="wizard-step">
          <PageHead eyebrow="Материалы" title="Что у вас уже есть?" />
          <p>{form.format === "unknown"
            ? "Раз точного списка нет, начнём с учебных материалов. Официальные вопросы можно будет добавить позже."
            : "Список вопросов или билетов уже считаем основой. Отметьте, есть ли что-то ещё."}</p>
          <div className={`wizard-material-grid${form.format === "unknown" ? " has-one" : ""}`}>
            {form.format !== "unknown" && (
              <SelectableMaterial
                selected
                locked
                icon={<ListChecks size={22} aria-hidden="true" />}
                title={form.format === "tickets" ? "Билеты" : "Список вопросов"}
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
              selected={form.format === "unknown" || form.hasTheory}
              locked={form.format === "unknown"}
              onChange={(selected) => void setOptionalMaterial("theory", selected)}
              icon={<Files size={22} aria-hidden="true" />}
              title="Учебные материалы"
              description="Учебники, методички, лекции или конспекты — один или несколько файлов."
              action="Добавить материалы"
            />
          </div>
          <div className="wizard-context-note">
            <Brain size={18} aria-hidden="true" />
            <span><b>Мнение системы</b>{getMaterialOpinion(form)}</span>
          </div>
          {form.format === "unknown" && <p className="wizard-quiet-note">Если ваша цель — изучать конкретную методичку, удобнее соседний маршрут «Изучение по учебнику».</p>}
          <div className="wizard-actions"><Button variant="ghost" onClick={() => changeStep(1)}>Назад</Button><Button onClick={() => void go(3)}>Продолжить</Button></div>
        </section>
      )}

      {step === 3 && (
        <section className="wizard-step">
          <PageHead
            eyebrow="Загрузка"
            title="Добавьте то, что у вас есть"
          />
          <p>Формат и нумерация могут быть любыми. Быстрый разбор списка выполняется сейчас; остальные файлы начнут обрабатываться после создания проекта.</p>
          <div className="wizard-upload-stack">
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
                onChooseLibrary={() => setLibraryPurpose("exam_structure")}
                onRemove={removeMaterial}
                onRetry={retryMaterial}
              />
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
                onChooseLibrary={() => setLibraryPurpose("reference_answers")}
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
                onChooseLibrary={() => setLibraryPurpose("study_source")}
                onRemove={removeMaterial}
                onRetry={retryMaterial}
              />
            )}
          </div>
          {(form.format === "unknown" || form.hasTheory) && <p className="wizard-quiet-note">Учебные материалы будут разобраны и доступны в Просмотрщике, поиске и ручных привязках. Автоматическую раскладку по темам пока не обещаем.</p>}

          {(counts.tickets > 0 || counts.questions > 0 || counts.tasks > 0 || warnings.length > 0) && (
            <Card className="wizard-import-result" aria-live="polite">
              <h2>Предварительный разбор</h2>
              <p>
                {counts.tickets > 0 && `${counts.tickets} ${plural(counts.tickets, "билет", "билета", "билетов")} · `}
                {counts.questions} {plural(counts.questions, "вопрос", "вопроса", "вопросов")} · {counts.tasks} {plural(counts.tasks, "задача", "задачи", "задач")}
              </p>
              {warnings.map((warning) => <p className="inline-warning" key={warning}>{warning}</p>)}
            </Card>
          )}

          <div className="wizard-actions">
            <Button variant="ghost" onClick={() => changeStep(2)}>Назад</Button>
            {form.format !== "unknown" && !form.hasAnswers && !form.hasTheory && <Button variant="secondary" disabled={busy} onClick={() => void go(4)}>
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
                <div className="wizard-field-pair">
                  <Field label="Дата экзамена" hint={examCountdown ?? "Если уже известна"}>
                    <input type="date" value={form.deadline} onChange={(event) => setForm((current) => ({ ...current, deadline: event.target.value }))} />
                  </Field>
                  <Field label={form.format === "tickets" ? "Ожидается билетов" : form.format === "unknown" ? "Ожидается разделов" : "Ожидается элементов"} hint={`Предварительно найдено: ${studyCount}`}>
                    <input min="1" type="number" value={form.expectedCount} onChange={(event) => setForm((current) => ({ ...current, expectedCount: event.target.value }))} />
                  </Field>
                </div>
                <Field label="Особый фокус" hint="Необязательно: напишите, что особенно важно или можно пропустить.">
                  <textarea rows={3} value={form.important} onChange={(event) => setForm((current) => ({ ...current, important: event.target.value }))} placeholder="Например: больше практики по SQL, обзорно пройти историю СУБД" />
                </Field>
                <Field label="О преподавателе" hint="Необязательно: строгость, любимые темы или типичные требования.">
                  <textarea rows={4} value={form.instructorRequirements} onChange={(event) => setForm((current) => ({ ...current, instructorRequirements: event.target.value }))} placeholder="Например: просит точные определения, любит уточняющие вопросы…" />
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
                  <SegmentedTabs label="Желаемый результат" value={form.targetOutcome} tabs={OUTCOME_TABS} onChange={(targetOutcome) => setForm((current) => ({ ...current, targetOutcome }))} />
                  <small>Чем выше уровень, тем больше практики и проверок понимания войдёт в программу.</small>
                </div>
                <div className="wizard-control-group">
                  <b>Формат подготовки</b>
                  <SegmentedTabs label="Формат подготовки" value={form.studyFormat} tabs={STUDY_TABS} onChange={(studyFormat) => setForm((current) => ({ ...current, studyFormat }))} />
                </div>
                <div className="wizard-control-group">
                  <b>Сколько времени в день уделять</b>
                  <small>{dailyLoad.hint}</small>
                  <div className="wizard-minutes">
                    {dailyLoad.options.map((value) => (
                      <button type="button" key={value} className={positive(form.minutesPerDay) === value ? "is-selected" : ""} onClick={() => setForm((current) => ({ ...current, minutesPerDay: String(value) }))}>
                        {formatStudyMinutes(value)}
                      </button>
                    ))}
                    <label>
                      <span className="wizard-visually-hidden">Своё время в минутах</span>
                      <input min="30" max="720" type="number" value={form.minutesPerDay} onChange={(event) => setForm((current) => ({ ...current, minutesPerDay: event.target.value }))} />
                      <small>мин</small>
                    </label>
                  </div>
                  <small>Системе кажется, что <b>{preparationForecast.title}</b>: {preparationForecast.text}</small>
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
          <p>Проверьте вопросы или билеты и заполненную информацию об экзамене, затем проект можно будет создать.</p>
          <section className="wizard-review-summary">
            <h2>
              <span>Вы готовитесь к экзамену по предмету:</span>
              <strong>{form.subject || "Без названия"}</strong>
            </h2>
            <p className={`wizard-review-countdown${examCountdown ? "" : " is-muted"}`}>
              {examCountdown ?? "Дата экзамена пока не указана."}
            </p>
            <div className="wizard-review-story">
              <p className="wizard-review-goal">{OUTCOME_SUMMARIES[form.targetOutcome]}</p>
              <p>На подготовку — <b>{form.minutesPerDay || "—"} минут в день</b>.</p>
              <p className="wizard-review-personal"><b>Текущий уровень:</b> {form.currentKnowledge.trim() || STARTING_SUMMARIES[form.startingLevel]}</p>
              {form.important.trim() && <p className="wizard-review-personal"><b>Особый фокус:</b> {form.important}</p>}
              {form.instructorRequirements.trim() && <p className="wizard-review-personal"><b>О преподавателе:</b> {form.instructorRequirements}</p>}
              <p className="wizard-review-personal">Системе кажется, что <b>{preparationForecast.title}</b>: {preparationForecast.text}</p>
            </div>
          </section>

          <Card className="wizard-review-card wizard-structure-card">
            <div className="wizard-review-block-head">
              <div>
                <h3>{form.format === "tickets" ? "Билеты" : form.format === "unknown" ? "Официальный список" : "Вопросы и задачи"}</h3>
                <p>{counts.tickets > 0 && `${counts.tickets} ${plural(counts.tickets, "билет", "билета", "билетов")} · `}{counts.questions} {plural(counts.questions, "вопрос", "вопроса", "вопросов")} · {counts.tasks} {plural(counts.tasks, "задача", "задачи", "задач")}</p>
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
                <button type="button" onClick={() => changeStep(4)}>Проверить</button>
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
            <p>{form.format === "unknown"
              ? "Создадим экзаменационный проект с пустой программой и запустим разбор учебных материалов."
              : "Структура экзамена уже сохранена. После создания запустим разбор ответов и учебных материалов."}</p>
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
          title={libraryPurpose === "exam_structure"
            ? "Выбрать список вопросов из Библиотеки"
            : libraryPurpose === "reference_answers"
              ? "Выбрать эталонные ответы из Библиотеки"
              : "Выбрать учебные материалы из Библиотеки"}
          purpose={libraryPurpose}
          multiple={libraryPurpose === "study_source"}
          existingStudySourceCount={materialsFor("study_source").length}
          studyRoleMode="first-main"
          onOpenChange={(open) => { if (!open) setLibraryPurpose(null); }}
          onAttached={attachedLibraryMaterials}
          onCreateNew={() => setLibraryPurpose(null)}
        />
      )}
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
  action,
}: {
  selected: boolean;
  locked?: boolean;
  onChange?: (value: boolean) => void;
  icon: ReactNode;
  title: string;
  description: string;
  action: string;
}) {
  return (
    <div className={`wizard-material-card ${selected ? "is-selected" : ""}`.trim()}>
      <button
        type="button"
        disabled={locked}
        aria-pressed={selected}
        onClick={() => onChange?.(!selected)}
      >
        <span className="wizard-material-icon">{icon}</span>
        <span>
          <b>{title}</b>
          <small>{description}</small>
        </span>
      </button>
      <Checkbox
        checked={selected}
        disabled={locked}
        onCheckedChange={(value) => onChange?.(value)}
        label={action}
      />
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
