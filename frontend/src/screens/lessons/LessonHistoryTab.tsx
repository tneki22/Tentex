import { useMemo } from "react";
import { CheckCircle2, History } from "lucide-react";
import type { ProgramNodeRead } from "../../api/projects";
import { Button, ErrorState, LoadingState } from "../../components/ui";
import { useLessonsOverview } from "../../hooks/useLessons";

const WHEN = new Intl.DateTimeFormat("ru-RU", { dateStyle: "long", timeStyle: "short" });

/**
 * «История» учебниковой темы, пока её ведут только уроки.
 *
 * Отметка «Урок пройден» пишет занятие в общий журнал `study_activities`, но
 * лента «Моей подготовки» работает только в экзаменационном проекте, поэтому
 * здесь видна её учебниковая часть — пройденные уроки темы.
 */
export function LessonHistoryTab({ projectId, node }: { projectId: string; node: ProgramNodeRead }) {
  const overview = useLessonsOverview(projectId);
  const completed = useMemo(
    () => (overview.data?.lessons ?? [])
      .filter((lesson) => lesson.program_node_ids.includes(node.id) && lesson.completed_at)
      .sort((left, right) => (right.completed_at ?? "").localeCompare(left.completed_at ?? "")),
    [overview.data, node.id],
  );

  if (overview.loading && !overview.data) return <LoadingState label="Загружаем историю темы" />;
  if (overview.error) {
    return (
      <div className="workspace-empty-copy">
        <ErrorState message={overview.error instanceof Error ? overview.error.message : "История не загрузилась"} />
        <Button variant="secondary" onClick={overview.refresh}>Повторить</Button>
      </div>
    );
  }

  if (completed.length === 0) {
    return (
      <div className="workspace-empty-copy">
        <History size={26} />
        <h2>История</h2>
        <p>Пока пусто: отметьте урок пройденным во вкладке «Урок». Занятия, попытки и повторения появятся вместе с вертикалью «Занятия».</p>
      </div>
    );
  }

  return (
    <div className="lesson-history">
      <ol className="lesson-history-list">
        {completed.map((lesson) => (
          <li key={lesson.id}>
            <CheckCircle2 size={15} aria-hidden="true" />
            <strong>{lesson.title}</strong>
            <span>Урок пройден</span>
            <time dateTime={lesson.completed_at ?? undefined}>
              {lesson.completed_at ? WHEN.format(new Date(lesson.completed_at)) : ""}
            </time>
          </li>
        ))}
      </ol>
      <p className="lessons-panel-hint">Время занятий, попытки и повторения появятся вместе с вертикалью «Занятия».</p>
    </div>
  );
}
