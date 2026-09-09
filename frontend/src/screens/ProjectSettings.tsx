import type { CSSProperties } from "react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { RadioGroup } from "radix-ui";
import {
  ArrowLeft,
  CalendarDays,
  Check,
  Flag,
  Save,
  Target,
} from "lucide-react";
import {
  getProject,
  ProjectApiError,
  updateProjectSettings,
} from "../api/projects";
import { ProjectNav } from "../components/domain";
import type {
  ExamFormat,
  GoalPassportWrite,
  GoalPurpose,
  GoalScope,
  ModuleKey,
  ProjectDetail,
  ProjectIconName,
  ProjectSettingsCommand,
  StartingLevel,
  StudyFormat,
  TargetOutcome,
} from "../api/projects";
import { PROJECT_ICONS } from "../components/domain";
import {
  Button,
  Card,
  Dialog,
  ErrorState,
  Field,
  LoadingState,
  PageHead,
  Tooltip,
} from "../components/ui";

interface SettingsForm {
  project: {
    name: string;
    description: string;
    icon: ProjectIconName | null;
    color: number | null;
    deadline: string;
  };
  goal: Omit<GoalPassportWrite, "minutes_per_day" | "days_per_week" | "session_minutes" | "expected_item_count" | "exam_time"> & {
    minutes_per_day: string;
    days_per_week: string;
    session_minutes: string;
    expected_item_count: string;
    exam_time: string;
  };
}

const ICON_OPTIONS: Array<{ value: ProjectIconName; label: string }> = [
  { value: "graduation-cap", label: "Учёба" },
  { value: "book-open", label: "Книга" },
  { value: "database", label: "База данных" },
  { value: "sigma", label: "Математика" },
  { value: "atom", label: "Физика" },
  { value: "code", label: "Программирование" },
  { value: "globe", label: "Мир" },
  { value: "scale", label: "Право" },
  { value: "flask", label: "Химия" },
];

const PURPOSE_OPTIONS: Array<{ value: GoalPurpose; label: string }> = [
  { value: "exam", label: "Экзамен" },
  { value: "work", label: "Рабочая задача" },
  { value: "interview", label: "Собеседование" },
  { value: "interest", label: "Общий интерес" },
];

const STARTING_LEVEL_OPTIONS: Array<{ value: StartingLevel; label: string }> = [
  { value: "beginner", label: "С нуля" },
  { value: "familiar", label: "Что-то знаю" },
  { value: "refreshing", label: "Повторяю забытое" },
];

const TARGET_OPTIONS: Array<{ value: TargetOutcome; label: string }> = [
  { value: "awareness", label: "Знать о существовании" },
  { value: "understanding", label: "Понимать" },
  { value: "application", label: "Уметь применять" },
  { value: "mastery", label: "Владеть свободно" },
];

const STUDY_FORMAT_OPTIONS: Array<{ value: StudyFormat; label: string }> = [
  { value: "theory", label: "Только теория" },
  { value: "theory_and_practice", label: "Теория и практика" },
  { value: "practice", label: "Больше практики" },
];

const EXAM_FORMAT_OPTIONS: Array<{ value: ExamFormat; label: string }> = [
  { value: "questions", label: "Отдельные вопросы" },
  { value: "questions_tasks", label: "Вопросы и задачи" },
  { value: "tickets", label: "Готовые билеты" },
  { value: "unknown", label: "Точный список неизвестен" },
];

function text(value: string | null): string {
  return value ?? "";
}

function numberText(value: number | null): string {
  return value === null ? "" : String(value);
}

function formFromDetail(detail: ProjectDetail): SettingsForm {
  const goal = detail.goal_passport;
  return {
    project: {
      name: text(detail.project.name),
      description: text(detail.project.description),
      icon: detail.project.icon,
      color: detail.project.color,
      deadline: text(detail.project.deadline),
    },
    goal: {
      subject: goal?.subject ?? null,
      purpose: goal?.purpose ?? null,
      scope: goal?.scope ?? null,
      starting_level: goal?.starting_level ?? null,
      current_knowledge: goal?.current_knowledge ?? null,
      target_outcome: goal?.target_outcome ?? null,
      goal: goal?.goal ?? null,
      success_criterion: goal?.success_criterion ?? null,
      important: goal?.important ?? null,
      excluded: goal?.excluded ?? null,
      study_format: goal?.study_format ?? null,
      minutes_per_day: numberText(goal?.minutes_per_day ?? null),
      days_per_week: numberText(goal?.days_per_week ?? null),
      session_minutes: numberText(goal?.session_minutes ?? null),
      exam_format: goal?.exam_format ?? null,
      expected_item_count: numberText(goal?.expected_item_count ?? null),
      instructor_requirements: goal?.instructor_requirements ?? null,
      exam_time: goal?.exam_time?.slice(0, 5) ?? "",
      exam_procedure: goal?.exam_procedure ?? null,
    },
  };
}

