/** Аналитика не смешивает затраченное время, проход программы и подтверждение памяти. */
import { useState } from "react";
import { Link } from "react-router";
import { Button, Select } from "../../components/ui";
import { activityLabels, type Overview } from "../../api/preparation";
import { dateLabel, duration } from "./dates";
export function Analytics({
  overview,
  onHistory,
}: {
  overview: Overview;
  onHistory: (filters: Record<string, string>) => void;
}) {
  const [filter, setFilter] = useState<string | null>(null);
  const summary = overview.summary;
  const topics = overview.topics.filter((topic) =>
    filter === "weak"
      ? topic.status !== "mastered"
      : filter === "unscored"
        ? topic.latest_outcome === null || topic.latest_outcome === "unscored"
        : filter === "errors" ? ["partial", "failed"].includes(topic.latest_outcome ?? "") : true,
  );
  const sections = [
    ...new Set(topics.map((topic) => topic.path[0] ?? "Без раздела")),
  ];
  const max = Math.max(
    1,
    ...overview.days.flatMap((day) => [
      day.planned_minutes,
      day.active_seconds / 60,
    ]),
  );
  const memory = overview.memory;
  const trend = overview.days.filter((day) => day.date <= overview.today);
  const points = (key: "passed_count" | "confirmed_count") => trend.map((day, index) =>
    `${20 + index * 600 / Math.max(1, trend.length - 1)},${110 - (day[key] ?? 0) * 90 / Math.max(1, summary.total_topics)}`).join(" ");
  const timeLabel = (value: string) => new Date(value).toLocaleTimeString("ru-RU", {
    hour: "2-digit", minute: "2-digit", timeZone: overview.settings.config.timezone,
  });
  return (
    <section className="prep-analytics">
      <div className="plan-summary">
        <div>
          <span>Пройдено</span>
          <strong>
            {summary.passed_topics} / {summary.total_topics}
          </strong>
        </div>
        <div>
          <span>Подтверждено</span>
          <strong>{summary.confirmed_topics}</strong>
        </div>
        <div>
          <span>Освоено до цели</span>
          <strong>{summary.mastered_topics}</strong>
        </div>
        <div>
          <span>Неделя</span>
          <strong>{duration(summary.week_seconds)}</strong>
        </div>
      </div>
      <p>{summary.pace_explanation}</p>
      <p>Учебных дней подряд: {summary.streak_days}. Запланированный отдых не прерывает серию.</p>
      <p>
        {summary.projected_finish
          ? `При таком темпе: ${dateLabel(summary.projected_finish)}`
          : "Даты завершения пока нет."}
      </p>
      <section className="prep-card">
        <h3>Занятия сегодня</h3>
        {!overview.today_intervals?.length ? <p>Активных интервалов пока нет.</p> :
          overview.today_intervals.map((interval, index) => <button className="prep-time-row" key={index}
            onClick={() => onHistory({date_from: overview.today, date_to: overview.today,
              ...(interval.node_id ? {node_id: interval.node_id} : {}), kind: interval.kind})}>
            <span>{timeLabel(interval.started_at)}–{timeLabel(interval.ended_at)}</span>
            <span>{activityLabels[interval.kind]} · {interval.title}</span>
            <strong>{duration(interval.seconds)}</strong>
          </button>)}
      </section>
      <section className="prep-card">
        <h3>Время: план и факт</h3>
        <p className="prep-muted">
          Тонкая линия — план, широкая — фактическое время.
        </p>
        {overview.days.map((day) => (
          <button
            className="prep-time-row"
            key={day.date}
            onClick={() =>
              onHistory({ date_from: day.date, date_to: day.date })
            }
          >
            <span>{dateLabel(day.date)}</span>
            <span className="prep-time-bars">
              <i style={{ width: `${(day.planned_minutes / max) * 100}%` }} />
              <b
                style={{ width: `${(day.active_seconds / 60 / max) * 100}%` }}
              />
            </span>
            <span>
              {day.planned_minutes} / {Math.round(day.active_seconds / 60)} мин
            </span>
          </button>
        ))}
        <Button
          variant="ghost"
          onClick={() =>
            onHistory({ date_from: overview.today, date_to: overview.today })
          }
        >
          Интервалы сегодня
        </Button>
      </section>
      <section className="prep-card">
        <h3>Проход и подтверждение по дням</h3>
        <svg viewBox="0 0 640 130" role="img" aria-label="Динамика пройденных и подтверждённых вопросов" style={{width: "100%"}}>
          <path d="M20 15V110H620" fill="none" stroke="var(--line)" />
          <polyline points={points("passed_count")} fill="none" stroke="var(--muted)" strokeWidth="2" strokeDasharray="5 4" />
          <polyline points={points("confirmed_count")} fill="none" stroke="var(--ink)" strokeWidth="2" />
          <text x="20" y="125" fill="var(--muted)" fontSize="10">{trend[0] ? dateLabel(trend[0].date) : ""}</text>
          <text x="620" y="125" textAnchor="end" fill="var(--muted)" fontSize="10">{dateLabel(overview.today)}</text>
        </svg>
        <div className="prep-trend">
          {overview.days.map((day) => (
            <button
              key={day.date}
              onClick={() =>
                onHistory({ date_from: day.date, date_to: day.date })
              }
            >
              <small>{dateLabel(day.date)}</small>
              <strong>
                {day.passed_count ?? 0} / {day.confirmed_count ?? 0}
              </strong>
            </button>
          ))}
        </div>
        <p className="prep-muted">
          Пройдено / подтверждено. Чтение само по себе не подтверждает знание.
        </p>
      </section>
      <section className="prep-card">
        <h3>Попытки и занятия</h3>
        <table className="prep-results-table">
          <thead><tr><th>Условия</th><th>Успешно</th><th>Частично</th><th>Неуспешно</th><th>Ожидают проверки</th></tr></thead>
          <tbody>{[["memory", "По памяти"], ["supported", "С опорой"], ["unknown", "Условия неизвестны"]].map(([mode,label]) =>
            <tr key={mode}><th>{label}</th>{["passed","partial","failed","pending"].map((outcome) =>
              <td key={outcome}>{summary.results_by_mode?.[mode]?.[outcome] ?? 0}</td>)}</tr>)}</tbody>
        </table>
        <p>{summary.disagreement_percent === null ? "Для сравнения оценок нужны системная оценка и самооценка одной попытки."
          : `Оценки расходятся в ${summary.disagreement_percent}% из ${summary.assessment_pairs} сопоставимых попыток.`}</p>
        <div className="prep-actions">
          {[
            ["passed", "Зачтено", summary.passed_attempts],
            ["partial", "Частично", summary.partial_attempts],
            ["failed", "Не зачтено", summary.failed_attempts],
            ["pending", "Ожидают проверки", summary.pending_attempts],
          ].map(([key, label, count]) => (
            <Button
              key={key}
              variant="ghost"
              onClick={() => onHistory({ outcome: String(key) })}
            >
              {label}: {count}
            </Button>
          ))}
        </div>
        <div className="prep-actions">
          <Button
            variant="ghost"
            onClick={() => onHistory({ disputed: "true" })}
          >
            Спорных оценок: {summary.disputed_attempts}
          </Button>
          <Button
            variant="ghost"
            onClick={() => onHistory({ answer_mode: "memory" })}
          >
            По памяти: {summary.memory_attempts}
          </Button>
          <Button
            variant="ghost"
            onClick={() => onHistory({ answer_mode: "supported" })}
          >
            С опорой: {summary.supported_attempts}
          </Button>
        </div>
        {Object.entries(summary.seconds_by_kind).map(([kind, seconds]) => (
          <Button
            variant="ghost"
            key={kind}
            onClick={() => onHistory({ kind })}
          >
            {activityLabels[kind] ?? kind}: {duration(seconds)}
          </Button>
        ))}
      </section>
      <section className="prep-card">
        <h3>Память к экзамену</h3>
        <p>{memory.reason}</p>
        {memory.available ? (
          <div className="prep-comparison">
            <div>
              <strong>С выполнением плана</strong>
              <p>
                {memory.with_plan
                  ? `${Math.round(memory.with_plan.lower_percent)}–${Math.round(memory.with_plan.upper_percent)}% подтверждённой части`
                  : "Недостаточно наблюдений"}
              </p>
            </div>
            <div>
              <strong>Без дальнейших занятий</strong>
              <p>
                {memory.without_study
                  ? `${Math.round(memory.without_study.lower_percent)}–${Math.round(memory.without_study.upper_percent)}% подтверждённой части`
                  : "Недостаточно наблюдений"}
              </p>
            </div>
          </div>
        ) : (
          <p>
            Процент не вычисляется, пока нет достаточных отложенных проверок.
          </p>
        )}
        <p className="prep-muted">
          {memory.observations} наблюдений · {memory.distinct_topics} вопросов ·{" "}
          {memory.observed_days} дней. Неизвестных вопросов:{" "}
          {memory.unknown_topics}. {memory.method}
        </p>
      </section>
      <section>
        <header className="prep-section-head">
          <h3>Вопросы по разделам</h3>
          <Select
            value={filter}
            emptyOption="Все вопросы"
            ariaLabel="Фильтр вопросов"
            options={[
              { value: "weak", label: "Ещё не освоены" },
              { value: "unscored", label: "Без проверки" },
              { value: "errors", label: "С последними ошибками" },
            ]}
            onValueChange={setFilter}
          />
        </header>
        {sections.map((section) => (
          <details className="prep-card" key={section}>
            <summary>
              {section} ·{" "}
              {
                topics.filter(
                  (topic) => (topic.path[0] ?? "Без раздела") === section,
                ).length
              }
            </summary>
            {topics
              .filter((topic) => (topic.path[0] ?? "Без раздела") === section)
              .map((topic) => (
                <article className="prep-topic" key={topic.node_id}>
                  <Link
                    to={`/projects/${overview.project_id}?topic=${topic.node_id}&tab=chat`}
                  >
                    {topic.title}
                  </Link>
                  <p>{topic.reason}</p>
                  <small>
                    Успешных проверок: {topic.successful_attempts} /{" "}
                    {topic.required_successes} ·{" "}
                    {duration(topic.active_seconds)} ·{" "}
                    {topic.has_material
                      ? "Материал есть"
                      : "Материал не привязан"}
                    {topic.due ? ` · Повторить ${dateLabel(topic.due)}` : ""}
                  </small>
                  {topic.missed_points.length > 0 && (
                    <p>Упущено: {topic.missed_points.join("; ")}</p>
                  )}
                  {Object.entries(topic.recurring_omissions ?? {}).map(([point, count]) =>
                    <p key={point}>Повторяющийся пропуск ({count} попытки): {point}</p>)}
                  <Button
                    variant="ghost"
                    onClick={() => onHistory({ node_id: topic.node_id })}
                  >
                    История вопроса
                  </Button>
                </article>
              ))}
          </details>
        ))}
      </section>
    </section>
  );
}
