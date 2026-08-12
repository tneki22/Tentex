import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import {
  ArrowLeft,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Clock3,
  GraduationCap,
  Layers,
  MoveRight,
  Pin,
  RotateCcw,
  Sparkles,
  WandSparkles,
} from "lucide-react";
import { Button, Dialog, Field, PageHead, SegmentedTabs, Tooltip } from "../components/ui";
import { CostEstimate, MachineMark, ProjectNav } from "../components/domain";

type DayKind = "past" | "today" | "future" | "review" | "exam";
type PlanItemKind = "new" | "review" | "gap";

interface PlanItem {
  id: string;
  title: string;
  section: string;
  minutes: number;
  kind: PlanItemKind;
  pinned?: boolean;
  machine?: boolean;
}

interface PlanDay {
  id: string;
  weekday: string;
  date: string;
  phase: string;
  kind: DayKind;
  capacity: number;
  items: PlanItem[];
  expanded?: boolean;
}

const INITIAL_DAYS: PlanDay[] = [
  {
    id: "day-1", weekday: "Понедельник", date: "4 августа", phase: "Первичный проход", kind: "past", capacity: 120, expanded: false,
    items: [
      { id: "db-purpose", title: "Назначение и компоненты СУБД", section: "Основы баз данных", minutes: 20, kind: "new" },
      { id: "data-models", title: "Модели данных", section: "Основы баз данных", minutes: 25, kind: "new" },
      { id: "db-architecture", title: "Архитектура ANSI/SPARC", section: "Основы баз данных", minutes: 35, kind: "new" },
    ],
  },
  {
    id: "day-2", weekday: "Вторник", date: "5 августа", phase: "Первичный проход", kind: "today", capacity: 120, expanded: true,
    items: [
      { id: "data-languages", title: "Языки определения и манипулирования данными", section: "Основы баз данных", minutes: 20, kind: "new" },
      { id: "relational-concepts", title: "Отношение, кортеж, домен", section: "Реляционная модель", minutes: 25, kind: "new" },
      { id: "keys", title: "Первичные и внешние ключи", section: "Реляционная модель", minutes: 35, kind: "new", pinned: true },
      { id: "repeat-models", title: "Повторить модели данных", section: "Основы баз данных", minutes: 15, kind: "review" },
    ],
  },
  {
    id: "day-3", weekday: "Среда", date: "6 августа", phase: "Первичный проход", kind: "future", capacity: 120, expanded: false,
    items: [
      { id: "relational-algebra", title: "Операции реляционной алгебры", section: "Реляционная модель", minutes: 45, kind: "new" },
      { id: "normalization", title: "Нормальные формы", section: "Реляционная модель", minutes: 50, kind: "new" },
    ],
  },
  {
    id: "day-4", weekday: "Четверг", date: "7 августа", phase: "Первичный проход", kind: "future", capacity: 120, expanded: false,
    items: [
      { id: "transactions", title: "Транзакции и свойства ACID", section: "Управление транзакциями", minutes: 50, kind: "new", machine: true },
      { id: "logging", title: "Журнализация и восстановление", section: "Управление транзакциями", minutes: 35, kind: "new", machine: true },
    ],
  },
  {
    id: "day-5", weekday: "Пятница", date: "8 августа", phase: "Повторение и пробелы", kind: "review", capacity: 100, expanded: false,
    items: [
      { id: "repeat-basics", title: "Повторить раздел «Основы баз данных»", section: "Повторение", minutes: 50, kind: "review" },
      { id: "gap-architecture", title: "Закрыть пробел: независимость данных", section: "Пробелы", minutes: 25, kind: "gap" },
    ],
  },
  {
    id: "day-6", weekday: "Суббота", date: "9 августа", phase: "Повторение и пробелы", kind: "review", capacity: 100, expanded: false,
    items: [
      { id: "repeat-relational", title: "Повторить реляционную модель", section: "Повторение", minutes: 55, kind: "review" },
      { id: "gap-normalization", title: "Разобрать нормальные формы", section: "Пробелы", minutes: 35, kind: "gap" },
    ],
  },
  {
    id: "day-7", weekday: "Воскресенье", date: "10 августа", phase: "Финальное повторение", kind: "exam", capacity: 80, expanded: false,
    items: [
      { id: "final", title: "Короткий прогон всех разделов", section: "Финальное повторение", minutes: 60, kind: "review" },
    ],
  },
];

const KIND_LABEL: Record<PlanItemKind, string> = { new: "Новый вопрос", review: "Повторение", gap: "Пробел" };

