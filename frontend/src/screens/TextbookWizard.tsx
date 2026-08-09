import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { BookOpen, ListTree, Plus, Trash2, Undo2 } from "lucide-react";
import {
  createProgramNode,
  removeProgramNode,
  updateProgramNode,
  type GoalPassportWrite,
  type ModuleKey,
  type NodeType,
} from "../api/projects";
import type { WizardDraftController } from "../hooks/useWizardDraft";
import { Button, Card, EmptyState, Field, LoadingState, PageHead, SegmentedTabs } from "../components/ui";
import { buildProgramTree, flattenProgramTree } from "./programTree";

type ProgramView = "tree" | "text" | "questions";

interface TextbookForm {
  name: string;
  subject: string;
  goal: string;
  currentKnowledge: string;
  important: string;
  excluded: string;
  minutesPerDay: string;
  daysPerWeek: string;
  sessionMinutes: string;
}

const EMPTY_FORM: TextbookForm = {
  name: "",
  subject: "",
  goal: "",
  currentKnowledge: "",
  important: "",
  excluded: "",
  minutesPerDay: "45",
  daysPerWeek: "4",
  sessionMinutes: "45",
};
const nullable = (value: string) => value.trim() || null;
const positive = (value: string) => Number(value) > 0 ? Number(value) : null;

