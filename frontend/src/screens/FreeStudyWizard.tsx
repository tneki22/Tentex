import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, LibraryBig, Link2, Trash2, Undo2, UploadCloud } from "lucide-react";
import type { ChatMessageRead } from "../api/chat";
import { attachLibraryMaterial, listLibraryMaterials, type MaterialRead } from "../api/materials";
import { suggestMaterialsForQuery, type MaterialSuggestion, type MaterialSuggestions } from "../api/materialSuggestions";
import type { GoalPassportWrite, ModuleKey, ProjectDetail, StartingLevel } from "../api/projects";
import type { WizardDraftController } from "../hooks/useWizardDraft";
import { useAiRoleAvailability } from "../hooks/useAiRoleAvailability";
import { useProjectMaterials } from "../hooks/useProjectMaterials";
import { ProjectFileUploadStatus } from "./materials/ProjectFileUploadStatus";
import {
  LibraryMaterialPickerDialog,
  MaterialSuggestionList,
  ProgramTreePreview,
  TextbookProgramEditor,
} from "../components/domain";
import type { TextbookProgramView } from "../components/domain";
import { Button, Card, Field, IconButton, LoadingState, PageHead, SegmentedTabs, StatusBadge } from "../components/ui";
import { TextbookOutlineReview } from "./TextbookOutlineReview";
import { TextbookSourceCard } from "./TextbookSourceCard";
import { buildProgramTree, flattenProgramTree } from "./programTree";
import { ProgramReviewList } from "./ProgramReviewList";
import { lastPendingDiff, ProgramChatWorkspace } from "./workspace/chat/ProgramChatWorkspace";
import {
  outlineItemsWithKeys,
  type OutlineDraftState,
  type OutlinesByMaterialId,
} from "../components/domain/program-editor/outlineState";

type ProgramMode = "manual" | "ai";

interface FreeStudyForm {
  goal: string;
  name: string;
  subject: string;
  important: string;
  excluded: string;
  deadline: string;
  startingLevel: StartingLevel;
}

const EMPTY_FORM: FreeStudyForm = {
  goal: "",
  name: "",
  subject: "",
  important: "",
  excluded: "",
  deadline: "",
  startingLevel: "familiar",
};

const STARTING_LEVELS: Array<{ value: StartingLevel; label: string }> = [
  { value: "beginner", label: "С нуля" },
  { value: "familiar", label: "Что-то знаю" },
  { value: "refreshing", label: "Повторяю забытое" },
];

const STEP_TITLES = ["Какая у вас цель?", "Подберите материалы", "Соберите программу", "Проверьте проект"];

const nullable = (value: string): string | null => value.trim() || null;

function suggestedProjectName(goal: string, subject: string): string {
  if (subject.trim()) return subject.trim().slice(0, 80);
  const phrase = goal.trim().split(/[.!?\n]/, 1)[0]?.trim() ?? "";
  return phrase.slice(0, 80);
}

/* Оглавление читается закладками PDF или печатной страницей сразу после
   загрузки, без разбора текста. Поэтому «текст не подготовлен» и «оглавление
   есть» — не противоречие, и статус говорит об этом прямо. */
function materialStatus(material: MaterialRead): string {
  if (material.status === "ready") return "Текст готов";
  if (material.status === "failed") return "Ошибка подготовки";
  if (material.status === "ready_to_process") {
    return material.outline.length > 0
      ? "Оглавление прочитано, текст ещё не разобран"
      : "Текст ещё не подготовлен";
  }
  return "Материал обрабатывается";
}

interface FreeStudyWizardProps {
  controller: WizardDraftController;
  requestedStep?: number;
  onStepChange?: (step: number) => void;
  onActivated?: (project: ProjectDetail) => void;
}

