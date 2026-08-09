import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import {
  ArrowLeft,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  BookOpen,
  Copy,
  ListTree,
  PanelsTopLeft,
  Plus,
  RotateCcw,
  Search,
  Settings,
  Target,
  Trash2,
  Undo2,
} from "lucide-react";
import {
  createProgramNode,
  getProject,
  moveProgramNode,
  removeProgramNode,
  restoreProgramNode,
  setProgramTargetLevel,
  undoProjectAction,
  updateProgramNode,
  ProjectApiError,
  type ExamKind,
  type ProgramChangeResult,
  type ProgramNodeRead,
  type ProjectDetail,
  type TargetOutcome,
} from "../api/projects";
import { GOAL_LEVELS, GoalLevelPicker } from "../components/domain";
import type { GoalLevelValue } from "../components/domain";
import {
  Button,
  Dialog,
  Disclosure,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  PageHead,
} from "../components/ui";
import { buildProgramTree, filterProgramTree, flattenProgramTree, visibleHiddenRoots } from "./programTree";

type AddKind = "section" | "ticket" | "question" | "task" | "topic" | "subpoint";

function apiKind(kind: AddKind): { node_type: ProgramNodeRead["node_type"]; exam_kind: ExamKind | null } {
  switch (kind) {
    case "ticket": return { node_type: "section", exam_kind: "ticket" };
    case "question": return { node_type: "topic", exam_kind: "question" };
    case "task": return { node_type: "topic", exam_kind: "task" };
    case "subpoint": return { node_type: "subpoint", exam_kind: null };
    case "topic": return { node_type: "topic", exam_kind: null };
    default: return { node_type: "section", exam_kind: null };
  }
}

function nodeKind(node: ProgramNodeRead, textbook: boolean): AddKind {
  if (textbook) return node.node_type;
  if (node.exam_kind === "ticket") return "ticket";
  if (node.exam_kind === "task") return "task";
  if (node.exam_kind === "question") return "question";
  return "section";
}