function nullableText(value: string | null): string | null {
  const normalized = value?.trim() ?? "";
  return normalized || null;
}

function nullableNumber(value: string): number | null {
  return value === "" ? null : Number(value);
}

function commandFromForm(
  form: SettingsForm,
  enabledModules: ModuleKey[],
): ProjectSettingsCommand {
  return {
    project: {
      name: form.project.name.trim(),
      description: nullableText(form.project.description),
      icon: form.project.icon,
      color: form.project.color,
      deadline: form.project.deadline || null,
      // Настройки проекта больше не управляют доступностью разделов. Поле пока
      // требуется существующим контрактом API, поэтому сохраняем его как есть.
      enabled_modules: enabledModules,
    },
    goal_passport: {
      subject: nullableText(form.goal.subject),
      purpose: form.goal.purpose,
      scope: form.goal.scope,
      starting_level: form.goal.starting_level,
      current_knowledge: nullableText(form.goal.current_knowledge),
      target_outcome: form.goal.target_outcome,
      goal: nullableText(form.goal.goal),
      success_criterion: nullableText(form.goal.success_criterion),
      important: nullableText(form.goal.important),
      excluded: nullableText(form.goal.excluded),
      study_format: form.goal.study_format,
      minutes_per_day: nullableNumber(form.goal.minutes_per_day),
      days_per_week: nullableNumber(form.goal.days_per_week),
      session_minutes: nullableNumber(form.goal.session_minutes),
      exam_format: form.goal.exam_format,
      expected_item_count: nullableNumber(form.goal.expected_item_count),
      instructor_requirements: nullableText(form.goal.instructor_requirements),
      exam_time: form.goal.exam_time || null,
      exam_procedure: nullableText(form.goal.exam_procedure),
    },
  };
}

function integerError(value: string, minimum: number, maximum?: number): string | undefined {
  if (!value) return undefined;
  const number = Number(value);
  if (!Number.isInteger(number) || number < minimum || (maximum !== undefined && number > maximum)) {
    return maximum === undefined
      ? `Укажите целое число не меньше ${minimum}`
      : `Укажите целое число от ${minimum} до ${maximum}`;
  }
  return undefined;
}

function validationErrors(form: SettingsForm): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!form.project.name.trim()) errors.name = "Название обязательно";
  const minutes = integerError(form.goal.minutes_per_day, 1);
  const days = integerError(form.goal.days_per_week, 1, 7);
  const session = integerError(form.goal.session_minutes, 1);
  const expected = integerError(form.goal.expected_item_count, 1);
  if (minutes) errors.minutes_per_day = minutes;
  if (days) errors.days_per_week = days;
  if (session) errors.session_minutes = session;
  if (expected) errors.expected_item_count = expected;
  return errors;
}

function requestErrorMessage(error: unknown): string {
  return error instanceof ProjectApiError
    ? error.message
    : "Не удалось связаться с сервером. Проверьте, что Tentex запущен, и повторите.";
}

function statusLabel(detail: ProjectDetail): string {
  if (detail.project.status === "archived") return "Проект в архиве";
  if (detail.project.status === "completed") return "Проект завершён";
  return "Активный проект";
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString("ru-RU", { dateStyle: "medium", timeStyle: "short" });
}

