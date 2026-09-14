import type { LessonSummaryRead } from "../../api/lessons";
import { Button } from "../../components/ui";
import type { ProgramTreeNode } from "../programTree";
import { countsByNode, lessonStateMark, studyNodesOf } from "./lessonTree";

interface LessonSectionOverviewProps {
  section: ProgramTreeNode;
  lessons: LessonSummaryRead[];
  onOpenTopic(nodeId: string): void;
  onSelectTopics(nodeIds: string[]): void;
}

/** Центр для раздела: темы по порядку и состояние их уроков. */
export function LessonSectionOverview({ section, lessons, onOpenTopic, onSelectTopics }: LessonSectionOverviewProps) {
  const topics = studyNodesOf(section.children);
  const counts = countsByNode(lessons);
  const withoutLessons = topics.filter((topic) => {
    const item = counts.get(topic.id);
    return !item || item.drafts + item.ready === 0;
  });

  return (
    <div className="lessons-center-scroll">
      <header className="lessons-center-head">
        <span className="lessons-eyebrow">Раздел {section.number}</span>
        <h1>{section.title}</h1>
        <p>Тем: {topics.length} · без уроков: {withoutLessons.length}</p>
        <Button variant="secondary" disabled={withoutLessons.length === 0} onClick={() => onSelectTopics(withoutLessons.map((topic) => topic.id))}>
          Выбрать темы без уроков
        </Button>
      </header>
      {topics.length === 0
        ? <p className="lesson-document-empty">В разделе нет тем для изучения.</p>
        : (
          <ol className="lessons-topic-list">
            {topics.map((topic) => {
              const item = counts.get(topic.id);
              const state = lessonStateMark(item);
              return (
                <li key={topic.id}>
                  <span className="lessons-topic-number">{topic.number}</span>
                  <strong>{topic.title}</strong>
                  <span className={`lessons-state-mark ${state.tone}`} title={state.label}>{state.mark}</span>
                  <span className="lessons-topic-count">{item ? `уроков: ${item.drafts + item.ready}` : "уроков нет"}</span>
                  <Button variant="ghost" onClick={() => onOpenTopic(topic.id)}>Открыть тему</Button>
                </li>
              );
            })}
          </ol>
        )}
    </div>
  );
}