export function FreeStudyWizard({
  controller,
  requestedStep,
  onStepChange,
  onActivated,
}: FreeStudyWizardProps) {
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<FreeStudyForm>(EMPTY_FORM);
  const [nameManual, setNameManual] = useState(false);
  const [basisMaterialId, setBasisMaterialId] = useState<string | null>(null);
  const [outlinesByMaterialId, setOutlinesByMaterialId] = useState<OutlinesByMaterialId>({});
  const [view, setView] = useState<TextbookProgramView>("tree");
  const [programMode, setProgramMode] = useState<ProgramMode | null>(null);
  const [aiChatMessages, setAiChatMessages] = useState<ChatMessageRead[]>([]);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkUrl, setLinkUrl] = useState("");
  const [actionError, setActionError] = useState("");
  const [librarySubjects, setLibrarySubjects] = useState<string[]>([]);
  const [libraryMaterialCount, setLibraryMaterialCount] = useState<number | null>(null);
  const [suggestions, setSuggestions] = useState<MaterialSuggestions | null>(null);
  const [suggestionsError, setSuggestionsError] = useState("");
  const [suggestionsKey, setSuggestionsKey] = useState(0);
  const [attachingId, setAttachingId] = useState<string | null>(null);
  const initializedKey = useRef<string | null>(null);
  const autosaveTimer = useRef<number | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const materials = useProjectMaterials(controller.detail?.project.id);
  const projectId = controller.detail?.project.id;
  const availability = useAiRoleAvailability("study_program_assistant");
  const lastPendingDiffValue = lastPendingDiff(aiChatMessages);

  useEffect(() => {
    if (controller.status !== "idle" || controller.detail
      || JSON.stringify(form) === JSON.stringify(EMPTY_FORM)) return;
    void controller.queueSave(command(step)).catch((error) => {
      setActionError(error instanceof Error ? error.message : "Не удалось создать черновик");
    });
  }, [form, controller.status, controller.detail, controller.queueSave, step]);

  useEffect(() => {
    const abort = new AbortController();
    void listLibraryMaterials(abort.signal).then((items) => {
      setLibraryMaterialCount(items.length);
      const subjects = items.flatMap((item) => item.subject ? [item.subject] : []);
      setLibrarySubjects([...new Set(subjects)].sort((a, b) => a.localeCompare(b, "ru")));
    }).catch(() => undefined);
    return () => abort.abort();
  }, []);

  useEffect(() => {
    const detail = controller.detail;
    const key = detail ? `${detail.project.id}:${controller.hydrationVersion}` : null;
    if (!detail || initializedKey.current === key) return;
    initializedKey.current = key;
    // WizardChrome перемонтирует шаг. Тогда локальная форма пуста, а уже
    // сохранённый draft нужно прочитать даже при hydrationVersion=0.
    if (controller.hydrationVersion === 0
      && JSON.stringify(form) !== JSON.stringify(EMPTY_FORM)) return;
    const state = detail.draft.state;
    const saved = (state.outlines_by_material_id as OutlinesByMaterialId | undefined) ?? {};
    setOutlinesByMaterialId(Object.fromEntries(Object.entries(saved).map(([materialId, outline]) => [
      materialId,
      { ...outline, items: outlineItemsWithKeys(materialId, outline.source, outline.items) },
    ])));
    setStep(Math.min(detail.draft.current_step, 4));
    setView((state.program_view as TextbookProgramView | undefined) ?? "tree");
    setProgramMode(state.program_mode === "ai" || state.program_mode === "manual" ? state.program_mode : null);
    setBasisMaterialId(typeof state.basis_material_id === "string" ? state.basis_material_id : null);
    setNameManual(state.name_manual === true);
    setForm({
      goal: detail.goal_passport?.goal ?? "",
      name: detail.project.name ?? "",
      subject: detail.goal_passport?.subject ?? "",
      important: detail.goal_passport?.important ?? "",
      excluded: detail.goal_passport?.excluded ?? "",
      deadline: detail.project.deadline ?? "",
      startingLevel: detail.goal_passport?.starting_level ?? "familiar",
    });
  }, [controller.detail, controller.hydrationVersion]);

  useEffect(() => {
    if (requestedStep !== undefined && requestedStep !== step) setStep(requestedStep);
  }, [requestedStep, step]);

  useEffect(() => {
    if (nameManual) return;
    setForm((current) => ({
      ...current,
      name: suggestedProjectName(current.goal, current.subject),
    }));
  }, [form.goal, form.subject, nameManual]);

  /* Режим программы выбирается один раз, когда станет известна доступность
     модели: с моделью пустая программа начинается с чата, без неё — вручную. */
  useEffect(() => {
    if (programMode !== null || availability.state === "loading" || !controller.detail) return;
    const hasNodes = controller.detail.program.nodes.some((node) => node.is_in_current_program && !node.is_archived);
    setProgramMode(availability.state === "ready" && !hasNodes ? "ai" : "manual");
  }, [availability.state, controller.detail, programMode]);

  /* Роль «Основной» в карточке источника и основа программы — один и тот же
     факт. Основа выводится из роли, иначе смена роли вручную оставляла бейдж
     и импорт оглавления на прежнем материале. */
  const basis = materials.materials.find((item) => item.id === basisMaterialId && item.source_role === "main")
    ?? materials.materials.find((item) => item.source_role === "main")
    ?? null;

  useEffect(() => {
    if (materials.loading) return;
    const derived = basis?.id ?? null;
    if (derived !== basisMaterialId) setBasisMaterialId(derived);
  }, [basis, basisMaterialId, materials.loading]);

  const suggestionQuery = [form.goal, form.subject, form.important]
    .map((part) => part.trim())
    .filter(Boolean)
    .join(". ");

  /* Подбор под цель: Библиотека ищет по смыслу цели без модели, уже
     подключённое исключается сервером, поэтому после подключения список
     перечитывается. */
  useEffect(() => {
    if (step !== 2 || !projectId || !suggestionQuery || libraryMaterialCount === 0) return;
    const abort = new AbortController();
    setSuggestionsError("");
    const timer = window.setTimeout(() => {
      suggestMaterialsForQuery(projectId, suggestionQuery, abort.signal)
        .then((result) => setSuggestions(result.by_query))
        .catch((caught) => {
          if (!abort.signal.aborted) setSuggestionsError(caught instanceof Error ? caught.message : "Подбор не удался");
        });
    }, 600);
    return () => {
      window.clearTimeout(timer);
      abort.abort();
    };
  }, [step, projectId, suggestionQuery, libraryMaterialCount, materials.materials.length, suggestionsKey]);

  function passport(): GoalPassportWrite {
    return {
      subject: nullable(form.subject),
      purpose: "interest",
      scope: "goal",
      starting_level: form.startingLevel,
      current_knowledge: null,
      target_outcome: "understanding",
      goal: nullable(form.goal),
      success_criterion: null,
      important: nullable(form.important),
      excluded: nullable(form.excluded),
      study_format: null,
      minutes_per_day: null,
      days_per_week: null,
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
        name: nullable(form.name),
        description: nullable(form.goal),
        icon: "book-open" as const,
        color: 4,
        deadline: nullable(form.deadline),
        enabled_modules: ["lessons", "repetitions"] as ModuleKey[],
      },
      goal_passport: passport(),
      state: {
        basis_material_id: basisMaterialId,
        name_manual: nameManual,
        program_view: view,
        program_mode: programMode,
        outlines_by_material_id: outlinesByMaterialId,
      },
    };
  }

  useEffect(() => {
    if (!controller.detail || initializedKey.current === null || controller.conflict) return;
    autosaveTimer.current = window.setTimeout(() => {
      void controller.queueSave(command(step)).catch(() => undefined);
    }, 400);
    return () => { if (autosaveTimer.current !== null) window.clearTimeout(autosaveTimer.current); };
  }, [form, step, nameManual, basisMaterialId, view, programMode, outlinesByMaterialId]);

  function changeStep(nextStep: number) {
    setStep(nextStep);
    onStepChange?.(nextStep);
  }

  async function go(nextStep: number) {
    setActionError("");
    if (autosaveTimer.current !== null) window.clearTimeout(autosaveTimer.current);
    try {
      await controller.queueSave(command(nextStep));
      changeStep(nextStep);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось сохранить черновик");
    }
  }

  async function activate() {
    setActionError("");
    try {
      await controller.queueSave(command(4));
      onActivated?.(await controller.activate());
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось создать проект");
    }
  }

  async function addFile(file: File) {
    const result = await materials.upload(
      file,
      basisMaterialId ? "additional" : "main",
      ["study_source"],
    );
    if (result && !basisMaterialId) setBasisMaterialId(result.id);
  }

  async function addLink() {
    const url = linkUrl.trim();
    if (/\.pdf(?:$|[?#])/i.test(url)) {
      setActionError("Ссылки на PDF пока не загружаются. Скачайте файл и добавьте его через «Загрузить файл».");
      return;
    }
    const result = await materials.createExternal({
      kind: /(?:^|\.)youtube\.com|youtu\.be/i.test(url) ? "youtube" : "url",
      url,
      source_role: basisMaterialId ? "additional" : "main",
      purposes: ["study_source"],
    });
    if (result && !basisMaterialId) setBasisMaterialId(result.id);
    if (result) {
      setLinkUrl("");
      setLinkOpen(false);
    }
  }

  async function attachSuggestion(item: MaterialSuggestion) {
    if (!projectId) return;
    setAttachingId(item.material_id);
    setActionError("");
    try {
      await attachLibraryMaterial(item.material_id, {
        project_id: projectId,
        source_role: basisMaterialId ? "additional" : "main",
        purposes: ["study_source"],
      });
      if (!basisMaterialId) setBasisMaterialId(item.material_id);
      await materials.refresh();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось подключить материал");
    } finally {
      setAttachingId(null);
    }
  }

  async function chooseBasis(materialId: string) {
    setBasisMaterialId(materialId);
    const demoted = materials.materials.filter((item) => item.id !== materialId && item.source_role === "main");
    for (const item of demoted) await materials.update(item.id, { source_role: "additional" });
    await materials.update(materialId, { source_role: "main" });
  }

  const updateOutline = useCallback((materialId: string, next: OutlineDraftState | null) => {
    setOutlinesByMaterialId((current) => {
      const updated = { ...current };
      if (next) updated[materialId] = next; else delete updated[materialId];
      return updated;
    });
  }, []);

  function executeProgramCommand(
    request: (revision: number) => Promise<import("../api/projects").ProgramChangeResult>,
  ) {
    return controller.enqueueProgramCommand((current) => request(current.program.revision));
  }

  const basisMaterials = basis ? [basis] : [];
  /* Импорт принимает оглавления всех источников: основа первой, остальные по
     приоритету. Проверку оглавления на шаге материалов проходит только основа. */
  const outlineMaterials = useMemo(() => {
    const withOutline = materials.materials.filter((item) => item.outline.length > 0 || outlinesByMaterialId[item.id]?.items.length);
    return [...withOutline].sort((a, b) => Number(b.id === basis?.id) - Number(a.id === basis?.id) || a.priority - b.priority);
  }, [basis?.id, materials.materials, outlinesByMaterialId]);
  const currentNodes = useMemo(
    () => (controller.detail?.program.nodes ?? []).filter((node) => node.is_in_current_program && !node.is_archived),
    [controller.detail?.program.nodes],
  );
  const counts = {
    sections: currentNodes.filter((node) => node.node_type === "section").length,
    topics: currentNodes.filter((node) => node.node_type === "topic").length,
    subpoints: currentNodes.filter((node) => node.node_type === "subpoint").length,
  };
  const studyNodes = currentNodes.filter((node) => node.node_type !== "section");
  const outlineStudyCount = studyNodes.filter((node) => node.basis_kind === "outline").length;
  const withoutSourceCount = studyNodes.length - outlineStudyCount;
  const flat = useMemo(() => {
    try { return flattenProgramTree(buildProgramTree(currentNodes)); }
    catch { return []; }
  }, [currentNodes]);
  const basisOutline = basis ? outlinesByMaterialId[basis.id] : undefined;
  const basisHasOutline = Boolean(basis?.outline.length || basisOutline?.items.length);
  const basisHasNoOutline = Boolean(
    basis
    && !basisHasOutline
    && (basis.status !== "ready" || basisOutline?.source === "none" || (basis.page_count ?? 0) === 0),
  );
  const busy = controller.status === "saving" || materials.busy;
  const errorBanner = actionError || controller.error?.message || materials.error;
  const mode: ProgramMode = programMode ?? "manual";

  if (controller.status === "loading" || (controller.status === "saving" && !controller.detail)) {
    return <LoadingState label="Загружаем черновик свободного изучения" placement="page" />;
  }

  return (
    <div className={`wizard-flow free-study-wizard${step === 3 ? " is-program-editor" : ""}${step === 1 ? " is-goal" : ""}`}>
      <PageHead title={STEP_TITLES[step - 1] ?? STEP_TITLES[0]} />
      {controller.conflict && <Card><h2>Черновик изменился в другой вкладке</h2><Button onClick={() => void controller.reload()}>Загрузить серверную версию</Button></Card>}

      {step === 1 && (
        <section className="free-study-step">
          <p className="wizard-step-intro">Цель может быть широкой — например, пройти базовый курс по экономике, — или узкой: разобраться, как работают свёрточные и генеративные нейросети.</p>
          <div className="free-study-form">
            <Field label="Цель" required>
              <textarea autoFocus rows={5} value={form.goal} onChange={(event) => setForm((current) => ({ ...current, goal: event.target.value }))} />
            </Field>
            <Field label="Название проекта" required hint="Мы подставим предмет или первую фразу цели. Название можно изменить.">
              <input value={form.name} maxLength={120} onChange={(event) => { setNameManual(true); setForm((current) => ({ ...current, name: event.target.value })); }} />
            </Field>
            <Field label="Предмет или область" hint="Необязательно. Можно выбрать готовый предмет или ввести новый.">
              <input aria-label="Предмет или область" list="free-study-subjects" value={form.subject} onChange={(event) => setForm((current) => ({ ...current, subject: event.target.value }))} />
              <datalist id="free-study-subjects">{librarySubjects.map((subject) => <option key={subject} value={subject} />)}</datalist>
            </Field>
            <Field label="С чего начинаете" hint="ИИ учтёт это, когда предложит программу: с нуля — больше основ, повторение — меньше.">
              <SegmentedTabs label="С чего начинаете" value={form.startingLevel} onChange={(value) => setForm((current) => ({ ...current, startingLevel: value }))} tabs={STARTING_LEVELS} />
            </Field>
            <Field label="Что особенно важно" hint="Необязательно"><textarea rows={3} value={form.important} onChange={(event) => setForm((current) => ({ ...current, important: event.target.value }))} /></Field>
            <Field label="Что можно не изучать" hint="Необязательно"><textarea rows={3} value={form.excluded} onChange={(event) => setForm((current) => ({ ...current, excluded: event.target.value }))} /></Field>
            <Field label="Желаемый срок" hint="Необязательный ориентир: календарь и прогноз пока не создаются."><input type="date" value={form.deadline} onChange={(event) => setForm((current) => ({ ...current, deadline: event.target.value }))} /></Field>
          </div>
          {errorBanner && <p className="inline-error" role="alert">{errorBanner}</p>}
          <div className="wizard-actions is-single"><Button disabled={busy || !form.goal.trim() || !form.name.trim()} onClick={() => void go(2)}>К материалам</Button></div>
        </section>
      )}

      {step === 2 && (
        <section className="free-study-step is-materials">
          <div className="wizard-step-intro free-study-intro">
            <p>Материалы необязательны: без них ИИ составит программу по цели и подскажет, что искать. С материалами программа опирается на их оглавления.</p>
            <p>Пока вы можете добавить материалы из Библиотеки. Если их нет, то после создания проекта вы сможете найти материалы в интернете в соответствующем разделе.</p>
          </div>

          <section className="free-study-suggestions" aria-label="Подходит к вашей цели">
            <h2>Подходит к вашей цели</h2>
            {libraryMaterialCount === 0 && <p className="free-study-suggestions-note">В Библиотеке пока ничего нет. Загрузите файл, добавьте ссылку — или продолжайте без материалов.</p>}
            {libraryMaterialCount !== 0 && !suggestions && !suggestionsError && <p className="free-study-suggestions-note" role="status">Ищем в Библиотеке материалы под вашу цель…</p>}
            {suggestionsError && <p className="free-study-suggestions-note is-error" role="alert">{suggestionsError} <Button variant="ghost" onClick={() => setSuggestionsKey((key) => key + 1)}>Повторить</Button></p>}
            {suggestions && suggestions.items.length === 0 && libraryMaterialCount !== 0 && (
              <p className="free-study-suggestions-note">В Библиотеке не нашлось подходящего под цель. Загрузите своё или продолжайте без материалов.</p>
            )}
            {suggestions && suggestions.items.length > 0 && (
              <MaterialSuggestionList items={suggestions.items} busyId={attachingId} onAttach={(item) => void attachSuggestion(item)} />
            )}
            {suggestions?.words_only && suggestions.items.length > 0 && <p className="free-study-suggestions-note">Подбор шёл по словам: активного поискового индекса нет.</p>}
          </section>

          <input ref={fileInput} className="materials-file-input" type="file" tabIndex={-1} aria-hidden="true" accept=".pdf,.docx,.txt,.md,.jpg,.jpeg,.png,.mp3,.wav,.m4a,.ogg,.flac" onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void addFile(file); }} />
          <div className="free-study-material-actions">
            <Button variant="secondary" onClick={() => setLibraryOpen(true)}><LibraryBig size={15} />Вся Библиотека</Button>
            <Button variant="secondary" disabled={materials.busy} onClick={() => fileInput.current?.click()}><UploadCloud size={15} />Загрузить файл</Button>
            <Button variant="secondary" onClick={() => setLinkOpen((open) => !open)}><Link2 size={15} />Добавить ссылку</Button>
          </div>
          {materials.uploadStatus && <ProjectFileUploadStatus {...materials.uploadStatus} />}
          {linkOpen && <Card className="free-study-link-card"><Field label="Веб-страница или YouTube" hint="Прямая ссылка на PDF пока не поддерживается"><input type="url" value={linkUrl} onChange={(event) => setLinkUrl(event.target.value)} placeholder="https://example.org/article" /></Field><Button disabled={busy || !linkUrl.trim()} onClick={() => void addLink()}>Добавить</Button></Card>}

          {materials.materials.length > 0 && <h2 className="free-study-section-title">В проекте</h2>}
          {(materials.loading || materials.materials.length > 0) && <div className="textbook-source-list">
            {materials.loading && <LoadingState label="Загружаем материалы" />}
            {materials.materials.map((material) => (
              <Card className={`textbook-source-card free-study-source${basisMaterialId === material.id ? " is-basis" : ""}`} key={material.id}>
                <div className="textbook-source-main">
                  <BookOpen className="textbook-source-icon" size={16} aria-hidden="true" />
                  <span className="textbook-source-copy"><b>{material.display_name}</b><small>{materialStatus(material)}</small></span>
                  {basisMaterialId === material.id ? <StatusBadge tone="success">Основа программы</StatusBadge> : <Button variant="ghost" disabled={busy} onClick={() => void chooseBasis(material.id)}>Сделать основой</Button>}
                  <IconButton label={`Убрать «${material.display_name}»`} disabled={busy} onClick={() => void materials.detach(material.id)}><Trash2 size={15} /></IconButton>
                </div>
                <TextbookSourceCard material={material} busy={busy} onSave={materials.update} />
              </Card>
            ))}
          </div>}

          {basisHasNoOutline && <Card className="free-study-material-note">Материал добавлен, но оглавление пока недоступно. Можно продолжить: ИИ составит программу по цели, а материал будет ждать в проекте.</Card>}
          {basis && (basis.outline.length > 0 || basis.status === "ready") && controller.detail && <>
            {basisHasOutline && <p className="free-study-outline-lead">Оглавление найдено. Проверьте его — на следующем шаге из него можно собрать программу.</p>}
            <TextbookOutlineReview projectId={controller.detail.project.id} materials={basisMaterials} values={outlinesByMaterialId} onChange={updateOutline} allowModel={false} />
          </>}

          {errorBanner && <p className="inline-error" role="alert">{errorBanner}</p>}
          <div className="wizard-actions"><Button variant="ghost" onClick={() => void go(1)}>Назад</Button><span className="wizard-actions-spacer" /><Button disabled={busy} onClick={() => void go(3)}>К программе</Button></div>
        </section>
      )}

      {step === 3 && (
        <section className="textbook-builder">
          {errorBanner && <p className="inline-error" role="alert">{errorBanner}</p>}
          {controller.detail && <TextbookProgramEditor
            projectId={controller.detail.project.id}
            projectName={form.name || "Программа"}
            program={controller.detail.program}
            latestUndoableAction={controller.detail.latest_undoable_action}
            materials={outlineMaterials}
            outlinesByMaterialId={outlinesByMaterialId}
            wizard
            busy={busy}
            view={view}
            onViewChange={setView}
            execute={executeProgramCommand}
            onUndo={async () => { await controller.undo(); }}
            mode={mode}
            aiContent={<div className="textbook-program-ai-layout">
              <ProgramChatWorkspace
                projectId={controller.detail.project.id}
                program={controller.detail.program}
                execute={executeProgramCommand}
                onMessagesChange={setAiChatMessages}
                variant="free"
                outlineSourceName={outlineMaterials[0]?.display_name}
                onSwitchToManual={() => setProgramMode("manual")}
              />
              <ProgramTreePreview
                program={controller.detail.program}
                pendingOperations={lastPendingDiffValue?.operations}
                pendingStates={lastPendingDiffValue?.operation_states}
              />
            </div>}
            renderHeader={(actions) => <header className="textbook-builder-head">
              <Button variant="ghost" disabled={!actions.canUndo || actions.busy} onClick={() => void actions.undo()}><Undo2 size={15} />Отменить</Button>
              <SegmentedTabs label="Режим составления программы" value={mode} onChange={setProgramMode} tabs={[{ value: "manual", label: "Вручную" }, { value: "ai", label: "С ИИ" }]} />
              <Button variant="secondary" disabled={actions.busy || outlineMaterials.length === 0} onClick={actions.openImport}>Импортировать оглавление</Button>
              <Button variant="ghost" disabled={actions.busy || !actions.hasNodes} onClick={actions.openRemoveAll}><Trash2 size={15} />Удалить все</Button>
              <Button className="textbook-builder-confirm" disabled={actions.busy} onClick={() => void go(4)}>{actions.hasNodes ? "К проверке" : "Продолжить без программы"}</Button>
            </header>}
          />}
        </section>
      )}

      {step === 4 && (
        <section className="free-study-step">
          <p className="wizard-step-intro">Проверьте данные перед созданием проекта.</p>
          <section className="wizard-review-summary">
            <div className="wizard-review-hero"><h2><span>Свободное изучение</span><strong>{form.name}</strong></h2><p className="wizard-review-lead">{form.goal}</p></div>
            <dl className="wizard-review-facts">
              <div><dt>Предмет</dt><dd>{form.subject.trim() || "Предмет не указан"}</dd></div>
              <div><dt>С чего начинаете</dt><dd>{STARTING_LEVELS.find((item) => item.value === form.startingLevel)?.label}</dd></div>
              {form.important.trim() && <div><dt>Что особенно важно</dt><dd>{form.important}</dd></div>}
              {form.excluded.trim() && <div><dt>Что можно не изучать</dt><dd>{form.excluded}</dd></div>}
              <div><dt>Срок</dt><dd>{form.deadline ? new Date(`${form.deadline}T00:00:00`).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" }) : "Без срока"}</dd></div>
            </dl>
          </section>
          <Card className="textbook-summary-card"><h3>Материалы</h3>{materials.materials.map((material) => <div key={material.id}><span>{basisMaterialId === material.id ? "Основа" : "Доп."}</span><b>{material.display_name}</b><small>{materialStatus(material)}</small></div>)}{materials.materials.length === 0 && <p>Пока без материалов — для свободного изучения это нормально. Их можно добавить в любой момент.</p>}</Card>
          <Card className="textbook-summary-card"><h3>Программа</h3><dl className="textbook-summary-metrics"><div className="is-sections"><dt>Разделы</dt><dd>{counts.sections}</dd></div><div className="is-topics"><dt>Темы</dt><dd>{counts.topics}</dd></div><div className="is-outside"><dt>Подпункты</dt><dd>{counts.subpoints}</dd></div></dl><ProgramReviewList nodes={flat} />{flat.length === 0 && <p>Программа пока пуста. После создания её можно составить в разделе «Программа» — вручную или с ИИ.</p>}</Card>
          {studyNodes.length > 0 && (
            <Card className="textbook-summary-card free-study-material-plan">
              <h3>Материал к темам</h3>
              {outlineStudyCount > 0 && <p>По оглавлению — {outlineStudyCount}: для них сразу можно собрать урок из страниц источника.</p>}
              {withoutSourceCount > 0 && <p>Без источника — {withoutSourceCount}. Это нормально: после создания раздел «Программа» подскажет, что для них есть в Библиотеке и что искать.</p>}
            </Card>
          )}
          <Card className="textbook-summary-card"><h3>После создания</h3><p>Откроется раздел «Программа». Цель, срок и материалы можно изменить позже.</p></Card>
          {errorBanner && <p className="inline-error" role="alert">{errorBanner}</p>}
          <div className="wizard-actions"><Button variant="ghost" onClick={() => void go(3)}>Назад</Button><span className="wizard-actions-spacer" /><Button disabled={busy || !form.goal.trim() || !form.name.trim()} onClick={() => void activate()}>Создать проект</Button></div>
        </section>
      )}

      {controller.detail && <LibraryMaterialPickerDialog
        open={libraryOpen}
        projectId={controller.detail.project.id}
        title="Выбрать материалы из Библиотеки"
        purpose="study_source"
        multiple
        existingStudySourceCount={materials.materials.length}
        studyRoleMode="first-main"
        recommendedSubject={form.subject}
        onOpenChange={setLibraryOpen}
        onAttached={async (attached) => {
          await materials.refresh();
          if (!basisMaterialId && attached[0]) setBasisMaterialId(attached[0].id);
        }}
        onCreateNew={() => { setLibraryOpen(false); window.setTimeout(() => fileInput.current?.click(), 0); }}
      />}
    </div>
  );
}
