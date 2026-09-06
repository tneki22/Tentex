/** Первые шаги и последние действия берутся из постоянного журнала проекта. */
import { ChevronDown, History, Trophy } from "lucide-react";
import { activityLabels, type Overview } from "../../api/preparation";

/** Тот же текст события, что и в ленте вкладки «История». */
function eventLabel(event: { kind: string; title: string }) {
  const label = event.kind === "answer" ? "Сдал ответ" : activityLabels[event.kind] ?? "Занятие";
  return event.title ? `${label} — «${event.title}»` : label;
}

/** Отображение дат событий всегда в часовом поясе учебного проекта. */
export function PreparationEvents({ overview }: { overview: Overview }) {
  const milestones = overview.milestones ?? [];
  const recent = overview.recent_events ?? [];
  const at = (value: string) => new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: overview.settings.config.timezone }).format(new Date(/[Z+]|-\d\d:\d\d$/.test(value.slice(10)) ? value : `${value}Z`));
  return <div className="prep-sidebar-events">
    <details className="prep-recent-events" open>
      <summary><History size={14} /> Последние события <ChevronDown size={13} /></summary>
      {recent.length ? <ol>{recent.map(event => <li key={event.id}><strong>{eventLabel(event)}</strong><time dateTime={event.occurred_at}>{at(event.occurred_at)}</time></li>)}</ol> : <p className="prep-note">Здесь появятся занятия и изменения плана.</p>}
    </details>
    <details className="prep-recent-events">
      <summary><Trophy size={14} /> Твои первые шаги <small>{milestones.length}/5</small> <ChevronDown size={13} /></summary>
      {milestones.length ? <ol className="prep-achievements">{milestones.map(event => <li key={event.key}>
        <span className="prep-achievement-icon" aria-hidden="true">{event.emoji}</span>
        <div><strong>{event.title}</strong><time dateTime={event.occurred_at}>{at(event.occurred_at)}</time></div>
      </li>)}</ol> : <p className="prep-note">Распредели вопросы на первый день — здесь появится первое достижение.</p>}
    </details>
  </div>;
}
