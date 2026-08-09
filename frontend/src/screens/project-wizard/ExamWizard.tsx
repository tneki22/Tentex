import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { CalendarDays, Check, FileText, Pencil, Upload } from "lucide-react";
import {
  updateProgramNode,
  type ExamFormat,
  type GoalPassportWrite,
  type ModuleKey,
  type StartingLevel,
  type StudyFormat,
  type TargetOutcome,
} from "../../api/projects";
import type { WizardDraftController } from "../../hooks/useWizardDraft";
import { Button, Card, EmptyState, Field, LoadingState, PageHead, SegmentedTabs } from "../../components/ui";

interface ExamForm {
  format: Exclude<ExamFormat, "unknown">;
  rawText: string;
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
  format: "questions",
  rawText: "",
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

export function ExamWizard({ controller }: { controller: WizardDraftController }) {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<ExamForm>(EMPTY_FORM);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [counts, setCounts] = useState({ tickets: 0, questions: 0, tasks: 0 });
  const [actionError, setActionError] = useState("");
  const initializedId = useRef<string | null>(null);

  useEffect(() => {
    const detail = controller.detail;
    if (!detail || initializedId.current === detail.project.id) return;
    initializedId.current = detail.project.id;
    const state = detail.draft.state;
    const goal = detail.goal_passport;
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
      format: (state.exam_format as ExamForm["format"]) ?? goal?.exam_format ?? "questions",
      rawText: typeof state.raw_text === "string" ? state.raw_text : "",
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
  }, [controller.detail]);

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
      state: { raw_text: form.rawText, exam_format: form.format, input_mode: "text", warnings: nextWarnings },
    };
  }

  useEffect(() => {
    if (!controller.detail || initializedId.current !== controller.detail.project.id || controller.conflict) return;
    const timer = window.setTimeout(() => {
      void controller.queueSave(command(step)).catch(() => undefined);
    }, 400);
    return () => window.clearTimeout(timer);
  }, [form, step, warnings]);

  async function go(nextStep: number) {
    setActionError("");
    try {
      await controller.queueSave(command(nextStep));
      setStep(nextStep);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось сохранить шаг");
    }
  }

  async function importText() {
    if (!form.rawText.trim()) return;
    setActionError("");
    try {
      await controller.queueSave(command(2));
      const result = await controller.importExam(form.rawText, form.format);
      setWarnings(result.warnings);
      setCounts(result.counts);
      await controller.queueSave(command(3, result.warnings));
      setStep(3);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось импортировать список");
    }
  }

  async function activate() {
    setActionError("");
    try {
      await controller.queueSave(command(5));
      const project = await controller.activate();
      const first = project.program.nodes.find((node) => ["topic", "subpoint"].includes(node.node_type) && node.is_in_current_program && !node.is_archived);
      navigate(`/projects/${project.project.id}${first ? `?topic=${first.id}` : ""}`);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось создать проект");
    }
  }

  if (controller.status === "loading") return <LoadingState label="Загружаем экзаменационный черновик" />;

  const busy = controller.status === "saving";
  const nodes = controller.detail?.program.nodes ?? [];
  const studyCount = nodes.filter((node) => node.node_type !== "section").length;
  const expectedCount = positive(form.expectedCount);
  const countMismatch = expectedCount !== null && expectedCount !== studyCount;
  const calendarDays = form.deadline ? Math.max(0, Math.ceil((new Date(`${form.deadline}T00:00:00`).getTime() - Date.now()) / 86_400_000)) : null;

  return (
    <div className="wizard-flow">
      <PageHead eyebrow={`Экзамен · шаг ${step} из 5`} title={step === 1 ? "Как устроен экзамен?" : step === 2 ? "Вставьте список" : step === 3 ? "Настроим подготовку" : step === 4 ? "Проверьте программу" : "Всё готово к созданию"} />
      {(actionError || controller.error) && <p className="inline-error" role="alert">{actionError || controller.error?.message}</p>}
      {controller.conflict && <Card><h2>Черновик изменился в другой вкладке</h2><p>Загрузите серверную версию, чтобы не затереть изменения.</p><Button onClick={() => void controller.reload()}>Загрузить серверную версию</Button></Card>}

      {step === 1 && <section className="wizard-step"><SegmentedTabs label="Формат экзамена" value={form.format} onChange={(format) => setForm((current) => ({ ...current, format }))} tabs={[{ value: "questions", label: "Вопросы" }, { value: "questions_tasks", label: "Вопросы и задачи" }, { value: "tickets", label: "Билеты" }]} /><Card><h2>Точного списка пока нет</h2><p>Этот путь станет доступен после загрузки материалов на этапе 5.</p><Button disabled variant="secondary">Выбрать материалы · этап 5</Button></Card><Button disabled={busy} onClick={() => void go(2)}>Продолжить</Button></section>}

      {step === 2 && <section className="wizard-step"><EmptyState title="Сейчас доступен вставленный текст" icon={<FileText size={28} />}><p>Файлы вопросов появятся на этапе 5. Эталоны можно добавить после создания проекта.</p></EmptyState><Field label={form.format === "tickets" ? "Билеты" : form.format === "questions" ? "Вопросы" : "Вопросы и задачи"} required><textarea rows={14} value={form.rawText} onChange={(event) => setForm((current) => ({ ...current, rawText: event.target.value }))} placeholder={form.format === "tickets" ? "Билет 1\n1. Реляционная модель\n2. Задача: нормализовать отношение" : "1. Архитектура СУБД\n2. Реляционная модель данных"} /></Field><div className="wizard-actions"><Button variant="ghost" onClick={() => setStep(1)}>Назад</Button><Button disabled={busy || !form.rawText.trim()} onClick={() => void importText()}><Upload size={15} />Импортировать список</Button></div></section>}

      {step === 3 && <section className="wizard-step"><div className="wizard-form-grid"><Field label="Предмет" required><input value={form.subject} onChange={(event) => setForm((current) => ({ ...current, subject: event.target.value }))} /></Field><Field label="Дата экзамена"><input type="date" value={form.deadline} onChange={(event) => setForm((current) => ({ ...current, deadline: event.target.value }))} /></Field><Field label="Ожидаемое число элементов"><input type="number" min="1" value={form.expectedCount} onChange={(event) => setForm((current) => ({ ...current, expectedCount: event.target.value }))} /></Field><Field label="Стартовый уровень"><select value={form.startingLevel} onChange={(event) => setForm((current) => ({ ...current, startingLevel: event.target.value as StartingLevel }))}><option value="beginner">Начинаю с нуля</option><option value="familiar">Знаком с основами</option><option value="refreshing">Нужно освежить</option></select></Field><Field label="Целевой уровень"><select value={form.targetOutcome} onChange={(event) => setForm((current) => ({ ...current, targetOutcome: event.target.value as TargetOutcome }))}><option value="awareness">Знать о существовании</option><option value="understanding">Понимать</option><option value="application">Уметь применять</option><option value="mastery">Владеть свободно</option></select></Field><Field label="Формат подготовки"><select value={form.studyFormat} onChange={(event) => setForm((current) => ({ ...current, studyFormat: event.target.value as StudyFormat }))}><option value="theory">Только теория</option><option value="theory_and_practice">Теория и практика</option><option value="practice">Упор на практику</option></select></Field><Field label="Минут в день"><input type="number" min="1" value={form.minutesPerDay} onChange={(event) => setForm((current) => ({ ...current, minutesPerDay: event.target.value }))} /></Field><Field label="Дней в неделю"><input type="number" min="1" max="7" value={form.daysPerWeek} onChange={(event) => setForm((current) => ({ ...current, daysPerWeek: event.target.value }))} /></Field><Field label="Длительность занятия"><input type="number" min="1" value={form.sessionMinutes} onChange={(event) => setForm((current) => ({ ...current, sessionMinutes: event.target.value }))} /></Field></div><Field label="Что уже знаете"><textarea value={form.currentKnowledge} onChange={(event) => setForm((current) => ({ ...current, currentKnowledge: event.target.value }))} /></Field><Field label="Что особенно важно"><textarea value={form.important} onChange={(event) => setForm((current) => ({ ...current, important: event.target.value }))} /></Field><Field label="Требования преподавателя"><textarea value={form.instructorRequirements} onChange={(event) => setForm((current) => ({ ...current, instructorRequirements: event.target.value }))} /></Field><div className="wizard-actions"><Button variant="ghost" onClick={() => setStep(2)}>Назад</Button><Button disabled={busy || !form.subject.trim()} onClick={() => void go(4)}>Продолжить</Button></div></section>}

      {step === 4 && <section className="wizard-step"><Card><h2>Импортировано: {studyCount}</h2><p>{counts.tickets ? `${counts.tickets} ${plural(counts.tickets, "билет", "билета", "билетов")} · ` : ""}{counts.questions} {plural(counts.questions, "вопрос", "вопроса", "вопросов")} · {counts.tasks} {plural(counts.tasks, "задача", "задачи", "задач")}</p>{countMismatch && <p className="inline-warning">Ожидалось {expectedCount}, распознано {studyCount}. Проверьте список перед созданием проекта.</p>}{warnings.map((warning) => <p className="inline-warning" key={warning}>{warning}</p>)}</Card><div className="wizard-review-list">{nodes.map((node) => <label key={node.id} style={{ paddingInlineStart: `calc(${node.parent_id ? 1 : 0} * var(--space-5))` }}><span className="sr-only">Формулировка</span><input defaultValue={node.title} onBlur={(event) => { const title = event.target.value.trim(); if (title && title !== node.title && controller.detail) void controller.enqueueProgramCommand((current) => updateProgramNode(current.project.id, node.id, { expected_program_revision: current.program.revision, title })); }} /><Pencil size={14} /></label>)}</div><div className="wizard-actions"><Button variant="ghost" onClick={() => setStep(3)}>Назад</Button><Button disabled={busy || studyCount === 0} onClick={() => void go(5)}>Подтвердить программу</Button></div></section>}

      {step === 5 && <section className="wizard-step"><Card><h2>{form.subject || "Экзаменационный проект"}</h2><p><Check size={15} /> Паспорт цели и {studyCount} {plural(studyCount, "элемент", "элемента", "элементов")} программы сохранены.</p>{calendarDays !== null && <p><CalendarDays size={15} /> До даты экзамена: {calendarDays} {plural(calendarDays, "календарный день", "календарных дня", "календарных дней")}.</p>}<p>Ритм: {form.minutesPerDay || "—"} минут, {form.daysPerWeek || "—"} {plural(Number(form.daysPerWeek), "день", "дня", "дней")} в неделю.</p></Card><p>После создания добавьте эталонные ответы в Карте эталонов. Материалы появятся на этапе 5.</p><div className="wizard-actions"><Button variant="ghost" onClick={() => setStep(4)}>Назад</Button><Button disabled={busy} onClick={() => void activate()}>Создать проект</Button></div></section>}
    </div>
  );
}
