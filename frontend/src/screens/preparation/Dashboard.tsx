/** Дашборд подготовки: время, состав программы и результаты сдач за один взгляд. */
import { Link } from "react-router";
import { BarChart, SegmentedTabs, StackedBar, StackedColumns, type ColumnDatum } from "../../components/ui";
import { answerResultOf, answerResultToken, type AnswerResult } from "../../components/domain";
import type { Activity, Overview } from "../../api/preparation";
import { duration } from "./dates";
import { dayOfMonth, programTotals, sectionStats, type DayFacts } from "./model";

export type DashboardPeriod = "14" | "30" | "90";

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
function goodShare(answers: Activity[], from: string, to: string) {
  const slice = answers.filter((item) => item.occurred_at.slice(0, 10) >= from && item.occurred_at.slice(0, 10) < to);
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
  answers,
  period,
  onPeriod,
  onDayAnswers,
  projectId,
}: DashboardProps) {
  const past = days.filter((day) => day.date <= overview.today);
  const budget = overview.settings.config.daily_minutes ?? null;
  const today = past[past.length - 1];
  const todayMinutes = Math.round((today?.seconds ?? 0) / 60);
  const remaining = budget != null ? Math.max(0, budget - todayMinutes) : null;

  const timeData = past.map((day) => ({
    key: day.date,
    label: String(dayOfMonth(day.date)),
    value: Math.round(day.seconds / 60),
    ghost: day.isToday && remaining ? remaining : undefined,
    hollow: (day.isRest || day.isOffDay) && day.seconds === 0,
    current: day.isToday,
    tooltip: `${day.date.slice(8)}.${day.date.slice(5, 7)} — ${duration(day.seconds)}${
      budget != null ? ` из ${budget} мин` : ""
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
    const date = answer.occurred_at.slice(0, 10);
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
  const week = goodShare(answers, shift(overview.today, -6), shift(overview.today, 1));
  const previousWeek = goodShare(answers, shift(overview.today, -13), shift(overview.today, -6));

  return (
    <section className="prep-dashboard" aria-label="Сводка подготовки">
      <header className="prep-dashboard-head">
        <SegmentedTabs
          label="Период сводки"
          value={period}
          onChange={onPeriod}
          className="prep-period"
          tabs={[
            { value: "14", label: "14 дней" },
            { value: "30", label: "30 дней" },
            { value: "90", label: "90 дней" },
          ]}
        />
      </header>

      <article className="prep-card prep-tile">
        <h3>Время сегодня</h3>
        <p className="prep-figure">
          <strong>{duration(today?.seconds ?? 0)}</strong>
          {budget != null ? (
            <span>
              из {budget} мин плана{remaining ? ` · осталось ${remaining} мин` : " · план выполнен"}
            </span>
          ) : (
            <span>план по времени не задан</span>
          )}
        </p>
        <BarChart
          data={timeData}
          target={budget}
          targetLabel={budget != null ? `${budget} мин` : undefined}
          ariaLabel="Время подготовки по дням"
          emptyLabel="Занятий за период ещё не было"
        />
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
        <p className="prep-result-line">
          {counts[0]} хороших · {counts[1]} частичных · {counts[2]} слабых · {counts[3]} без проверки
        </p>
        <StackedColumns
          data={answerData}
          ariaLabel="Сданные ответы по дням"
          emptyLabel="Ответов за период не было"
          onSelect={onDayAnswers}
        />
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
