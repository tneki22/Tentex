import { useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";
import { useNavigate } from "react-router";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, BookOpen, Copy, Filter, MessageSquare, Pencil, Plus, Search, Trash2, Undo2, UploadCloud, WandSparkles } from "lucide-react";
import {
  createProgramNode,
  moveProgramNode,
  removeProgramNode,
  updateProgramNode,
  type GoalPassportWrite,
  type GoalScope,
  type ModuleKey,
  type NodeType,
  type ProjectDetail,
  type StudyFormat,
  type TargetOutcome,
} from "../api/projects";
import type { WizardDraftController } from "../hooks/useWizardDraft";
import { Button, Card, ContextMenu, Disclosure, Field, IconButton, LoadingState, PageHead, SegmentedTabs, StatusBadge, Switch } from "../components/ui";
import type { ContextMenuItem } from "../components/ui";
import { QualityBadge, TaskRow } from "../components/domain";
import { buildProgramTree, filterProgramTree, flattenProgramTree, type ProgramTreeNode } from "./programTree";
import { useProjectMaterials } from "../hooks/useProjectMaterials";

type ProgramView = "tree" | "text" | "questions";

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
  sessionMinutes: string;
  studyFormat: StudyFormat;
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
  sessionMinutes: "45",
  studyFormat: "theory_and_practice",
};
const nullable = (value: string) => value.trim() || null;
const positive = (value: string) => Number(value) > 0 ? Number(value) : null;

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
  const [view, setView] = useState<ProgramView>("tree");
  const [query, setQuery] = useState("");
  const [missingOnly, setMissingOnly] = useState(false);
  const [selectedId, setSelectedId] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [actionError, setActionError] = useState("");
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
    setView((detail.draft.state.program_view as ProgramView) ?? "tree");
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
      sessionMinutes: goal?.session_minutes ? String(goal.session_minutes) : "45",
      studyFormat: goal?.study_format ?? "theory_and_practice",
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
      study_format: form.studyFormat,
      minutes_per_day: positive(form.minutesPerDay),
      days_per_week: positive(form.daysPerWeek),
      session_minutes: positive(form.sessionMinutes),
      exam_format: null,
      expected_item_count: null,
      instructor_requirements: null,
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
        enabled_modules: ["plan", "lessons", "cards", "repetitions"] as ModuleKey[],
      },
      goal_passport: passport(),
      state: { program_view: view, selected_node_id: controller.detail?.program.nodes[0]?.id ?? null },
    };
  }

  const nodes = (controller.detail?.program.nodes ?? []).filter((node) => node.is_in_current_program && !node.is_archived);
  let tree = [] as ReturnType<typeof buildProgramTree>;
  let flat = [] as ReturnType<typeof flattenProgramTree>;
  try {
    tree = buildProgramTree(nodes);
    flat = flattenProgramTree(tree);
  } catch { /* The draft error state remains available instead of crashing the editor. */ }
  const visibleFlat = flattenProgramTree(filterProgramTree(tree, query)).filter((node) => !missingOnly || node.needs_material);
  const selected = flat.find((node) => node.id === selectedId) ?? flat[0] ?? null;
  const selectedSiblings = selected ? flat.filter((node) => node.parent_id === selected.parent_id) : [];
  const selectedIndex = selected ? selectedSiblings.findIndex((node) => node.id === selected.id) : -1;
  const sectionCount = nodes.filter((node) => node.node_type === "section").length;
  const topicCount = nodes.filter((node) => node.node_type === "topic").length;
  const subpointCount = nodes.filter((node) => node.node_type === "subpoint").length;
  const readyMaterialCount = materials.materials.filter((material) => material.status === "ready").length;
  const scanPageCount = materials.materials.reduce((sum, material) => sum + material.scan_page_count, 0);
  const reviewPageCount = materials.materials.reduce((sum, material) => sum + material.ocr_low_page_count, 0);

  useEffect(() => {
    if (selected && selected.id !== selectedId) setSelectedId(selected.id);
  }, [selected, selectedId]);

  useEffect(() => {
    const key = controller.detail ? `${controller.detail.project.id}:${controller.hydrationVersion}` : null;
    if (!controller.detail || initializedKey.current !== key || controller.conflict) return;
    const timer = window.setTimeout(() => {
      void controller.queueSave(command(step)).catch(() => undefined);
    }, 400);
    return () => window.clearTimeout(timer);
  }, [form, step, view]);

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

  async function createNode(nodeType: NodeType, parentId: string | null, position: number | null = null) {
    if (!controller.detail) return;
    setActionError("");
    try {
      const result = await controller.enqueueProgramCommand((current) => createProgramNode(current.project.id, {
        expected_program_revision: current.program.revision,
        parent_id: parentId,
        position,
        node_type: nodeType,
        exam_kind: null,
        title: nodeType === "section" ? "Новый раздел" : nodeType === "topic" ? "Новая тема" : "Новый подпункт",
        goal_role: "target",
      }));
      if (result.changed_node) {
        setSelectedId(result.changed_node.id);
        setEditingId(result.changed_node.id);
        setEditingTitle(result.changed_node.title);
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось добавить узел");
    }
  }

  async function renameNode(node: ProgramTreeNode) {
    if (!editingTitle.trim() || editingTitle.trim() === node.title) {
      setEditingId(null);
      return;
    }
    setActionError("");
    try {
      await controller.enqueueProgramCommand((current) => updateProgramNode(current.project.id, node.id, {
        expected_program_revision: current.program.revision,
        title: editingTitle.trim(),
      }));
      setEditingId(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось переименовать узел");
    }
  }

  async function moveNode(node: ProgramTreeNode, position: number, parentId = node.parent_id) {
    setActionError("");
    try {
      await controller.enqueueProgramCommand((current) => moveProgramNode(current.project.id, node.id, {
        expected_program_revision: current.program.revision,
        parent_id: parentId,
        position,
      }));
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось переместить узел");
    }
  }

  async function removeNode(node: ProgramTreeNode) {
    setActionError("");
    try {
      await controller.enqueueProgramCommand((current) => removeProgramNode(current.project.id, node.id, current.program.revision));
      setSelectedId("");
      setEditingId(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось убрать узел из программы");
    }
  }

  function startRename(node: ProgramTreeNode) {
    setSelectedId(node.id);
    setEditingId(node.id);
    setEditingTitle(node.title);
  }

  async function changeNodeType(node: ProgramTreeNode, nodeType: NodeType) {
    if (node.node_type === nodeType) return;
    setActionError("");
    try {
      await controller.enqueueProgramCommand((current) => updateProgramNode(current.project.id, node.id, {
        expected_program_revision: current.program.revision,
        node_type: nodeType,
        exam_kind: null,
      }));
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось изменить тип узла");
    }
  }

  async function duplicateNode(node: ProgramTreeNode) {
    const siblings = flat.filter((item) => item.parent_id === node.parent_id);
    const index = siblings.findIndex((item) => item.id === node.id);
    setActionError("");
    try {
      const result = await controller.enqueueProgramCommand((current) => createProgramNode(current.project.id, {
        expected_program_revision: current.program.revision,
        parent_id: node.parent_id,
        position: index + 1,
        node_type: node.node_type,
        exam_kind: null,
        title: `${node.title} — копия`,
        section_purpose: node.section_purpose,
        goal_role: node.goal_role,
        target_level: node.target_level,
        needs_material: node.needs_material,
      }));
      if (result.changed_node) setSelectedId(result.changed_node.id);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось продублировать узел");
    }
  }

  function subtreeHeight(nodeId: string): number {
    const children = flat.filter((node) => node.parent_id === nodeId);
    return children.length ? 1 + Math.max(...children.map((child) => subtreeHeight(child.id))) : 1;
  }

  const previousSibling = selectedIndex > 0 ? selectedSiblings[selectedIndex - 1] : null;
  const canIndent = Boolean(selected && previousSibling && previousSibling.depth + subtreeHeight(selected.id) <= 4);
  const selectedParent = selected?.parent_id ? flat.find((node) => node.id === selected.parent_id) ?? null : null;

  function childType(node: ProgramTreeNode): NodeType {
    return node.node_type === "section" ? "topic" : "subpoint";
  }

  function nodeMenuItems(node: ProgramTreeNode): ContextMenuItem[] {
    const siblings = flat.filter((item) => item.parent_id === node.parent_id);
    const index = siblings.findIndex((item) => item.id === node.id);
    const previous = index > 0 ? siblings[index - 1] : null;
    const parent = node.parent_id ? flat.find((item) => item.id === node.parent_id) ?? null : null;
    const canNest = Boolean(previous && previous.depth + subtreeHeight(node.id) <= 4);
    return [
      {
        label: "Добавить внутрь",
        icon: <Plus size={14} />,
        items: (["section", "topic", "subpoint"] as NodeType[]).map((nodeType) => ({
          label: nodeType === "section" ? "Раздел" : nodeType === "topic" ? "Тему" : "Подпункт",
          disabled: busy || node.depth >= 4,
          onSelect: () => void createNode(nodeType, node.id),
        })),
      },
      { label: "Добавить перед", icon: <ArrowUp size={14} />, disabled: busy, onSelect: () => void createNode(node.node_type, node.parent_id, index) },
      { label: "Добавить после", icon: <ArrowDown size={14} />, disabled: busy, onSelect: () => void createNode(node.node_type, node.parent_id, index + 1) },
      { label: "Переименовать", icon: <Pencil size={14} />, disabled: busy, onSelect: () => startRename(node) },
      { label: "Продублировать", icon: <Copy size={14} />, disabled: busy, onSelect: () => void duplicateNode(node) },
      {
        label: "Тип узла",
        items: (["section", "topic", "subpoint"] as NodeType[]).map((nodeType) => ({
          label: nodeType === "section" ? "Раздел" : nodeType === "topic" ? "Тема" : "Подпункт",
          disabled: busy || node.node_type === nodeType,
          onSelect: () => void changeNodeType(node, nodeType),
        })),
      },
      { label: "Поднять", icon: <ArrowUp size={14} />, disabled: busy || index <= 0, onSelect: () => void moveNode(node, index - 1) },
      { label: "Опустить", icon: <ArrowDown size={14} />, disabled: busy || index < 0 || index === siblings.length - 1, onSelect: () => void moveNode(node, index + 1) },
      { label: "Уменьшить вложенность", icon: <ArrowLeft size={14} />, disabled: busy || !parent, onSelect: () => parent && void moveNode(node, parent.sort_order + 1, parent.parent_id) },
      { label: "Увеличить вложенность", icon: <ArrowRight size={14} />, disabled: busy || !canNest || !previous, onSelect: () => previous && void moveNode(node, previous.children.length, previous.id) },
      { label: "Убрать из программы", icon: <Trash2 size={14} />, destructive: true, disabled: busy, onSelect: () => void removeNode(node) },
    ];
  }

  async function activate() {
    setActionError("");
    try {
      await controller.queueSave(command(5));
      const project = await controller.activate();
      onActivated?.(project);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось создать проект");
    }
  }

  if (controller.status === "loading" || (controller.status === "saving" && !controller.detail)) return <LoadingState label="Загружаем учебниковый черновик" />;
  const busy = controller.status === "saving";

  return (
    <div className="wizard-flow">
      {step !== 4 && <PageHead title={step === 1 ? "Добавьте материалы, на которых строить программу" : step === 2 ? "Чему именно вы хотите научиться?" : step === 3 ? "Проверка" : "Итог"} />}
      {(actionError || controller.error) && <p className="inline-error" role="alert">{actionError || controller.error?.message}</p>}
      {controller.conflict && <Card><h2>Черновик изменился в другой вкладке</h2><Button onClick={() => void controller.reload()}>Загрузить серверную версию</Button></Card>}

      {step === 1 && (
        <section className="textbook-step">
          <p className="wizard-step-intro">Добавьте материалы и подготовьте их текст. Tentex сам определит страницы, которым нужен OCR.</p>
          <input ref={materialInput} className="materials-file-input" type="file" multiple tabIndex={-1} aria-hidden="true" accept=".pdf,.docx,.txt,.md,.jpg,.jpeg,.png,.mp3,.wav,.m4a,.ogg,.flac" onChange={(event) => { Array.from(event.target.files ?? []).forEach((file) => void addMaterial(file)); event.target.value = ""; }} />
          <div onDragOver={(event: DragEvent<HTMLDivElement>) => event.preventDefault()} onDrop={(event: DragEvent<HTMLDivElement>) => { event.preventDefault(); Array.from(event.dataTransfer.files).forEach((file) => void addMaterial(file)); }}>
            <Card className="textbook-dropzone">
              <UploadCloud size={24} aria-hidden="true" />
              <span><b>Перетащите учебники, методички, конспекты, статьи или аудио</b><small>PDF, DOCX, TXT, MD, изображения и аудио. До 100 МБ и 500 страниц на файл.</small></span>
              <Button disabled={materials.busy || !controller.detail} variant="secondary" onClick={() => materialInput.current?.click()}>Добавить материал</Button>
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
                  <span className="textbook-source-copy"><b>{material.display_name}</b><small>{material.page_count ?? 1} стр.</small>{material.ocr_low_page_count > 0 && <em><QualityBadge quality="ocr_low" count={material.ocr_low_page_count} /></em>}</span>
                  {material.status !== "ready_to_process" && <StatusBadge tone={material.status === "ready" ? "success" : material.status === "failed" ? "danger" : "neutral"}>{material.status === "ready" ? "Текст готов" : material.status === "failed" ? "Ошибка" : "Подготавливаем"}</StatusBadge>}
                  <div className="textbook-source-actions">
                    {material.status === "ready_to_process" && <Button variant="secondary" disabled={materials.busy} onClick={() => void materials.start(material.id)}>Подготовить текст</Button>}
                    {material.status === "failed" && <Button variant="secondary" disabled={materials.busy} onClick={() => void materials.control(material.id, "retry")}>Повторить</Button>}
                    <IconButton label={`Удалить файл «${material.display_name}»`} disabled={materials.busy} onClick={() => void materials.detach(material.id)}><Trash2 size={15} /></IconButton>
                  </div>
                </div>
                {material.task && material.task.state !== "completed" && <TaskRow task={{ id: material.task.id, kind: "parse", subject: material.display_name, unit: "страниц", done: material.task.done, total: material.task.total, etaMinutes: null, state: material.task.state, error: material.task.error ?? undefined }} onPause={() => void materials.control(material.id, "pause")} onResume={() => void materials.control(material.id, "resume")} onRetry={() => void materials.control(material.id, "retry")} />}
                <Disclosure summary="Роль и инструкция">
                  <div className="textbook-source-settings">
                    <Field label="Роль источника"><select value={material.source_role} onChange={(event) => void materials.update(material.id, { source_role: event.target.value as "main" | "additional" | "reference" })}><option value="main">Основной</option><option value="additional">Дополнительный</option><option value="reference">Справочный</option></select></Field>
                    <Field label="Приоритет"><input type="number" min="0" value={material.priority} onChange={(event) => void materials.update(material.id, { priority: Number(event.target.value) })} /></Field>
                    <Field label="Как использовать"><textarea value={material.instruction ?? ""} onChange={(event) => void materials.update(material.id, { instruction: event.target.value })} placeholder="Например, отсюда брать определения" /></Field>
                  </div>
                </Disclosure>
              </Card>
            ))}
          </div>

          <Card className="textbook-analysis-card">
            <div className="textbook-analysis-head"><WandSparkles size={18} aria-hidden="true" /><span><b>Подготовка материалов</b><small>Кнопка «Подготовить текст» извлечёт текст со всех страниц. Для сканов автоматически используется быстрый локальный OCR.</small></span></div>
            <table className="textbook-analysis-table">
              <thead><tr><th scope="col">Текст готов</th><th scope="col">Всего файлов</th><th scope="col">Страницы-сканы</th><th scope="col">Нужно проверить</th></tr></thead>
              <tbody><tr><td>{readyMaterialCount}</td><td>{materials.materials.length}</td><td>{scanPageCount}</td><td>{reviewPageCount}</td></tr></tbody>
            </table>
          </Card>

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
                  <Field label="Минут на занятие" hint="Необязательно"><input type="number" min="10" step="5" value={form.sessionMinutes} onChange={(event) => setForm((current) => ({ ...current, sessionMinutes: event.target.value }))} /></Field>
                </div>
                <SegmentedTabs label="Формат занятий" value={form.studyFormat} onChange={(studyFormat) => setForm((current) => ({ ...current, studyFormat: studyFormat as StudyFormat }))} tabs={[{ value: "theory", label: "Теория" }, { value: "theory_and_practice", label: "Смешанный" }, { value: "practice", label: "Практика" }]} />
                <div className="textbook-source-summary"><b>Источники</b>{materials.materials.map((material, index) => <span key={material.id}><i>{index + 1}</i>{material.display_name}<small>{material.status === "ready" ? "текст готов" : "текст не подготовлен"}</small></span>)}<Button variant="ghost" onClick={() => void go(1)}>К источникам</Button></div>
              </div>
            </Card>
          </div>
          <div className="wizard-actions"><Button variant="ghost" onClick={() => void go(1)}>Назад</Button><Button disabled={busy || !form.name.trim() || !form.subject.trim() || (form.scope === "goal" && !form.goal.trim())} onClick={() => void go(3)}>Продолжить</Button></div>
        </section>
      )}

      {step === 3 && (
        <section className="textbook-step textbook-preflight">
          <p className="wizard-step-intro">Проверьте материалы и профиль перед составлением программы.</p>
          <Card className="textbook-preflight-card">
            <div className="textbook-preflight-summary"><b>{form.name || form.subject || "Учебниковый черновик"}</b><p><strong>Ваша цель:</strong> {form.scope === "goal" ? form.goal || "не указана" : "изучить весь основной материал."}</p><p><strong>Предмет:</strong> {form.subject || "не указан"}</p></div>
            <div className="textbook-preflight-list">
              <section><h2>Источники</h2>{materials.materials.map((material, index) => <p key={material.id}><span>{index + 1}</span>{material.display_name}<small>{material.source_role === "main" ? "основной" : material.source_role === "additional" ? "дополнительный" : "справочный"}</small></p>)}</section>
              <section className="is-processing-copy"><h2>Подготовка материалов</h2><p>Текст готов для {readyMaterialCount} из {materials.materials.length} файлов. Всё происходит на этом компьютере.</p></section>
              <section className="is-processing-copy"><h2>Составление программы</h2><p>На следующем шаге вы сможете составить программу вручную.</p></section>
            </div>
            <Switch checked={false} onCheckedChange={() => undefined} disabled label="Составить программу автоматически" hint="Пока недоступно" />
          </Card>
          <div className="wizard-actions"><Button variant="ghost" onClick={() => void go(2)}>Назад</Button><Button disabled={busy} onClick={() => void go(4)}>Перейти к программе</Button></div>
        </section>
      )}

      {step === 4 && (
        <section className="textbook-builder">
          <header className="textbook-builder-head">
            <Button variant="ghost" onClick={() => void go(3)}><ArrowLeft size={15} />К проверке</Button>
            <span><b>{form.name || form.subject || "Учебниковый черновик"}</b><small>Изменения сохраняются автоматически</small></span>
            <StatusBadge>Ручной режим</StatusBadge>
            <Button variant="ghost" disabled={!controller.detail?.latest_undoable_action || busy} onClick={() => void controller.undo()}><Undo2 size={15} />Отменить</Button>
            <Button disabled={busy} onClick={() => void go(5)}>{nodes.length === 0 ? "Продолжить без программы" : "Утвердить программу"}</Button>
          </header>

          <div className="textbook-builder-grid">
            <div className="textbook-program-panel">
              <div className="textbook-program-toolbar">
                <SegmentedTabs label="Представление программы" value={view} onChange={setView} tabs={[{ value: "tree", label: "Дерево" }, { value: "text", label: "Текст" }, { value: "questions", label: "Вопросы" }]} />
                <label className="textbook-search"><Search size={15} aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти тему" aria-label="Найти тему" /></label>
                <Button variant="ghost" aria-pressed={missingOnly} onClick={() => setMissingOnly((current) => !current)}><Filter size={15} />Нужен материал</Button>
              </div>

              <div className="textbook-manual-toolbar" aria-label="Ручные действия с узлом программы">
                <div className="textbook-add-actions">
                  <Button disabled={busy} onClick={() => void createNode("section", null)}><Plus size={15} />Добавить раздел</Button>
                  <Button variant="secondary" disabled={busy || !selected || selected.depth >= 4} onClick={() => selected && void createNode(childType(selected), selected.id)}><Plus size={15} />{selected ? selected.node_type === "section" ? "Добавить тему" : "Добавить подпункт" : "Добавить внутрь"}</Button>
                  <Button variant="ghost" disabled={busy || !selected} onClick={() => selected && void createNode(selected.node_type, selected.parent_id, selectedIndex + 1)}>Добавить рядом</Button>
                </div>
                <span>Выбрано: <b>{selected?.title ?? "узел не выбран"}</b></span>
                {selected && <label className="textbook-selected-type"><span>Тип</span><select value={selected.node_type} disabled={busy} onChange={(event) => void changeNodeType(selected, event.target.value as NodeType)}><option value="section">Раздел</option><option value="topic">Тема</option><option value="subpoint">Подпункт</option></select></label>}
                <div className="textbook-node-actions">
                  <IconButton label="Поднять узел" disabled={busy || selectedIndex <= 0} onClick={() => selected && void moveNode(selected, selectedIndex - 1)}><ArrowUp size={15} /></IconButton>
                  <IconButton label="Опустить узел" disabled={busy || selectedIndex < 0 || selectedIndex === selectedSiblings.length - 1} onClick={() => selected && void moveNode(selected, selectedIndex + 1)}><ArrowDown size={15} /></IconButton>
                  <IconButton label="Уменьшить вложенность" disabled={busy || !selectedParent} onClick={() => selected && selectedParent && void moveNode(selected, selectedParent.sort_order + 1, selectedParent.parent_id)}><ArrowLeft size={15} /></IconButton>
                  <IconButton label="Увеличить вложенность" disabled={busy || !canIndent || !previousSibling} onClick={() => selected && previousSibling && void moveNode(selected, previousSibling.children.length, previousSibling.id)}><ArrowRight size={15} /></IconButton>
                  <IconButton label="Редактировать формулировку" disabled={busy || !selected} onClick={() => selected && startRename(selected)}><Pencil size={15} /></IconButton>
                  <IconButton label="Продублировать узел" disabled={busy || !selected} onClick={() => selected && void duplicateNode(selected)}><Copy size={15} /></IconButton>
                  <IconButton label="Убрать узел из программы" disabled={busy || !selected} onClick={() => selected && void removeNode(selected)}><Trash2 size={15} /></IconButton>
                </div>
              </div>

              <div className="textbook-program-content" role={view === "tree" ? "tree" : undefined} aria-label={view === "tree" ? "Дерево программы" : undefined}>
                {view === "tree" && visibleFlat.map((node) => (
                  <ContextMenu
                    key={node.id}
                    label={`Действия с «${node.title}»`}
                    items={nodeMenuItems(node)}
                    trigger={
                      <div
                        className={`textbook-program-row ${selected?.id === node.id ? "is-selected" : ""}`.trim()}
                        style={{ paddingInlineStart: `calc(var(--space-4) + ${node.depth - 1} * var(--space-6))` }}
                        role="treeitem"
                        aria-level={node.depth}
                        aria-selected={selected?.id === node.id}
                        tabIndex={selected?.id === node.id ? 0 : -1}
                        onClick={() => setSelectedId(node.id)}
                        onContextMenu={() => setSelectedId(node.id)}
                        onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedId(node.id); } }}
                      >
                        <span className="textbook-program-number">{node.number}</span>
                        <span className="textbook-program-copy">
                          {editingId === node.id
                            ? <input autoFocus value={editingTitle} onClick={(event) => event.stopPropagation()} onChange={(event) => setEditingTitle(event.target.value)} onBlur={() => void renameNode(node)} onKeyDown={(event) => { if (event.key === "Enter") void renameNode(node); if (event.key === "Escape") setEditingId(null); }} aria-label={`Формулировка «${node.title}»`} />
                            : <b>{node.title}</b>}
                          <small>{node.node_type === "section" ? "раздел" : node.node_type === "topic" ? "тема" : "подпункт"}</small>
                        </span>
                        <span className="textbook-program-source"><StatusBadge>{node.needs_material ? "Материал нужен" : "Материал не добавлен"}</StatusBadge><small>Правой кнопкой — действия с узлом</small></span>
                      </div>
                    }
                  />
                ))}
                {view === "tree" && visibleFlat.length === 0 && (missingOnly
                  ? <div className="textbook-editor-empty"><h2>Нет узлов с такой отметкой</h2><p>Отключите фильтр, чтобы вернуться ко всей программе.</p><Button variant="secondary" onClick={() => setMissingOnly(false)}>Показать всю программу</Button></div>
                  : <div className="textbook-editor-empty"><BookOpen size={28} aria-hidden="true" /><h2>Составьте программу вручную</h2><p>Начните с раздела и добавляйте в него темы и подпункты. До четырёх уровней вложенности.</p><div><Button disabled={busy} onClick={() => void createNode("section", null)}><Plus size={15} />Добавить первый раздел</Button><Button variant="secondary" disabled={busy} onClick={() => void createNode("topic", null)}><Plus size={15} />Добавить тему без раздела</Button></div></div>)}
                {view === "text" && <article className="textbook-text-view"><h2>{form.name || form.subject || "Программа"}</h2>{visibleFlat.map((node) => <p key={node.id}><b>{node.number}. {node.title}</b> — {node.node_type === "section" ? "раздел" : node.node_type === "topic" ? "тема" : "подпункт"}.</p>)}</article>}
                {view === "questions" && <ol className="textbook-question-view">{visibleFlat.filter((node) => node.node_type !== "section").map((node) => <li key={node.id}>Как объяснить: «{node.title}»?</li>)}</ol>}
              </div>
            </div>

            <aside className="textbook-assistant" aria-label="Помощник по программе">
              <header><span><MessageSquare size={17} aria-hidden="true" /><b>Помощник по программе</b></span><label>Контекст<select disabled><option>Вся программа</option></select></label></header>
              <div className="textbook-chat-body"><div className="textbook-chat-locked"><WandSparkles size={24} aria-hidden="true" /><b>Помощник пока недоступен</b><p>Сейчас программу можно редактировать вручную</p></div></div>
              <footer><textarea disabled placeholder="Опишите изменение программы" /><Button disabled><ArrowUp size={15} />Отправить</Button><small>Ручное редактирование программы уже доступно.</small></footer>
            </aside>
          </div>
        </section>
      )}

      {step === 5 && (
        <section className="textbook-step textbook-summary">
          <p className="wizard-step-intro">Проверьте данные перед созданием проекта.</p>
          <Card className="textbook-summary-story">
            <h2>{form.name || form.subject || "Учебниковый черновик"}</h2>
            <dl className="textbook-summary-profile">
              <div><dt>Предмет</dt><dd>{form.subject || "Не указан"}</dd></div>
              <div><dt>{form.scope === "goal" ? "Цель" : "Охват"}</dt><dd>{form.scope === "goal" ? form.goal || "Не указана" : "Весь основной материал"}</dd></div>
              <div><dt>Срок</dt><dd>{form.deadline ? new Date(`${form.deadline}T00:00:00`).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" }) : "Не задан"}</dd></div>
              <div><dt>Темп</dt><dd>{form.minutesPerDay || "—"} мин. в день, {form.daysPerWeek || "—"} дн. в неделю</dd></div>
              <div><dt>Занятие</dt><dd>{form.sessionMinutes ? `${form.sessionMinutes} мин.` : "Не задано"}</dd></div>
              <div><dt>Критерий успеха</dt><dd>{form.successCriterion || "Не указан"}</dd></div>
            </dl>
          </Card>

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
            {flat.slice(0, 5).map((node) => <div key={node.id}><span>{node.number}</span><b>{node.title}</b><small>{node.node_type === "section" ? "раздел" : node.node_type === "topic" ? "тема" : "подпункт"}</small></div>)}
            {flat.length === 0 && <p>Программа пока пуста.</p>}
          </Card>

          <Card className="textbook-summary-card"><h3>После создания</h3><p>Проект станет активным, а источники сохранят свои роли и настройки. {nodes.length === 0 ? "Программа останется пустой — её можно составить позже в разделе «Программа»." : "Программа сразу откроется для ручной работы."} Автоматическое составление можно будет запустить позже.</p></Card>
          <div className="wizard-actions"><Button variant="ghost" onClick={() => void go(4)}>Вернуться к программе</Button><Button disabled={busy} onClick={() => void activate()}>Создать проект</Button></div>
        </section>
      )}
    </div>
  );
}
