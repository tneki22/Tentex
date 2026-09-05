/** Первые шаги и последние действия берутся из постоянного журнала проекта. */
import { ChevronDown, History, Trophy } from "lucide-react";
import type { Overview } from "../../api/preparation";

/** Отображение дат событий всегда в часовом поясе учебного проекта. */
export function PreparationEvents({ overview, onHistory }: { overview: Overview; onHistory: () => void }) {
  const milestones = overview.milestones ?? [];
  const recent = overview.recent_events ?? [];
  const at = (value: string) => new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: overview.settings.config.timezone }).format(new Date(/[Z+]|-\d\d:\d\d$/.test(value.slice(10)) ? value : `${value}Z`));
  return <div className="prep-sidebar-events">
    <h2><Trophy size={15} /> Твои первые шаги <small>{milestones.length}/5</small></h2>
    {milestones.length ? <ol className="prep-achievements">{milestones.map(event => <li key={event.key}>
      <span className="prep-achievement-icon" aria-hidden="true">{event.emoji}</span>
      <div><strong>{event.title}</strong><time dateTime={event.occurred_at}>{at(event.occurred_at)}</time></div>
    </li>)}</ol> : <p className="prep-note">Распредели вопросы на первый день — здесь появится первое достижение.</p>}
    <details className="prep-recent-events">
      <summary><History size={14} /> Последние события <ChevronDown size={13} /></summary>
      {recent.length ? <ol>{recent.map(event => <li key={event.id}><strong>{event.kind === "answer" ? "Сдан ответ" : event.title}</strong><time dateTime={event.occurred_at}>{at(event.occurred_at)}</time></li>)}</ol> : <p className="prep-note">Здесь появятся занятия и изменения плана.</p>}
      <button className="text-button" onClick={onHistory}>Вся история</button>
    </details>
  </div>;
}
