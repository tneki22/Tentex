import { useMemo, useState } from "react";
import { Link } from "react-router";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  BookOpen,
  Check,
  CircleAlert,
  Copy,
  FileText,
  Filter,
  MessageSquare,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  Undo2,
  UploadCloud,
  WandSparkles,
  X,
} from "lucide-react";
import { DEMO_TEXTBOOK_PROJECT_ID } from "../app/screens";
import {
  Button,
  Card,
  Checkbox,
  Disclosure,
  Field,
  IconButton,
  Progress,
  SegmentedTabs,
  StatusBadge,
  Switch,
} from "../components/ui";
import { CostEstimate, MachineMark, OfflineNotice, SourceChip } from "../components/domain";

type SourceRole = "main" | "additional" | "reference";
type Scope = "whole" | "goal";
type ProgramView = "tree" | "text" | "questions";
type GenerationState = "building" | "ready";
type ProposalState = "pending" | "accepted" | "rejected";

interface TextbookSource {
  id: string;
  name: string;
  meta: string;
  role: SourceRole;
  note: string;
  warning?: string;
}

interface ProgramRow {
  id: string;
  number: string;
  depth: number;
  title: string;
  purpose: "цель" | "предпосылка" | "смежная";
  source: string;
  pages?: string;
  missing?: boolean;
  outside?: boolean;
  manual?: boolean;
}

const STEPS = ["Источники", "Профиль", "Проверка", "Программа", "Итог"];

const ROLE_LABELS: Record<SourceRole, string> = {
  main: "Основной",
  additional: "Дополнительный",
  reference: "Справочный",
};

const INITIAL_SOURCES: TextbookSource[] = [
  {
    id: "db-book",
    name: "Архитектура систем баз данных.pdf",
    meta: "PDF · 486 стр. · текстовый слой",
    role: "main",
    note: "Строить основную последовательность по этому учебнику, но не копировать оглавление буквально.",
  },
  {
    id: "vector-notes",
    name: "Векторные базы данных — методичка.pdf",
    meta: "PDF · 74 стр. · потребуется OCR",
    role: "additional",
    note: "Использовать для примеров HNSW, IVFFlat и настройки поиска.",
    warning: "Скан: возможны ошибки OCR в формулах и псевдокоде",
  },
];

const INITIAL_PROGRAM: ProgramRow[] = [
  { id: "storage", number: "1", depth: 0, title: "Как СУБД хранит и находит данные", purpose: "предпосылка", source: "Архитектура систем баз данных", pages: "с. 41–67" },
  { id: "index-basics", number: "1.1", depth: 1, title: "Назначение индексов и цена ускорения чтения", purpose: "предпосылка", source: "Архитектура систем баз данных", pages: "с. 188–204" },
  { id: "vectors", number: "2", depth: 0, title: "Векторный поиск и меры близости", purpose: "цель", source: "Векторные базы данных — методичка", pages: "с. 8–19" },
  { id: "ann", number: "2.1", depth: 1, title: "Приближённый поиск ближайших соседей", purpose: "цель", source: "Векторные базы данных — методичка", pages: "с. 20–31" },
  { id: "hnsw", number: "2.2", depth: 1, title: "HNSW: построение графа и параметры поиска", purpose: "цель", source: "", missing: true },
  { id: "ivf", number: "2.3", depth: 1, title: "IVF и IVFFlat: кластеризация пространства", purpose: "смежная", source: "Векторные базы данных — методичка", pages: "с. 44–55" },
  { id: "relational", number: "3", depth: 0, title: "Реляционные индексы и B-деревья", purpose: "смежная", source: "Архитектура систем баз данных", pages: "с. 205–238", outside: true },
];

