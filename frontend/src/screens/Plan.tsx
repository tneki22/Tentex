/** «Моя подготовка»: дашборд, очередь дня, периоды и три вкладки на одном экране. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { ChevronDown, Settings2, Sparkles, Undo2, Wand2 } from "lucide-react";
import {
  Button,
  ConfirmDialog,
  Dialog,
  ErrorState,
  IconButton,
  LoadingState,
  Menu,
  PageHead,
  SegmentedTabs,
  StatusBadge,
  Tooltip,
} from "../components/ui";
import { ProjectNav } from "../components/domain";
import {
  preparation,
  revisions,
  errorText,
  type Activity,
  type Draft,
  type Overview,
  type Phase,
  type PlanItem,
} from "../api/preparation";
import { getBackgroundJobResult } from "../api/backgroundJobs";
import { getProject, type ModuleKey } from "../api/projects";
import { useBackgroundJob } from "../hooks/useBackgroundJob";
import { Dashboard, type DashboardPeriod } from "./preparation/Dashboard";
import { TodayQueue } from "./preparation/TodayQueue";
import { BlocksStrip } from "./preparation/BlocksStrip";
import { BlockForm } from "./preparation/BlockForm";
import { DayTree } from "./preparation/DayTree";
import { DayQuestionsEditor } from "./preparation/DayQuestionsEditor";
import { HistoryTab } from "./preparation/HistoryTab";
import { AnalyticsTab } from "./preparation/AnalyticsTab";
import { StartDayGreeting } from "./preparation/StartDayGreeting";
import { Settings } from "./preparation/Settings";
import { addDays, dateLabel } from "./preparation/dates";
import {
  autoPhases,
  autoRestDate,
  buildDays,
  debtOf,
  planStatus,
  queueCards,
  type DayFacts,
} from "./preparation/model";

type Tab = "calendar" | "history" | "analytics";

const PERIOD_DAYS: Record<DashboardPeriod, number> = { "14": 14, "30": 30, "90": 90 };

const COMPOSED_LABEL = {
  none: "План не составлен",
  partial: "План частично составлен",
  full: "План составлен",
} as const;

export function Plan() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams(
    localStorage.getItem(`tentex-preparation-view:${projectId}`) ?? "",
  );
  useEffect(() => {
    localStorage.setItem(`tentex-preparation-view:${projectId}`, params.toString());
  }, [projectId, params]);

  const [overview, setOverview] = useState<Overview | null>(null);
  const [answers, setAnswers] = useState<Activity[]>([]);
  /** Панель проекта должна быть той же, что на других экранах: без лишних вкладок. */
  const [modules, setModules] = useState<ModuleKey[] | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);
  const [block, setBlock] = useState<Phase | { start: string; end: string } | null>(null);
  const [confirm, setConfirm] = useState<{ title: string; body: string; run: () => void } | null>(null);
  const [greeting, setGreeting] = useState(false);
  const [settings, setSettings] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const delivered = useRef<string | null>(null);

  const period = (params.get("period") as DashboardPeriod) ?? "14";
  const tab = (params.get("view") as Tab) ?? "calendar";
  const date = params.get("date") ?? overview?.today ?? "";

  const refresh = useCallback(() => setVersion((value) => value + 1), []);
  const ui = (key: string, value: string) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.set(key, value);
        return next;
      },
      { replace: true },
    );

  useEffect(() => {
    const controller = new AbortController();
    const back = PERIOD_DAYS[period] ?? 14;
    preparation
      .overview(projectId, undefined, undefined, controller.signal)
      .then((snapshot) =>
        preparation.overview(
          projectId,
          addDays(snapshot.today, -back),
          snapshot.deadline && snapshot.deadline > snapshot.today
            ? snapshot.deadline
            : addDays(snapshot.today, 30),
          controller.signal,
        ),
      )
      .then((value) => {
        setOverview(value);
        setError(null);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorText(caught));
      });
    return () => controller.abort();
  }, [projectId, period, version]);

  useEffect(() => {
    if (!overview) return;
    const controller = new AbortController();
    const query = new URLSearchParams({
      kind: "answer",
      date_from: addDays(overview.today, -(PERIOD_DAYS[period] ?? 14)),
      date_to: overview.today,
      limit: "200",
    });
    preparation
      .history(projectId, query, controller.signal)
      .then((value) => setAnswers(value.items))
      .catch(() => undefined);
    return () => controller.abort();
  }, [projectId, period, overview?.plan.revision, version]);

  useEffect(() => {
    const controller = new AbortController();
    getProject(projectId, controller.signal)
      .then((detail) => setModules(detail.project.enabled_modules))
      .catch(() => undefined);
    return () => controller.abort();
  }, [projectId]);

  const { job } = useBackgroundJob(jobId);
  useEffect(() => {
    if (job?.state !== "completed" || !jobId || delivered.current === jobId) return;
    delivered.current = jobId;
    getBackgroundJobResult<Draft>(jobId)
      .then((value) => {
        if (value && "items" in value) setDraft(value);
        setJobId(null);
      })
      .catch((caught) => setError(errorText(caught)));
  }, [job?.state, jobId]);

  const days: DayFacts[] = useMemo(() => {
    if (!overview) return [];
    const start = overview.days[0]?.date ?? overview.today;
    const end = overview.days[overview.days.length - 1]?.date ?? overview.today;
    return buildDays(overview, start, end);
  }, [overview]);

  const cards = useMemo(
    () => (overview ? queueCards(overview, overview.today) : []),
    [overview],
  );
  const debt = useMemo(() => (overview ? debtOf(overview) : null), [overview]);
  const status = useMemo(() => (overview ? planStatus(overview) : null), [overview]);

  /** Любая правка плана идёт черновиком: сервер сам защищает прошлое и закрепления. */
  const commit = useCallback(
    async (change: { items?: PlanItem[]; phases?: Phase[] }) => {
      if (!overview || overview.readonly) return;
      setBusy(true);
      try {
        const created = await preparation.draft(projectId, {
          mode: "manual",
          phases: change.phases ?? null,
          items: change.items ?? null,
          unit_ids: null,
          start: null,
          end: null,
          ...revisions(overview),
        });
        await preparation.apply(projectId, created.id, {
          selected_item_ids: null,
          apply_phases: change.phases != null,
        });
        setError(null);
        refresh();
      } catch (caught) {
        setError(errorText(caught));
      } finally {
        setBusy(false);
      }
    },
    [overview, projectId, refresh],
  );

  /** Серверные режимы распределения и долга: результат сразу виден в календаре. */
  const runMode = useCallback(
    async (mode: "count" | "catch_up" | "dismiss", range?: { start: string; end: string }) => {
      if (!overview || overview.readonly) return;
      setBusy(true);
      try {
        const created = await preparation.draft(projectId, {
          mode,
          phases: null,
          items: null,
          unit_ids: null,
          start: range?.start ?? overview.today,
          end: range?.end ?? overview.deadline ?? addDays(overview.today, 30),
          ...revisions(overview),
        });
        await preparation.apply(projectId, created.id, {
          selected_item_ids: null,
          apply_phases: false,
        });
        setError(null);
        refresh();
      } catch (caught) {
        setError(errorText(caught));
      } finally {
        setBusy(false);
      }
    },
    [overview, projectId, refresh],
  );

  /** Отметка даты пропускаемой живёт в параметрах, отдельной сущности не нужно. */
  const toggleRest = useCallback(
    async (value: string) => {
      if (!overview || overview.readonly) return;
      const current = overview.settings.config.rest_dates ?? [];
      const next = current.includes(value)
        ? current.filter((entry) => entry !== value)
        : [...current, value];
      setBusy(true);
      try {
        await preparation.settings(projectId, {
          expected_revision: overview.settings.revision,
          config: { ...overview.settings.config, rest_dates: next },
        });
        setError(null);
        refresh();
      } catch (caught) {
        setError(errorText(caught));
      } finally {
        setBusy(false);
      }
    },
    [overview, projectId, refresh],
  );

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

  async function startAi() {
    if (!overview || overview.readonly) return;
    setBusy(true);
    try {
      const started = await preparation.ai(projectId, {
        action: "distribute",
        instruction: "",
        confirmed: true,
        automatic: false,
        ...revisions(overview),
      });
      if (started.job_id) setJobId(started.job_id);
      else setError(started.reason ?? "Внешние модели недоступны.");
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  async function applyDraft() {
    if (!draft) return;
    setBusy(true);
    try {
      await preparation.apply(projectId, draft.id, { selected_item_ids: null, apply_phases: true });
      setDraft(null);
      refresh();
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  function openQuestion(topicId: string) {
    if (!topicId) return;
    navigate(`/projects/${projectId}?topic=${topicId}&tab=chat`);
  }

  if (!overview)
    return (
      <main className="prep-loading">
        {error ? (
          <>
            <ErrorState title="Подготовка не загрузилась" message={error} />
            <Button onClick={refresh}>Повторить</Button>
          </>
        ) : (
          <LoadingState label="Загружаем подготовку" placement="page" />
        )}
      </main>
    );

  const readonly = overview.readonly;
  const stripStart = overview.today;
  const stripEnd =
    overview.deadline && overview.deadline > overview.today
      ? overview.deadline
      : addDays(overview.today, 30);
  const started = cards.some((card) => card.opened);
  const invite = !readonly && cards.length > 0 && !started;
  const draftDates = draft ? new Set(draft.items.map((item) => item.on_date)) : undefined;

  return (
    <div className="plan-screen prep-screen">
      <aside className="plan-project-panel">
        <header className="program-project-title">
          <Link to={`/projects/${projectId}`} aria-label="В рабочую область">
            ←
          </Link>
          <strong>{overview.project_name}</strong>
        </header>
        <ProjectNav
          projectId={projectId}
          active="plan"
          modules={modules}
          className={`program-project-nav${invite ? " is-inviting" : ""}`}
        />
      </aside>

      <main className="plan-main prep-main">
        <PageHead
          title="Моя подготовка"
          eyebrow={
            overview.deadline
              ? `Экзамен ${dateLabel(overview.deadline)}${overview.exam_time ? `, ${overview.exam_time.slice(0, 5)}` : ""}`
              : "Дата экзамена не задана"
          }
          leading={
            status && (
              <span className="prep-status">
                <StatusBadge tone={status.composed === "full" ? "info" : "neutral"}>
                  {COMPOSED_LABEL[status.composed]}
                </StatusBadge>
                {status.progress && (
                  <StatusBadge tone={status.progress === "onTrack" ? "success" : "warning"}>
                    {status.progress === "onTrack" ? "Идёшь по плану" : `Отстаёшь · ${status.debt}`}
                  </StatusBadge>
                )}
              </span>
            )
          }
          actions={
            <>
              {started ? (
                <span className="prep-day-started">День начат</span>
              ) : (
                <Button
                  className={invite ? "is-inviting" : undefined}
                  disabled={busy || readonly}
                  onClick={() => setGreeting(true)}
                >
                  Начать день
                </Button>
              )}
              <Menu
                label="Распределить вопросы по дням"
                items={[
                  {
                    label: "Распределить без ИИ",
                    icon: <Wand2 size={13} />,
                    disabled: busy || readonly || !overview.deadline,
                    onSelect: () => void runMode("count"),
                  },
                  {
                    label: "Распределить с ИИ…",
                    icon: <Sparkles size={13} />,
                    disabled: busy || readonly || Boolean(jobId),
                    onSelect: () => void startAi(),
                  },
                ]}
                trigger={
                  <Button variant="secondary" disabled={busy || readonly}>
                    Распределить вопросы по дням <ChevronDown size={14} />
                  </Button>
                }
              />
            </>
          }
        />

        {error && <ErrorState title="Действие не завершено" message={error} />}
        {readonly && <p className="prep-note">Проект только для чтения. История и план сохранены.</p>}

        <Dashboard
          overview={overview}
          days={days}
          answers={answers}
          period={period}
          projectId={projectId}
          onPeriod={(value) => ui("period", value)}
          onDayAnswers={(value) => {
            ui("view", "history");
            ui("date", value);
          }}
        />

        <TodayQueue
          cards={cards}
          title="Сегодня"
          onOpen={openQuestion}
          onDistribute={() => void runMode("count")}
          onPickDay={() => {
            ui("view", "calendar");
            ui("date", overview.today);
          }}
          disabled={busy || readonly}
        />

        <BlocksStrip
          overview={overview}
          start={stripStart}
          end={stripEnd}
          disabled={busy || readonly}
          onEdit={setBlock}
          onAdd={setBlock}
          onAuto={() => {
            if (!overview.deadline) return;
            void commit({ phases: autoPhases(overview.today, overview.deadline) });
            const rest = autoRestDate(overview.today, overview.deadline);
            if (rest && !(overview.settings.config.rest_dates ?? []).includes(rest)) void toggleRest(rest);
          }}
        />

        <div className="prep-tabs">
          <SegmentedTabs
            label="Подготовка"
            value={tab}
            onChange={(value) => ui("view", value)}
            tabs={[
              { value: "calendar", label: "Календарь подготовки" },
              { value: "history", label: "История" },
              { value: "analytics", label: "Аналитика" },
            ]}
          />
          <span className="prep-tabs-tools">
            {overview.plan.can_undo && !readonly && (
              <Button variant="ghost" disabled={busy} onClick={() => void undo()}>
                <Undo2 size={13} /> Откатить план
              </Button>
            )}
            <IconButton label="Параметры подготовки" onClick={() => setSettings(true)}>
              <Settings2 size={15} />
            </IconButton>
          </span>
        </div>

        {tab === "calendar" && (
          <section className="prep-calendar">
            {draft && (
              <div className="prep-draft-ribbon">
                <span>
                  Предложение ИИ · {new Set(draft.items.map((item) => item.unit_id)).size} вопросов на{" "}
                  {new Set(draft.items.map((item) => item.on_date)).size} дней
                </span>
                <Button disabled={busy} onClick={() => void applyDraft()}>
                  Применить
                </Button>
                <Button variant="secondary" disabled={busy} onClick={() => setDraft(null)}>
                  Отклонить предложение
                </Button>
              </div>
            )}
            {jobId && (
              <p className="prep-note">
                ИИ распределяет вопросы: {job?.done ?? 0} из {job?.total ?? 0}.
              </p>
            )}
            <div className="prep-calendar-body">
              <aside className="prep-calendar-days">
                <DayTree
                  days={days}
                  selected={date}
                  onSelect={(value) => ui("date", value)}
                  onToggleRest={(value) => {
                    const day = days.find((entry) => entry.date === value);
                    if (day && day.planned > 0 && !day.isRest) {
                      setConfirm({
                        title: "Отметить день пропускаемым?",
                        body: `На ${dateLabel(value)} назначено ${day.planned} вопросов, ${day.opened} из них открыты. Назначения останутся на месте, автораспределение эту дату использовать не будет.`,
                        run: () => void toggleRest(value),
                      });
                    } else void toggleRest(value);
                  }}
                  onCatchUp={(value) => void runMode("catch_up", { start: value, end: stripEnd })}
                  hasDebt={Boolean(debt?.count)}
                  draftDates={draftDates}
                  disabled={busy || readonly}
                />
                <div className="prep-calendar-tools">
                  <Button
                    variant="secondary"
                    disabled={busy || readonly || !overview.deadline}
                    onClick={() => void runMode("count")}
                  >
                    <Wand2 size={13} /> Распределить вопросы
                  </Button>
                  <Tooltip label="Сложный пересчёт в эту переделку не входит" side="top">
                    <span>
                      <Button variant="ghost" disabled>
                        Пересчитать
                      </Button>
                    </span>
                  </Tooltip>
                </div>
              </aside>
              <DayQuestionsEditor
                key={date}
                overview={overview}
                date={date}
                busy={busy}
                disabled={readonly}
                hasDebt={Boolean(debt?.count)}
                onSave={(items) => void commit({ items })}
                onDropDebt={() =>
                  setConfirm({
                    title: "Снять долг?",
                    body: `В долге ${debt?.count ?? 0} вопросов с ${debt?.dates.length ?? 0} дат. Назначения будут сняты, реальные занятия и ответы останутся.`,
                    run: () => void runMode("dismiss"),
                  })
                }
                onCatchUp={() =>
                  setConfirm({
                    title: "Наверстать долг?",
                    body: `В долге ${debt?.count ?? 0} вопросов с ${debt?.dates.length ?? 0} дат. Они переедут на ближайшие свободные дни, старые незакрытые назначения снимутся.`,
                    run: () => void runMode("catch_up", { start: date, end: stripEnd }),
                  })
                }
                onEditProgram={() => navigate(`/projects/${projectId}/program`)}
              />
            </div>
          </section>
        )}

        {tab === "history" && (
          <HistoryTab
            projectId={projectId}
            overview={overview}
            days={days}
            selected={date}
            onSelect={(value) => ui("date", value)}
            onChanged={refresh}
          />
        )}

        {tab === "analytics" && (
          <AnalyticsTab
            overview={overview}
            days={days}
            answers={answers}
            aiAvailable={!readonly}
            aiBusy={busy}
            onRefreshCoach={() => void startAi()}
          />
        )}
      </main>

      {block && (
        <BlockForm
          overview={overview}
          value={block}
          busy={busy}
          onClose={() => setBlock(null)}
          onSave={(phases) => {
            setBlock(null);
            void commit({ phases });
          }}
        />
      )}

      {confirm && (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && setConfirm(null)}
          title={confirm.title}
          confirmLabel="Продолжить"
          onConfirm={() => {
            confirm.run();
            setConfirm(null);
          }}
        >
          <p>{confirm.body}</p>
        </ConfirmDialog>
      )}

      <Dialog
        open={settings}
        onOpenChange={setSettings}
        title="Параметры подготовки"
        description="Бюджет времени, правило долга и лимиты дня. Дата экзамена берётся из паспорта проекта."
      >
        <Settings
          key={overview.settings.revision}
          overview={overview}
          onSaved={() => {
            setSettings(false);
            refresh();
          }}
        />
      </Dialog>

      {greeting && <StartDayGreeting cards={cards} onClose={() => setGreeting(false)} />}
    </div>
  );
}
