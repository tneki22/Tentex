/** Небольшой календарь готовых уроков и фактическое время сегодня. */
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { ArrowLeft, ChevronLeft, ChevronRight, Wand2 } from "lucide-react";
import { getProject, type ProjectDetail } from "../api/projects";
import {
  lessonPlanning,
  type LessonDistribution,
  type LessonPlanItem,
  type LessonPlanningOverview,
} from "../api/lessonPlanning";
import { errorText } from "../api/preparation";
import { ProjectNav } from "../components/domain/ProjectNav";
import { Button, Dialog, ErrorState, LoadingState, PageHead, StackedBar } from "../components/ui";
import "../styles/lesson-planning.css";

const dateLabel = (value: string) =>
  new Date(`${value}T12:00:00`).toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
function duration(seconds: number): string {
  if (seconds > 0 && seconds < 60) return `${seconds} с`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} мин`;
  return `${Math.floor(seconds / 3600)} ч ${Math.round((seconds % 3600) / 60)} мин`;
}

function lessonCount(count: number): string {
  const lastTwo = count % 100;
  const last = count % 10;
  if (last === 1 && lastTwo !== 11) return `${count} урок`;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return `${count} урока`;
  return `${count} уроков`;
}
const iso = (year: number, month: number, day: number) =>
  new Date(Date.UTC(year, month - 1, day)).toISOString().slice(0, 10);

function monthDates(month: string): Array<string | null> {
  const [year, number] = month.split("-").map(Number);
  const first = new Date(Date.UTC(year, number - 1, 1));
  const count = new Date(Date.UTC(year, number, 0)).getUTCDate();
  const offset = (first.getUTCDay() + 6) % 7;
  return [...Array<string | null>(offset).fill(null), ...Array.from({ length: count }, (_, index) => iso(year, number, index + 1))];
}

function shiftMonth(month: string, delta: number): string {
  const [year, number] = month.split("-").map(Number);
  return new Date(Date.UTC(year, number - 1 + delta, 1)).toISOString().slice(0, 7);
}

export function LessonPlanning() {
  const { projectId = "" } = useParams();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [data, setData] = useState<LessonPlanningOverview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<LessonDistribution | null>(null);
  const [selectedDate, setSelectedDate] = useState("");
  const [month, setMonth] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    void Promise.all([
      getProject(projectId, controller.signal),
      lessonPlanning.overview(projectId, controller.signal),
    ]).then(([projectValue, overview]) => {
      if (controller.signal.aborted) return;
      setProject(projectValue);
      setData(overview);
      setSelectedDate(overview.today);
      setMonth(overview.today.slice(0, 7));
    }).catch((caught) => {
      if (!controller.signal.aborted) setError(errorText(caught));
    });
    return () => controller.abort();
  }, [projectId]);

  useEffect(() => {
    const refreshTime = () => {
      void lessonPlanning.overview(projectId).then(setData).catch(() => undefined);
    };
    window.addEventListener("tentex-lesson-time-updated", refreshTime);
    return () => window.removeEventListener("tentex-lesson-time-updated", refreshTime);
  }, [projectId]);

  const lessons = useMemo(() => new Map(data?.lessons.map((lesson) => [lesson.id, lesson]) ?? []), [data]);
  const days = useMemo(() => {
    const grouped = new Map<string, LessonPlanItem[]>();
    for (const item of data?.items ?? []) grouped.set(item.on_date, [...(grouped.get(item.on_date) ?? []), item]);
    return grouped;
  }, [data]);
  const dayItems = days.get(selectedDate) ?? [];
  const unassigned = data?.lessons.filter((lesson) => data.unassigned_ids.includes(lesson.id)) ?? [];
  const unavailable = new Set(data?.unavailable_ids ?? []);
  const maxSeconds = Math.max(1, ...(data?.today_by_lesson.map((row) => row.seconds) ?? []));

  async function save(items: LessonPlanItem[], expected = data?.revision) {
    if (!data || expected === undefined) return;
    setBusy(true);
    setError("");
    try {
      const result = await lessonPlanning.save(projectId, expected, items);
      setData(result);
      setPreview(null);
      window.dispatchEvent(new Event("tentex-lesson-planning-changed"));
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  async function distribute(mode: "append" | "rebuild_future") {
    setBusy(true);
    setError("");
    try {
      setPreview(await lessonPlanning.preview(projectId, mode));
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  if (!data && !error) return <LoadingState label="Открываем планирование занятий" />;
  if (!data) return <div className="lesson-planning-unavailable"><ErrorState message={error} /><Link to={`/projects/${projectId}/settings`}>Открыть настройки проекта</Link></div>;
  const forecast = data.estimated_finish
    ? `${dateLabel(data.estimated_finish)}${data.deadline ? data.estimated_finish <= data.deadline ? " · укладывается в срок" : " · позже срока" : ""}`
    : "Пока нечего рассчитывать";
  const currentMonth = new Date(`${month}-01T12:00:00`).toLocaleDateString("ru-RU", { month: "long", year: "numeric" });

  return (
    <div className="program-screen lesson-planning-screen">
      <aside className="project-side-panel">
        <header className="project-side-title">
          <Link className="workspace-back-button" to={`/projects/${projectId}`} aria-label="Вернуться в рабочую область"><ArrowLeft size={15} /></Link>
          <strong>{project?.project.name ?? "Проект"}</strong>
        </header>
        <ProjectNav projectId={projectId} active="lesson-planning" textbook modules={project?.project.enabled_modules} className="project-side-nav" />
      </aside>
      <main className="program-main lesson-planning-main">
        <PageHead title="Планирование занятий" />
        <p className="lesson-planning-lead">Распределяйте готовые уроки по дням. Время учитывается, когда готовый урок открыт в рабочей области.</p>
        {error && <p className="inline-error" role="alert">{error}</p>}
        <div className="lesson-planning-summary">
          <article><span>Сегодня в плане</span><strong>{(days.get(data.today) ?? []).length}</strong></article>
          <article><span>Без даты</span><strong>{data.unassigned_ids.length}</strong></article>
          <article><span>За уроками сегодня</span><strong>{duration(data.today_seconds)}</strong></article>
          <article><span>Расчёт по плану</span><strong>{forecast}</strong></article>
        </div>
        <div className="lesson-planning-actions">
          <Button disabled={busy || data.readonly || unassigned.length === 0} onClick={() => void distribute("append")}><Wand2 size={15} />Распределить уроки</Button>
          <Button variant="secondary" disabled={busy || data.readonly || data.items.every((item) => item.origin === "manual")} onClick={() => void distribute("rebuild_future")}>Перестроить будущие</Button>
          <span>Ритм: {data.daily_minutes} мин/день · {data.days_per_week} дней в неделю{data.deadline ? ` · срок ${dateLabel(data.deadline)}` : ""}</span>
        </div>
        {data.outside_deadline_count > 0 && <p className="lesson-planning-note">За текущим сроком осталось назначений: {data.outside_deadline_count}. Перенесите их вручную.</p>}
        {data.lessons.length === 0 && <p className="lesson-planning-note">Сначала составьте программу и уроки. Раздел уже включён и будет готов к планированию после их подготовки. <Link to={`/projects/${projectId}/lessons`}>Открыть уроки</Link></p>}
        {data.lessons.length > 0 && data.lessons.every((lesson) => !lesson.eligible) && <p className="lesson-planning-note">Пока нет готовых непустых уроков для действующей программы. <Link to={`/projects/${projectId}/lessons`}>Подготовить уроки</Link></p>}
        <section className="lesson-planning-calendar" aria-label="Календарь уроков">
          <div className="lesson-planning-section-head">
            <h2>Календарь</h2>
            <div><Button variant="ghost" onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Предыдущий месяц"><ChevronLeft size={16} /></Button><strong>{currentMonth}</strong><Button variant="ghost" onClick={() => setMonth(shiftMonth(month, 1))} aria-label="Следующий месяц"><ChevronRight size={16} /></Button></div>
          </div>
          <div className="lesson-planning-grid">
            {["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map((day) => <span className="lesson-planning-weekday" key={day}>{day}</span>)}
            {monthDates(month).map((day, index) => day
              ? <button type="button" key={day} className={`lesson-planning-day${day === selectedDate ? " is-selected" : ""}${day === data.today ? " is-today" : ""}`} onClick={() => setSelectedDate(day)}><span>{Number(day.slice(-2))}</span>{(days.get(day) ?? []).length > 0 && <small>{lessonCount((days.get(day) ?? []).length)}</small>}</button>
              : <span key={`blank-${index}`} />)}
          </div>
        </section>
        <section className="lesson-planning-day-list">
          <div className="lesson-planning-section-head"><h2>{dateLabel(selectedDate)}</h2><span>{dayItems.length ? lessonCount(dayItems.length) : "Уроков нет"}</span></div>
          {dayItems.map((item) => {
            const locked = item.on_date < data.today || Boolean(lessons.get(item.lesson_id)?.completed_at);
            return <div className="lesson-planning-row" key={item.id}>
              <div><strong>{lessons.get(item.lesson_id)?.title ?? item.title}</strong><span>{item.minutes} мин{unavailable.has(item.id) ? " · урок недоступен" : ""}</span></div>
              {!data.readonly && <><input aria-label={`Дата урока «${item.title}»`} type="date" value={item.on_date} min={data.today} max={data.deadline ?? undefined} disabled={busy || locked} onChange={(event) => void save(data.items.map((entry) => entry.id === item.id ? { ...entry, on_date: event.target.value, origin: "manual" } : entry))} /><Button variant="ghost" disabled={busy || locked} onClick={() => void save(data.items.filter((entry) => entry.id !== item.id))}>Убрать</Button></>}
            </div>;
          })}
        </section>
        {unassigned.length > 0 && <section className="lesson-planning-unassigned">
          <div className="lesson-planning-section-head"><h2>Без даты</h2><span>{unassigned.length}</span></div>
          {unassigned.map((lesson) => <div className="lesson-planning-row" key={lesson.id}><div><strong>{lesson.title}</strong><span>≈ {lesson.minutes} мин</span></div><Button variant="secondary" disabled={busy || data.readonly || selectedDate < data.today || Boolean(data.deadline && selectedDate > data.deadline)} onClick={() => void save([...data.items, { id: crypto.randomUUID(), lesson_id: lesson.id, title: lesson.title, on_date: selectedDate, minutes: lesson.minutes, origin: "manual" }])}>На выбранный день</Button></div>)}
        </section>}
        <section className="lesson-planning-time">
          <div className="lesson-planning-section-head"><h2>Время за уроками сегодня</h2><strong>{duration(data.today_seconds)}</strong></div>
          {data.today_by_lesson.length === 0 ? <p className="lesson-planning-note">Сегодня время за уроками ещё не записано.</p> : data.today_by_lesson.map((row, index) => <div className="lesson-planning-time-row" key={`${row.lesson_id ?? row.title}-${index}`}><strong>{row.title}</strong><StackedBar ariaLabel={`${row.title}: ${duration(row.seconds)}`} total={maxSeconds} segments={[{ value: row.seconds, token: "--chart-fact", label: row.title }]} /><span>{duration(row.seconds)}</span></div>)}
        </section>
      </main>
      <Dialog open={preview !== null} onOpenChange={(open) => { if (!open) setPreview(null); }} title="Распределение уроков" description="Проверьте даты перед применением." footer={<><Button variant="secondary" onClick={() => setPreview(null)}>Отмена</Button><Button disabled={busy || !preview} onClick={() => { if (preview) void save(preview.items, preview.base_revision); }}>Применить</Button></>}>
        {preview && <div className="lesson-planning-preview"><p>Назначений: {preview.items.length} · {data.deadline ? "не поместилось до срока" : "без даты"}: {preview.unassigned_ids.length}</p><p>Расчётное окончание: {preview.estimated_finish ? dateLabel(preview.estimated_finish) : "не определено"}</p><ul>{preview.items.filter((item) => !data.items.some((old) => old.id === item.id && old.on_date === item.on_date)).map((item) => <li key={item.id}>{dateLabel(item.on_date)} — {item.title}</li>)}</ul></div>}
      </Dialog>
    </div>
  );
}
