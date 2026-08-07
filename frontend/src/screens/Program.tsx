import { useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import {
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  FileText,
  Files,
  Layers,
  ListTree,
  MoreHorizontal,
  Plus,
  Search,
  Settings,
  Sparkles,
  Target,
  Trash2,
  WandSparkles,
} from "lucide-react";
import {
  Button,
  Dialog,
  Field,
  IconButton,
  Menu,
  PageHead,
  SegmentedTabs,
  Tooltip,
} from "../components/ui";
import { CostEstimate, GOAL_LEVELS, GoalLevelPicker, MachineMark } from "../components/domain";
import type { GoalLevelValue } from "../components/domain";
import { TextbookProgramActive } from "./TextbookWizard";

type NodeType = "section" | "question" | "task" | "ticket";

interface ProgramNode {
  id: string;
  title: string;
  type: NodeType;
  goal: GoalLevelValue;
  source: "import" | "manual" | "machine";
  attention?: "review" | "similar";
  children?: ProgramNode[];
}

const NODE_LABEL: Record<NodeType, string> = {
  section: "Раздел",
  question: "Вопрос",
  task: "Задача",
  ticket: "Билет",
};

const NODE_DATA: ProgramNode[] = [
  {
    id: "basics",
    title: "Основы баз данных",
    type: "section",
    goal: "understanding",
    source: "import",
    children: [
      { id: "db-purpose", title: "Назначение и основные компоненты СУБД", type: "question", goal: "understanding", source: "import" },
      { id: "data-models", title: "Модели данных: иерархическая, сетевая и реляционная", type: "question", goal: "understanding", source: "import" },
      { id: "db-architecture", title: "Трёхуровневая архитектура ANSI/SPARC и независимость данных", type: "question", goal: "application", source: "import", attention: "review" },
      { id: "data-languages", title: "Языки определения и манипулирования данными", type: "question", goal: "understanding", source: "import" },
    ],
  },
  {
    id: "relational",
    title: "Реляционная модель",
    type: "section",
    goal: "application",
    source: "machine",
    children: [
      { id: "relational-concepts", title: "Основные понятия: отношение, кортеж, домен", type: "question", goal: "understanding", source: "import" },
      { id: "keys", title: "Потенциальные, первичные и внешние ключи", type: "question", goal: "application", source: "import" },
      { id: "relational-algebra", title: "Операции реляционной алгебры", type: "task", goal: "application", source: "manual" },
      { id: "normalization", title: "Нормализация отношений и нормальные формы", type: "question", goal: "mastery", source: "import", attention: "similar" },
    ],
  },
  { id: "transactions", title: "Транзакции и свойства ACID", type: "question", goal: "application", source: "import" },
  { id: "logging", title: "Журнализация и восстановление", type: "question", goal: "understanding", source: "import" },
];

function findNode(nodes: ProgramNode[], id: string): ProgramNode | undefined {
  for (const node of nodes) {
    if (node.id === id) return node;
    const child = node.children && findNode(node.children, id);
    if (child) return child;
  }
  return undefined;
}

function updateNode(nodes: ProgramNode[], id: string, edit: (node: ProgramNode) => ProgramNode): ProgramNode[] {
  return nodes.map((node) => ({
    ...node,
    ...(node.id === id ? edit(node) : {}),
    children: node.children ? updateNode(node.children, id, edit) : undefined,
  }));
}

function removeNode(nodes: ProgramNode[], id: string): ProgramNode[] {
  return nodes
    .filter((node) => node.id !== id)
    .map((node) => ({ ...node, children: node.children ? removeNode(node.children, id) : undefined }));
}

function countQuestions(nodes: ProgramNode[]): number {
  return nodes.reduce((total, node) => total + (node.type === "section" ? 0 : 1) + countQuestions(node.children ?? []), 0);
}

function goalLabel(goal: GoalLevelValue): string {
  return GOAL_LEVELS.find((level) => level.value === goal)?.label ?? "понимать";
}

export function Program() {
  const [searchParams] = useSearchParams();
  return searchParams.get("mode") === "textbook" ? <TextbookProgramActive /> : <ExamProgram />;
}

function ExamProgram() {
  const { projectId = "demo" } = useParams();
  const [nodes, setNodes] = useState(NODE_DATA);
  const [selectedId, setSelectedId] = useState("data-models");
  const [expanded, setExpanded] = useState<string[]>(["basics", "relational"]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "sections" | "ungrouped" | "review">("all");
  const [addOpen, setAddOpen] = useState(false);
  const [organizeOpen, setOrganizeOpen] = useState(false);
  const [aiPreview, setAiPreview] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newType, setNewType] = useState<NodeType>("question");
  const [planStale, setPlanStale] = useState(true);
  const selected = findNode(nodes, selectedId) ?? nodes[0];
  const questionCount = countQuestions(nodes);
  const sectionCount = nodes.filter((node) => node.type === "section").length;
  const ungroupedNodes = nodes.filter((node) => node.type !== "section");

  const normalizedQuery = query.trim().toLocaleLowerCase("ru");
  const visibleSections = useMemo(() => nodes.filter((node) => {
    if (node.type !== "section" || filter === "ungrouped") return false;
    if (filter === "review" && !node.children?.some((child) => child.attention)) return false;
    if (!normalizedQuery) return true;
    return node.title.toLocaleLowerCase("ru").includes(normalizedQuery)
      || node.children?.some((child) => child.title.toLocaleLowerCase("ru").includes(normalizedQuery));
  }), [filter, nodes, normalizedQuery]);

  const visibleUngrouped = useMemo(() => ungroupedNodes.filter((node) => {
    if (filter === "sections") return false;
    if (filter === "review" && !node.attention) return false;
    return !normalizedQuery || node.title.toLocaleLowerCase("ru").includes(normalizedQuery);
  }), [filter, normalizedQuery, ungroupedNodes]);

  function toggleExpanded(id: string) {
    setExpanded((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function applyGoal(goal: GoalLevelValue) {
    setNodes((current) => updateNode(current, selected.id, (node) => ({ ...node, goal })));
    setPlanStale(true);
  }

  function addNode() {
    const title = newTitle.trim();
    if (!title) return;
    const id = `draft-${Date.now()}`;
    setNodes((current) => [...current, { id, title, type: newType, goal: "understanding", source: "manual" }]);
    setSelectedId(id);
    setNewTitle("");
    setAddOpen(false);
    setPlanStale(true);
  }

  function deleteNode(node: ProgramNode) {
    setNodes((current) => removeNode(current, node.id));
    if (selected.id === node.id) setSelectedId("data-models");
    setPlanStale(true);
  }

  function applyOrganization() {
    setNodes((current) => current.map((node) => node.id === "transactions" || node.id === "logging"
      ? { ...node, source: "machine" }
      : node));
    setAiPreview(true);
    setOrganizeOpen(false);
  }

  function nodeMenu(node: ProgramNode) {
    return (
      <Menu
        label={`Действия с ${node.title}`}
        trigger={<IconButton label={`Действия с ${node.title}`}><MoreHorizontal size={16} /></IconButton>}
        items={[
          { label: "Открыть в рабочей области", icon: <FileText size={15} />, onSelect: () => setSelectedId(node.id) },
          { label: "Удалить из списка", icon: <Trash2 size={15} />, onSelect: () => deleteNode(node) },
        ]}
      />
    );
  }

  function questionRow(node: ProgramNode, number: string) {
    return (
      <div className={`program-question-row ${selected.id === node.id ? "is-selected" : ""}`.trim()} key={node.id}>
        <button type="button" className="program-question-main" onClick={() => setSelectedId(node.id)}>
          <span className="program-question-number">{number}</span>
          <span className="program-question-copy">
            <strong>{node.title}</strong>
            <small>{NODE_LABEL[node.type]}</small>
          </span>
        </button>
        <span className="program-goal-label"><Target size={14} />{goalLabel(node.goal)}</span>
        {node.attention
          ? <span className="program-review-label"><CircleAlert size={14} />Проверить</span>
          : <span className="program-review-placeholder" />}
        {nodeMenu(node)}
      </div>
    );
  }

  return (
    <div className="program-screen">
      <aside className="program-project-panel">
        <header className="program-project-title">
          <Tooltip label="Вернуться в рабочую область">
            <Link className="workspace-back-button" to={`/projects/${projectId}`} aria-label="Вернуться в рабочую область"><ArrowLeft size={15} /></Link>
          </Tooltip>
          <strong>Базы данных — экзамен</strong>
        </header>
        <nav className="program-quick-filters" aria-label="Быстрые выборки вопросов">
          {[
            ["all", "Все вопросы", questionCount],
            ["sections", "Разделы", sectionCount],
            ["ungrouped", "Без раздела", ungroupedNodes.length],
            ["review", "Требуют проверки", 2],
          ].map(([value, label, amount]) => (
            <button type="button" className={filter === value ? "is-active" : ""} key={value} onClick={() => setFilter(value as typeof filter)}>
              <span>{label}</span><small>{amount}</small>
            </button>
          ))}
        </nav>
        <nav className="workspace-project-nav program-project-nav" aria-label="Разделы проекта">
          <Link className="workspace-project-link" to={`/projects/${projectId}/materials`}><Files size={15} /><span>Материалы</span><small>3</small></Link>
          <span className="workspace-project-link is-active"><ListTree size={15} /><span>Вопросы экзамена</span><small>{questionCount}</small></span>
          <Link className="workspace-project-link" to={`/projects/${projectId}/plan`}><Layers size={15} /><span>План подготовки</span><small>{planStale ? "обновить" : "готов"}</small></Link>
          <Link className="workspace-project-link" to={`/projects/${projectId}/settings`}><Settings size={15} /><span>Настройки</span></Link>
        </nav>
      </aside>

      <main className="program-main">
        <PageHead
          eyebrow="Структура экзамена"
          title="Вопросы экзамена"
          actions={<><Button variant="secondary" onClick={() => setOrganizeOpen(true)}><WandSparkles size={15} /> Разложить по разделам</Button><Button onClick={() => setAddOpen(true)}><Plus size={15} /> Добавить</Button></>}
        />
        <section className="program-metrics" aria-label="Состояние списка вопросов">
          <button type="button" onClick={() => setFilter("all")}><strong>{questionCount}</strong><span>вопросов и задач</span></button>
          <button type="button" onClick={() => setFilter("sections")}><strong>{sectionCount}</strong><span>раздела</span></button>
          <button type="button" onClick={() => setFilter("ungrouped")}><strong>{ungroupedNodes.length}</strong><span>без раздела</span></button>
          <button type="button" onClick={() => setFilter("review")}><strong>2</strong><span>требуют проверки</span></button>
        </section>
        {planStale && <section className="program-plan-notice"><span><Sparkles size={16} /> Список изменился. План подготовки ещё не учитывает последние правки.</span><Link to={`/projects/${projectId}/plan`}>Обновить план</Link></section>}
        <div className="program-toolbar">
          <label className="program-search"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти вопрос" aria-label="Найти вопрос" /></label>
        </div>
        <div className="program-editor-grid">
          <section className="program-outline" aria-label="Структура вопросов экзамена">
            {visibleSections.map((section, sectionIndex) => {
              const ownMatch = normalizedQuery && section.title.toLocaleLowerCase("ru").includes(normalizedQuery);
              const children = (section.children ?? []).filter((child) => {
                if (filter === "review" && !child.attention) return false;
                return ownMatch || !normalizedQuery || child.title.toLocaleLowerCase("ru").includes(normalizedQuery);
              });
              const open = expanded.includes(section.id) || Boolean(normalizedQuery);
              return (
                <article className="program-section-card" key={section.id}>
                  <div className={`program-section-row ${selected.id === section.id ? "is-selected" : ""}`.trim()}>
                    <IconButton label={open ? "Свернуть раздел" : "Раскрыть раздел"} onClick={() => toggleExpanded(section.id)}>
                      {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                    </IconButton>
                    <button type="button" className="program-section-main" onClick={() => setSelectedId(section.id)}>
                      <span className="program-section-index">{sectionIndex + 1}</span>
                      <span><strong>{section.title}</strong><small>{section.children?.length ?? 0} элементов</small></span>
                    </button>
                    <span className="program-goal-label"><Target size={14} />{goalLabel(section.goal)}</span>
                    {nodeMenu(section)}
                  </div>
                  {open && <div className="program-section-children">{children.map((child, childIndex) => questionRow(child, `${sectionIndex + 1}.${childIndex + 1}`))}</div>}
                </article>
              );
            })}
            {visibleUngrouped.length > 0 && (
              <article className="program-section-card is-ungrouped">
                <div className="program-ungrouped-head"><span><Layers size={16} />Без раздела</span><small>{visibleUngrouped.length} вопроса</small></div>
                <div className="program-section-children">{visibleUngrouped.map((node, index) => questionRow(node, `—${index + 1}`))}</div>
              </article>
            )}
          </section>
          <aside className="program-inspector" aria-label="Свойства выбранного узла">
            <p className="eyebrow">Свойства</p>
            <h2>{selected.title}</h2>
            {selected.source === "machine" && <MachineMark origin="предложено моделью" onUndo={() => setNodes((current) => updateNode(current, selected.id, (node) => ({ ...node, source: "manual" })))} />}
            <Field label="Формулировка">
              <input value={selected.title} onChange={(event) => setNodes((current) => updateNode(current, selected.id, (node) => ({ ...node, title: event.target.value })))} />
            </Field>
            <SegmentedTabs label="Тип узла" value={selected.type} onChange={(type) => { setNodes((current) => updateNode(current, selected.id, (node) => ({ ...node, type }))); setPlanStale(true); }} tabs={Object.entries(NODE_LABEL).map(([value, label]) => ({ value: value as NodeType, label }))} />
            <GoalLevelPicker label={selected.type === "section" ? "раздела" : "вопроса"} value={selected.goal} onChange={applyGoal} />
            <section className="program-impact"><h3>Что связано</h3><dl><div><dt>Эталон</dt><dd>есть, проверить после правки</dd></div><div><dt>Материалы</dt><dd>3 фрагмента</dd></div><div><dt>План</dt><dd>день 2</dd></div></dl></section>
            <div className="program-inspector-links"><Link to={`/projects/${projectId}`}>Открыть рабочую область</Link><Link to={`/projects/${projectId}/materials`}>Показать материалы</Link></div>
          </aside>
        </div>
      </main>

      <Dialog open={addOpen} onOpenChange={setAddOpen} title="Добавить в экзамен" description="Новый элемент появится в списке и попадёт в План после его обновления." footer={<><Button variant="ghost" onClick={() => setAddOpen(false)}>Отменить</Button><Button disabled={!newTitle.trim()} onClick={addNode}>Добавить</Button></>}>
        <Field label="Формулировка" required><input autoFocus value={newTitle} onChange={(event) => setNewTitle(event.target.value)} placeholder="Например, индексы и B-деревья" /></Field>
        <SegmentedTabs label="Тип нового узла" value={newType} onChange={setNewType} tabs={[{ value: "question", label: "Вопрос" }, { value: "task", label: "Задача" }, { value: "section", label: "Раздел" }, { value: "ticket", label: "Билет" }]} />
      </Dialog>
      <Dialog open={organizeOpen} onOpenChange={setOrganizeOpen} title="Разложить вопросы по разделам" description="Модель предложит структуру, но не изменит список без вашего выбора." footer={<><Button variant="ghost" onClick={() => setOrganizeOpen(false)}>Отменить</Button><Button onClick={applyOrganization}><Sparkles size={15} /> Получить предложение</Button></>}>
        <p className="program-dialog-copy">Отправим формулировки вопросов без раздела, текущий порядок и названия разделов. Полные материалы и личные конспекты не отправляются.</p>
        <CostEstimate calls={1} cost={0.01} minutes={1} pricesFrom="01.08.2026" units={`${ungroupedNodes.length} вопроса`} />
      </Dialog>
      <Dialog open={aiPreview} onOpenChange={setAiPreview} title="Предложенная структура" description="Сначала проверьте изменения, затем примените их." footer={<Button variant="secondary" onClick={() => setAiPreview(false)}>Закрыть</Button>}>
        <div className="program-ai-preview"><MachineMark origin="предложено моделью" onUndo={() => setAiPreview(false)} /><p>«Транзакции и свойства ACID» и «Журнализация и восстановление» можно объединить в раздел «Управление транзакциями».</p><Button onClick={() => { setNodes((current) => [{ id: "transactions-section", title: "Управление транзакциями", type: "section", goal: "application", source: "machine", children: current.filter((node) => node.id === "transactions" || node.id === "logging") }, ...current.filter((node) => node.id !== "transactions" && node.id !== "logging")]); setPlanStale(true); setAiPreview(false); }}>Применить предложение</Button></div>
      </Dialog>
    </div>
  );
}
