import { useEffect, useRef, useState } from "react";
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
  type StudyFormat,
  type TargetOutcome,
} from "../api/projects";
import type { WizardDraftController } from "../hooks/useWizardDraft";
import { Button, Card, Field, IconButton, LoadingState, PageHead, SegmentedTabs, StatusBadge, Switch } from "../components/ui";
import { OfflineNotice } from "../components/domain";
import { buildProgramTree, filterProgramTree, flattenProgramTree } from "./programTree";

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
}

export function TextbookWizard({ controller, requestedStep, onStepChange }: TextbookWizardProps) {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<TextbookForm>(EMPTY_FORM);
  const [view, setView] = useState<ProgramView>("tree");
  const [query, setQuery] = useState("");
  const [missingOnly, setMissingOnly] = useState(false);
  const [selectedId, setSelectedId] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [newNodeType, setNewNodeType] = useState<NodeType>("topic");
  const [newParentId, setNewParentId] = useState("");
  const [actionError, setActionError] = useState("");
  const initializedKey = useRef<string | null>(null);

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
  const parentOptions = flat.filter((node) => node.depth < 4);
  const sectionCount = nodes.filter((node) => node.node_type === "section").length;
  const topicCount = nodes.filter((node) => node.node_type === "topic").length;
  const subpointCount = nodes.filter((node) => node.node_type === "subpoint").length;

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

  async function createNode() {
    if (!controller.detail) return;
    setActionError("");
    try {
      const result = await controller.enqueueProgramCommand((current) => createProgramNode(current.project.id, {
        expected_program_revision: current.program.revision,
        parent_id: newParentId || null,
        position: null,
        node_type: newNodeType,
        exam_kind: null,
        title: newNodeType === "section" ? "Новый раздел" : newNodeType === "topic" ? "Новая тема" : "Новый подпункт",
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

  async function renameSelected() {
    if (!selected || !editingTitle.trim() || editingTitle.trim() === selected.title) {
      setEditingId(null);
      return;
    }
    setActionError("");
    try {
      await controller.enqueueProgramCommand((current) => updateProgramNode(current.project.id, selected.id, {
        expected_program_revision: current.program.revision,
        title: editingTitle.trim(),
      }));
      setEditingId(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось переименовать узел");
    }
  }

  async function moveSelected(position: number, parentId = selected?.parent_id ?? null) {
    if (!selected) return;
    setActionError("");
    try {
      await controller.enqueueProgramCommand((current) => moveProgramNode(current.project.id, selected.id, {
        expected_program_revision: current.program.revision,
        parent_id: parentId,
        position,
      }));
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось переместить узел");
    }
  }

  async function removeSelected() {
    if (!selected) return;
    setActionError("");
    try {
      await controller.enqueueProgramCommand((current) => removeProgramNode(current.project.id, selected.id, current.program.revision));
      setSelectedId("");
      setEditingId(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось убрать узел из программы");
    }
  }

  function startRename() {
    if (!selected) return;
    setEditingId(selected.id);
    setEditingTitle(selected.title);
  }

  function subtreeHeight(nodeId: string): number {
    const children = flat.filter((node) => node.parent_id === nodeId);
    return children.length ? 1 + Math.max(...children.map((child) => subtreeHeight(child.id))) : 1;
  }

  const previousSibling = selectedIndex > 0 ? selectedSiblings[selectedIndex - 1] : null;
  const canIndent = Boolean(selected && previousSibling && previousSibling.depth + subtreeHeight(selected.id) <= 4);
  const selectedParent = selected?.parent_id ? flat.find((node) => node.id === selected.parent_id) ?? null : null;

  async function saveAndExit() {
    try {
      await controller.queueSave(command(5));
      await controller.flush();
      navigate("/projects");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось сохранить черновик");
    }
  }

  if (controller.status === "loading") return <LoadingState label="Загружаем учебниковый черновик" />;
  const busy = controller.status === "saving";

  return (
    <div className="wizard-flow">
      <PageHead eyebrow={`Учебник · шаг ${step} из 5`} title={step === 1 ? "Добавьте материалы, на которых строить программу" : step === 2 ? "Чему именно вы хотите научиться?" : step === 3 ? "Проверьте, что будет обработано" : step === 4 ? "Проверьте представления программы" : "Черновик готов"} />
      {(actionError || controller.error) && <p className="inline-error" role="alert">{actionError || controller.error?.message}</p>}
      {controller.conflict && <Card><h2>Черновик изменился в другой вкладке</h2><Button onClick={() => void controller.reload()}>Загрузить серверную версию</Button></Card>}

      {step === 1 && (
        <section className="textbook-step">
          <p className="wizard-step-intro">Учебник станет источником программы на этапе 5. Пока можно сохранить честный черновик и собрать программу вручную.</p>
          <Card className="textbook-dropzone">
            <UploadCloud size={24} aria-hidden="true" />
            <span><b>Перетащите учебники, методички, конспекты или статьи</b><small>PDF, DOCX, TXT, MD и изображения · до 100 МБ и 500 страниц на файл</small></span>
            <Button disabled variant="secondary">Добавить материал · этап 5</Button>
          </Card>

          <div className="textbook-source-list">
            <Card className="textbook-empty-source">Источников пока нет. Добавление материалов, роли и приоритет появятся на этапе 5.</Card>
          </div>

          <Card className="textbook-analysis-card">
            <div className="textbook-analysis-head"><WandSparkles size={18} aria-hidden="true" /><span><b>Что поняла система</b><small>Здесь появится результат разбора добавленных материалов.</small></span></div>
            <p>Загрузка и анализ учебника появятся на этапе 5</p>
          </Card>

          <div className="wizard-actions"><Button variant="ghost" onClick={() => navigate("/projects/new")}>Вернуться к выбору</Button><Button disabled={busy} onClick={() => void go(2)}>Собрать программу вручную</Button></div>
        </section>
      )}

      {step === 2 && (
        <section className="textbook-step">
          <p className="wizard-step-intro">Свободный текст станет главным контекстом для ручной программы. Темп можно изменить после создания проекта.</p>
          <div className="textbook-profile-grid">
            <Card className="textbook-profile-card is-goal">
              <header><BookOpen size={18} aria-hidden="true" /><span><h2>Что изучать</h2><p>Источник задаст границы на этапе 5, ваша цель — нужный маршрут уже сейчас.</p></span></header>
              <div className="textbook-profile-fields">
                <Field label="Название проекта" required><input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} /></Field>
                <Field label="Предмет" required><input value={form.subject} onChange={(event) => setForm((current) => ({ ...current, subject: event.target.value }))} /></Field>
                <SegmentedTabs label="Охват программы" value={form.scope} onChange={(scope) => setForm((current) => ({ ...current, scope: scope as GoalScope }))} tabs={[{ value: "whole", label: "Весь материал" }, { value: "goal", label: "Конкретная цель" }]} />
                {form.scope === "goal" && <Field label="Ваша цель" hint="Опишите задачу своими словами: программа включит цель, предпосылки и смежные темы."><textarea rows={5} value={form.goal} onChange={(event) => setForm((current) => ({ ...current, goal: event.target.value }))} /></Field>}
                <Field label="Что вы уже знаете"><textarea rows={3} value={form.currentKnowledge} onChange={(event) => setForm((current) => ({ ...current, currentKnowledge: event.target.value }))} /></Field>
                <SegmentedTabs label="Желаемый результат" value={form.targetOutcome} onChange={(targetOutcome) => setForm((current) => ({ ...current, targetOutcome: targetOutcome as TargetOutcome }))} tabs={[{ value: "awareness", label: "Ориентироваться" }, { value: "understanding", label: "Понимать" }, { value: "application", label: "Применять" }, { value: "mastery", label: "Освоить" }]} />
                <Field label="Как поймёте, что цель достигнута"><textarea rows={2} value={form.successCriterion} onChange={(event) => setForm((current) => ({ ...current, successCriterion: event.target.value }))} /></Field>
                <Field label="Что особенно важно"><textarea rows={2} value={form.important} onChange={(event) => setForm((current) => ({ ...current, important: event.target.value }))} /></Field>
                <Field label="Что можно исключить"><textarea rows={2} value={form.excluded} onChange={(event) => setForm((current) => ({ ...current, excluded: event.target.value }))} /></Field>
              </div>
            </Card>

            <Card className="textbook-profile-card">
              <header><WandSparkles size={18} aria-hidden="true" /><span><h2>Как учиться</h2><p>Параметры попадут в паспорт цели черновика.</p></span></header>
              <div className="textbook-profile-fields">
                <Field label="Срок" hint="Необязательно"><input type="date" value={form.deadline} onChange={(event) => setForm((current) => ({ ...current, deadline: event.target.value }))} /></Field>
                <div className="textbook-number-grid">
                  <Field label="Минут в день" hint="Необязательно"><input type="number" min="10" step="5" value={form.minutesPerDay} onChange={(event) => setForm((current) => ({ ...current, minutesPerDay: event.target.value }))} /></Field>
                  <Field label="Дней в неделю" hint="Необязательно"><input type="number" min="1" max="7" value={form.daysPerWeek} onChange={(event) => setForm((current) => ({ ...current, daysPerWeek: event.target.value }))} /></Field>
                  <Field label="Минут на занятие" hint="Необязательно"><input type="number" min="10" step="5" value={form.sessionMinutes} onChange={(event) => setForm((current) => ({ ...current, sessionMinutes: event.target.value }))} /></Field>
                </div>
                <SegmentedTabs label="Формат занятий" value={form.studyFormat} onChange={(studyFormat) => setForm((current) => ({ ...current, studyFormat: studyFormat as StudyFormat }))} tabs={[{ value: "theory", label: "Теория" }, { value: "theory_and_practice", label: "Смешанный" }, { value: "practice", label: "Практика" }]} />
                <div className="textbook-source-summary"><b>Источники</b><span><i>—</i>Материалы пока не добавлены<small>Этап 5</small></span><Button variant="ghost" onClick={() => void go(1)}>К источникам</Button></div>
              </div>
            </Card>
          </div>
          <div className="wizard-actions"><Button variant="ghost" onClick={() => void go(1)}>Назад</Button><Button disabled={busy || !form.name.trim() || !form.subject.trim() || (form.scope === "goal" && !form.goal.trim())} onClick={() => void go(3)}>Продолжить</Button></div>
        </section>
      )}

      {step === 3 && (
        <section className="textbook-step textbook-preflight">
          <p className="wizard-step-intro">Текст материалов останется на вашем компьютере. Сейчас программа собирается вручную и сохраняется как черновик.</p>
          <Card className="textbook-preflight-card">
            <div className="textbook-preflight-summary"><b>{form.name || form.subject || "Учебниковый черновик"}</b><p><strong>Ваша цель:</strong> {form.scope === "goal" ? form.goal || "не указана" : "изучить весь основной материал."}</p><p><strong>Предмет:</strong> {form.subject || "не указан"}</p></div>
            <div className="textbook-preflight-list">
              <section><h2>Источники</h2><p><span>—</span>Не добавлены<small>Этап 5</small></p></section>
              <section className="is-processing-copy"><h2>Обработка на вашем компьютере</h2><p>Разбор страниц, оглавления и качества текста начнётся после добавления материалов на этапе 5.</p></section>
              <section className="is-processing-copy"><h2>Автоматическое построение программы</h2><p>Внешняя модель пока не вызывается. Сейчас доступно ручное составление программы.</p></section>
            </div>
            <Switch checked={false} onCheckedChange={() => undefined} disabled label="Автоматическое составление программы с внешней моделью" hint="Автоматическое построение программы появится на этапе 7" />
            <OfflineNotice reason="disabled" alternative="Соберите программу вручную — этот путь работает офлайн." />
          </Card>
          <div className="wizard-actions"><Button variant="ghost" onClick={() => void go(2)}>Назад</Button><Button disabled={busy} onClick={() => void go(4)}>Собрать программу вручную</Button></div>
        </section>
      )}

      {step === 4 && (
        <section className="textbook-builder">
          <header className="textbook-builder-head">
            <Button variant="ghost" onClick={() => void go(3)}><ArrowLeft size={15} />К проверке</Button>
            <span><b>{form.name || form.subject || "Учебниковый черновик"}</b><small>Ручная программа · изменения сохраняются в черновике</small></span>
            <StatusBadge>ручной режим</StatusBadge>
            <Button variant="ghost" disabled={!controller.detail?.latest_undoable_action || busy} onClick={() => void controller.undo()}><Undo2 size={15} />Отменить</Button>
            <Button disabled={busy || nodes.length === 0} onClick={() => void go(5)}>Продолжить</Button>
          </header>

          <div className="textbook-builder-grid">
            <div className="textbook-program-panel">
              <div className="textbook-program-toolbar">
                <SegmentedTabs label="Представление программы" value={view} onChange={setView} tabs={[{ value: "tree", label: "Дерево" }, { value: "text", label: "Текст" }, { value: "questions", label: "Вопросы" }]} />
                <label className="textbook-search"><Search size={15} aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти тему" aria-label="Найти тему" /></label>
                <label className="visually-hidden" htmlFor="textbook-new-node-type">Тип нового узла</label>
                <select id="textbook-new-node-type" value={newNodeType} onChange={(event) => setNewNodeType(event.target.value as NodeType)} aria-label="Тип нового узла">
                  <option value="section">Раздел</option><option value="topic">Тема</option><option value="subpoint">Подпункт</option>
                </select>
                <label className="visually-hidden" htmlFor="textbook-new-node-parent">Родитель нового узла</label>
                <select id="textbook-new-node-parent" value={newParentId} onChange={(event) => setNewParentId(event.target.value)} aria-label="Родитель нового узла">
                  <option value="">Корень программы</option>{parentOptions.map((node) => <option key={node.id} value={node.id}>{node.number}. {node.title}</option>)}
                </select>
                <Button variant="secondary" disabled={busy} onClick={() => void createNode()}><Plus size={15} />Добавить тему</Button>
                <Button variant="ghost" aria-pressed={missingOnly} onClick={() => setMissingOnly((current) => !current)}><Filter size={15} />Нужен материал</Button>
              </div>

              <div className="textbook-manual-toolbar" aria-label="Ручные действия с узлом программы">
                <span>Выбрано: <b>{selected?.title ?? "узел не выбран"}</b></span>
                <IconButton label="Поднять узел" disabled={busy || selectedIndex <= 0} onClick={() => void moveSelected(selectedIndex - 1)}><ArrowUp size={15} /></IconButton>
                <IconButton label="Опустить узел" disabled={busy || selectedIndex < 0 || selectedIndex === selectedSiblings.length - 1} onClick={() => void moveSelected(selectedIndex + 1)}><ArrowDown size={15} /></IconButton>
                <IconButton label="Уменьшить вложенность" disabled={busy || !selectedParent} onClick={() => selectedParent && void moveSelected(selectedParent.sort_order + 1, selectedParent.parent_id)}><ArrowLeft size={15} /></IconButton>
                <IconButton label="Увеличить вложенность" disabled={busy || !canIndent || !previousSibling} onClick={() => previousSibling && void moveSelected(previousSibling.children.length, previousSibling.id)}><ArrowRight size={15} /></IconButton>
                <IconButton label="Редактировать формулировку" disabled={busy || !selected} onClick={startRename}><Pencil size={15} /></IconButton>
                <IconButton label="Дублирование недоступно: API пока не поддерживает копирование узлов" disabled><Copy size={15} /></IconButton>
                <IconButton label="Убрать узел из программы" disabled={busy || !selected} onClick={() => void removeSelected()}><Trash2 size={15} /></IconButton>
              </div>

              <div className="textbook-program-content">
                {view === "tree" && visibleFlat.map((node) => (
                  <div className={`textbook-program-row ${selected?.id === node.id ? "is-selected" : ""}`.trim()} key={node.id} style={{ paddingInlineStart: `calc(var(--space-4) + ${node.depth - 1} * var(--space-6))` }} onClick={() => setSelectedId(node.id)}>
                    <span className="textbook-program-number">{node.number}</span>
                    <span className="textbook-program-copy">
                      {editingId === node.id
                        ? <input autoFocus value={editingTitle} onClick={(event) => event.stopPropagation()} onChange={(event) => setEditingTitle(event.target.value)} onBlur={() => void renameSelected()} onKeyDown={(event) => { if (event.key === "Enter") void renameSelected(); if (event.key === "Escape") setEditingId(null); }} aria-label={`Формулировка «${node.title}»`} />
                        : <b>{node.title}</b>}
                      <small>{node.node_type === "section" ? "раздел" : node.node_type === "topic" ? "тема" : "подпункт"}</small>
                    </span>
                    <span className="textbook-program-source"><StatusBadge>{node.needs_material ? "Материал нужен" : "Материал не добавлен"}</StatusBadge><small>Ручная программа</small></span>
                  </div>
                ))}
                {view === "tree" && visibleFlat.length === 0 && <div className="textbook-text-view"><p>{missingOnly ? "Нет узлов с отметкой о необходимом материале." : "Программа пока пуста. Добавьте первый раздел или тему."}</p></div>}
                {view === "text" && <article className="textbook-text-view"><h2>{form.name || form.subject || "Программа"}</h2>{visibleFlat.map((node) => <p key={node.id}><b>{node.number}. {node.title}</b> — {node.node_type === "section" ? "раздел" : node.node_type === "topic" ? "тема" : "подпункт"}.</p>)}</article>}
                {view === "questions" && <ol className="textbook-question-view">{visibleFlat.filter((node) => node.node_type !== "section").map((node) => <li key={node.id}>Как объяснить: «{node.title}»?</li>)}</ol>}
              </div>
            </div>

            <aside className="textbook-assistant" aria-label="Помощник по программе">
              <header><span><MessageSquare size={17} aria-hidden="true" /><b>Помощник по программе</b></span><label>Контекст<select disabled><option>Вся программа</option></select></label></header>
              <div className="textbook-chat-body"><div className="textbook-chat-locked"><WandSparkles size={24} aria-hidden="true" /><b>Помощник пока недоступен</b><p>Помощник по программе появится на этапе 7</p></div></div>
              <footer><textarea disabled placeholder="Опишите изменение программы" /><Button disabled><ArrowUp size={15} />Отправить</Button><small>Ручное редактирование программы уже доступно.</small></footer>
            </aside>
          </div>
        </section>
      )}

      {step === 5 && (
        <section className="textbook-step textbook-summary">
          <p className="wizard-step-intro">Проверьте паспорт и ручную программу. После сохранения черновик можно продолжить с этого же места.</p>
          <Card className="textbook-summary-story">
            <h2>{form.name || form.subject || "Учебниковый черновик"}</h2>
            <p><b>Предмет:</b> {form.subject || "не указан"}</p>
            <p><b>Ваша цель:</b> {form.scope === "goal" ? form.goal || "не указана" : "изучить весь основной материал."}</p>
            <p>{form.deadline ? `До ${new Date(`${form.deadline}T00:00:00`).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" })}` : "Без срока"} · {form.minutesPerDay || "—"} минут в день, {form.daysPerWeek || "—"} дня в неделю, занятиями по {form.sessionMinutes || "—"} минут.</p>
            <p><b>Критерий успеха:</b> {form.successCriterion || "не указан"}</p>
          </Card>

          <Card className="textbook-summary-card"><h3>Источники</h3><p>Не добавлены</p></Card>

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

          <Card className="textbook-summary-card"><h3>После сохранения</h3><p>Черновик останется неактивным. Его можно открыть снова, менять ручную программу и добавить материалы, когда разбор учебников появится на этапе 5.</p></Card>
          <div className="wizard-actions"><Button variant="ghost" onClick={() => void go(4)}>Назад</Button><Button disabled={busy} onClick={() => void saveAndExit()}>Сохранить черновик и выйти</Button></div>
        </section>
      )}
    </div>
  );
}
