/** «Моя подготовка»: дашборд, очередь дня, периоды и три вкладки на одном экране. */
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { ArrowLeft, ChevronDown, Settings2, Sparkles, Undo2, Wand2 } from "lucide-react";
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
} from "../components/ui";
import { ProjectNav } from "../components/domain";
import {
  preparation,
  revisions,
  errorText,
  type Phase,
  type PlanItem,
} from "../api/preparation";
import { cancelBackgroundJob } from "../api/backgroundJobs";
import { usePreparationData } from "../hooks/usePreparationData";
import { usePreparationAi } from "../hooks/usePreparationAi";
import { Dashboard, type DashboardPeriod } from "./preparation/Dashboard";
import { TodayQueue } from "./preparation/TodayQueue";
import { BlocksStrip } from "./preparation/BlocksStrip";
import { BlockForm } from "./preparation/BlockForm";
import { DayTree } from "./preparation/DayTree";
import { DayQuestionsEditor } from "./preparation/DayQuestionsEditor";
import { HistoryTab } from "./preparation/HistoryTab";
import { AnalyticsTab } from "./preparation/AnalyticsTab";
import { AiDistributionDialog } from "./preparation/AiDistributionDialog";
import { ExamBudget } from "./preparation/ExamBudget";
import { PreparationEvents } from "./preparation/PreparationEvents";
import { StartDayGreeting } from "./preparation/StartDayGreeting";
import { Settings } from "./preparation/Settings";
import { addDays, dateLabel } from "./preparation/dates";
import {
  autoPhases,
  buildDays,
  debtOf,
  planStatus,
  queueCards,
  type DayFacts,
} from "./preparation/model";

type Tab = "calendar" | "history" | "analytics";

const COMPOSED_LABEL = {
  none: "План не составлен",
  partial: "План частично составлен",
  full: "План составлен",
} as const;

