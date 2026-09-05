/** Дашборд подготовки: время, состав программы и результаты сдач за один взгляд. */
import { QuestionProgressGrid } from "./QuestionProgressGrid";
import { Link } from "react-router";
import { BarChart, SegmentedTabs, StackedBar, StackedColumns, type ColumnDatum } from "../../components/ui";
import { answerResultOf, answerResultToken, type AnswerResult } from "../../components/domain";
import type { Activity, Overview } from "../../api/preparation";
import { duration, studyDate } from "./dates";
import { dayOfMonth, programTotals, sectionStats, type DayFacts } from "./model";

export type DashboardPeriod = "7" | "14";

interface DashboardProps {
  overview: Overview;
  days: DayFacts[];
  answers: Activity[];
  period: DashboardPeriod;
  onPeriod: (value: DashboardPeriod) => void;
  onDayAnswers: (date: string) => void;
  projectId: string;
}

const RESULTS: AnswerResult[] = ["good", "partial", "weak", "unchecked"];
const MAX_SECTIONS = 5;

/** Доля хороших ответов за отрезок, чтобы сравнить две недели одной строкой. */
function goodShare(answers: Activity[], from: string, to: string, config: Overview["settings"]["config"]) {
  const slice = answers.filter((item) => studyDate(item.occurred_at, config) >= from && studyDate(item.occurred_at, config) < to);
  if (!slice.length) return null;
  const good = slice.filter((item) => answerResultOf(item.outcome) === "good").length;
  return Math.round((good / slice.length) * 100);
}

/**
 * Три карточки дашборда с общей осью времени.
 *
 * «Время» и «Ответы» делят один период и одинаковый шаг столбцов, поэтому
 * день читается по вертикали без чтения подписей.
 */
