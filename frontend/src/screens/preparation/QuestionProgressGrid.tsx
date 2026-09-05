/** Один квадрат — один вопрос: видно масштаб оставшейся подготовки. */
import { Link } from "react-router";
import { Tooltip } from "../../components/ui";
import type { Overview } from "../../api/preparation";

const MAX_VISIBLE_QUESTIONS = 80;

/** Открытия и назначения различаются яркостью; результат проверки живёт отдельно. */
export function QuestionProgressGrid({ overview }: { overview: Overview }) {
  const opened = new Set(overview.days.flatMap(day => day.opened_topic_ids ?? []));
  const assigned = new Set(overview.plan.items.map(item => item.unit_id));
  return <div className="prep-question-grid" aria-label="Состояние вопросов программы">
    {overview.topics.slice(0, MAX_VISIBLE_QUESTIONS).map((topic, index) => {
      const state = opened.has(topic.node_id) || topic.active_seconds > 0 || topic.status !== "unseen" ? "open" : assigned.has(topic.unit_id) ? "assigned" : "empty";
      const label = `${index + 1}. ${topic.title} · ${state === "open" ? "открыт" : state === "assigned" ? "назначен" : "без даты"}`;
      return <Tooltip key={topic.node_id} label={label} side="top"><Link to={`/projects/${overview.project_id}?topic=${topic.node_id}`} aria-label={label} className={`prep-question-cell is-${state}`}>{index + 1}</Link></Tooltip>;
    })}
    {overview.topics.length > MAX_VISIBLE_QUESTIONS && <span className="prep-note">+{overview.topics.length - MAX_VISIBLE_QUESTIONS}</span>}
  </div>;
}