export function TextbookWizard({ onBackToTracks }: { onBackToTracks: () => void }) {
  const [step, setStep] = useState(1);
  const [maxStep, setMaxStep] = useState(1);
  const [created, setCreated] = useState(false);
  const [sources, setSources] = useState(INITIAL_SOURCES);
  const [projectName, setProjectName] = useState("Индексы в векторных базах данных");
  const [subject, setSubject] = useState("Базы данных");
  const [nameSuggested, setNameSuggested] = useState(true);
  const [subjectSuggested, setSubjectSuggested] = useState(true);
  const [scope, setScope] = useState<Scope>("goal");
  const [goal, setGoal] = useState("Хочу разобраться, когда применять HNSW и IVFFlat, как выбирать параметры и оценивать компромисс между скоростью, памятью и качеством поиска.");
  const [startingLevel, setStartingLevel] = useState("Знаю SQL и обычные индексы, но векторный поиск раньше не настраивал.");
  const [outcome, setOutcome] = useState("Уметь выбрать тип индекса под задачу и объяснить решение.");
  const [successCriterion, setSuccessCriterion] = useState("Смогу самостоятельно сравнить HNSW и IVFFlat на трёх практических сценариях.");
  const [important, setImportant] = useState("Практические параметры, ограничения памяти и типичные ошибки.");
  const [skip, setSkip] = useState("Глубокие доказательства сложности алгоритмов.");
  const [deadline, setDeadline] = useState("2026-09-30");
  const [minutes, setMinutes] = useState(45);
  const [daysPerWeek, setDaysPerWeek] = useState(4);
  const [sessionMinutes, setSessionMinutes] = useState(35);
  const [studyFormat, setStudyFormat] = useState<"theory" | "mixed" | "practice">("mixed");
  const [externalModels, setExternalModels] = useState(true);
  const [generation, setGeneration] = useState<GenerationState>("building");
  const [background, setBackground] = useState(false);
  const [offlineBuilt, setOfflineBuilt] = useState(false);
  const [programView, setProgramView] = useState<ProgramView>("tree");
  const [programRows, setProgramRows] = useState(INITIAL_PROGRAM);
  const [selectedId, setSelectedId] = useState("hnsw");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [missingOnly, setMissingOnly] = useState(false);
  const [chatScope, setChatScope] = useState("Вся программа");
  const [chatText, setChatText] = useState("");
  const [lastChatText, setLastChatText] = useState("");
  const [proposalState, setProposalState] = useState<ProposalState>("pending");
  const [proposalItems, setProposalItems] = useState([true, true]);

  const selected = programRows.find((row) => row.id === selectedId) ?? programRows[0];
  const visibleRows = useMemo(() => programRows.filter((row) => {
    if (missingOnly && !row.missing) return false;
    return !query.trim() || row.title.toLocaleLowerCase("ru").includes(query.trim().toLocaleLowerCase("ru"));
  }), [missingOnly, programRows, query]);

  function go(next: number) {
    setStep(next);
    setMaxStep((current) => Math.max(current, next));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function updateSource(id: string, patch: Partial<TextbookSource>) {
    setSources((current) => current.map((source) => source.id === id ? { ...source, ...patch } : source));
  }

  function moveSource(id: string, direction: -1 | 1) {
    setSources((current) => {
      const index = current.findIndex((source) => source.id === id);
      const nextIndex = index + direction;
      if (index < 0 || nextIndex < 0 || nextIndex >= current.length) return current;
      const next = [...current];
      [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
      return next;
    });
  }

  function addDemoSource() {
    if (sources.some((source) => source.id === "linux-notes")) return;
    setSources((current) => [...current, {
      id: "linux-notes",
      name: "Конспект по устройству Linux.md",
      meta: "MD · 38 стр. · текстовый слой",
      role: "reference",
      note: "Использовать только для аналогий с файловыми структурами.",
    }]);
  }

  function beginProgram() {
    setOfflineBuilt(!externalModels);
    setGeneration("building");
    go(4);
  }

  function addTopic(title = "Новая тема") {
    const row: ProgramRow = {
      id: `manual-${Date.now()}`,
      number: `${programRows.length + 1}`,
      depth: 0,
      title,
      purpose: "смежная",
      source: "",
      manual: true,
    };
    setProgramRows((current) => [...current, row]);
    setSelectedId(row.id);
    setEditingId(row.id);
  }

  function updateSelected(patch: Partial<ProgramRow>) {
    setProgramRows((current) => current.map((row) => row.id === selectedId ? { ...row, ...patch } : row));
  }

  function moveSelected(direction: -1 | 1) {
    setProgramRows((current) => {
      const index = current.findIndex((row) => row.id === selectedId);
      const nextIndex = index + direction;
      if (index < 0 || nextIndex < 0 || nextIndex >= current.length) return current;
      const next = [...current];
      [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
      return next;
    });
  }

  function duplicateSelected() {
    if (!selected) return;
    const copy = { ...selected, id: `copy-${Date.now()}`, title: `${selected.title} — копия`, manual: true };
    const index = programRows.findIndex((row) => row.id === selected.id);
    setProgramRows((current) => [...current.slice(0, index + 1), copy, ...current.slice(index + 1)]);
    setSelectedId(copy.id);
  }

  function deleteSelected() {
    setProgramRows((current) => current.filter((row) => row.id !== selectedId));
    setSelectedId(programRows.find((row) => row.id !== selectedId)?.id ?? "");
  }

  function acceptProposal() {
    if (proposalItems[0] && !programRows.some((row) => row.id === "quality-metrics")) {
      setProgramRows((current) => [...current, {
        id: "quality-metrics",
        number: "2.4",
        depth: 1,
        title: "Метрики качества и скорости векторного поиска",
        purpose: "цель",
        source: "Векторные базы данных — методичка",
        pages: "с. 61–68",
      }]);
    }
    setProposalState("accepted");
  }

  function undoProposal() {
    setProgramRows((current) => current.filter((row) => row.id !== "quality-metrics"));
    setProposalState("pending");
  }

  function submitChat() {
    if (!chatText.trim()) return;
    setLastChatText(chatText.trim());
    setChatText("");
    setProposalState("pending");
  }

  if (created) {
    return (
      <div className="project-wizard textbook-wizard is-success">
        <div className="wizard-success-card">
          <h1>Создан проект: {projectName}</h1>
          <p>Профиль, источники и утверждённая программа сохранены.</p>
          <p className="wizard-success-next">Проход 2 уже начался в фоне: он привяжет все блоки материалов к темам программы.</p>
          <div className="wizard-success-actions">
            <Link className="primary-button" to={`/projects/${DEMO_TEXTBOOK_PROJECT_ID}/program?mode=textbook`}>Открыть программу</Link>
            <Button variant="ghost" onClick={() => setCreated(false)}>Вернуться к сводке</Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="project-wizard textbook-wizard">
      <header className="wizard-topbar">
        <Link className="wizard-back-projects" to="/projects"><ArrowLeft size={16} />К проектам</Link>
        <span className="wizard-brand"><Sparkles size={17} />Tentex</span>
        <span className="wizard-step-caption">Учебник — шаг {step} из 5 · черновик сохранён</span>
      </header>

      <nav className="wizard-progress" aria-label="Шаги создания проекта по учебнику">
        <span className="wizard-progress-line" aria-hidden="true"><i style={{ width: `${((step - 1) / 4) * 100}%` }} /></span>
        {STEPS.map((label, index) => {
          const itemStep = index + 1;
          return (
            <button
              type="button"
              key={label}
              className={`${itemStep === step ? "is-current" : ""} ${itemStep < step ? "is-complete" : ""}`.trim()}
              disabled={itemStep > maxStep}
              aria-current={itemStep === step ? "step" : undefined}
              onClick={() => go(itemStep)}
            >
              <span>{itemStep < step ? <Check size={13} strokeWidth={3} /> : itemStep}</span>
              <small>{label}</small>
            </button>
          );
        })}
      </nav>

      <main className={`wizard-main ${step === 4 ? "is-textbook-editor" : ""}`.trim()}>
        {step === 1 && (
          <section className="wizard-section is-wide textbook-step">
            <StepHead eyebrow="Источники и цель" title="Добавьте материалы, на которых строить программу" description="Система прочитает первые страницы и оглавление. Полный разбор начнётся только после подтверждения." />

            <Card className="textbook-dropzone">
              <UploadCloud size={24} aria-hidden="true" />
              <span><b>Перетащите учебники, методички, конспекты или статьи</b><small>PDF, DOCX, TXT, MD и изображения · до 100 МБ и 500 страниц на файл</small></span>
              <Button variant="secondary" onClick={addDemoSource}>Добавить пример</Button>
            </Card>

            <div className="textbook-source-list">
              {sources.length === 0 && <Card className="textbook-empty-source">Источников пока нет. Добавьте хотя бы один материал.</Card>}
              {sources.map((source, index) => (
                <Card className="textbook-source-card" key={source.id}>
                  <div className="textbook-source-main">
                    <span className="textbook-source-icon"><FileText size={18} /></span>
                    <span className="textbook-source-copy">
                      <b>{source.name}</b>
                      <small>{source.meta}</small>
                      {source.warning && <em><CircleAlert size={13} />{source.warning}</em>}
                    </span>
                    {source.id === "vector-notes"
                      ? <span className="textbook-source-progress"><small>Анализируется · 42%</small><Progress value={42} max={100} label={`Анализ материала ${source.name}`} size="thin" /></span>
                      : <StatusBadge tone="success">проанализирован</StatusBadge>}
                    <label className="textbook-role-select">
                      <span>Роль</span>
                      <select value={source.role} onChange={(event) => updateSource(source.id, { role: event.target.value as SourceRole })}>
                        <option value="main">Основной</option>
                        <option value="additional">Дополнительный</option>
                        <option value="reference">Справочный</option>
                      </select>
                    </label>
                    <span className="textbook-source-actions">
                      <IconButton label="Поднять приоритет" disabled={index === 0} onClick={() => moveSource(source.id, -1)}><ArrowUp size={15} /></IconButton>
                      <IconButton label="Опустить приоритет" disabled={index === sources.length - 1} onClick={() => moveSource(source.id, 1)}><ArrowDown size={15} /></IconButton>
                      <IconButton label="Удалить источник" onClick={() => setSources((current) => current.filter((item) => item.id !== source.id))}><X size={15} /></IconButton>
                    </span>
                  </div>
                  <Disclosure summary="Как использовать этот источник">
                    <textarea value={source.note} onChange={(event) => updateSource(source.id, { note: event.target.value })} aria-label={`Как использовать ${source.name}`} />
                  </Disclosure>
                </Card>
              ))}
            </div>

            <Card className="textbook-analysis-card">
              <div className="textbook-analysis-head"><WandSparkles size={18} /><span><b>Что поняла система</b><small>Предложено по первым страницам и оглавлениям</small></span></div>
              <dl>
                <div><dt>Предмет</dt><dd>Базы данных и информационный поиск</dd></div>
                <div><dt>О чём материалы</dt><dd>Архитектура хранения, классические и векторные индексы, настройка поиска.</dd></div>
                <div><dt>Найдены разделы</dt><dd>11 глав · 46 подразделов · русский язык</dd></div>
              </dl>
              <p><CircleAlert size={14} />В методичке есть сканированные страницы. Формулы и псевдокод могут распознаться с ошибками — проверим их по изображению страницы.</p>
            </Card>

            <StepActions backLabel="К выбору пути" onBack={onBackToTracks} nextLabel="Продолжить к профилю" onNext={() => go(2)} disabled={sources.length === 0} />
          </section>
        )}

        {step === 2 && (
          <section className="wizard-section is-wide textbook-step">
            <StepHead eyebrow="Профиль проекта" title="Чему именно вы хотите научиться?" description="Предложенные поля можно исправить. Свободный текст станет главным контекстом при построении программы." />
            <div className="textbook-profile-grid">
              <Card className="textbook-profile-card is-goal">
                <header><BookOpen size={18} /><span><h2>Что изучать</h2><p>Источник задаёт границы, ваша цель — нужный маршрут.</p></span></header>
                <div className="textbook-profile-fields">
                  <Field label="Название проекта" suggested={nameSuggested}><input value={projectName} onChange={(event) => { setProjectName(event.target.value); setNameSuggested(false); }} /></Field>
                  <Field label="Предмет" suggested={subjectSuggested}><input value={subject} onChange={(event) => { setSubject(event.target.value); setSubjectSuggested(false); }} /></Field>
                  <SegmentedTabs label="Охват программы" value={scope} onChange={setScope} tabs={[{ value: "whole", label: "Весь материал" }, { value: "goal", label: "Конкретная цель" }]} />
                  {scope === "goal" && <Field label="Ваша цель" hint="Опишите задачу своими словами: система добавит цель, предпосылки и смежные темы."><textarea rows={5} value={goal} onChange={(event) => setGoal(event.target.value)} /></Field>}
                  <Field label="Что вы уже знаете"><textarea rows={3} value={startingLevel} onChange={(event) => setStartingLevel(event.target.value)} /></Field>
                  <Field label="Желаемый результат"><textarea rows={2} value={outcome} onChange={(event) => setOutcome(event.target.value)} /></Field>
                  <Field label="Как поймёте, что цель достигнута"><textarea rows={2} value={successCriterion} onChange={(event) => setSuccessCriterion(event.target.value)} /></Field>
                  <Field label="Что особенно важно"><textarea rows={2} value={important} onChange={(event) => setImportant(event.target.value)} /></Field>
                  <Field label="Что можно пропустить"><textarea rows={2} value={skip} onChange={(event) => setSkip(event.target.value)} /></Field>
                </div>
              </Card>

              <Card className="textbook-profile-card">
                <header><Sparkles size={18} /><span><h2>Как учиться</h2><p>Темп можно изменить после создания проекта.</p></span></header>
                <div className="textbook-profile-fields">
                  <Field label="Срок" hint="Необязательно"><input type="date" value={deadline} onChange={(event) => setDeadline(event.target.value)} /></Field>
                  <div className="textbook-number-grid">
                    <Field label="Минут в день" hint="Необязательно"><input type="number" min={10} step={5} value={minutes} onChange={(event) => setMinutes(Number(event.target.value))} /></Field>
                    <Field label="Дней в неделю" hint="Необязательно"><input type="number" min={1} max={7} value={daysPerWeek} onChange={(event) => setDaysPerWeek(Number(event.target.value))} /></Field>
                    <Field label="Мин. на занятие" hint="Необязательно"><input type="number" min={10} step={5} value={sessionMinutes} onChange={(event) => setSessionMinutes(Number(event.target.value))} /></Field>
                  </div>
                  <SegmentedTabs label="Формат занятий" value={studyFormat} onChange={setStudyFormat} tabs={[{ value: "theory", label: "Теория" }, { value: "mixed", label: "Смешанный" }, { value: "practice", label: "Практика" }]} />
                  <div className="textbook-source-summary">
                    <b>Роли источников</b>
                    {sources.map((source, index) => <span key={source.id}><i>{index + 1}</i>{source.name}<small>{ROLE_LABELS[source.role]}</small></span>)}
                    <Button variant="ghost" onClick={() => go(1)}>Изменить источники</Button>
                  </div>
                </div>
              </Card>
            </div>
            <StepActions backLabel="К источникам" onBack={() => go(1)} nextLabel="Проверить запуск" onNext={() => go(3)} disabled={!projectName.trim() || !subject.trim() || (scope === "goal" && !goal.trim())} />
          </section>
        )}

        {step === 3 && (
          <section className="wizard-section textbook-step textbook-preflight">
            <StepHead eyebrow="Перед построением" title="Проверьте, что будет обработано" description="Текст материалов останется на вашем компьютере. Вы сами выбираете, использовать ли автоматическое составление программы." />
            <Card className="textbook-preflight-card">
              <div className="textbook-preflight-summary"><b>{projectName}</b><p><strong>Ваша цель:</strong> {scope === "goal" ? goal : "изучить весь основной материал."}</p><p><strong>Тема, которую вы изучаете:</strong> {subject}</p></div>
              <div className="textbook-preflight-list">
                <section><h3>Источники</h3>{sources.map((source, index) => <p key={source.id}><span>{index + 1}</span>{source.name}<small>{ROLE_LABELS[source.role]}</small></p>)}</section>
                <section className="is-processing-copy"><h3>Обработка на вашем компьютере</h3><p>Локально будут обработаны 17 глав: система извлечёт текст и оглавление, сохранит страницы и отметит места, где качество OCR требует проверки.</p></section>
                <section className="is-processing-copy"><h3>Автоматическое составление программы с внешней моделью</h3><p>Система сопоставит содержание глав с вашей целью, предложит последовательность тем, необходимые предпосылки и связи между разделами. Поиск материалов в интернете выполняться не будет.</p></section>
              </div>
              <Switch checked={externalModels} onCheckedChange={setExternalModels} label="Автоматическое составление программы с внешней моделью" hint="Если выключить, черновик будет собран локально по оглавлениям и заголовкам." />
              {externalModels
                ? <CostEstimate calls={9} cost={0.18} minutes={4} pricesFrom="01.08.2026" units="17 глав" />
                : <OfflineNotice reason="disabled" alternative="Черновик будет собран по оглавлениям и заголовкам; связи с целью придётся проверить вручную." />}
              <p className="textbook-preflight-warning"><CircleAlert size={14} />В одном PDF потребуется OCR. Формулы и псевдокод могут содержать ошибки распознавания.</p>
            </Card>
            <StepActions backLabel="К профилю" onBack={() => go(2)} nextLabel="Построить программу" onNext={beginProgram} />
          </section>
        )}

        {step === 4 && (
          <section className="textbook-builder">
            <header className="textbook-builder-head">
              <Button variant="ghost" onClick={() => go(2)}><ArrowLeft size={15} />Профиль</Button>
              <span><b>{projectName}</b><small>{generation === "ready" ? background ? "Черновик готов · дополнение идёт в фоне" : offlineBuilt ? "Собрано по оглавлению" : "Черновик программы готов" : "Черновик появляется по мере обработки материалов"}</small></span>
              <StatusBadge tone={generation === "ready" ? "success" : "info"}>{generation === "ready" ? "готово к проверке" : "обработка"}</StatusBadge>
              <Button variant="ghost" disabled={generation === "building"} onClick={() => { setProgramRows(INITIAL_PROGRAM); setProposalState("pending"); }}><Undo2 size={15} />Отменить</Button>
              <Button variant="secondary" onClick={() => { setBackground(true); setGeneration("ready"); }}>Продолжить в фоне</Button>
              <Button disabled={generation !== "ready"} onClick={() => go(5)}>Утвердить программу</Button>
            </header>

            <div className="textbook-builder-grid">
              <div className="textbook-program-panel">
                {generation === "building" && (
                  <div className="textbook-generation-banner">
                    <span><WandSparkles size={18} /><b>Проход ИИ по материалам №1</b><small>Обработано 7 из 17 глав. Уже готовые разделы не пропадут при ошибке.</small></span>
                    <Progress value={7} max={17} label="Построение программы" />
                    <div><Button variant="secondary" onClick={() => setGeneration("ready")}>Принять частичный результат</Button><Button variant="ghost" onClick={() => { setOfflineBuilt(true); setGeneration("ready"); }}>Собрать по оглавлению</Button><Button variant="ghost"><RefreshCw size={14} />Повторить упавшую главу</Button></div>
                  </div>
                )}

                <div className="textbook-program-toolbar">
                  <SegmentedTabs label="Представление программы" value={programView} onChange={setProgramView} tabs={[{ value: "tree", label: "Дерево" }, { value: "text", label: "Текст" }, { value: "questions", label: "Вопросы" }]} />
                  <label className="textbook-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти тему" /></label>
                  <Button variant="secondary" onClick={() => addTopic()}><Plus size={15} />Добавить тему</Button>
                  <Button variant={missingOnly ? "primary" : "ghost"} onClick={() => setMissingOnly((current) => !current)}><Filter size={15} />Нужно найти материал</Button>
                </div>

                <div className="textbook-manual-toolbar" aria-label="Ручные действия с темой">
                  <span>Выбрано: <b>{selected?.title}</b></span>
                  <IconButton label="Поднять тему" onClick={() => moveSelected(-1)}><ArrowUp size={15} /></IconButton>
                  <IconButton label="Опустить тему" onClick={() => moveSelected(1)}><ArrowDown size={15} /></IconButton>
                  <IconButton label="Уменьшить вложенность" onClick={() => updateSelected({ depth: Math.max(0, selected.depth - 1) })}><ArrowLeft size={15} /></IconButton>
                  <IconButton label="Увеличить вложенность" onClick={() => updateSelected({ depth: Math.min(3, selected.depth + 1) })}><ArrowRight size={15} /></IconButton>
                  <IconButton label="Редактировать формулировку" onClick={() => setEditingId(selectedId)}><Pencil size={15} /></IconButton>
                  <IconButton label="Дублировать тему" onClick={duplicateSelected}><Copy size={15} /></IconButton>
                  <IconButton label="Удалить тему" onClick={deleteSelected}><Trash2 size={15} /></IconButton>
                </div>

                <div className="textbook-program-content">
                  {programView === "tree" && visibleRows.map((row) => (
                    <div className={`textbook-program-row ${selectedId === row.id ? "is-selected" : ""} ${row.outside ? "is-outside" : ""}`.trim()} key={row.id} style={{ paddingLeft: `calc(var(--space-4) + ${row.depth} * var(--space-6))` }} onClick={() => setSelectedId(row.id)}>
                      <span className="textbook-program-number">{row.number}</span>
                      <span className="textbook-program-copy">
                        {editingId === row.id
                          ? <input autoFocus value={row.title} onChange={(event) => setProgramRows((current) => current.map((item) => item.id === row.id ? { ...item, title: event.target.value } : item))} onBlur={() => setEditingId(null)} onKeyDown={(event) => event.key === "Enter" && setEditingId(null)} />
                          : <b>{row.title}</b>}
                        <small>{row.purpose}{row.outside ? " · вне текущей программы" : ""}</small>
                      </span>
                      <span className="textbook-program-source">
                        {row.missing ? <><SourceChip source={{ kind: "none" }} /><b>Нужно найти материал по теме</b><Button variant="ghost" onClick={(event) => { event.stopPropagation(); go(1); }}>Добавить материал</Button></> : <><span className="textbook-source-chip">{row.source}</span><span className="textbook-pages-chip">{row.pages ?? "страницы не указаны"}</span></>}
                      </span>
                    </div>
                  ))}
                  {programView === "text" && <article className="textbook-text-view"><h2>{projectName}</h2>{visibleRows.map((row) => <p key={row.id} className={row.outside ? "is-outside" : ""}><b>{row.number}. {row.title}</b>{row.missing ? " — Нужно найти материал по теме." : ` — ${row.purpose}; ${row.source}, ${row.pages ?? "раздел"}.`}</p>)}</article>}
                  {programView === "questions" && <ol className="textbook-question-view">{visibleRows.filter((row) => row.depth > 0).map((row) => <li key={row.id}>Как объяснить: «{row.title}»?{row.missing && <small>Нужно найти материал по теме</small>}</li>)}</ol>}
                </div>
              </div>

              <aside className="textbook-assistant">
                <header><span><MessageSquare size={17} /><b>Помощник по программе</b></span><label>Контекст<select value={chatScope} onChange={(event) => setChatScope(event.target.value)}><option>Вся программа</option><option>Выбранный раздел</option><option>Выбранная тема</option></select></label></header>
                <div className="textbook-chat-body">
                  {generation === "building" ? (
                    <div className="textbook-chat-locked"><WandSparkles size={24} /><b>Сначала закончим черновик программы</b><p>Пока можно проверить появившиеся разделы или принять частичный результат.</p></div>
                  ) : (
                    <>
                      <div className="textbook-chat-message is-assistant">Я сопоставил цель с обоими источниками. Для уверенного выбора индекса не хватает отдельной темы о метриках качества поиска. По HNSW стоит загрузить ещё один материал: в текущих файлах есть только краткое упоминание.</div>
                      {lastChatText && <div className="textbook-chat-message is-user">{lastChatText}</div>}
                      <Card className={`textbook-diff-card is-${proposalState}`}>
                        <header><Sparkles size={15} /><span><b>Предложение к программе</b><small>Ничего не изменится до подтверждения</small></span></header>
                        <Checkbox checked={proposalItems[0]} onCheckedChange={(checked) => setProposalItems(([_, second]) => [checked, second])} label="Добавить «Метрики качества и скорости поиска» после IVFFlat" />
                        <Checkbox checked={proposalItems[1]} onCheckedChange={(checked) => setProposalItems(([first]) => [first, checked])} label="Пометить HNSW как тему, для которой нужен дополнительный материал" />
                        <p>Зачем: обе темы нужны для вашего критерия успеха, но оглавление основного учебника их не покрывает.</p>
                        {proposalState === "pending" && <div><Button onClick={acceptProposal}>Принять выбранное</Button><Button variant="ghost" onClick={() => setProposalState("rejected")}>Отклонить</Button></div>}
                        {proposalState === "accepted" && <div><StatusBadge tone="success">принято</StatusBadge><Button variant="ghost" onClick={undoProposal}><Undo2 size={14} />Отменить</Button></div>}
                        {proposalState === "rejected" && <div><StatusBadge>отклонено</StatusBadge><Button variant="ghost" onClick={() => setProposalState("pending")}>Вернуть предложение</Button></div>}
                      </Card>
                    </>
                  )}
                </div>
                <footer><textarea value={chatText} onChange={(event) => setChatText(event.target.value)} placeholder="Например: добавь практическое сравнение HNSW и IVFFlat" disabled={generation === "building"} /><Button onClick={submitChat} disabled={generation === "building" || !chatText.trim()}><ArrowUp size={15} />Отправить</Button><small>Помощник меняет программу только через подтверждаемый диф. Автопоиска в интернете нет.</small></footer>
              </aside>
            </div>
          </section>
        )}

        {step === 5 && (
          <section className="wizard-section textbook-step textbook-summary">
            <StepHead eyebrow="Итог" title="Проект готов к созданию" description="Проверьте цель, источники и программу. После создания их можно будет изменить." />
            <Card className="textbook-summary-story">
              <h2>{projectName}</h2>
              <p><b>Ваша цель:</b> {goal}</p>
              <p>До {new Date(`${deadline}T00:00:00`).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" })} запланировано {minutes} минут в день, {daysPerWeek} дня в неделю, занятиями примерно по {sessionMinutes} минут.</p>
              <p><b>Критерий успеха:</b> {successCriterion}</p>
            </Card>
            <Card className="textbook-summary-card"><h3>Источники</h3>{sources.map((source, index) => <div key={source.id}><span>{index + 1}</span><b>{source.name}</b><small>{ROLE_LABELS[source.role]} · приоритет {index + 1}</small></div>)}</Card>
            <Card className="textbook-summary-card"><h3>Программа</h3><dl className="textbook-summary-metrics"><div className="is-sections"><dt>Разделы</dt><dd>{programRows.filter((row) => row.depth === 0).length}</dd></div><div className="is-topics"><dt>Темы</dt><dd>{programRows.length}</dd></div><div className="is-missing"><dt>Нужно найти материал</dt><dd>{programRows.filter((row) => row.missing).length}</dd></div><div className="is-outside"><dt>Вне текущей программы</dt><dd>{programRows.filter((row) => row.outside).length}</dd></div></dl>{programRows.slice(0, 5).map((row) => <div key={row.id} className={row.missing ? "is-missing" : ""}><span>{row.number}</span><b>{row.title}</b>{row.missing && <small>Нужно найти материал по теме</small>}</div>)}</Card>
            <Card className="textbook-summary-card"><h3>Что произойдёт после создания</h3><p>Откроется рабочая программа: по ней можно сразу переходить к темам и занятиям, а формулировки и порядок разделов менять вручную. В фоне система продолжит разбирать материалы и связывать их фрагменты с подходящими темами. Если для темы пока нет источника, она останется в программе с понятной отметкой.</p></Card>
            <StepActions backLabel="Вернуться к программе" onBack={() => go(4)} nextLabel="Создать проект" onNext={() => setCreated(true)} />
          </section>
        )}
      </main>
    </div>
  );
}

function StepHead({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  return <div className="wizard-section-head"><span>{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>;
}

function StepActions({ backLabel, onBack, nextLabel, onNext, disabled = false }: { backLabel: string; onBack: () => void; nextLabel: string; onNext: () => void; disabled?: boolean }) {
  return <div className="wizard-actions"><Button variant="ghost" onClick={onBack}><ArrowLeft size={15} />{backLabel}</Button><span className="wizard-actions-spacer" /><Button onClick={onNext} disabled={disabled}>{nextLabel}<ArrowRight size={15} /></Button></div>;
}

export function TextbookProgramActive() {
  const [view, setView] = useState<ProgramView>("tree");

  return (
    <div className="textbook-active-program">
      <header className="textbook-active-head">
        <Link to={`/projects/${DEMO_TEXTBOOK_PROJECT_ID}`}><ArrowLeft size={15} />В рабочую область</Link>
        <span><b>Индексы в векторных базах данных</b><small>Программа активного проекта</small></span>
        <StatusBadge tone="success">программа утверждена</StatusBadge>
        <Button variant="secondary">Пересобрать программу</Button>
      </header>
      <div className="textbook-active-grid">
        <section className="textbook-active-list">
          <div className="textbook-program-toolbar">
            <SegmentedTabs label="Представление программы" value={view} onChange={setView} tabs={[{ value: "tree", label: "Дерево" }, { value: "text", label: "Текст" }, { value: "questions", label: "Вопросы" }]} />
            <label className="textbook-search"><Search size={15} /><input placeholder="Найти тему" /></label>
            <Button variant="secondary"><Plus size={15} />Добавить тему</Button>
          </div>
          <div className="textbook-program-content">
            {view === "tree" && INITIAL_PROGRAM.map((row) => (
              <div className={`textbook-program-row ${row.outside ? "is-outside" : ""}`.trim()} key={row.id} style={{ paddingLeft: `calc(var(--space-4) + ${row.depth} * var(--space-6))` }}>
                <span className="textbook-program-number">{row.number}</span>
                <span className="textbook-program-copy"><b>{row.title}</b><small>{row.purpose}{row.outside ? " · вне текущей программы" : ""}</small></span>
                <MachineMark origin="проход 1" />
                <span className="textbook-program-source">{row.missing ? <><SourceChip source={{ kind: "none" }} /><b>Нужно найти материал по теме</b></> : <><SourceChip source={{ kind: "pass1", pages: row.pages ?? "главы" }} /><small>{row.source}</small></>}</span>
              </div>
            ))}
            {view === "text" && <article className="textbook-text-view"><h2>Индексы в векторных базах данных</h2>{INITIAL_PROGRAM.map((row) => <p key={row.id}><b>{row.number}. {row.title}</b>{row.missing ? " — Нужно найти материал по теме." : ` — ${row.purpose}; ${row.pages}.`}</p>)}</article>}
            {view === "questions" && <ol className="textbook-question-view">{INITIAL_PROGRAM.filter((row) => row.depth > 0).map((row) => <li key={row.id}>Как объяснить: «{row.title}»?{row.missing && <small>Нужно найти материал по теме</small>}</li>)}</ol>}
          </div>
        </section>
        <aside className="textbook-active-side">
          <Card>
            <header><WandSparkles size={17} /><span><b>Проход 2 идёт в фоне</b><small>96 из 214 блоков разнесены по программе</small></span></header>
            <Progress value={96} max={214} label="Привязка блоков к программе" />
            <Button variant="ghost">Открыть фоновые задачи</Button>
          </Card>
          <Card>
            <h2>Цель проекта</h2>
            <p>Выбрать тип векторного индекса под задачу и объяснить компромисс между скоростью, памятью и качеством поиска.</p>
            <dl><div><dt>Темп</dt><dd>45 минут · 4 дня в неделю</dd></div><div><dt>Источники</dt><dd>2 материала</dd></div><div><dt>Пробелы</dt><dd>1 тема</dd></div></dl>
          </Card>
          <Card className="textbook-active-assistant">
            <h2>Помощник по программе</h2>
            <p>Предлагайте изменения — я покажу диф и ничего не применю без подтверждения.</p>
            <textarea placeholder="Что изменить в программе?" />
            <Button><ArrowUp size={15} />Отправить</Button>
          </Card>
        </aside>
      </div>
    </div>
  );
}