export function Dashboard({
  overview,
  days,
  answers: allAnswers,
  period,
  onPeriod,
  onDayAnswers,
  projectId,
}: DashboardProps) {
  const start = shift(overview.today, 1 - Number(period));
  const past = days.filter((day) => day.date >= start && day.date <= overview.today);
  const answers = allAnswers.filter(answer => studyDate(answer.occurred_at, overview.settings.config) >= start);
  const todayLoad = overview.days.find(day => day.date === overview.today);
  const budget = overview.settings.config.daily_minutes == null ? null : todayLoad?.capacity_minutes ?? null;
  const today = past[past.length - 1];
  const todayMinutes = Math.round((today?.seconds ?? 0) / 60);
  const remaining = budget != null ? Math.max(0, budget - todayMinutes) : null;

  const timeData = past.map((day) => ({
    key: day.date,
    label: day.isToday ? "сег." : String(dayOfMonth(day.date)),
    target: overview.days.find(load => load.date === day.date)?.capacity_minutes ?? 0,
    value: Math.round(day.seconds / 60),
    hollow: (day.isRest || day.isOffDay) && day.seconds === 0,
    current: day.isToday,
    tooltip: `${day.date.slice(8)}.${day.date.slice(5, 7)} — ${duration(day.seconds)}${
      budget != null ? ` · бюджет ${overview.days.find(load => load.date === day.date)?.capacity_minutes ?? 0} мин` : ""
    }${day.planned ? `, открыто ${day.opened} из ${day.planned}` : ""}`,
  }));

  const totals = programTotals(overview);
  const sections = sectionStats(overview);
  const visibleSections = sections.slice(0, MAX_SECTIONS);
  // Плоская программа: одна строка «Без раздела» ничего не объясняет,
  // поэтому вместо неё те же числа словами.
  const flat = sections.length <= 1;

  const byDate = new Map<string, Record<AnswerResult, number>>();
  for (const answer of answers) {
    const date = studyDate(answer.occurred_at, overview.settings.config);
    const bucket = byDate.get(date) ?? { good: 0, partial: 0, weak: 0, unchecked: 0 };
    bucket[answerResultOf(answer.outcome)] += 1;
    byDate.set(date, bucket);
  }
  const answerData: ColumnDatum[] = past.map((day) => {
    const bucket = byDate.get(day.date);
    const total = bucket ? RESULTS.reduce((sum, key) => sum + bucket[key], 0) : 0;
    return {
      key: day.date,
      label: String(dayOfMonth(day.date)),
      segments: RESULTS.map((result) => ({
        value: bucket?.[result] ?? 0,
        token: answerResultToken[result],
      })),
      tooltip: total ? `${day.date.slice(8)}.${day.date.slice(5, 7)} — ${total} ответов` : undefined,
    };
  });
  const counts = RESULTS.map((result) => answers.filter((a) => answerResultOf(a.outcome) === result).length);
  const week = goodShare(allAnswers, shift(overview.today, -6), shift(overview.today, 1), overview.settings.config);
  const previousWeek = goodShare(allAnswers, shift(overview.today, -13), shift(overview.today, -6), overview.settings.config);

  return (
    <section className="prep-dashboard" aria-label="Сводка подготовки">
      <header className="prep-dashboard-head"><h2 className="prep-area-title">Подготовка в цифрах</h2>
        <SegmentedTabs
          label="Период сводки"
          value={period}
          onChange={onPeriod}
          className="prep-period"
          tabs={[
            { value: "7", label: "7 дней" },
            { value: "14", label: "14 дней" },
          ]}
        />
      </header>

      <article className="prep-card prep-tile">
        <h3>Время сегодня</h3>
        <p className="prep-figure">
          <strong>{duration(today?.seconds ?? 0)}</strong>
          {budget === 0 ? <span>Сегодня отдых по расписанию · время сохранено</span> : budget != null ? (
            <span>
              из {budget} мин плана{remaining ? ` · осталось ${remaining} мин` : " · план выполнен"}
            </span>
          ) : (
            <span>план по времени не задан</span>
          )}
        </p>
        <BarChart
          data={timeData}
          height={116}
          ariaLabel="Время подготовки по дням"
          emptyLabel="Занятий за период ещё не было"
        />
        <p className="prep-chart-legend"><i className="is-fact" /> время <i className="is-budget" /> бюджет дня</p>
        {budget == null && (
          <Link className="prep-tile-link" to={`/projects/${projectId}/settings`}>
            Задать дневной бюджет
          </Link>
        )}
      </article>

      <article className="prep-card prep-tile">
        <h3>Вопросы</h3>
        <p className="prep-figure">
          <strong>
            {totals.opened} из {totals.total}
          </strong>
          <span>пройдено</span>
        </p>
        <StackedBar
          size="large"
          ariaLabel="Состав программы"
          total={totals.total}
          segments={[
            { value: totals.opened, token: "--chart-fact", label: "открыто" },
            { value: totals.assigned, token: "--chart-fact", label: "назначено", soft: true },
          ]}
        />
        {flat ? (
          <p className="prep-result-line">
            {totals.opened} открыто · {totals.assigned} назначено ·{" "}
            {totals.total - totals.opened - totals.assigned} не в плане
          </p>
        ) : (
          <ul className="prep-sections">
            {visibleSections.map((section) => (
              <li key={section.title}>
                <span className="prep-section-name" title={section.title}>
                  {section.title}
                </span>
                <StackedBar
                  ariaLabel={`${section.title}: открыто ${section.opened} из ${section.total}`}
                  total={section.total}
                  segments={[
                    { value: section.opened, token: "--chart-fact", label: "открыто" },
                    { value: section.assigned, token: "--chart-fact", label: "назначено", soft: true },
                  ]}
                />
                <span className="prep-section-count">
                  {section.opened}/{section.total}
                </span>
              </li>
            ))}
          </ul>
        )}
        {flat && <QuestionProgressGrid overview={overview} />}
        <p className="prep-legend">
          <i className="is-open" /> открыто <i className="is-assigned" /> назначено <i className="is-rest" /> не в плане
          {sections.length > MAX_SECTIONS && <span> · ещё {sections.length - MAX_SECTIONS}</span>}
        </p>
      </article>

      <article className="prep-card prep-tile">
        <h3>Сданные ответы</h3>
        <p className="prep-figure">
          <strong>{answers.length}</strong>
          <span>за {period} дней</span>
        </p>
        <div className="prep-answer-counts">{RESULTS.map((result, index) => <span key={result}><i style={{ background: `var(${answerResultToken[result]})` }} /><b>{counts[index]}</b> {["хороших", "частичных", "слабых", "без проверки"][index]}</span>)}</div>
        <StackedColumns
          data={answerData}
          ariaLabel="Сданные ответы по дням"
          emptyLabel="Ответов за период не было"
          onSelect={onDayAnswers}
        />
        {answers.length === 0 && <Link className="prep-tile-link" to={`/projects/${projectId}`}>Сдать первый ответ →</Link>}
        {week != null && (
          <p className="prep-trend-line">
            Доля хороших за неделю — {week}%{previousWeek != null && `, было ${previousWeek}%`}
          </p>
        )}
      </article>
    </section>
  );
}

/** Сдвиг даты без перевода через часовой пояс браузера. */
function shift(value: string, days: number) {
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}
