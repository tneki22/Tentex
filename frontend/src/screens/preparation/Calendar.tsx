/** Дневной календарь показывает план и факт без рейтинга или окраски метрик. */
import { Link } from "react-router";
import { Button } from "../../components/ui";
import {
  workLabels,
  type Overview,
  type PlanItem,
} from "../../api/preparation";
import { dateLabel, duration } from "./dates";
export function Calendar({
  overview,
  selected,
  onSelect,
  onEdit,
  onStart,
  onUnderstood,
}: {
  overview: Overview;
  selected: string;
  onSelect: (date: string) => void;
  onEdit: (item: PlanItem) => void;
  onStart: (date: string) => void;
  onUnderstood: (id: string) => void;
}) {
  return (
    <section className="plan-agenda" aria-label="Календарь подготовки">
      {overview.days.map((day) => (
        <article
          key={day.date}
          className={`plan-day ${selected === day.date ? "is-selected" : ""}`}
        >
          <button
            className="plan-day-head"
            type="button"
            onClick={() => onSelect(day.date)}
            aria-expanded={selected === day.date}
          >
            <strong>
              {dateLabel(day.date)}
              {day.date === overview.today ? " · Сегодня" : ""}
            </strong>
            <span>План {day.planned_minutes} мин</span>
            <span>Факт {duration(day.active_seconds)}</span>
            <span>
              {day.completed_count}/{day.planned_count} заданий
            </span>
          </button>
          {selected === day.date && (
            <div className="plan-day-body">
              <p className="prep-muted">
                {day.is_rest
                  ? "День отдыха"
                  : `Доступно ${day.capacity_minutes} мин`}
                {day.overload_minutes > 0
                  ? ` · На ${day.overload_minutes} мин больше бюджета`
                  : ""}
              </p>
              {overview.plan.items
                .filter((item) => item.on_date === day.date)
                .sort((a, b) => a.order - b.order)
                .map((item) => {
                  const unit = overview.units.find(
                    (unit) => unit.id === item.unit_id,
                  );
                  const complete = overview.plan.completed_ids.includes(
                    item.id,
                  );
                  return (
                    <article className="prep-assignment" key={item.id}>
                      <header>
                        <span>
                          {complete ? "Выполнено" : "Запланировано"} ·{" "}
                          {workLabels[item.kind]}
                          {item.pinned ? " · Закреплено" : ""}
                        </span>
                        <strong>
                          {unit?.title ?? "Вопрос удалён из программы"}
                        </strong>
                        <span>{item.minutes} мин</span>
                      </header>
                      <p>{item.reason}</p>
                      <small>{item.estimate_source}</small>
                      <details>
                        <summary>
                          {unit?.kind === "ticket"
                            ? "Вопросы билета"
                            : "Открыть вопрос"}
                        </summary>
                        {unit?.topic_ids.map((id, index) => (
                          <p key={id}>
                            <Link
                              to={`/projects/${overview.project_id}?topic=${id}&tab=chat`}
                            >
                              {unit.topic_titles[index] ?? "Вопрос"}
                            </Link>
                          </p>
                        ))}
                      </details>
                      <div className="prep-actions">
                        <Button
                          variant="ghost"
                          disabled={
                            overview.readonly ||
                            complete ||
                            item.on_date < overview.today
                          }
                          onClick={() => onEdit(item)}
                        >
                          Дата, порядок и закрепление
                        </Button>
                        <Button
                          variant="ghost"
                          disabled={overview.readonly}
                          onClick={() => onUnderstood(item.unit_id)}
                        >
                          Разобрался
                        </Button>
                      </div>
                    </article>
                  );
                })}
              {day.planned_count === 0 && (
                <p>
                  На этот день заданий нет. Добавьте вопросы или распределите
                  оставшиеся.
                </p>
              )}
              <Button
                disabled={overview.readonly || !day.planned_count}
                onClick={() => onStart(day.date)}
              >
                Начать день
              </Button>
            </div>
          )}
        </article>
      ))}
    </section>
  );
}
