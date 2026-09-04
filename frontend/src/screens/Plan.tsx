/** Рабочий экран подготовки: серверный снимок, защищённые черновики и независимые представления. */
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import {
  Button,
  Dialog,
  Field,
  PageHead,
  SegmentedTabs,
  LoadingState,
  ErrorState,
} from "../components/ui";
import { ProjectNav } from "../components/domain";
import {
  preparation,
  revisions,
  errorText,
  type Overview,
  type Draft,
  type DraftWrite,
  type Phase,
  type PlanItem,
} from "../api/preparation";
import { MiniCalendar } from "./preparation/MiniCalendar";
import { Timeline } from "./preparation/Timeline";
import { Calendar } from "./preparation/Calendar";
import { History } from "./preparation/History";
import { Analytics } from "./preparation/Analytics";
import { Settings } from "./preparation/Settings";
import { DraftDialog } from "./preparation/DraftDialog";
import { PhaseEditor } from "./preparation/PhaseEditor";
import { AssignmentEditor } from "./preparation/AssignmentEditor";
import { AiPreparation } from "./preparation/AiPreparation";
import { addDays, dateLabel, duration } from "./preparation/dates";
export function Plan() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams(localStorage.getItem(`tentex-preparation-view:${projectId}`) ?? "");
  useEffect(() => {
    localStorage.setItem(`tentex-preparation-view:${projectId}`, params.toString());
  }, [projectId, params]);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [editor, setEditor] = useState<Phase | PlanItem | "assignment" | null>(
    null,
  );
  const [side, setSide] = useState<"why" | "settings">("why");
  const [busy, setBusy] = useState(false);
  const [schedule, setSchedule] = useState(false);
  const [range, setRange] = useState({ start: "", end: "" });
  const date = params.get("date") ?? overview?.today ?? "";
  const view = params.get("view") ?? "calendar";
  const refresh = () => setVersion((value) => value + 1);
  const draftKey = `tentex-preparation-draft:${projectId}`;
  const showDraft = (value: Draft) => {
    localStorage.setItem(draftKey, value.id);
    setDraft(value);
  };
  const closeDraft = () => {
    localStorage.removeItem(draftKey);
    setDraft(null);
  };
  useEffect(() => {
    const id = localStorage.getItem(draftKey);
    if (!id) return;
    const controller = new AbortController();
    preparation
      .getDraft(projectId, id, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setDraft(value);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) {
          setError(errorText(caught));
          localStorage.removeItem(draftKey);
        }
      });
    return () => controller.abort();
  }, [projectId, draftKey]);
  useEffect(() => {
    const controller = new AbortController();
    const selected = params.get("date");
    preparation
      .overview(
        projectId,
        selected ? addDays(selected, -7) : undefined,
        selected ? addDays(selected, 30) : undefined,
        controller.signal,
      )
      .then((value) => {
        setOverview(value);
        setError(null);
        setRange((current) =>
          current.start
            ? current
            : {
                start: value.today,
                end: value.deadline ?? addDays(value.today, 30),
              },
        );
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorText(caught));
      });
    return () => controller.abort();
  }, [projectId, params.get("date"), version]);
  const ui = (key: string, value: string) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.set(key, value);
        return next;
      },
      { replace: true },
    );
  async function preview(change: Partial<DraftWrite>) {
    if (!overview || overview.readonly) return;
    setBusy(true);
    try {
      const value = await preparation.draft(projectId, {
        mode: "manual",
        phases: null,
        items: null,
        unit_ids: null,
        start: null,
        end: null,
        ...revisions(overview),
        ...change,
      });
      showDraft(value);
      setEditor(null);
      setSchedule(false);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }
  async function startDay(onDate: string) {
    if (overview?.readonly) return;
    setBusy(true);
    try {
      const queue = await preparation.queue(projectId, onDate, true);
      const topic =
        queue.items[queue.position]?.topic_ids[queue.topic_position];
      if (topic)
        navigate(
          `/projects/${projectId}?queue=${onDate}&topic=${topic}&tab=chat`,
        );
      else
        setError("В очереди дня нет вопросов. Добавьте задания в календарь.");
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }
  async function undo() {
    if (!overview || overview.readonly) return;
    setBusy(true);
    try {
      await preparation.undo(projectId, overview.plan.revision);
      refresh();
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }
  const history = (filters: Record<string, string>) =>
    setParams((current) => {
      const next = new URLSearchParams();
      next.set("view", "history");
      if (current.get("date")) next.set("date", current.get("date")!);
      Object.entries(filters).forEach(([key, value]) => next.set(key, value));
      return next;
    });
  if (!overview)
    return (
      <main className="prep-loading">
        {error ? (
          <>
            <ErrorState title="Подготовка не загрузилась" message={error} />
            <Button onClick={refresh}>Повторить</Button>
          </>
        ) : (
          <LoadingState label="Загружаем подготовку" />
        )}
      </main>
    );
  const selected = overview.days.find((day) => day.date === date);
  return (
    <div className="plan-screen prep-screen">
      <aside className="plan-project-panel">
        <header className="program-project-title">
          <Link to={`/projects/${projectId}`} aria-label="В рабочую область">
            ←
          </Link>
          <strong>{overview.project_name}</strong>
        </header>
        <MiniCalendar
          value={date}
          today={overview.today}
          onChange={(value) => ui("date", value)}
        />
        <ProjectNav
          projectId={projectId}
          active="plan"
          className="program-project-nav"
        />
      </aside>
      <main className="plan-main">
        <PageHead
          title="Моя подготовка"
          eyebrow={
            overview.deadline
              ? `Экзамен ${dateLabel(overview.deadline)}`
              : "Дата экзамена не задана"
          }
          actions={
            <>
              <Button
                variant="secondary"
                disabled={busy || overview.readonly || !overview.plan.can_undo}
                onClick={() => void undo()}
              >
                Отменить изменение
              </Button>
              <Button
                disabled={busy || overview.readonly}
                onClick={() => void startDay(overview.today)}
              >
                Начать день
              </Button>
            </>
          }
        />
        {error && <ErrorState title="Действие не завершено" message={error} />}
        {overview.readonly && (
          <p className="prep-card">
            Проект доступен только для чтения. История и план сохранены.
          </p>
        )}
        <section className="prep-coach">
          <p className="eyebrow">Сегодня</p>
          {overview.readonly && <strong>{overview.coach.text}</strong>}
          {!overview.readonly && (
            <AiPreparation
              key={projectId}
              overview={overview}
              onDraft={showDraft}
              onAction={(action) => {
                if (action === "start") void startDay(overview.today);
                else if (action === "redistribute") void preview({mode: "spread"});
                else setSchedule(true);
              }}
            />
          )}
        </section>
        <section className="plan-summary">
          <div>
            <span>Сегодня</span>
            <strong>{duration(overview.summary.today_seconds)}</strong>
          </div>
          <div>
            <span>Доступно до экзамена</span>
            <strong>{duration(overview.summary.available_minutes * 60)}</strong>
          </div>
          <div>
            <span>Осталось работы</span>
            <strong>{duration(overview.summary.remaining_work_minutes * 60)}</strong>
          </div>
          <div><span>Пройдено</span><strong>{overview.summary.passed_topics} / {overview.summary.total_topics}</strong></div>
          <div><span>Подтверждено</span><strong>{overview.summary.confirmed_topics}</strong></div>
          {overview.plan.unassigned_ids.length > 0 && <div>
            <span>Без даты</span>
            <Button
              variant="ghost"
              disabled={overview.readonly}
              onClick={() => setSchedule(true)}
            >
              {overview.plan.unassigned_ids.length} заданий · распределить
            </Button>
          </div>}
        </section>
        {overview.settings.config.daily_minutes == null && (
          <section className="prep-card">
            <p>Укажите дневной бюджет, чтобы рассчитать нагрузку.</p>
            <Button variant="secondary" onClick={() => setSide("settings")}>
              Задать бюджет
            </Button>
          </section>
        )}
        {overview.plan.stale && (
          <p className="prep-card">
            Программа или параметры изменились. Пересчитайте будущие назначения
            и проверьте предложение.
          </p>
        )}
        <Timeline
          overview={overview}
          selected={date}
          onEdit={(phase) => {
            if (!overview.readonly) setEditor(phase);
          }}
        />
        <div className="prep-actions">
          <SegmentedTabs
            label="Подготовка"
            value={view}
            onChange={(value) => ui("view", value)}
            tabs={[
              { value: "calendar", label: "Календарь" },
              { value: "history", label: "История" },
              { value: "analytics", label: "Аналитика" },
            ]}
          />
          <Button
            variant="secondary"
            disabled={busy || overview.readonly}
            onClick={() => setEditor("assignment")}
          >
            Добавить задания
          </Button>
          <Button
            variant="ghost"
            disabled={busy || overview.readonly}
            onClick={() => setSchedule(true)}
          >
            Пересчитать
          </Button>
        </div>
        <div className="plan-content-grid">
          <div>
            {view === "history" ? (
              <History overview={overview} onChanged={refresh} />
            ) : view === "analytics" ? (
              <Analytics overview={overview} onHistory={history} />
            ) : (
              <Calendar
                overview={overview}
                selected={date}
                onSelect={(value) => ui("date", value)}
                onEdit={(phase) => {
                  if (!overview.readonly) setEditor(phase);
                }}
                onStart={(value) => void startDay(value)}
                onUnderstood={(id) => {
                  void preparation
                    .understood(projectId, id)
                    .then(refresh)
                    .catch((caught) => setError(errorText(caught)));
                }}
              />
            )}
          </div>
          <aside className="plan-side-panel">
            <SegmentedTabs
              label="Панель подготовки"
              value={side}
              onChange={setSide}
              tabs={[
                { value: "why", label: "Почему так" },
                { value: "settings", label: "Параметры" },
              ]}
            />
            {side === "settings" ? (
              <Settings
                key={overview.settings.revision}
                overview={overview}
                onSaved={refresh}
              />
            ) : (
              <div className="plan-why">
                <h2>{dateLabel(date)}</h2>
                <p>
                  {selected
                    ? `План ${selected.planned_minutes} мин · факт ${duration(selected.active_seconds)} · доступно ${selected.capacity_minutes} мин`
                    : "Выберите день в календаре."}
                </p>
                {[...new Set(overview.plan.items.filter((item) => item.on_date === date)
                  .map((item) => item.reason + (item.pinned ? " Дата закреплена." : "")))]
                  .map((reason) => <p key={reason}>{reason}</p>)}
                <h3>Если пропустил</h3>
                <p>
                  Выберите, как обработать невыполненные назначения. Сначала
                  покажем изменения.
                </p>
                <div className="prep-debt-actions">
                  {(
                    [
                      ["catch_up", "Наверстать"],
                      ["spread", "Распределить долг"],
                      ["dismiss", "Снять долг"],
                    ] as const
                  ).map(([mode, label]) => (
                    <Button
                      variant="ghost"
                      disabled={busy || overview.readonly}
                      key={mode}
                      onClick={() =>
                        void preview({
                          mode,
                          start: overview.today,
                          end: overview.deadline ?? addDays(overview.today, 30),
                        })
                      }
                    >
                      {label}
                    </Button>
                  ))}
                </div>
                <Link to={`/projects/${projectId}/program`}>
                  Изменить вопросы и уровни цели
                </Link>
              </div>
            )}
          </aside>
        </div>
      </main>
      {draft && (
        <DraftDialog
          key={draft.id}
          draft={draft}
          overview={overview}
          onClose={closeDraft}
          onApplied={refresh}
        />
      )}
      {editor && editor !== "assignment" && "title" in editor && (
        <PhaseEditor
          key={editor.id}
          phase={editor}
          overview={overview}
          onClose={() => setEditor(null)}
          onPreview={(change) => void preview(change)}
        />
      )}{" "}
      {editor && (editor === "assignment" || "unit_id" in editor) && (
        <AssignmentEditor
          key={editor === "assignment" ? "new" : editor.id}
          overview={overview}
          date={date}
          item={editor === "assignment" ? undefined : editor}
          onClose={() => setEditor(null)}
          onPreview={(change) => void preview(change)}
        />
      )}
      <Dialog
        open={schedule}
        onOpenChange={setSchedule}
        title="Распределить подготовку"
        description="Прошлое, выполненные задания и закрепления останутся под защитой сервера."
      >
        <div className="prep-form">
          <Field label="С даты">
            <input
              type="date"
              value={range.start}
              onChange={(event) =>
                setRange({ ...range, start: event.target.value })
              }
            />
          </Field>
          <Field label="По дату">
            <input
              type="date"
              min={range.start}
              value={range.end}
              onChange={(event) =>
                setRange({ ...range, end: event.target.value })
              }
            />
          </Field>
        </div>
        <div className="prep-actions">
          <Button
            disabled={
              busy ||
              overview.readonly ||
              !range.start ||
              range.end < range.start
            }
            onClick={() => void preview({ mode: "count", ...range })}
          >
            По числу вопросов
          </Button>
          <Button
            disabled={
              busy ||
              overview.readonly ||
              overview.settings.config.daily_minutes == null ||
              !range.start ||
              range.end < range.start
            }
            onClick={() => void preview({ mode: "time", ...range })}
          >
            По времени
          </Button>
          <Button
            variant="ghost"
            disabled={busy || overview.readonly}
            onClick={() => void preview({ mode: "manual", items: [] })}
          >
            Пустой план — предпросмотр
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