export function ProjectSettings() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [form, setForm] = useState<SettingsForm | null>(null);
  const [baseline, setBaseline] = useState<SettingsForm | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saved, setSaved] = useState(false);
  const [exitDialogOpen, setExitDialogOpen] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError(null);
    getProject(projectId, controller.signal)
      .then((loaded) => {
        const nextForm = formFromDetail(loaded);
        setDetail(loaded);
        setForm(nextForm);
        setBaseline(nextForm);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setLoadError(error);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [projectId, reloadKey]);

  const dirty = Boolean(form && baseline && JSON.stringify(form) !== JSON.stringify(baseline));
  const errors = useMemo(() => form ? validationErrors(form) : {}, [form]);
  const valid = Object.keys(errors).length === 0;
  const readOnly = detail?.project.status !== "active";

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function changeForm(update: (current: SettingsForm) => SettingsForm) {
    setForm((current) => current ? update(current) : current);
    setSaved(false);
    setSaveError("");
  }

  function updateProject<K extends keyof SettingsForm["project"]>(
    key: K,
    value: SettingsForm["project"][K],
  ) {
    changeForm((current) => ({ ...current, project: { ...current.project, [key]: value } }));
  }

  function updateGoal<K extends keyof SettingsForm["goal"]>(
    key: K,
    value: SettingsForm["goal"][K],
  ) {
    changeForm((current) => ({ ...current, goal: { ...current.goal, [key]: value } }));
  }

  async function save(): Promise<boolean> {
    if (!form || !detail || readOnly || !dirty || !valid || saving) return false;
    setSaving(true);
    setSaveError("");
    setSaved(false);
    try {
      const updated = await updateProjectSettings(
        projectId,
        commandFromForm(form, detail.project.enabled_modules),
      );
      const nextDetail = {
        ...detail,
        project: updated.project,
        goal_passport: updated.goal_passport,
      };
      const nextForm = formFromDetail(nextDetail);
      setDetail(nextDetail);
      setForm(nextForm);
      setBaseline(nextForm);
      setSaved(true);
      return true;
    } catch (error: unknown) {
      setSaveError(requestErrorMessage(error));
      return false;
    } finally {
      setSaving(false);
    }
  }

  function returnToWorkspace() {
    if (dirty) {
      setExitDialogOpen(true);
      return;
    }
    navigate(`/projects/${projectId}`);
  }

  async function saveAndReturn() {
    if (await save()) {
      setExitDialogOpen(false);
      navigate(`/projects/${projectId}`);
    }
  }

  if (loading) return <div className="screen project-settings-screen"><LoadingState label="Загружаем настройки проекта" placement="page" /></div>;

  if (loadError instanceof ProjectApiError && loadError.status === 404) {
    return (
      <div className="screen project-settings-screen settings-state">
        <ErrorState title="Проект не найден" message={loadError.message} />
        <Link className="secondary-button" to="/projects"><ArrowLeft size={15} aria-hidden="true" /> К проектам</Link>
      </div>
    );
  }

  if (loadError || !detail || !form) {
    return (
      <div className="screen project-settings-screen settings-state">
        <ErrorState message={requestErrorMessage(loadError)} />
        <Button variant="secondary" onClick={() => setReloadKey((value) => value + 1)}>Повторить</Button>
      </div>
    );
  }

  return (
    <div className="program-screen settings-screen">
      <aside className="project-side-panel">
        <header className="project-side-title">
          <Tooltip label="Вернуться в рабочую область">
            <button type="button" className="workspace-back-button" onClick={returnToWorkspace} aria-label="Вернуться в рабочую область">
              <ArrowLeft size={15} />
            </button>
          </Tooltip>
          <strong>{detail.project.name}</strong>
        </header>
        <section className="settings-recent" aria-label="Последние изменения">
          <header><span>Последние изменения</span></header>
          <ul className="settings-recent-list">
            <li><span>Проект</span><time dateTime={detail.project.updated_at}>{formatDateTime(detail.project.updated_at)}</time></li>
            {detail.goal_passport && (
              <li><span>Паспорт цели</span><time dateTime={detail.goal_passport.updated_at}>{formatDateTime(detail.goal_passport.updated_at)}</time></li>
            )}
          </ul>
        </section>
        <ProjectNav
          projectId={projectId}
          active="settings"
          modules={detail.project.enabled_modules}
          className="project-side-nav"
        />
      </aside>

      <main className="program-main settings-main">
      <PageHead title="Настройки" />

      {readOnly && (
        <Card className="settings-readonly" >
          <strong>{statusLabel(detail)} — настройки доступны только для чтения.</strong>
          <span>Верните проект в активные, чтобы изменить его.</span>
        </Card>
      )}

      <form onSubmit={(event) => { event.preventDefault(); void save(); }} noValidate>
        <fieldset className="settings-fieldset" disabled={readOnly || saving}>
          <Card className="settings-section">
            <h2><Flag size={17} aria-hidden="true" /> Проект</h2>
            <div className={`settings-grid ${detail.project.workspace_variant === "exam" ? "is-three-columns" : "is-two-columns"}`}>
              <Field label="Название" required error={errors.name}>
                <input value={form.project.name} onChange={(event) => updateProject("name", event.target.value)} autoComplete="off" />
              </Field>
              <Field label={detail.project.workspace_variant === "exam" ? "Дата экзамена" : "Дедлайн"} hint="Необязательно">
                <input type="date" value={form.project.deadline} onChange={(event) => updateProject("deadline", event.target.value)} />
              </Field>
              {detail.project.workspace_variant === "exam" && (
                <Field label="Время экзамена" hint="Необязательно">
                  <input type="time" value={form.goal.exam_time} onChange={(event) => updateGoal("exam_time", event.target.value)} />
                </Field>
              )}
            </div>
            <Field label="Описание" hint="Коротко: чем этот проект отличается от других по тому же предмету">
              <textarea rows={3} value={form.project.description} onChange={(event) => updateProject("description", event.target.value)} />
            </Field>

            <fieldset className="settings-choice-fieldset">
              <legend>Иконка проекта</legend>
              <RadioGroup.Root
                className="settings-icon-options"
                value={form.project.icon ?? ""}
                onValueChange={(value) => updateProject("icon", value as ProjectIconName)}
                disabled={readOnly || saving}
                aria-label="Иконка проекта"
              >
                {ICON_OPTIONS.map((option) => {
                  const Icon = PROJECT_ICONS[option.value];
                  return (
                    <RadioGroup.Item className="settings-icon-option" value={option.value} key={option.value}>
                      <Icon size={17} aria-hidden="true" />
                      <span>{option.label}</span>
                      <RadioGroup.Indicator><Check size={13} aria-hidden="true" /></RadioGroup.Indicator>
                    </RadioGroup.Item>
                  );
                })}
              </RadioGroup.Root>
            </fieldset>

            <fieldset className="settings-choice-fieldset">
              <legend>Цвет проекта</legend>
              <RadioGroup.Root
                className="settings-color-options"
                value={form.project.color === null ? "" : String(form.project.color)}
                onValueChange={(value) => updateProject("color", Number(value))}
                disabled={readOnly || saving}
                aria-label="Цвет проекта"
              >
                {Array.from({ length: 8 }, (_, index) => index + 1).map((color) => (
                  <RadioGroup.Item
                    className="settings-color-option"
                    value={String(color)}
                    key={color}
                    aria-label={`Цвет ${color}`}
                    style={{ "--settings-project-color": `var(--project-color-${color})` } as CSSProperties}
                  >
                    <span aria-hidden="true" />
                    <RadioGroup.Indicator><Check size={14} aria-hidden="true" /></RadioGroup.Indicator>
                  </RadioGroup.Item>
                ))}
              </RadioGroup.Root>
            </fieldset>
          </Card>

          <Card className="settings-section">
            <h2><Target size={17} aria-hidden="true" /> Паспорт цели</h2>
            <p className="settings-section-lead">Паспорт влияет на программу и будущий план, но после сохранения программа автоматически не перестраивается.</p>
            <div className="settings-grid is-two-columns">
              <Field label="Предмет">
                <input value={text(form.goal.subject)} onChange={(event) => updateGoal("subject", event.target.value)} />
              </Field>
              <Field label="Зачем изучаете">
                <select value={form.goal.purpose ?? ""} onChange={(event) => updateGoal("purpose", (event.target.value || null) as GoalPurpose | null)}>
                  <option value="">Не указано</option>
                  {PURPOSE_OPTIONS.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}
                </select>
              </Field>
              <Field label="Охват">
                <select value={form.goal.scope ?? ""} onChange={(event) => updateGoal("scope", (event.target.value || null) as GoalScope | null)}>
                  <option value="">Не указано</option>
                  <option value="whole">Весь материал</option>
                  <option value="goal">Конкретная цель</option>
                </select>
              </Field>
              <Field label="Стартовый уровень">
                <select value={form.goal.starting_level ?? ""} onChange={(event) => updateGoal("starting_level", (event.target.value || null) as StartingLevel | null)}>
                  <option value="">Не указано</option>
                  {STARTING_LEVEL_OPTIONS.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}
                </select>
              </Field>
              <Field label="Целевой результат">
                <select value={form.goal.target_outcome ?? ""} onChange={(event) => updateGoal("target_outcome", (event.target.value || null) as TargetOutcome | null)}>
                  <option value="">Не указано</option>
                  {TARGET_OPTIONS.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}
                </select>
              </Field>
              <Field label="Формат работы">
                <select value={form.goal.study_format ?? ""} onChange={(event) => updateGoal("study_format", (event.target.value || null) as StudyFormat | null)}>
                  <option value="">Не указано</option>
                  {STUDY_FORMAT_OPTIONS.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}
                </select>
              </Field>
            </div>
            <Field label="Что уже знаете">
              <textarea rows={3} value={text(form.goal.current_knowledge)} onChange={(event) => updateGoal("current_knowledge", event.target.value)} />
            </Field>
            <div className="settings-grid is-two-columns">
              <Field label="Конкретная цель">
                <textarea rows={4} value={text(form.goal.goal)} onChange={(event) => updateGoal("goal", event.target.value)} />
              </Field>
              <Field label="Критерий результата">
                <textarea rows={4} value={text(form.goal.success_criterion)} onChange={(event) => updateGoal("success_criterion", event.target.value)} />
              </Field>
              <Field label="Что особенно важно">
                <textarea rows={3} value={text(form.goal.important)} onChange={(event) => updateGoal("important", event.target.value)} />
              </Field>
              <Field label="Что можно пропустить">
                <textarea rows={3} value={text(form.goal.excluded)} onChange={(event) => updateGoal("excluded", event.target.value)} />
              </Field>
            </div>
          </Card>

          <Card className="settings-section">
            <h2><CalendarDays size={17} aria-hidden="true" /> Ритм занятий</h2>
            <div className="settings-grid is-three-columns">
              <Field label="Минут в день" error={errors.minutes_per_day}>
                <input type="number" min="1" step="1" inputMode="numeric" value={form.goal.minutes_per_day} onChange={(event) => updateGoal("minutes_per_day", event.target.value)} />
              </Field>
              <Field label="Дней в неделю" error={errors.days_per_week}>
                <input type="number" min="1" max="7" step="1" inputMode="numeric" value={form.goal.days_per_week} onChange={(event) => updateGoal("days_per_week", event.target.value)} />
              </Field>
              <Field label="Минут в занятии" error={errors.session_minutes}>
                <input type="number" min="1" step="1" inputMode="numeric" value={form.goal.session_minutes} onChange={(event) => updateGoal("session_minutes", event.target.value)} />
              </Field>
            </div>
          </Card>

          {detail.project.workspace_variant === "exam" && (
            <Card className="settings-section">
              <h2><CalendarDays size={17} aria-hidden="true" /> Экзамен</h2>
              <div className="settings-grid is-two-columns">
                <Field label="Формат экзамена">
                  <select value={form.goal.exam_format ?? ""} onChange={(event) => updateGoal("exam_format", (event.target.value || null) as ExamFormat | null)}>
                    <option value="">Не указано</option>
                    {EXAM_FORMAT_OPTIONS.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}
                  </select>
                </Field>
                <Field label="Ожидаемое число элементов" error={errors.expected_item_count} hint="Для проверки импорта, а не вместо распознавания">
                  <input type="number" min="1" step="1" inputMode="numeric" value={form.goal.expected_item_count} onChange={(event) => updateGoal("expected_item_count", event.target.value)} />
                </Field>
              </div>
              <div className="settings-grid is-two-columns">
                <Field label="Требования преподавателя">
                  <textarea rows={4} value={text(form.goal.instructor_requirements)} onChange={(event) => updateGoal("instructor_requirements", event.target.value)} />
                </Field>
                <Field label="Как проходит экзамен">
                  <textarea rows={4} value={text(form.goal.exam_procedure)} onChange={(event) => updateGoal("exam_procedure", event.target.value)} />
                </Field>
              </div>
            </Card>
          )}

        </fieldset>

        <div className="settings-actions">
          <span className="settings-save-state" role="status" aria-live="polite">
            {saving ? "Сохраняем…" : saved ? "Сохранено" : dirty ? "Есть несохранённые изменения" : ""}
          </span>
          <Button className="settings-save-button" type="submit" disabled={readOnly || !dirty || !valid || saving}>
            <Save size={17} aria-hidden="true" /> Сохранить изменения
          </Button>
        </div>
        {saveError && <p className="settings-save-error" role="alert">{saveError}</p>}
      </form>
      </main>

      <Dialog
        open={exitDialogOpen}
        onOpenChange={setExitDialogOpen}
        title="Сохранить изменения?"
        description="Вы изменили настройки проекта. Сохраните их перед возвратом в рабочую область."
        footer={
          <>
            <Button variant="ghost" disabled={saving} onClick={() => setExitDialogOpen(false)}>Остаться</Button>
            <Button variant="secondary" disabled={saving} onClick={() => navigate(`/projects/${projectId}`)}>Не сохранять</Button>
            <Button disabled={!valid || saving} onClick={() => void saveAndReturn()}>
              <Save size={15} aria-hidden="true" /> {saving ? "Сохраняем…" : "Сохранить и вернуться"}
            </Button>
          </>
        }
      />
    </div>
  );
}
