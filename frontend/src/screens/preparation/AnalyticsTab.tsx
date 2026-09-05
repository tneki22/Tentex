/** Аналитика: план и факт, темп, результаты по разделам и регулярность. */
import {
  HeatGrid,
  LineChart,
  StackedBar,
  StackedColumns,
  type ColumnDatum,
  type HeatCell,
} from "../../components/ui";
import { answerResultOf, answerResultToken, type AnswerResult } from "../../components/domain";
import type { Activity, Overview } from "../../api/preparation";
import { dateLabel, duration } from "./dates";
import { burnUp, dayOfMonth, decimal, paceOf, plural, programTotals, type DayFacts } from "./model";

interface AnalyticsTabProps {
  overview: Overview;
  days: DayFacts[];
  answers: Activity[];
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
}: AnalyticsTabProps) {
  const totals = programTotals(overview);
  const pace = paceOf(overview, days);
  const { plan, fact, total } = burnUp(overview, days);
  const todayIndex = days.findIndex((day) => day.isToday);
  const examIndex = days.findIndex((day) => day.isExam);

  const availableDates = days.filter(day => day.date > overview.today && !day.isRest && !day.isOffDay && !day.isExam && (!overview.deadline || day.date < overview.deadline));
  const projection = pace.observedDays >= MIN_OBSERVED_DAYS && pace.actual && pace.actual > 0 && pace.remaining > 0 && fact.length && availableDates.length
    ? (() => {
        const last = fact[fact.length - 1];
        const neededDays = Math.ceil(Math.max(0, total - last.y) / pace.actual!);
        const finish = availableDates[neededDays - 1];
        const targetDay = finish ?? availableDates[availableDates.length - 1];
        const y = Math.min(total, last.y + pace.actual! * availableDates.length);
        return { x: days.findIndex(day => day.date === targetDay.date), y, from: last, finish: finish?.date ?? null, missing: Math.max(0, total - Math.floor(y)) };
      })()
    : null;
  const overrun = null;
  const finishDate = projection?.finish;

  const xLabels = days
    .map((day, index) => ({ x: index, label: dateLabel(day.date) }))
    .filter((_, index) => index % Math.max(1, Math.ceil(days.length / 6)) === 0 || index === days.length - 1);

  const work: ColumnDatum[] = days
    .filter((day) => day.date <= overview.today)
    .map((day) => {
      const load = overview.days.find((entry) => entry.date === day.date);
      return {
        key: day.date,
        label: String(dayOfMonth(day.date)),
        segments: [
          { value: load?.opened_new_count ?? 0, token: "--purpose-study" },
          { value: load?.opened_review_count ?? 0, token: "--purpose-review" },
        ],
        tooltip: `${dateLabel(day.date)} — изучено ${load?.opened_new_count ?? 0}, повторений ${load?.opened_review_count ?? 0}`,
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
  const worst = [...sectionRows].sort((a, b) => b.bucket.partial - a.bucket.partial).find(row => row.bucket.partial > 0);
  const checked = new Set(answers.map(answer => answer.node_id));
  const unchecked = overview.topics.filter(topic => !checked.has(topic.node_id)).length;

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
        <div className="prep-analytics-chart-head"><div><h3>Как продвигается подготовка</h3><p className="prep-note">Уникальные открытые вопросы за весь срок · {days[0] ? dateLabel(days[0].date) : ""} — {days.length ? dateLabel(days[days.length - 1].date) : ""}</p></div><p className="prep-figure"><strong>{totals.opened}<small> / {totals.total}</small></strong></p></div>
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
            { key: "plan", points: plan, token: "--chart-plan", label: "План по датам", stepped: true },
            { key: "fact", points: fact, token: "--chart-fact", label: "Открыто", filled: true, stepped: true },
            ...(projection
              ? [
                  {
                    key: "projection",
                    points: [projection.from, { x: projection.x, y: projection.y }],
                    token: "--chart-fact",
                    label: "При текущем темпе",
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
        {projection ? <p className={`prep-note${projection.missing ? " is-warning" : ""}`}>
          {projection.missing ? `При текущем темпе к экзамену останется ${projection.missing} ${plural(projection.missing, "вопрос", "вопроса", "вопросов")}. Нужен темп ${decimal(pace.required ?? 0)} за учебный день.` : `При текущем темпе первый проход закончится ${finishDate ? dateLabel(finishDate) : "к экзамену"}.`}
          {" "}Отдых и пропуски исключены из прогноза.
        </p> : <p className="prep-note">{pace.remaining === 0 ? "Все вопросы уже открыты. Результаты проверки знаний показаны отдельно ниже." : `Для прогноза нужны три дня с занятиями и новые открытые вопросы. Сейчас дней с занятиями: ${pace.observedDays}.`}</p>}

      </article>

      <article className="prep-card prep-analytics-main">
        <h3>Изучение и повторение</h3>
        <p className="prep-note">Выполненные назначения календаря по дням</p>
        <StackedColumns data={work} ariaLabel="Изучение и повторение по дням" emptyLabel="Занятий пока не было" />
        <p className="prep-note">
          <i className="prep-swatch is-study" /> изучено {studied}
          <i className="prep-swatch is-review" /> повторений {reviewed}
        </p>
      </article>

      <article className="prep-card prep-analytics-side">
        <h3>Темп и прогноз</h3>
        <p className="prep-figure">
          <strong>{pace.actual != null ? `${decimal(pace.actual)} ${Number.isInteger(pace.actual) ? plural(pace.actual, "вопрос", "вопроса", "вопросов") : "вопроса"}` : "—"}</strong>
          <span>новых за учебный день · последние 7 дней</span>
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
                      label: ({ good: "Хорошие", partial: "Частичные", weak: "Слабые", unchecked: "Без проверки" })[result],
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
        <p className="prep-note">Интенсивность: до 30 мин · 30–60 мин · 1–2 ч · от 2 ч. Отдых не считается пропуском.</p>
        <p className="prep-note">
          Занимался {days.filter((day) => day.seconds > 0).length} из{" "}
          {days.filter((day) => day.date <= overview.today && ((!day.isRest && !day.isOffDay) || day.seconds > 0)).length}{" "}
          {plural(days.filter((day) => day.date <= overview.today && ((!day.isRest && !day.isOffDay) || day.seconds > 0)).length, "учебного дня", "учебных дней", "учебных дней")} · подряд{" "}
          {overview.summary.streak_days}.
        </p>
      </article>


    </div>
  );
}

/** Недели для тепловой карты: столбец — неделя, строка — день с понедельника. */
function buildWeeks(days: DayFacts[], overview: Overview): (HeatCell | null)[][] {
  if (!days.length) return [];
  const weeks: (HeatCell | null)[][] = [];
  let current: (HeatCell | null)[] = Array.from({ length: 7 }, () => null);
  days.forEach((day) => {
    const minutes = day.seconds / 60;
    const level = minutes === 0 ? 0 : minutes < 30 ? 1 : minutes < 60 ? 2 : minutes < 120 ? 3 : 4;
    current[day.weekdayIndex] = {
      date: day.date,
      level,
      state: day.isExam ? "exam" : day.date > overview.today ? "future" : (day.isRest || day.isOffDay) && day.seconds === 0 ? "rest" : undefined,
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