export function Plan() {
  const { projectId = "demo" } = useParams();
  const [days, setDays] = useState(INITIAL_DAYS);
  const [selectedDayId, setSelectedDayId] = useState("day-2");
  const [rightTab, setRightTab] = useState<"settings" | "why">("why");
  const [aiOpen, setAiOpen] = useState(false);
  const [aiDiffOpen, setAiDiffOpen] = useState(false);
  const [recoveryOpen, setRecoveryOpen] = useState(false);
  const [recalculated, setRecalculated] = useState(false);
  const [dailyMinutes, setDailyMinutes] = useState("120");
  const [aiRequest, setAiRequest] = useState("");
  const selectedDay = days.find((day) => day.id === selectedDayId) ?? days[0];
  const plannedMinutes = (day: PlanDay) => day.items.reduce((sum, item) => sum + item.minutes, 0);
  const totalPlanned = useMemo(() => days.reduce((sum, day) => sum + plannedMinutes(day), 0), [days]);

  function toggleDay(id: string) {
    setDays((current) => current.map((day) => day.id === id ? { ...day, expanded: !day.expanded } : day));
    setSelectedDayId(id);
  }

  function moveItem(itemId: string, fromDayId: string) {
    const currentIndex = days.findIndex((day) => day.id === fromDayId);
    const target = days[currentIndex + 1];
    if (!target) return;
    const item = days[currentIndex].items.find((candidate) => candidate.id === itemId);
    if (!item || item.pinned) return;
    setDays((current) => current.map((day) => {
      if (day.id === fromDayId) return { ...day, items: day.items.filter((candidate) => candidate.id !== itemId) };
      if (day.id === target.id) return { ...day, items: [...day.items, { ...item, machine: false }] };
      return day;
    }));
  }

  function togglePinned(itemId: string, dayId: string) {
    setDays((current) => current.map((day) => day.id === dayId ? { ...day, items: day.items.map((item) => item.id === itemId ? { ...item, pinned: !item.pinned } : item) } : day));
  }

  function applyAiDiff() {
    setDays((current) => current.map((day) => {
      const avoidWednesday = /сред/i.test(aiRequest);
      if (day.id === "day-3") return { ...day, items: avoidWednesday ? day.items.filter((item) => item.id !== "normalization") : day.items.map((item) => item.id === "normalization" ? { ...item, minutes: 40, machine: true } : item) };
      if (day.id === "day-4") return { ...day, items: [...day.items, ...(avoidWednesday ? [{ id: "normalization", title: "Нормальные формы", section: "Реляционная модель", minutes: 35, kind: "new" as const, machine: true }] : [{ id: "repeat-keys", title: "Коротко повторить ключи", section: "Реляционная модель", minutes: 15, kind: "review" as const, machine: true }])] };
      return day;
    }));
    setAiDiffOpen(false);
    setAiOpen(false);
  }

  return (
    <div className="plan-screen">
      <aside className="plan-project-panel">
        <header className="program-project-title">
          <Tooltip label="Вернуться в рабочую область"><Link className="workspace-back-button" to={`/projects/${projectId}`} aria-label="Вернуться в рабочую область"><ArrowLeft size={15} /></Link></Tooltip>
          <strong>Базы данных — экзамен</strong>
        </header>
        <section className="plan-mini-calendar" aria-label="Неделя подготовки">
          <p className="eyebrow">До экзамена</p>
          <strong>7 учебных дней</strong>
          <div>{days.map((day) => <button type="button" className={`is-${day.kind} ${selectedDayId === day.id ? "is-selected" : ""}`.trim()} key={day.id} onClick={() => setSelectedDayId(day.id)} aria-label={`${day.weekday}, ${day.date}`}><span>{day.weekday.slice(0, 2)}</span><b>{day.date.split(" ")[0]}</b></button>)}</div>
        </section>
        <ProjectNav
          projectId={projectId}
          active="plan"
          counts={{ materials: 3, program: 10, plan: "7 дней" }}
          className="program-project-nav"
        />
      </aside>

      <main className="plan-main">
        <PageHead
          eyebrow="До экзамена осталось 7 дней"
          title="План подготовки"
          actions={<><Button variant="secondary" onClick={() => setAiOpen(true)}><WandSparkles size={15} /> Уточнить с ИИ</Button><Button onClick={() => setRecalculated(true)}><RotateCcw size={15} /> {recalculated ? "План обновлён" : "Пересчитать"}</Button></>}
        />
        <section className="plan-summary" aria-label="Параметры подготовки">
          <div><span>Экзамен</span><strong>11 августа, 10:00</strong></div>
          <div><span>Доступно</span><strong>{dailyMinutes} минут в день</strong></div>
          <div><span>Первичный проход</span><strong>До 7 августа</strong></div>
          <div><span>Резерв</span><strong>2 дня и финальный прогон</strong></div>
          <div><span>В плане</span><strong>10 из 10 вопросов</strong></div>
        </section>
        {!recalculated && <section className="plan-stale-notice"><span><Sparkles size={16} /> В списке вопросов есть изменения после последнего пересчёта.</span><button type="button" onClick={() => setRecalculated(true)}>Пересчитать план</button></section>}
        <section className="plan-phase-strip" aria-label="Фазы подготовки">
          <button type="button" className="is-pass" onClick={() => setSelectedDayId("day-2")}><span>4–7 августа</span><strong>Первичный проход</strong></button>
          <button type="button" className="is-review" onClick={() => setSelectedDayId("day-5")}><span>8–9 августа</span><strong>Повторение и пробелы</strong></button>
          <button type="button" className="is-final" onClick={() => setSelectedDayId("day-7")}><span>10 августа</span><strong>Финальный прогон</strong></button>
          <span className="plan-phase-exam">Экзамен<br />11 августа</span>
        </section>
        <div className="plan-content-grid">
          <section className="plan-agenda" aria-label="Календарный план">
            <div className="plan-agenda-head"><div><h2>Календарь подготовки</h2><p>{totalPlanned} минут назначено, ручные переносы сохранятся.</p></div><Button variant="ghost" onClick={() => setRecoveryOpen(true)}><CircleAlert size={15} /> Пропустил день</Button></div>
            {days.map((day) => {
              const minutes = plannedMinutes(day);
              const overloaded = minutes > day.capacity;
              const open = day.expanded || selectedDayId === day.id;
              return <article className={`plan-day is-${day.kind} ${selectedDayId === day.id ? "is-selected" : ""}`.trim()} key={day.id}>
                <button type="button" className="plan-day-head" onClick={() => toggleDay(day.id)} aria-expanded={open}>
                  <span className="plan-day-marker">{day.kind === "past" ? <CheckCircle2 size={16} /> : day.kind === "today" ? <Clock3 size={16} /> : day.kind === "review" ? <RotateCcw size={16} /> : day.kind === "exam" ? <GraduationCap size={16} /> : <CalendarDays size={16} />}</span>
                  <span className="plan-day-date"><strong>{day.weekday}</strong><small>{day.date}</small></span>
                  <span className="plan-day-phase">{day.phase}</span>
                  <span className={`plan-day-load ${overloaded ? "is-overloaded" : ""}`}>{minutes} / {day.capacity} мин</span>
                  {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                </button>
                {open && <div className="plan-day-body">
                  {day.items.map((item) => <div className={`plan-item is-${item.kind}`.trim()} key={item.id}>
                    <span className="plan-item-kind">{KIND_LABEL[item.kind]}</span>
                    <Link to={`/projects/${projectId}`}>{item.title}<small>{item.section}</small></Link>
                    <span>{item.minutes} мин</span>
                    {item.machine && <MachineMark origin="уточнено моделью" onUndo={() => setDays((current) => current.map((candidate) => candidate.id === day.id ? { ...candidate, items: candidate.items.map((entry) => entry.id === item.id ? { ...entry, machine: false } : entry) } : candidate))} />}
                    <button type="button" className={`plan-pin ${item.pinned ? "is-active" : ""}`.trim()} onClick={() => togglePinned(item.id, day.id)} aria-label={item.pinned ? "Снять закрепление" : "Закрепить дату"}><Pin size={14} /></button>
                    <button type="button" className="plan-move" disabled={item.pinned || day.kind === "exam"} onClick={() => moveItem(item.id, day.id)}><MoveRight size={14} /> На следующий день</button>
                  </div>)}
                  {day.kind === "today" && <div className="plan-day-actions"><Button><GraduationCap size={15} /> Начать день</Button><Button variant="ghost">Перенести остаток</Button></div>}
                </div>}
              </article>;
            })}
          </section>
          <aside className="plan-side-panel" aria-label="Параметры и объяснения">
            <SegmentedTabs label="Панель Плана" value={rightTab} onChange={setRightTab} tabs={[{ value: "why", label: "Почему так" }, { value: "settings", label: "Параметры" }]} />
            {rightTab === "why" ? <div className="plan-why"><p className="eyebrow">{selectedDay.weekday}, {selectedDay.date}</p><h2>{selectedDay.phase}</h2><dl><div><dt>Порядок</dt><dd>Вопросы идут в порядке экзамена и по возможности остаются в одном разделе.</dd></div><div><dt>Нагрузка</dt><dd>{plannedMinutes(selectedDay)} минут из доступных {selectedDay.capacity}.</dd></div><div><dt>Повторение</dt><dd>Повторить модели данных: наступил срок SM-2.</dd></div><div><dt>Закрепления</dt><dd>Первичные и внешние ключи останутся сегодня при пересчёте.</dd></div></dl><button type="button" className="plan-repeat-load" onClick={() => setRecoveryOpen(true)}><Layers size={15} /> Нагрузка повторений на 30 дней</button></div> : <div className="plan-settings"><Field label="Минут в обычный день"><input value={dailyMinutes} inputMode="numeric" onChange={(event) => setDailyMinutes(event.target.value)} /></Field><Field label="Стратегия"><SegmentedTabs label="Стратегия Плана" value="exam" onChange={() => undefined} tabs={[{ value: "exam", label: "Экзаменационная" }, { value: "steady", label: "Равномерная" }]} /></Field><dl><div><dt>Максимум новых</dt><dd>5 вопросов в день</dd></div><div><dt>Дни отдыха</dt><dd>Нет до экзамена</dd></div><div><dt>Правило долга</dt><dd>Распределить по остатку</dd></div></dl><Link to={`/projects/${projectId}/program`}>Изменить уровень цели вопросов</Link></div>}
          </aside>
        </div>
      </main>

      <Dialog open={aiOpen} onOpenChange={setAiOpen} title="Уточнить нагрузку с ИИ" description="Локальный План уже создан. Модель может только предложить более ровное распределение." footer={<><Button variant="ghost" onClick={() => setAiOpen(false)}>Отменить</Button><Button onClick={() => { setAiOpen(false); setAiDiffOpen(true); }}><Sparkles size={15} /> Получить предложения</Button></>}>
        <Field label="Пожелания к плану">
          <textarea value={aiRequest} onChange={(event) => setAiRequest(event.target.value)} placeholder="Например: в среду не смогу заниматься, перенеси нагрузку на другие дни" />
        </Field>
        <p className="plan-dialog-copy">Отправим формулировки, уровни цели, даты, дневной бюджет и локальную оценку времени. Полные материалы и личные конспекты не отправляются.</p>
        <CostEstimate calls={1} cost={0.02} minutes={1} pricesFrom="01.08.2026" units="10 вопросов" />
      </Dialog>
      <Dialog open={aiDiffOpen} onOpenChange={setAiDiffOpen} title="Предложения к Плану" description="Посмотрите последствия до применения." footer={<><Button variant="ghost" onClick={() => setAiDiffOpen(false)}>Оставить текущий</Button><Button onClick={applyAiDiff}>Применить выбранное</Button></>}>
        <div className="plan-ai-diff"><MachineMark origin="предложено моделью" />{aiRequest.trim() && <div><strong>Учтено пожелание</strong><span>{aiRequest.trim()}</span></div>}<div><strong>{/сред/i.test(aiRequest) ? "Среда освобождена" : "Нормальные формы"}</strong><span>{/сред/i.test(aiRequest) ? "«Нормальные формы» перенесены на четверг и займут свободные 35 минут." : "50 → 40 минут. Вопрос остаётся в среду, чтобы не перегружать день."}</span></div><div><strong>{/сред/i.test(aiRequest) ? "Четверг без перегрузки" : "Повторить ключи"}</strong><span>{/сред/i.test(aiRequest) ? "Нагрузка станет 120 из 120 минут. Дополнительное повторение не добавляется." : "Добавить в четверг перед транзакциями: короткое повторение укрепит связку разделов."}</span></div></div>
      </Dialog>
      <Dialog open={recoveryOpen} onOpenChange={setRecoveryOpen} title="Если пропустили день" description="Остаток не превращается в долг без понятного выхода." footer={<Button variant="secondary" onClick={() => setRecoveryOpen(false)}>Закрыть</Button>}>
        <div className="plan-recovery-options"><button type="button" onClick={() => setRecoveryOpen(false)}><strong>Догнать сразу</strong><span>Добавит 35 минут к двум ближайшим дням.</span></button><button type="button" onClick={() => setRecoveryOpen(false)}><strong>Распределить по остатку</strong><span>Добавит по 15 минут к дням первичного прохода.</span></button><button type="button" onClick={() => setRecoveryOpen(false)}><strong>Простить часть долга</strong><span>Оставит только повторения и вопросы уровня «применять».</span></button></div>
      </Dialog>
    </div>
  );
}