export function TextbookWizard({ controller }: { controller: WizardDraftController }) {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<TextbookForm>(EMPTY_FORM);
  const [view, setView] = useState<ProgramView>("tree");
  const [newTitle, setNewTitle] = useState("");
  const [newType, setNewType] = useState<NodeType>("topic");
  const [newParentId, setNewParentId] = useState("");
  const [actionError, setActionError] = useState("");
  const initializedId = useRef<string | null>(null);

  useEffect(() => {
    const detail = controller.detail;
    if (!detail || initializedId.current === detail.project.id) return;
    initializedId.current = detail.project.id;
    const goal = detail.goal_passport;
    setStep(detail.draft.current_step);
    setView((detail.draft.state.program_view as ProgramView) ?? "tree");
    setForm({
      name: detail.project.name ?? "",
      subject: goal?.subject ?? "",
      goal: goal?.goal ?? "",
      currentKnowledge: goal?.current_knowledge ?? "",
      important: goal?.important ?? "",
      excluded: goal?.excluded ?? "",
      minutesPerDay: goal?.minutes_per_day ? String(goal.minutes_per_day) : "45",
      daysPerWeek: goal?.days_per_week ? String(goal.days_per_week) : "4",
      sessionMinutes: goal?.session_minutes ? String(goal.session_minutes) : "45",
    });
  }, [controller.detail]);

  function passport(): GoalPassportWrite {
    return {
      subject: nullable(form.subject),
      purpose: "interest",
      scope: "whole",
      starting_level: "familiar",
      current_knowledge: nullable(form.currentKnowledge),
      target_outcome: "understanding",
      goal: nullable(form.goal),
      success_criterion: "Объяснить ключевые темы своими словами и применить их на примере",
      important: nullable(form.important),
      excluded: nullable(form.excluded),
      study_format: "theory_and_practice",
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
        description: nullable(form.goal),
        icon: "book-open" as const,
        color: 4,
        deadline: null,
        enabled_modules: ["plan", "lessons", "cards", "repetitions"] as ModuleKey[],
      },
      goal_passport: passport(),
      state: { program_view: view, selected_node_id: controller.detail?.program.nodes[0]?.id ?? null },
    };
  }

  useEffect(() => {
    if (!controller.detail || initializedId.current !== controller.detail.project.id || controller.conflict) return;
    const timer = window.setTimeout(() => {
      void controller.queueSave(command(step)).catch(() => undefined);
    }, 400);
    return () => window.clearTimeout(timer);
  }, [form, step, view]);

  async function go(nextStep: number) {
    setActionError("");
    try {
      await controller.queueSave(command(nextStep));
      setStep(nextStep);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось сохранить черновик");
    }
  }

  async function addNode() {
    if (!controller.detail || !newTitle.trim()) return;
    setActionError("");
    try {
      await controller.enqueueProgramCommand((current) => createProgramNode(current.project.id, {
        expected_program_revision: current.program.revision,
        parent_id: newParentId || null,
        position: null,
        node_type: newType,
        exam_kind: null,
        title: newTitle.trim(),
        goal_role: "target",
      }));
      setNewTitle("");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось добавить узел");
    }
  }

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
  const nodes = controller.detail?.program.nodes ?? [];
  let flat = [] as ReturnType<typeof flattenProgramTree>;
  try { flat = flattenProgramTree(buildProgramTree(nodes)); } catch { flat = []; }
  const busy = controller.status === "saving";
  const parentOptions = nodes.filter((node) => node.is_in_current_program && !node.is_archived);

  return (
    <div className="wizard-flow">
      <PageHead eyebrow={`Учебник · шаг ${step} из 5`} title={step === 1 ? "Сначала соберём честный черновик" : step === 2 ? "Опишите цель изучения" : step === 3 ? "Соберите программу вручную" : step === 4 ? "Проверьте представления программы" : "Черновик готов"} />
      {(actionError || controller.error) && <p className="inline-error" role="alert">{actionError || controller.error?.message}</p>}
      {controller.conflict && <Card><h2>Черновик изменился в другой вкладке</h2><Button onClick={() => void controller.reload()}>Загрузить серверную версию</Button></Card>}

      {step === 1 && <section className="wizard-step"><EmptyState title="Файлы ещё не загружаются" icon={<BookOpen size={28} />}><p>На этапе 3 сохраняются паспорт и ручная программа. Источник можно будет добавить на этапе 5.</p><Button disabled variant="secondary">Добавить учебник · этап 5</Button></EmptyState><div className="wizard-actions"><Button variant="ghost" onClick={() => navigate("/projects/new")}>Вернуться к выбору</Button><Button disabled={busy} onClick={() => void go(2)}>Собрать программу вручную</Button></div></section>}

      {step === 2 && <section className="wizard-step"><div className="wizard-form-grid"><Field label="Название проекта" required><input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} /></Field><Field label="Предмет" required><input value={form.subject} onChange={(event) => setForm((current) => ({ ...current, subject: event.target.value }))} /></Field><Field label="Минут в день"><input type="number" min="1" value={form.minutesPerDay} onChange={(event) => setForm((current) => ({ ...current, minutesPerDay: event.target.value }))} /></Field><Field label="Дней в неделю"><input type="number" min="1" max="7" value={form.daysPerWeek} onChange={(event) => setForm((current) => ({ ...current, daysPerWeek: event.target.value }))} /></Field></div><Field label="Цель"><textarea value={form.goal} onChange={(event) => setForm((current) => ({ ...current, goal: event.target.value }))} /></Field><Field label="Что уже знаете"><textarea value={form.currentKnowledge} onChange={(event) => setForm((current) => ({ ...current, currentKnowledge: event.target.value }))} /></Field><Field label="Что особенно важно"><textarea value={form.important} onChange={(event) => setForm((current) => ({ ...current, important: event.target.value }))} /></Field><Field label="Что исключить"><textarea value={form.excluded} onChange={(event) => setForm((current) => ({ ...current, excluded: event.target.value }))} /></Field><div className="wizard-actions"><Button variant="ghost" onClick={() => setStep(1)}>Назад</Button><Button disabled={busy || !(form.name || form.subject).trim()} onClick={() => void go(3)}>Продолжить</Button></div></section>}

      {step === 3 && <section className="wizard-step"><Card><div className="wizard-form-grid"><Field label="Новая формулировка"><input value={newTitle} onChange={(event) => setNewTitle(event.target.value)} placeholder="Например, устройство B-дерева" /></Field><Field label="Тип"><select value={newType} onChange={(event) => setNewType(event.target.value as NodeType)}><option value="section">Раздел</option><option value="topic">Тема</option><option value="subpoint">Подпункт</option></select></Field><Field label="Родитель"><select value={newParentId} onChange={(event) => setNewParentId(event.target.value)}><option value="">Корень программы</option>{parentOptions.map((node) => <option key={node.id} value={node.id}>{node.title}</option>)}</select></Field></div><Button disabled={busy || !newTitle.trim()} onClick={() => void addNode()}><Plus size={15} />Добавить узел</Button></Card>{nodes.length === 0 ? <EmptyState title="Программа пока пуста"><p>Добавьте первый раздел или тему.</p></EmptyState> : <div className="wizard-review-list">{flat.map((node) => <div key={node.id} style={{ paddingInlineStart: `calc(${node.depth - 1} * var(--space-5))` }}><input defaultValue={node.title} onBlur={(event) => { const title = event.target.value.trim(); if (title && title !== node.title) void controller.enqueueProgramCommand((current) => updateProgramNode(current.project.id, node.id, { expected_program_revision: current.program.revision, title })); }} /><Button variant="ghost" aria-label={`Убрать «${node.title}»`} onClick={() => controller.detail && void controller.enqueueProgramCommand((current) => removeProgramNode(current.project.id, node.id, current.program.revision))}><Trash2 size={14} /></Button></div>)}</div>}<div className="wizard-actions"><Button variant="secondary" disabled={!controller.detail?.latest_undoable_action || busy} onClick={() => void controller.undo()}><Undo2 size={15} />Отменить</Button><Button variant="ghost" onClick={() => setStep(2)}>Назад</Button><Button disabled={busy || nodes.length === 0} onClick={() => void go(4)}>Проверить программу</Button></div></section>}

      {step === 4 && <section className="wizard-step"><SegmentedTabs label="Представление" value={view} onChange={setView} tabs={[{ value: "tree", label: "Дерево" }, { value: "text", label: "Текст" }, { value: "questions", label: "Вопросы" }]} /><Card>{view === "tree" && flat.map((node) => <p key={node.id} style={{ paddingInlineStart: `calc(${node.depth - 1} * var(--space-5))` }}><ListTree size={14} />{node.number}. {node.title}</p>)}{view === "text" && <pre>{flat.map((node) => `${node.number}. ${node.title}`).join("\n")}</pre>}{view === "questions" && flat.filter((node) => node.node_type !== "section").map((node) => <p key={node.id}>{node.title.endsWith("?") ? node.title : `Объясните тему: ${node.title}`}</p>)}</Card><p>Все три вида строятся из одних ProgramNode и отдельно не сохраняются.</p><div className="wizard-actions"><Button variant="ghost" onClick={() => setStep(3)}>Назад</Button><Button onClick={() => void go(5)}>Подтвердить черновик</Button></div></section>}

      {step === 5 && <section className="wizard-step"><Card><h2>{form.name || form.subject}</h2><p>Паспорт цели, модули и {nodes.length} узлов программы сохранены.</p><p>Источники не добавлены, проект не активирован.</p></Card><div className="wizard-actions"><Button variant="ghost" onClick={() => setStep(4)}>Назад</Button><Button disabled={busy} onClick={() => void saveAndExit()}>Сохранить черновик и выйти</Button></div></section>}
    </div>
  );
}
