/** Аналитика: план и факт, темп, результаты по разделам и регулярность. */
import { Sparkles } from "lucide-react";
import {
  Button,
  HeatGrid,
  LineChart,
  StackedBar,
  StackedColumns,
  type ColumnDatum,
  type HeatCell,
} from "../../components/ui";
import { MachineMark, OfflineNotice, answerResultOf, answerResultToken, type AnswerResult } from "../../components/domain";
import type { Activity, Overview } from "../../api/preparation";
import { dateLabel, duration } from "./dates";
import { burnUp, dayOfMonth, decimal, paceOf, plural, programTotals, type DayFacts } from "./model";

interface AnalyticsTabProps {
  overview: Overview;
  days: DayFacts[];
  answers: Activity[];
  aiAvailable: boolean;
  aiBusy: boolean;
  onRefreshCoach: () => void;
}

const RESULTS: AnswerResult[] = ["good", "partial", "weak", "unchecked"];
/** Прогноз рисуется только при достаточном числе наблюдений. */
const MIN_OBSERVED_DAYS = 3;

/**
 * Вкладка аналитики.
 *
 * Накопительный график стоит первым: он один отвечает на план и факт,
 * отставание и прогноз завершения.
 */
export function AnalyticsTab({
  overview,
  days,
  answers,
  aiAvailable,
  aiBusy,
  onRefreshCoach,
}: AnalyticsTabProps) {
  const totals = programTotals(overview);
  const pace = paceOf(overview, days);
  const { plan, fact, total } = burnUp(overview, days);
  const todayIndex = days.findIndex((day) => day.isToday);
  const examIndex = days.findIndex((day) => day.isExam);

  const projection =
    pace.observedDays >= MIN_OBSERVED_DAYS && pace.actual && pace.actual > 0 && fact.length
      ? (() => {
          const last = fact[fact.length - 1];
          const need = Math.max(0, total - last.y);
          const span = need / pace.actual!;
          return { x: last.x + span, y: total, from: last };
        })()
      : null;

  const overrun =
    projection && examIndex >= 0 && projection.x > examIndex
      ? { from: examIndex, to: Math.min(projection.x, days.length - 1) }
      : null;
  const finishDate =
    projection && Math.round(projection.x) < days.length ? days[Math.round(projection.x)]?.date : null;

  const xLabels = days
    .map((day, index) => ({ x: index, label: dateLabel(day.date) }))
    .filter((_, index) => index % Math.max(1, Math.ceil(days.length / 6)) === 0);

  const work: ColumnDatum[] = days
    .filter((day) => day.date <= overview.today)
    .map((day) => {
      const load = overview.days.find((entry) => entry.date === day.date);
      return {
        key: day.date,
        label: String(dayOfMonth(day.date)),
        segments: [
          { value: load?.new_count ?? 0, token: "--purpose-study" },
          { value: load?.review_count ?? 0, token: "--purpose-review" },
        ],
        tooltip: `${dateLabel(day.date)} — изучено ${load?.new_count ?? 0}, повторений ${load?.review_count ?? 0}`,
      };
    });
  const studied = work.reduce((sum, column) => sum + column.segments[0].value, 0);
  const reviewed = work.reduce((sum, column) => sum + column.segments[1].value, 0);

  const bySection = new Map<string, Record<AnswerResult, number>>();
  for (const answer of answers) {
    const title = answer.path[0] ?? "Без раздела";
    const bucket = bySection.get(title) ?? { good: 0, partial: 0, weak: 0, unchecked: 0 };
    bucket[answerResultOf(answer.outcome)] += 1;
    bySection.set(title, bucket);
  }
  const sectionRows = [...bySection.entries()]
    .map(([title, bucket]) => {
      const count = RESULTS.reduce((sum, key) => sum + bucket[key], 0);
      return { title, bucket, count, share: count ? bucket.good / count : 0 };
    })
    .sort((left, right) => left.share - right.share);
  const worst = sectionRows.find((row) => row.bucket.partial > 0);
  const unchecked = overview.topics.filter((topic) => !topic.successful_attempts && !topic.latest_outcome).length;

  const weeks = buildWeeks(days, overview);

  const yesterday = days.find((day) => day.date === shift(overview.today, -1));
  const today = days.find((day) => day.isToday);

  return (
    <div className="prep-analytics-grid">
      <p className="prep-summary-sentence">
        {yesterday && yesterday.planned > 0 ? (
          <>
            Вчера открыто <strong>{yesterday.opened} из {yesterday.planned}</strong> вопросов,{" "}
          </>
        ) : (
          <>Вчера назначений не было, </>
        )}
        сегодня — <strong>{today?.opened ?? 0} из {today?.planned ?? 0}</strong>
        {pace.remaining > 0 ? (
          <>
            : осталось пройти <strong>{pace.remaining}</strong> из {totals.total}
          </>
        ) : (
          <>: программа пройдена целиком</>
        )}
        {overview.plan.unassigned_ids.length > 0 && <>, без даты — {overview.plan.unassigned_ids.length}</>}.
      </p>

      <article className="prep-card prep-analytics-wide">
        <h3>План и факт</h3>
        <LineChart
          ariaLabel="Накопительный график плана и факта"
          maxX={Math.max(days.length - 1, 1)}
          maxY={Math.max(total, 1)}
          ceilingLabel={`${total} вопросов`}
          xLabels={xLabels}
          overrun={overrun}
          markers={[
            ...(todayIndex >= 0 ? [{ x: todayIndex, label: "сегодня", token: "--accent" }] : []),
            ...(examIndex >= 0 ? [{ x: examIndex, label: "экзамен" }] : []),
          ]}
          series={[
            { key: "plan", points: plan, token: "--chart-plan", label: "Назначено", stepped: true },
            { key: "fact", points: fact, token: "--chart-fact", label: "Открыто", filled: true },
            ...(projection
              ? [
                  {
                    key: "projection",
                    points: [projection.from, { x: projection.x, y: projection.y }],
                    token: "--chart-fact",
                    label: "Прогноз",
                    dashed: true,
                  },
                ]
              : []),
          ]}
          readout={(x) => {
            const day = days[Math.round(x)];
            if (!day) return null;
            const planned = plan[Math.round(x)]?.y ?? 0;
            const done = fact[Math.round(x)]?.y;
            return `${dateLabel(day.date)} — назначено ${planned}${done != null ? `, открыто ${done}` : ""}`;
          }}
        />
        {projection ? (
          overrun && finishDate ? (
            <p className="prep-note is-warning">
              При текущем темпе программа закончится {dateLabel(finishDate)} — позже экзамена.
            </p>
          ) : (
            <p className="prep-note">
              При текущем темпе программа закончится {finishDate ? dateLabel(finishDate) : "до экзамена"}.
            </p>
          )
        ) : (
          <p className="prep-note">
            Для прогноза нужно не меньше трёх учебных дней с занятиями. Сейчас их {pace.observedDays}.
          </p>
        )}
      </article>

      <article className="prep-card prep-analytics-main">
        <h3>Изучение и повторение</h3>
        <StackedColumns data={work} ariaLabel="Изучение и повторение по дням" emptyLabel="Занятий пока не было" />
        <p className="prep-note">
          <i className="prep-swatch is-study" /> изучено {studied}
          <i className="prep-swatch is-review" /> повторений {reviewed}
        </p>
      </article>

      <article className="prep-card prep-analytics-side">
        <h3>Темп и прогноз</h3>
        <p className="prep-figure">
          <strong>{pace.actual != null ? `${decimal(pace.actual)} ${plural(Math.round(pace.actual), "вопрос", "вопроса", "вопросов")}` : "—"}</strong>
          <span>в день за последние 7 дней</span>
        </p>
        {pace.required != null && (
          <p className="prep-note">
            Чтобы успеть{overview.deadline ? ` к ${dateLabel(overview.deadline)}` : ""} — нужно{" "}
            {decimal(pace.required)} в день
            {pace.actual != null && (
              <>
                {" · "}
                {pace.actual >= pace.required
                  ? `опережение ${decimal(pace.actual - pace.required)}`
                  : `отставание ${decimal(pace.required - pace.actual)}`}
              </>
            )}
          </p>
        )}
        <p className="prep-note">
          Осталось {pace.remaining} {plural(pace.remaining, "вопрос", "вопроса", "вопросов")} на{" "}
          {pace.available} {plural(pace.available, "доступный день", "доступных дня", "доступных дней")}.
        </p>
        <p className="prep-note">Время за неделю: {duration(overview.summary.week_seconds)}.</p>
      </article>

      <article className="prep-card prep-analytics-main">
        <h3>Результаты по разделам</h3>
        {sectionRows.length ? (
          <>
            <ul className="prep-sections">
              {sectionRows.map((row) => (
                <li key={row.title}>
                  <span className="prep-section-name" title={row.title}>
                    {row.title}
                  </span>
                  <StackedBar
                    ariaLabel={`${row.title}: ${row.bucket.good} хороших из ${row.count}`}
                    segments={RESULTS.map((result) => ({
                      value: row.bucket[result],
                      token: answerResultToken[result],
                      label: result,
                    }))}
                  />
                  <span className="prep-section-count">{row.count}</span>
                </li>
              ))}
            </ul>
            {worst && (
              <p className="prep-note">
                Больше всего частичных ответов — «{worst.title}»: {worst.bucket.partial} из {worst.count}.
              </p>
            )}
          </>
        ) : (
          <p className="prep-note">За период сдач не было.</p>
        )}
        <p className="prep-note">Вопросов без единой проверки: {unchecked}.</p>
      </article>

      <article className="prep-card prep-analytics-side">
        <h3>Регулярность</h3>
        <HeatGrid weeks={weeks} ariaLabel="Занятия по дням недели" />
        <p className="prep-note">
          Занимался {days.filter((day) => day.seconds > 0).length} из{" "}
          {days.filter((day) => day.date <= overview.today).length}{" "}
          {plural(days.filter((day) => day.date <= overview.today).length, "дня", "дней", "дней")} · подряд{" "}
          {overview.summary.streak_days}.
        </p>
      </article>

      <article className="prep-card prep-analytics-wide prep-coach-card">
        <header>
          <h3>Что говорит наставник</h3>
          <MachineMark origin={overview.coach.origin === "ai" ? "Внешняя модель" : "Локальная рекомендация"} />
        </header>
        <p className="prep-coach-text">{overview.coach.text || "Рекомендации пока нет."}</p>
        {aiAvailable ? (
          <Button variant="secondary" onClick={onRefreshCoach} disabled={aiBusy}>
            <Sparkles size={14} /> {aiBusy ? "Обновляем…" : "Обновить аналитику с ИИ"}
          </Button>
        ) : (
          <OfflineNotice reason="disabled" alternative="Локальная рекомендация выше остаётся доступной." />
        )}
      </article>
    </div>
  );
}

/** Недели для тепловой карты: столбец — неделя, строка — день с понедельника. */
function buildWeeks(days: DayFacts[], overview: Overview): (HeatCell | null)[][] {
  if (!days.length) return [];
  const peak = Math.max(...days.map((day) => day.seconds), 1);
  const weeks: (HeatCell | null)[][] = [];
  let current: (HeatCell | null)[] = Array.from({ length: 7 }, () => null);
  days.forEach((day) => {
    const level = day.seconds === 0 ? 0 : (Math.min(4, Math.ceil((day.seconds / peak) * 4)) as 1 | 2 | 3 | 4);
    current[day.weekdayIndex] = {
      date: day.date,
      level,
      state: day.isExam ? "exam" : day.date > overview.today ? "future" : day.isRest ? "rest" : undefined,
      title: `${dateLabel(day.date)} — ${duration(day.seconds)}`,
    };
    if (day.weekdayIndex === 6) {
      weeks.push(current);
      current = Array.from({ length: 7 }, () => null);
    }
  });
  if (current.some(Boolean)) weeks.push(current);
  return weeks;
}

const shift = (value: string, days: number) => {
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
};