/** Экран управляет действиями пользователя; загрузка и фоновые задачи изолированы в хуках. */
export function Plan() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams(
    localStorage.getItem(`tentex-preparation-view:${projectId}`) ?? "",
  );
  useEffect(() => {
    localStorage.setItem(`tentex-preparation-view:${projectId}`, params.toString());
  }, [projectId, params]);

  const { overview, setOverview, answers, modules, error: dataError, refresh } = usePreparationData(projectId);
  const [error, setError] = useState<string | null>(null);
  const [aiDialog, setAiDialog] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [block, setBlock] = useState<Phase | { start: string; end: string } | null>(null);
  const [confirm, setConfirm] = useState<{ title: string; body: string; run: () => void } | null>(null);
  const [greeting, setGreeting] = useState(false);
  const [settings, setSettings] = useState(false);
  const { jobId, setJobId, job, draft, clearDraft, error: aiError, retry: retryAi } = usePreparationAi(projectId);
  const displayError = error ?? dataError ?? aiError;

  const period: DashboardPeriod = params.get("period") === "14" ? "14" : "7";
  const tab = (params.get("view") as Tab) ?? "calendar";
  const date = params.get("date") ?? overview?.today ?? "";

  const ui = (key: string, value: string, extra: Record<string, string> = {}) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.set(key, value);
        Object.entries(extra).forEach(([name, entry]) => next.set(name, entry));
        return next;
      },
      { replace: true },
    );

  const days: DayFacts[] = overview ? buildDays(overview, overview.days[0]?.date ?? overview.today, overview.days[overview.days.length - 1]?.date ?? overview.today) : [];
  const cards = overview ? queueCards(overview, overview.today) : [];
  const debt = overview ? debtOf(overview) : null;
  const status = overview ? planStatus(overview) : null;

  /** Любая правка плана идёт черновиком: сервер сам защищает прошлое и закрепления. */
  const commit = async (change: { items?: PlanItem[]; phases?: Phase[] }) => {
      if (!overview || overview.readonly) return;
      setBusy(true);
      try {
        const created = await preparation.draft(projectId, {
          mode: "manual",
          include_pinned: false,
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
        setNotice("Изменения сохранены. Их можно откатить ниже.");
        window.dispatchEvent(new Event("tentex-preparation-changed"));
        refresh();
      } catch (caught) {
        setError(errorText(caught));
      } finally {
        setBusy(false);
      }
    };

  /** Серверные режимы распределения и долга: результат сразу виден в календаре. */
  const runMode = async (mode: "count" | "catch_up" | "dismiss", range?: { start: string; end: string }) => {
      if (!overview || overview.readonly) return;
      setBusy(true);
      try {
        const created = await preparation.draft(projectId, {
          mode,
          include_pinned: mode === "dismiss" || mode === "catch_up",
          phases: null,
          items: null,
          unit_ids: null,
          start: range?.start ?? overview.today,
          end: mode === "dismiss" ? overview.today : range?.end ?? overview.deadline ?? addDays(overview.today, 30),
          ...revisions(overview),
        });
        await preparation.apply(projectId, created.id, {
          selected_item_ids: null,
          apply_phases: false,
        });
        setError(null);
        const before = new Map(overview.plan.items.map(item => [item.id, item]));
        const changed = created.items.filter(item => JSON.stringify(before.get(item.id)) !== JSON.stringify(item)).length;
        setNotice(mode === "dismiss"
          ? `Снято назначений: ${created.removed_ids.length}. Занятия и ответы сохранены.`
          : `${mode === "catch_up" ? "Перенесено" : "Распределено"} назначений: ${changed}. Без даты: ${created.unassigned_ids.length}.${changed === 0 ? " Свободных дат с достаточным бюджетом нет или все вопросы уже назначены. Проверь параметры и календарь." : ""}`);
        window.dispatchEvent(new Event("tentex-preparation-changed"));
        ui("view", "calendar");
        refresh();
      } catch (caught) {
        setError(errorText(caught));
      } finally {
        setBusy(false);
      }
    };

  /** Отметка даты пропускаемой живёт в параметрах, отдельной сущности не нужно. */
  const toggleRest = async (value: string) => {
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
    };

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

  async function applyDraft() {
    if (!draft) return;
    setBusy(true);
    try {
      await preparation.apply(projectId, draft.id, { selected_item_ids: null, apply_phases: true });
      clearDraft();
      setNotice("Предложение ИИ применено. План можно откатить.");
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
        {displayError ? (
          <>
            <ErrorState title="Подготовка не загрузилась" message={displayError!} />
            <Button onClick={refresh}>Повторить</Button>
          </>
        ) : (
          <LoadingState label="Загружаем подготовку" placement="page" />
        )}
      </main>
    );

  const readonly = overview.readonly || Boolean(overview.deadline && overview.deadline < overview.today);
  const stripStart = overview.today;
  const stripEnd =
    overview.deadline && overview.deadline > overview.today
      ? overview.deadline
      : addDays(overview.today, 30);
  const started = overview.day_started;
  const invite = !readonly && cards.some(card => !card.opened) && !started;
  const draftDates = draft ? new Set(draft.items.map((item) => item.on_date)) : undefined;

  return (
    <div className="plan-screen prep-screen">
      <aside className="plan-project-panel">
        <header className="program-project-title">
          <Link to={`/projects/${projectId}`} aria-label="В рабочую область">
            <ArrowLeft size={16} />
          </Link>
          <strong>{overview.project_name}</strong>
        </header>
        <PreparationEvents overview={overview} onHistory={() => ui("view", "history")} />
        <ProjectNav
          projectId={projectId}
          active="plan"
          modules={modules}
          className="program-project-nav"
        />
      </aside>

      <main className="plan-main prep-main">
        <PageHead
          title="Моя подготовка"
          actions={
            <>
              {started ? (
                <span className="prep-day-started">День начат</span>
              ) : (
                <Button
                  className={invite ? "is-inviting" : undefined}
                  disabled={busy || readonly}
                  onClick={() => {
                    setBusy(true);
                    preparation.queue(projectId, overview.today, true).then(() => {
                      setGreeting(true); setOverview({ ...overview, day_started: true });
                      window.dispatchEvent(new Event("tentex-preparation-changed")); refresh();
                    }).catch(caught => setError(errorText(caught))).finally(() => setBusy(false));
                  }}
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
                    onSelect: () => setAiDialog(true),
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

        {status && <span className="prep-status">
                <StatusBadge tone={status.composed === "full" ? "info" : "neutral"}>
                  {COMPOSED_LABEL[status.composed]}
                </StatusBadge>
                {status.progress && (
                  <StatusBadge tone={status.progress === "onTrack" ? "success" : "warning"}>
                    {status.progress === "onTrack" ? "Идёшь по плану" : `Отстаёшь · ${status.debt}`}
                  </StatusBadge>
                )}
              </span>}
        <ExamBudget overview={overview} />
        {notice && <p className="prep-action-notice" role="status">{notice}</p>}
        {displayError && <ErrorState title="Действие не завершено" message={displayError} />}
        {aiError && job?.state === "completed" && <Button variant="secondary" onClick={retryAi}>Повторить загрузку предложения</Button>}
        {readonly && <p className="prep-note">Проект только для чтения. История и план сохранены.</p>}

        <Dashboard
          overview={overview}
          days={days}
          answers={answers}
          period={period}
          projectId={projectId}
          onPeriod={(value) => ui("period", value)}
          onDayAnswers={(value) => {
            ui("view", "history", { date: value });
          }}
        />

        <TodayQueue
          cards={cards}
          title="Сегодня"
          onOpen={openQuestion}
          onDistribute={() => void runMode("count")}
          onPickDay={() => {
            ui("view", "calendar", { date: overview.today });
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
            if (overview.deadline) void commit({ phases: autoPhases(overview.today, overview.deadline) });
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
                <Button variant="secondary" disabled={busy} onClick={() => { clearDraft(); }}>
                  Отклонить предложение
                </Button>
              </div>
            )}
            {jobId && (
              <p className="prep-note">
                {job?.state === "completed" ? "Загружаем предложение ИИ" : "ИИ распределяет вопросы"}{job?.total ? `: ${job.done} из ${job.total}` : "…"} <Button variant="ghost" onClick={() => { void cancelBackgroundJob(jobId).catch(caught => setError(errorText(caught))); }}>Отменить запрос</Button>
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
                    body: `В долге ${debt?.count ?? 0} вопросов с ${debt?.dates.length ?? 0} дат. Неоткрытые назначения, включая закреплённые, будут сняты. Занятия и ответы останутся.`,
                    run: () => void runMode("dismiss"),
                  })
                }
                onCatchUp={() =>
                  setConfirm({
                    title: "Наверстать долг?",
                    body: `В долге ${debt?.count ?? 0} вопросов с ${debt?.dates.length ?? 0} дат. Они переедут на ближайшие свободные дни, включая закреплённые назначения. Старые незакрытые назначения снимутся.`,
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

      {aiDialog && <AiDistributionDialog overview={overview} onClose={() => setAiDialog(false)} onStarted={id => { setJobId(id); setAiDialog(false); ui("view", "calendar"); }} />}
      {greeting && <StartDayGreeting cards={cards} onClose={() => setGreeting(false)} />}
    </div>
  );
}