export function Program() {
  const { projectId = "" } = useParams();
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [commandError, setCommandError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [addOpen, setAddOpen] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newKind, setNewKind] = useState<AddKind>("question");
  const [newParentId, setNewParentId] = useState<string>("");
  const [duplicateWarning, setDuplicateWarning] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");

  async function load(signal?: AbortSignal) {
    setLoading(true);
    setLoadError(null);
    setConflict(false);
    try {
      const next = await getProject(projectId, signal);
      setDetail(next);
      const first = next.program.nodes.find((node) => node.is_in_current_program && !node.is_archived);
      setSelectedId((current) => current && next.program.nodes.some((node) => node.id === current) ? current : first?.id ?? null);
      setExpanded(new Set(next.program.nodes.filter((node) => node.node_type === "section").map((node) => node.id)));
    } catch (error) {
      if (!signal?.aborted) setLoadError(error);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [projectId]);

  const treeResult = useMemo(() => {
    try {
      return { tree: buildProgramTree(detail?.program.nodes ?? []), error: "" };
    } catch (error) {
      return { tree: [], error: error instanceof Error ? error.message : "Некорректное дерево программы" };
    }
  }, [detail?.program.nodes]);
  const flat = useMemo(() => flattenProgramTree(treeResult.tree), [treeResult.tree]);
  const selected = detail?.program.nodes.find((node) => node.id === selectedId) ?? null;
  const textbook = detail?.project.workspace_variant === "textbook";

  useEffect(() => setTitleDraft(selected?.title ?? ""), [selected?.id, selected?.title]);

  function acceptResult(result: ProgramChangeResult) {
    setDetail((current) => current ? {
      ...current,
      program: result.program,
      latest_undoable_action: result.latest_undoable_action,
    } : current);
    const visibleIds = new Set(result.program.nodes
      .filter((node) => node.is_in_current_program && !node.is_archived)
      .map((node) => node.id));
    setSelectedId((current) => {
      if (result.changed_node && visibleIds.has(result.changed_node.id)) return result.changed_node.id;
      if (current && visibleIds.has(current)) return current;
      return result.program.nodes.find((node) => visibleIds.has(node.id))?.id ?? null;
    });
  }

  async function runCommand(command: Promise<ProgramChangeResult>) {
    setBusy(true);
    setCommandError("");
    try {
      acceptResult(await command);
    } catch (error) {
      if (error instanceof ProjectApiError && ["stale_program_revision", "stale_action_sequence"].includes(error.code ?? "")) {
        setConflict(true);
      } else {
        setCommandError(error instanceof Error ? error.message : "Не удалось изменить программу");
      }
    } finally {
      setBusy(false);
    }
  }

  function toggle(nodeId: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(nodeId)) next.delete(nodeId); else next.add(nodeId);
      return next;
    });
  }

  function siblingInfo(node: ProgramNodeRead) {
    const siblings = detail ? [...detail.program.nodes]
      .filter((item) => item.parent_id === node.parent_id && item.is_in_current_program && !item.is_archived)
      .sort((left, right) => left.sort_order - right.sort_order) : [];
    return { siblings, index: siblings.findIndex((item) => item.id === node.id) };
  }

  function move(node: ProgramNodeRead, offset: number) {
    if (!detail) return;
    const { index } = siblingInfo(node);
    void runCommand(moveProgramNode(projectId, node.id, {
      expected_program_revision: detail.program.revision,
      parent_id: node.parent_id,
      position: index + offset,
    }));
  }

  function indent(node: ProgramNodeRead) {
    if (!detail) return;
    const { siblings, index } = siblingInfo(node);
    const previous = siblings[index - 1];
    if (!previous) return;
    void runCommand(moveProgramNode(projectId, node.id, {
      expected_program_revision: detail.program.revision,
      parent_id: previous.id,
      position: null,
    }));
  }

  function outdent(node: ProgramNodeRead) {
    if (!detail || !node.parent_id) return;
    const parent = detail.program.nodes.find((item) => item.id === node.parent_id);
    if (!parent) return;
    const parentSiblings = [...detail.program.nodes]
      .filter((item) => item.parent_id === parent.parent_id && item.is_in_current_program && !item.is_archived)
      .sort((left, right) => left.sort_order - right.sort_order);
    const parentIndex = parentSiblings.findIndex((item) => item.id === parent.id);
    void runCommand(moveProgramNode(projectId, node.id, {
      expected_program_revision: detail.program.revision,
      parent_id: parent.parent_id,
      position: parentIndex + 1,
    }));
  }

  function addNode(force = false) {
    if (!detail || !newTitle.trim()) return;
    const duplicate = detail.program.nodes.some((node) =>
      node.title.trim().toLocaleLowerCase("ru") === newTitle.trim().toLocaleLowerCase("ru"));
    if (duplicate && !force) {
      setDuplicateWarning(true);
      return;
    }
    const kind = apiKind(newKind);
    setDuplicateWarning(false);
    setAddOpen(false);
    void runCommand(createProgramNode(projectId, {
      expected_program_revision: detail.program.revision,
      parent_id: newParentId || null,
      position: null,
      ...kind,
      title: newTitle.trim(),
      goal_role: "target",
    }));
    setNewTitle("");
  }

  function duplicate(node: ProgramNodeRead) {
    if (!detail) return;
    const { index } = siblingInfo(node);
    void runCommand(createProgramNode(projectId, {
      expected_program_revision: detail.program.revision,
      parent_id: node.parent_id,
      position: index + 1,
      node_type: node.node_type,
      exam_kind: node.exam_kind,
      title: `${node.title} — копия`,
      section_purpose: node.section_purpose,
      goal_role: node.goal_role,
      target_level: node.target_level,
      needs_material: node.needs_material,
    }));
  }

  function changeKind(node: ProgramNodeRead, kind: AddKind) {
    if (!detail) return;
    const mapped = apiKind(kind);
    void runCommand(updateProgramNode(projectId, node.id, {
      expected_program_revision: detail.program.revision,
      ...mapped,
    }));
  }

  async function undo() {
    if (!detail?.latest_undoable_action) return;
    setBusy(true);
    setCommandError("");
    try {
      const result = await undoProjectAction(projectId, detail.latest_undoable_action.sequence);
      if (result.program) {
        setDetail({ ...detail, program: result.program, latest_undoable_action: result.latest_undoable_action });
        const visible = result.program.nodes.filter((node) => node.is_in_current_program && !node.is_archived);
        setSelectedId((current) => current && visible.some((node) => node.id === current) ? current : visible[0]?.id ?? null);
      }
    } catch (error) {
      if (error instanceof ProjectApiError && error.code === "stale_action_sequence") setConflict(true);
      else setCommandError(error instanceof Error ? error.message : "Не удалось отменить действие");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <div className="screen"><LoadingState label="Загружаем программу" /></div>;
  if (loadError) {
    const notFound = loadError instanceof ProjectApiError && loadError.status === 404;
    return <div className="screen"><ErrorState title={notFound ? "Проект не найден" : undefined} message={notFound ? "Проверьте адрес или вернитесь к списку проектов." : loadError instanceof Error ? loadError.message : "Не удалось загрузить программу"} /><Button onClick={() => void load()}>Повторить загрузку</Button><Link className="secondary-button" to="/projects">К проектам</Link></div>;
  }
  if (!detail) return null;
  if (treeResult.error) return <div className="screen"><ErrorState title="Программа повреждена" message={treeResult.error} /></div>;

  const currentFlat = flat.filter((node) => node.is_in_current_program && !node.is_archived);
  const shown = flattenProgramTree(filterProgramTree(treeResult.tree, query))
    .filter((node) => node.is_in_current_program && !node.is_archived);
  const hiddenRoots = visibleHiddenRoots(detail.program.nodes);
  const parentOptions = currentFlat.filter((node) => node.node_type === "section" || textbook);

  return (
    <div className="program-screen">
      <aside className="program-project-panel">
        <header className="program-project-title">
          <Link className="workspace-back-button" to={`/projects/${projectId}`} aria-label="Вернуться в рабочую область"><ArrowLeft size={15} /></Link>
          <strong>{detail.project.name}</strong>
        </header>
        <nav className="workspace-project-nav program-project-nav" aria-label="Разделы проекта">
          <Link className="workspace-project-link" to={`/projects/${projectId}`}><ListTree size={15} /><span>Рабочая область</span></Link>
          <span className="workspace-project-link is-active"><ListTree size={15} /><span>{textbook ? "Программа" : "Вопросы экзамена"}</span><small>{currentFlat.filter((node) => node.node_type !== "section").length}</small></span>
          {!textbook && <Link className="workspace-project-link" to={`/projects/${projectId}/coverage-map`}><Target size={15} /><span>Карта эталонов</span></Link>}
          <Link className="workspace-project-link" to={`/projects/${projectId}/settings`}><Settings size={15} /><span>Настройки</span></Link>
          <span className="workspace-project-link is-disabled" title="Материалы появятся на этапе 5"><BookOpen size={15} /><span>Материалы · этап 5</span></span>
          <span className="workspace-project-link is-disabled" title="План появится на этапе 9"><PanelsTopLeft size={15} /><span>План · этап 9</span></span>
        </nav>
      </aside>

      <main className="program-main">
        <PageHead
          eyebrow={textbook ? "Ручная структура" : "Структура экзамена"}
          title={textbook ? "Программа" : "Вопросы экзамена"}
          actions={<><Button variant="secondary" disabled={busy || !detail.latest_undoable_action} onClick={() => void undo()}><Undo2 size={15} />Отменить</Button><Button disabled={busy} onClick={() => { setNewKind(textbook ? "topic" : "question"); setNewParentId(""); setAddOpen(true); }}><Plus size={15} />Добавить</Button></>}
        />
        {conflict && <section className="program-plan-notice" role="alert"><span>Программа изменилась в другой вкладке.</span><Button onClick={() => void load()}>Загрузить серверную версию</Button></section>}
        {commandError && <p className="inline-error" role="alert">{commandError}</p>}
        <div className="program-toolbar"><label className="program-search"><Search size={16} /><span className="sr-only">Найти в программе</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Название темы" /></label></div>

        {currentFlat.length === 0 ? (
          <EmptyState title="Программа пока пуста">
            <p>{textbook ? "Добавьте первую тему вручную." : "Вернитесь в мастер и импортируйте список или добавьте вопрос вручную."}</p>
            <Button onClick={() => setAddOpen(true)}>Добавить первый узел</Button>
          </EmptyState>
        ) : (
          <div className="program-editor-grid">
            <section className="program-outline" aria-label="Дерево программы">
              {shown.map((node) => {
                const info = siblingInfo(node);
                const hasChildren = node.children.length > 0;
                const visibleByParent = !node.parent_id || expanded.has(node.parent_id) || Boolean(query.trim());
                if (!visibleByParent) return null;
                return (
                  <div className={`program-question-row ${selectedId === node.id ? "is-selected" : ""}`.trim()} style={{ paddingInlineStart: `calc(${node.depth - 1} * var(--space-5))` }} key={node.id}>
                    {hasChildren ? <button type="button" className="text-button" aria-label={expanded.has(node.id) ? "Свернуть" : "Раскрыть"} onClick={() => toggle(node.id)}>{expanded.has(node.id) ? "−" : "+"}</button> : <span className="program-review-placeholder" />}
                    <button type="button" className="program-question-main" onClick={() => setSelectedId(node.id)}><span className="program-question-number">{node.number}</span><span className="program-question-copy"><strong>{node.title}</strong><small>{nodeKind(node, textbook)}</small></span></button>
                    <span className="program-goal-label"><Target size={14} />{GOAL_LEVELS.find((level) => level.value === node.target_level)?.label ?? "уровень не задан"}</span>
                    <div className="program-row-actions">
                      <Button variant="ghost" aria-label="Вверх" disabled={busy || info.index <= 0} onClick={() => move(node, -1)}><ArrowUp size={14} /></Button>
                      <Button variant="ghost" aria-label="Вниз" disabled={busy || info.index >= info.siblings.length - 1} onClick={() => move(node, 1)}><ArrowDown size={14} /></Button>
                      <Button variant="ghost" aria-label="Сделать дочерним" disabled={busy || info.index <= 0} onClick={() => indent(node)}><ArrowRight size={14} /></Button>
                      <Button variant="ghost" aria-label="Поднять на уровень" disabled={busy || !node.parent_id} onClick={() => outdent(node)}><ArrowLeft size={14} /></Button>
                    </div>
                  </div>
                );
              })}
              {shown.length === 0 && <EmptyState title={`Нет результатов для «${query}»`}><Button variant="secondary" onClick={() => setQuery("")}>Очистить поиск</Button></EmptyState>}
              {hiddenRoots.length > 0 && <Disclosure summary={`Убрано из списка (${hiddenRoots.length})`}>{hiddenRoots.map((node) => <div className="dash-archive-row" key={node.id}><span>{node.title}</span><Button variant="ghost" disabled={busy} onClick={() => void runCommand(restoreProgramNode(projectId, node.id, detail.program.revision))}><RotateCcw size={14} />Вернуть</Button></div>)}</Disclosure>}
            </section>

            <aside className="program-inspector" aria-label="Свойства выбранного узла">
              {selected ? <>
                <p className="eyebrow">Свойства</p>
                <Field label="Формулировка"><input value={titleDraft} onChange={(event) => setTitleDraft(event.target.value)} onBlur={() => { const title = titleDraft.trim(); if (title && title !== selected.title) void runCommand(updateProgramNode(projectId, selected.id, { expected_program_revision: detail.program.revision, title })); }} /></Field>
                <Field label="Тип узла"><select value={nodeKind(selected, textbook)} onChange={(event) => changeKind(selected, event.target.value as AddKind)}>{(textbook ? [["section", "Раздел"], ["topic", "Тема"], ["subpoint", "Подпункт"]] : [["section", "Раздел"], ["ticket", "Билет"], ["question", "Вопрос"], ["task", "Задача"]]).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
                <GoalLevelPicker label="узла" value={(selected.target_level ?? "understanding") as GoalLevelValue} onChange={(target) => void runCommand(setProgramTargetLevel(projectId, selected.id, { expected_program_revision: detail.program.revision, target_level: target as TargetOutcome, include_descendants: true }))} />
                <div className="program-inspector-links"><Link to={`/projects/${projectId}?topic=${selected.id}`}>Открыть в рабочей области</Link></div>
                <div className="program-row-actions"><Button variant="secondary" disabled={busy} onClick={() => duplicate(selected)}><Copy size={15} />Продублировать</Button><Button variant="ghost" disabled={busy} onClick={() => void runCommand(removeProgramNode(projectId, selected.id, detail.program.revision))}><Trash2 size={15} />Убрать из списка</Button></div>
              </> : <p>Выберите узел программы.</p>}
            </aside>
          </div>
        )}
      </main>

      <Dialog open={addOpen} onOpenChange={setAddOpen} title="Добавить в программу" description="Положение и происхождение узла сохранит сервер." footer={<><Button variant="ghost" onClick={() => setAddOpen(false)}>Отменить</Button><Button disabled={!newTitle.trim()} onClick={() => addNode(false)}>Добавить узел</Button></>}>
        <Field label="Формулировка" required><input autoFocus value={newTitle} onChange={(event) => { setNewTitle(event.target.value); setDuplicateWarning(false); }} placeholder="Например, индексы и B-деревья" /></Field>
        <Field label="Тип"><select value={newKind} onChange={(event) => setNewKind(event.target.value as AddKind)}>{(textbook ? [["section", "Раздел"], ["topic", "Тема"], ["subpoint", "Подпункт"]] : [["section", "Раздел"], ["ticket", "Билет"], ["question", "Вопрос"], ["task", "Задача"]]).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
        <Field label="Родитель"><select value={newParentId} onChange={(event) => setNewParentId(event.target.value)}><option value="">Корень программы</option>{parentOptions.map((node) => <option key={node.id} value={node.id}>{node.title}</option>)}</select></Field>
        {duplicateWarning && <div className="inline-error" role="alert"><p>Узел с такой формулировкой уже есть.</p><Button variant="secondary" onClick={() => addNode(true)}>Всё равно добавить</Button></div>}
      </Dialog>
    </div>
  );
}
