import { useCallback, useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";
import { useNavigate } from "react-router";
import { BookOpen, Info, LibraryBig, Trash2, Undo2, UploadCloud, WandSparkles } from "lucide-react";
import type { ChatMessageRead } from "../api/chat";
import {
  type GoalPassportWrite,
  type GoalScope,
  type ModuleKey,
  type ProjectDetail,
  type TargetOutcome,
} from "../api/projects";
import type { WizardDraftController } from "../hooks/useWizardDraft";
import { Button, Card, Disclosure, Field, IconButton, LoadingState, PageHead, SegmentedTabs, StatusBadge } from "../components/ui";
import {
  LibraryMaterialPickerDialog,
  ProgramTreePreview,
  QualityBadge,
  ResearchLaunchDialog,
  TaskRow,
  TextbookProgramEditor,
} from "../components/domain";
import type { TextbookProgramView } from "../components/domain";
import { buildProgramTree, flattenProgramTree } from "./programTree";
import { useProjectMaterials } from "../hooks/useProjectMaterials";
import { TextbookSourceCard } from "./TextbookSourceCard";
import {
  TextbookOutlineReview,
} from "./TextbookOutlineReview";
import { lastPendingDiff, ProgramChatWorkspace } from "./workspace/chat/ProgramChatWorkspace";
import {
  outlineItemsWithKeys,
  type OutlineDraftState,
  type OutlinesByMaterialId,
} from "../components/domain/program-editor/outlineState";

type ProgramMode = "manual" | "ai";

interface TextbookForm {
  name: string;
  subject: string;
  scope: GoalScope;
  goal: string;
  currentKnowledge: string;
  targetOutcome: TargetOutcome;
  successCriterion: string;
  important: string;
  excluded: string;
  deadline: string;
  minutesPerDay: string;
  daysPerWeek: string;
}

const EMPTY_FORM: TextbookForm = {
  name: "",
  subject: "",
  scope: "goal",
  goal: "",
  currentKnowledge: "",
  targetOutcome: "understanding",
  successCriterion: "",
  important: "",
  excluded: "",
  deadline: "",
  minutesPerDay: "45",
  daysPerWeek: "4",
};
const nullable = (value: string) => value.trim() || null;
const positive = (value: string) => Number(value) > 0 ? Number(value) : null;

const TARGET_OUTCOME_LABEL: Record<TargetOutcome, string> = {
  awareness: "Ориентироваться",
  understanding: "Понимать",
  application: "Применять",
  mastery: "Освоить",
};

function volumeLabel(totalBytes: number): string {
  if (totalBytes < 1024) return `${totalBytes} Б`;
  if (totalBytes < 1024 ** 2) return `${(totalBytes / 1024).toFixed(1)} КБ`;
  if (totalBytes < 1024 ** 3) return `${(totalBytes / 1024 ** 2).toFixed(1)} МБ`;
  return `${(totalBytes / 1024 ** 3).toFixed(1)} ГБ`;
}

interface TextbookWizardProps {
  controller: WizardDraftController;
  requestedStep?: number;
  onStepChange?: (step: number) => void;
  onActivated?: (project: ProjectDetail) => void;
}

export function TextbookWizard({ controller, requestedStep, onStepChange, onActivated }: TextbookWizardProps) {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<TextbookForm>(EMPTY_FORM);
  const [view, setView] = useState<TextbookProgramView>("tree");
  const [programMode, setProgramMode] = useState<ProgramMode>("manual");
  const [aiChatMessages, setAiChatMessages] = useState<ChatMessageRead[]>([]);
  const lastPendingDiffValue = lastPendingDiff(aiChatMessages);
  function executeProgramCommand(
    request: (revision: number) => Promise<import("../api/projects").ProgramChangeResult>,
  ) {
    return controller.enqueueProgramCommand((current) => request(current.program.revision));
  }
  const [actionError, setActionError] = useState("");
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [researchProject, setResearchProject] = useState<ProjectDetail | null>(null);
  const [researchOpen, setResearchOpen] = useState(false);
  const researchStarted = useRef(false);
  const [outlinesByMaterialId, setOutlinesByMaterialId] = useState<OutlinesByMaterialId>({});
  const initializedKey = useRef<string | null>(null);
  const materialInput = useRef<HTMLInputElement>(null);
  const materials = useProjectMaterials(controller.detail?.project.id);

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
    const goal = detail.goal_passport;
    setStep(detail.draft.current_step);
    setView((detail.draft.state.program_view as TextbookProgramView) ?? "tree");
    setProgramMode((detail.draft.state.program_mode as ProgramMode) ?? "manual");
    const saved = (detail.draft.state.outlines_by_material_id as OutlinesByMaterialId | undefined) ?? {};
    const legacy = detail.draft.state.outline as OutlineDraftState | undefined;
    const outlineEntries = Object.keys(saved).length ? saved : legacy ? { [legacy.material_id]: legacy } : {};
    setOutlinesByMaterialId(Object.fromEntries(Object.entries(outlineEntries).map(([materialId, outline]) => [
      materialId,
      { ...outline, items: outlineItemsWithKeys(materialId, outline.source, outline.items) },
    ])));
    setForm({
      name: detail.project.name ?? "",
      subject: goal?.subject ?? "",
      scope: goal?.scope ?? "goal",
      goal: goal?.goal ?? "",
      currentKnowledge: goal?.current_knowledge ?? "",
      targetOutcome: goal?.target_outcome ?? "understanding",
      successCriterion: goal?.success_criterion ?? "",
      important: goal?.important ?? "",
      excluded: goal?.excluded ?? "",
      deadline: detail.project.deadline ?? "",
      minutesPerDay: goal?.minutes_per_day ? String(goal.minutes_per_day) : "45",
      daysPerWeek: goal?.days_per_week ? String(goal.days_per_week) : "4",
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
      purpose: "interest",
      scope: form.scope,
      starting_level: "familiar",
      current_knowledge: nullable(form.currentKnowledge),
      target_outcome: form.targetOutcome,
      goal: form.scope === "goal" ? nullable(form.goal) : null,
      success_criterion: nullable(form.successCriterion),
      important: nullable(form.important),
      excluded: nullable(form.excluded),
      study_format: null,
      minutes_per_day: positive(form.minutesPerDay),
      days_per_week: positive(form.daysPerWeek),
      session_minutes: null,
      exam_format: null,
      expected_item_count: null,
      instructor_requirements: null,
      exam_time: null,
      exam_procedure: null,
    };
  }

  function command(nextStep: number) {
    return {
      current_step: nextStep,
      max_completed_step: Math.max(nextStep, controller.detail?.draft.max_completed_step ?? 1),
      schema_version: 1,
      project: {
        name: nullable(form.name || form.subject),
        description: form.scope === "goal" ? nullable(form.goal) : null,
        icon: "book-open" as const,
        color: 4,
        deadline: nullable(form.deadline),
        enabled_modules: ["plan", "lessons", "repetitions"] as ModuleKey[],
      },
      goal_passport: passport(),
      state: {
        program_view: view,
        program_mode: programMode,
        selected_node_id: controller.detail?.program.nodes[0]?.id ?? null,
        outlines_by_material_id: outlinesByMaterialId,
      },
    };
  }

  const nodes = (controller.detail?.program.nodes ?? []).filter((node) => node.is_in_current_program && !node.is_archived);
  let tree = [] as ReturnType<typeof buildProgramTree>;
  let flat = [] as ReturnType<typeof flattenProgramTree>;
  try {
    tree = buildProgramTree(nodes);
    flat = flattenProgramTree(tree);
  } catch { /* The draft error state remains available instead of crashing the editor. */ }
  const sectionCount = nodes.filter((node) => node.node_type === "section").length;
  const topicCount = nodes.filter((node) => node.node_type === "topic").length;
  const subpointCount = nodes.filter((node) => node.node_type === "subpoint").length;
  const readyMaterialCount = materials.materials.filter((material) => material.status === "ready").length;
  const totalPageCount = materials.materials.reduce((sum, material) => sum + (material.page_count ?? 0), 0);
  const totalSizeBytes = materials.materials.reduce((sum, material) => sum + material.size_bytes, 0);

  useEffect(() => {
    const key = controller.detail ? `${controller.detail.project.id}:${controller.hydrationVersion}` : null;
    if (!controller.detail || initializedKey.current !== key || controller.conflict) return;
    const timer = window.setTimeout(() => {
      void controller.queueSave(command(step)).catch(() => undefined);
    }, 400);
    return () => window.clearTimeout(timer);
  }, [form, step, view, programMode, outlinesByMaterialId]);

  const updateOutline = useCallback((materialId: string, next: OutlineDraftState | null) => {
    setOutlinesByMaterialId((current) => {
      const updated = { ...current };
      if (next) updated[materialId] = next; else delete updated[materialId];
      return updated;
    });
  }, []);

  async function go(nextStep: number) {
    setActionError("");
    try {
      await controller.queueSave(command(nextStep));
      changeStep(nextStep);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось сохранить черновик");
    }
  }

  async function addMaterial(file: File) {
    await materials.upload(file, "main", ["study_source"]);
  }

  async function activate(startResearch: boolean) {
    setActionError("");
    try {
      await controller.queueSave(command(5));
      const project = await controller.activate();
      if (startResearch) {
        researchStarted.current = false;
        setResearchProject(project);
        setResearchOpen(true);
      } else {
        onActivated?.(project);
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось создать проект");
    }
  }

  if (controller.status === "loading" || (controller.status === "saving" && !controller.detail)) return <LoadingState label="Загружаем учебниковый черновик" placement="page" />;
  const busy = controller.status === "saving";

  // Ошибка шага показывается прямо над кнопкой действия того же шага, а не
  // баннером наверху страницы: пользователь смотрит на кнопку, которую только
  // что нажал, а не листает вверх, чтобы понять, почему сохранение не прошло.
  const errorBanner = (actionError || controller.error)
    ? <p className="inline-error" role="alert">{actionError || controller.error?.message}</p>
    : null;

  return (
    <div className={`wizard-flow ${step === 4 ? "is-program-editor" : ""}`.trim()}>
      {step !== 4 && <PageHead title={step === 1 ? "Добавьте материалы, на которых строить программу" : step === 2 ? "Чему именно вы хотите научиться?" : step === 3 ? "Проверка" : "Итог"} />}
      {controller.conflict && <Card><h2>Черновик изменился в другой вкладке</h2><Button onClick={() => void controller.reload()}>Загрузить серверную версию</Button></Card>}

      {step === 1 && (
        <section className="textbook-step">
          <p className="wizard-step-intro">Добавьте материалы и подготовьте их текст. Tentex сам определит страницы, которым нужен OCR.</p>
          <input ref={materialInput} className="materials-file-input" type="file" multiple tabIndex={-1} aria-hidden="true" accept=".pdf,.docx,.txt,.md,.jpg,.jpeg,.png,.mp3,.wav,.m4a,.ogg,.flac" onChange={(event) => { Array.from(event.target.files ?? []).forEach((file) => void addMaterial(file)); event.target.value = ""; }} />
          <div onDragOver={(event: DragEvent<HTMLDivElement>) => event.preventDefault()} onDrop={(event: DragEvent<HTMLDivElement>) => { event.preventDefault(); Array.from(event.dataTransfer.files).forEach((file) => void addMaterial(file)); }}>
            <Card className="textbook-dropzone">
              <UploadCloud size={24} aria-hidden="true" />
              <span><b>Перетащите учебники, методички, конспекты, статьи или аудио</b><small>PDF, DOCX, TXT, MD, изображения и аудио. До 200 МБ на файл.</small></span>
              <div className="material-entry-actions">
                <Button disabled={materials.busy || !controller.detail} variant="secondary" onClick={() => materialInput.current?.click()}>Добавить материал</Button>
                <Button disabled={materials.busy || !controller.detail} variant="secondary" onClick={() => setLibraryOpen(true)}><LibraryBig size={15} aria-hidden="true" />Из Библиотеки</Button>
              </div>
            </Card>
          </div>

          <div className="textbook-source-list">
            {materials.loading && <LoadingState label="Загружаем источники" />}
            {materials.error && <p className="inline-error" role="alert">{materials.error}</p>}
            {!materials.loading && materials.materials.length === 0 && <Card className="textbook-empty-source">Источников пока нет. Добавьте хотя бы один основной материал.</Card>}
            {materials.materials.map((material) => (
              <Card className="textbook-source-card" key={material.id}>
                <div className="textbook-source-main">
                  <BookOpen className="textbook-source-icon" size={16} aria-hidden="true" />
                  <span className="textbook-source-copy"><b>{material.display_name}</b><small>{material.page_count ?? 1} стр.</small>{material.parser_mode !== "fast" && material.ocr_low_page_count > 0 && <em><QualityBadge quality="ocr_low" count={material.ocr_low_page_count} /></em>}</span>
                  {material.status !== "ready_to_process" && <StatusBadge tone={material.status === "ready" ? "success" : material.status === "failed" ? "danger" : "neutral"}>{material.status === "ready" ? "Текст готов" : material.status === "failed" ? "Ошибка" : "Подготавливаем"}</StatusBadge>}
                  <div className="textbook-source-actions">
                    {material.status === "ready_to_process" && <Button variant="secondary" disabled={materials.busy} onClick={() => void materials.start(material.id)}>Подготовить текст</Button>}
                    {material.status === "failed" && <Button variant="secondary" disabled={materials.busy} onClick={() => void materials.control(material.id, "retry")}>Повторить</Button>}
                    <IconButton label={`Удалить файл «${material.display_name}»`} disabled={materials.busy} onClick={() => void materials.detach(material.id)}><Trash2 size={15} /></IconButton>
                  </div>
                </div>
                {material.task && material.task.state !== "completed" && <TaskRow task={{ id: material.task.id, kind: "parse", subject: material.display_name, unit: "страниц", done: material.task.done, total: material.task.total, etaMinutes: null, state: material.task.state, error: material.task.error ?? undefined }} onPause={() => void materials.control(material.id, "pause")} onResume={() => void materials.control(material.id, "resume")} onRetry={() => void materials.control(material.id, "retry")} />}
                <Disclosure summary="Роль и инструкция">
                  <TextbookSourceCard material={material} busy={materials.busy} onSave={materials.update} />
                </Disclosure>
              </Card>
            ))}
          </div>

          <Card className="textbook-analysis-card">
            <div className="textbook-analysis-head"><WandSparkles size={18} aria-hidden="true" /><span><b>Подготовка материалов</b><small>Кнопка «Подготовить текст» извлекает текст источника на этом компьютере.</small></span></div>
            <table className="textbook-analysis-table">
              <thead><tr><th scope="col">Всего файлов</th><th scope="col">Всего страниц</th><th scope="col">Общий объём</th></tr></thead>
              <tbody><tr><td>{materials.materials.length}</td><td>{totalPageCount}</td><td>{volumeLabel(totalSizeBytes)}</td></tr></tbody>
            </table>
            <p><Info size={14} aria-hidden="true" />Подготовка идёт в фоне — можно перейти к следующему шагу, не дожидаясь конца. Прогресс виден в панели фоновых задач и в разделе «Материалы».</p>
          </Card>

          {errorBanner}
          <div className="wizard-actions"><Button variant="ghost" onClick={() => navigate("/projects/new")}>Вернуться к выбору</Button><Button disabled={busy || materials.materials.length === 0} onClick={() => void go(2)}>Продолжить с источниками</Button></div>
        </section>
      )}

      {step === 2 && (
        <section className="textbook-step">
          <p className="wizard-step-intro">Профиль можно изменить после создания проекта.</p>
          <div className="textbook-profile-grid">
            <Card className="textbook-profile-card is-goal">
              <header><BookOpen size={18} aria-hidden="true" /><span><h2>Что изучать</h2><p>Выберите весь материал или укажите конкретную цель.</p></span></header>
              <div className="textbook-profile-fields">
                <Field label="Название проекта" required><input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} /></Field>
                <Field label="Предмет" required><input value={form.subject} onChange={(event) => setForm((current) => ({ ...current, subject: event.target.value }))} /></Field>
                <SegmentedTabs label="Охват программы" value={form.scope} onChange={(scope) => setForm((current) => ({ ...current, scope: scope as GoalScope }))} tabs={[{ value: "whole", label: "Весь материал" }, { value: "goal", label: "Конкретная цель" }]} />
                {form.scope === "goal" && <Field label="Ваша цель" required hint="Опишите результат, которого хотите достичь."><textarea required rows={5} value={form.goal} onChange={(event) => setForm((current) => ({ ...current, goal: event.target.value }))} /></Field>}
                <Field label="Что вы уже знаете"><textarea rows={3} value={form.currentKnowledge} onChange={(event) => setForm((current) => ({ ...current, currentKnowledge: event.target.value }))} /></Field>
                <SegmentedTabs label="Желаемый результат" value={form.targetOutcome} onChange={(targetOutcome) => setForm((current) => ({ ...current, targetOutcome: targetOutcome as TargetOutcome }))} tabs={[{ value: "awareness", label: "Ориентироваться" }, { value: "understanding", label: "Понимать" }, { value: "application", label: "Применять" }, { value: "mastery", label: "Освоить" }]} />
                <Field label={form.scope === "goal" ? "Как поймёте, что цель достигнута" : "Критерий успеха"} hint={form.scope === "whole" ? "Необязательно" : undefined}><textarea rows={2} value={form.successCriterion} onChange={(event) => setForm((current) => ({ ...current, successCriterion: event.target.value }))} /></Field>
                <Field label="Что особенно важно"><textarea rows={2} value={form.important} onChange={(event) => setForm((current) => ({ ...current, important: event.target.value }))} /></Field>
                <Field label="Что можно исключить"><textarea rows={2} value={form.excluded} onChange={(event) => setForm((current) => ({ ...current, excluded: event.target.value }))} /></Field>
              </div>
            </Card>

            <Card className="textbook-profile-card">
              <header><WandSparkles size={18} aria-hidden="true" /><span><h2>Как учиться</h2><p>Настройте удобный темп. Эти параметры можно изменить позже.</p></span></header>
              <div className="textbook-profile-fields">
                <Field label="Срок" hint="Необязательно"><input type="date" value={form.deadline} onChange={(event) => setForm((current) => ({ ...current, deadline: event.target.value }))} /></Field>
                <div className="textbook-number-grid">
                  <Field label="Минут в день" hint="Необязательно"><input type="number" min="10" step="5" value={form.minutesPerDay} onChange={(event) => setForm((current) => ({ ...current, minutesPerDay: event.target.value }))} /></Field>
                  <Field label="Дней в неделю" hint="Необязательно"><input type="number" min="1" max="7" value={form.daysPerWeek} onChange={(event) => setForm((current) => ({ ...current, daysPerWeek: event.target.value }))} /></Field>
                </div>
                <div className="textbook-source-summary"><b>Источники</b>{materials.materials.map((material, index) => <span key={material.id}><i>{index + 1}</i>{material.display_name}<small>{material.status === "ready" ? "текст готов" : "текст не подготовлен"}</small></span>)}<Button variant="ghost" onClick={() => void go(1)}>К источникам</Button></div>
              </div>
            </Card>
          </div>
          {errorBanner}
          <div className="wizard-actions"><Button variant="ghost" onClick={() => void go(1)}>Назад</Button><Button disabled={busy || !form.name.trim() || !form.subject.trim() || (form.scope === "goal" && !form.goal.trim())} onClick={() => void go(3)}>Продолжить</Button></div>
        </section>
      )}

      {step === 3 && (
        <section className="textbook-step textbook-preflight">
          <p className="wizard-step-intro">Проверьте профиль, материалы и оглавление перед программой.</p>

          <section className="wizard-review-summary">
            <div className="wizard-review-hero">
              <h2>
                <span>Вы изучаете предмет</span>
                <strong>{form.subject || "Без названия"}</strong>
              </h2>
              <p className="wizard-review-lead">
                {form.scope === "goal" ? form.goal || "Цель пока не указана." : "Весь основной материал."} На подготовку — <b>{form.minutesPerDay || "—"} минут в день</b>.
              </p>
            </div>
            <dl className="wizard-review-facts">
              {form.currentKnowledge.trim() && <div><dt>Что вы уже знаете</dt><dd>{form.currentKnowledge}</dd></div>}
              <div><dt>Желаемый результат</dt><dd>{TARGET_OUTCOME_LABEL[form.targetOutcome]}</dd></div>
              {form.successCriterion.trim() && <div><dt>{form.scope === "goal" ? "Как поймёте, что цель достигнута" : "Критерий успеха"}</dt><dd>{form.successCriterion}</dd></div>}
              {form.important.trim() && <div><dt>Что особенно важно</dt><dd>{form.important}</dd></div>}
              {form.excluded.trim() && <div><dt>Что можно исключить</dt><dd>{form.excluded}</dd></div>}
              <div><dt>Темп</dt><dd>{form.minutesPerDay || "—"} мин. в день, {form.daysPerWeek || "—"} дн. в неделю</dd></div>
            </dl>
          </section>

          <Card className="textbook-preflight-card">
            <div className="textbook-preflight-list">
              <section><h3>Источники</h3>{materials.materials.map((material, index) => <p key={material.id}><span>{index + 1}</span>{material.display_name}<small>{material.source_role === "main" ? "основной" : material.source_role === "additional" ? "дополнительный" : "справочный"}</small></p>)}</section>
              <section className="is-processing-copy"><h3>Подготовка материалов</h3><p>Текст готов для {readyMaterialCount} из {materials.materials.length} файлов. Всё происходит на этом компьютере.</p></section>
              <section className="is-processing-copy"><h3>Составление программы</h3><p>На следующем шаге можно собрать программу вручную или попросить ИИ-чат составить её по оглавлению или по вашей цели.</p></section>
            </div>
          </Card>

          {controller.detail && (
            <TextbookOutlineReview
              projectId={controller.detail.project.id}
              materials={materials.materials}
              values={outlinesByMaterialId}
              onChange={updateOutline}
            />
          )}

          {errorBanner}
          <div className="wizard-actions"><Button variant="ghost" onClick={() => void go(2)}>Назад</Button><Button disabled={busy} onClick={() => void go(4)}>Перейти к программе</Button></div>
        </section>
      )}

      {step === 4 && (
        <section className="textbook-builder">
          {/* Кнопка подтверждения этого шага — в шапке редактора, а не внизу
              страницы, поэтому и ошибка нужна рядом с ней, а не под деревом. */}
          {errorBanner}
          {controller.detail && <TextbookProgramEditor
            projectId={controller.detail.project.id}
            projectName={form.name || form.subject || "Программа"}
            program={controller.detail.program}
            latestUndoableAction={controller.detail.latest_undoable_action}
            materials={materials.materials}
            outlinesByMaterialId={outlinesByMaterialId}
            wizard
            busy={busy}
            view={view}
            onViewChange={setView}
            execute={executeProgramCommand}
            onUndo={async () => { await controller.undo(); }}
            mode={programMode}
            aiContent={<div className="textbook-program-ai-layout">
              <ProgramChatWorkspace
                projectId={controller.detail.project.id}
                program={controller.detail.program}
                execute={executeProgramCommand}
                onMessagesChange={setAiChatMessages}
              />
              <ProgramTreePreview
                program={controller.detail.program}
                pendingOperations={lastPendingDiffValue?.operations}
                pendingStates={lastPendingDiffValue?.operation_states}
              />
            </div>}
            renderHeader={(actions) => <header className="textbook-builder-head">
              <Button variant="ghost" disabled={!actions.canUndo || actions.busy} onClick={() => void actions.undo()}><Undo2 size={15} />Отменить</Button>
              <SegmentedTabs label="Режим составления программы" value={programMode} onChange={setProgramMode} tabs={[{ value: "manual", label: "Вручную" }, { value: "ai", label: "С ИИ" }]} />
              <Button variant="secondary" disabled={actions.busy} onClick={actions.openImport}>Импортировать оглавление</Button>
              <Button variant="ghost" disabled={actions.busy || !actions.hasNodes} onClick={actions.openRemoveAll}><Trash2 size={15} />Удалить все</Button>
              <Button className="textbook-builder-confirm" disabled={actions.busy} onClick={() => void go(5)}>{actions.hasNodes ? "Утвердить программу" : "Продолжить без программы"}</Button>
            </header>}
          />}
        </section>
      )}

      {step === 5 && (
        <section className="textbook-step">
          <p className="wizard-step-intro">Проверьте данные перед созданием проекта.</p>

          <section className="wizard-review-summary">
            <div className="wizard-review-hero">
              <h2>
                <span>Итог: вы изучаете предмет</span>
                <strong>{form.subject || form.name || "Без названия"}</strong>
              </h2>
              <p className="wizard-review-lead">
                {form.scope === "goal" ? form.goal || "Цель пока не указана." : "Весь основной материал."} На подготовку — <b>{form.minutesPerDay || "—"} минут в день</b>.
              </p>
            </div>
            <dl className="wizard-review-facts">
              <div><dt>Срок</dt><dd>{form.deadline ? new Date(`${form.deadline}T00:00:00`).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" }) : "Не задан"}</dd></div>
              {form.currentKnowledge.trim() && <div><dt>Что вы уже знаете</dt><dd>{form.currentKnowledge}</dd></div>}
              <div><dt>Желаемый результат</dt><dd>{TARGET_OUTCOME_LABEL[form.targetOutcome]}</dd></div>
              {form.successCriterion.trim() && <div><dt>{form.scope === "goal" ? "Как поймёте, что цель достигнута" : "Критерий успеха"}</dt><dd>{form.successCriterion}</dd></div>}
              {form.important.trim() && <div><dt>Что особенно важно</dt><dd>{form.important}</dd></div>}
              {form.excluded.trim() && <div><dt>Что можно исключить</dt><dd>{form.excluded}</dd></div>}
              <div><dt>Темп</dt><dd>{form.minutesPerDay || "—"} мин. в день, {form.daysPerWeek || "—"} дн. в неделю</dd></div>
            </dl>
          </section>

          <Card className="textbook-summary-card">
            <h3>Источники</h3>
            {materials.materials.map((material, index) => (
              <div key={material.id}>
                <span>{index + 1}</span>
                <b>{material.display_name}</b>
                <small>
                  {material.source_role === "main" ? "основной" : material.source_role === "additional" ? "дополнительный" : "справочный"}
                  {`, ${material.status === "ready" ? "текст готов" : material.status === "failed" ? "ошибка подготовки" : material.status === "ready_to_process" ? "текст не подготовлен" : "подготавливается"}`}
                </small>
              </div>
            ))}
            {materials.materials.length === 0 && <p>Источники не добавлены.</p>}
          </Card>

          <Card className="textbook-summary-card">
            <h3>Программа</h3>
            <dl className="textbook-summary-metrics">
              <div className="is-sections"><dt>Разделы</dt><dd>{sectionCount}</dd></div>
              <div className="is-topics"><dt>Темы</dt><dd>{topicCount}</dd></div>
              <div className="is-outside"><dt>Подпункты</dt><dd>{subpointCount}</dd></div>
              <div className="is-missing"><dt>Всего узлов</dt><dd>{nodes.length}</dd></div>
            </dl>
            {flat.map((node) => <div key={node.id}><span>{node.number}</span><b>{node.title}</b><small>{node.node_type === "section" ? "раздел" : node.node_type === "topic" ? "тема" : "подпункт"}</small></div>)}
            {flat.length === 0 && <p>Программа пока пуста.</p>}
          </Card>

          <Card className="textbook-summary-card"><h3>После создания</h3><p>Проект станет активным, а источники сохранят свои роли и настройки. {nodes.length === 0 ? "Программа останется пустой — её можно собрать вручную в разделе «Программа» после создания проекта." : "Программа сразу откроется для ручной работы."}</p></Card>
          {errorBanner}
          <div className="wizard-actions">
            <Button variant="ghost" onClick={() => void go(4)}>Вернуться к программе</Button>
            <Button variant="secondary" disabled={busy} onClick={() => void activate(false)}>Создать без исследования</Button>
            <Button disabled={busy} onClick={() => void activate(true)}>Создать и исследовать</Button>
          </div>
        </section>
      )}
      {controller.detail && (
        <LibraryMaterialPickerDialog
          open={libraryOpen}
          projectId={controller.detail.project.id}
          title="Выбрать учебные материалы из Библиотеки"
          purpose="study_source"
          multiple
          existingStudySourceCount={materials.materials.length}
          studyRoleMode="first-main"
          onOpenChange={setLibraryOpen}
          onAttached={() => materials.refresh()}
          onCreateNew={() => {
            setLibraryOpen(false);
            window.setTimeout(() => materialInput.current?.click(), 0);
          }}
        />
      )}
      {researchProject && (
        <ResearchLaunchDialog
          open={researchOpen}
          projectId={researchProject.project.id}
          onOpenChange={(open) => {
            setResearchOpen(open);
            if (!open && !researchStarted.current) onActivated?.(researchProject);
          }}
          onStarted={() => {
            researchStarted.current = true;
            navigate(`/projects/${researchProject.project.id}/coverage`);
          }}
        />
      )}
    </div>
  );
}
