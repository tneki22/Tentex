import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { CheckCircle2, GraduationCap, PencilLine, Zap } from "lucide-react";
import { createQuickLesson, LESSON_STATUS_LABELS, type LessonSummaryRead } from "../../api/lessons";
import type { ProgramNodeRead } from "../../api/projects";
import { LessonDocument } from "../../components/domain";
import { Button, EmptyState, ErrorState, LoadingState, SegmentedTabs, Select, StatusBadge, Tooltip } from "../../components/ui";
import { useLesson, useLessonsOverview } from "../../hooks/useLessons";
import { useLessonViewMode, type LessonViewMode } from "../../hooks/useLessonViewMode";

const CHOICE_PREFIX = "tentex:lesson-choice:";

function readChoice(projectId: string, nodeId: string): string | null {
  try {
    return window.localStorage.getItem(`${CHOICE_PREFIX}${projectId}:${nodeId}`);
  } catch {
    return null;
  }
}

function saveChoice(projectId: string, nodeId: string, lessonId: string) {
  try {
    window.localStorage.setItem(`${CHOICE_PREFIX}${projectId}:${nodeId}`, lessonId);
  } catch {
    // выбор останется только до перезагрузки
  }
}

export const VIEW_MODE_TABS: Array<{ value: LessonViewMode; label: string }> = [
  { value: "pages", label: "Страницы" },
  { value: "text", label: "Текст" },
];

/** Уроки темы, которые можно читать сейчас: готовые первыми, архивные — нет. */
export function readableLessons(lessons: LessonSummaryRead[], nodeId: string): LessonSummaryRead[] {
  const rank = { ready: 0, draft: 1, archived: 2 } as const;
  return lessons
    .filter((lesson) => lesson.program_node_ids.includes(nodeId) && lesson.status !== "archived")
    .sort((left, right) => rank[left.status] - rank[right.status]);
}

interface LessonTabProps {
  projectId: string;
  node: ProgramNodeRead;
  preferredLessonId: string | null;
}

/** Вкладка «Урок» Рабочей области: чтение урока темы (записка «Уроки» §4.6). */
export function LessonTab({ projectId, node, preferredLessonId }: LessonTabProps) {
  const overview = useLessonsOverview(projectId);
  const { mode, setMode } = useLessonViewMode(projectId);
  const lessons = useMemo(() => readableLessons(overview.data?.lessons ?? [], node.id), [overview.data, node.id]);
  const [choice, setChoice] = useState<string | null>(() => preferredLessonId ?? readChoice(projectId, node.id));
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  useEffect(() => {
    setChoice(preferredLessonId ?? readChoice(projectId, node.id));
  }, [projectId, node.id, preferredLessonId]);

  const selectedId = lessons.find((lesson) => lesson.id === choice)?.id ?? lessons[0]?.id ?? null;
  const lesson = useLesson(projectId, selectedId);
  const sectionLink = `/projects/${projectId}/lessons?topic=${node.id}`;

  async function quickLesson() {
    setCreating(true);
    setCreateError("");
    try {
      const result = await createQuickLesson(projectId, node.id);
      saveChoice(projectId, node.id, result.lesson.id);
      setChoice(result.lesson.id);
      overview.refresh();
    } catch (caught) {
      setCreateError(caught instanceof Error ? caught.message : "Не удалось создать урок");
    } finally {
      setCreating(false);
    }
  }

  if (overview.loading && !overview.data) return <LoadingState label="Загружаем уроки темы" />;
  if (overview.error) {
    return <div className="lesson-tab"><ErrorState message={overview.error instanceof Error ? overview.error.message : "Уроки не загрузились"} /><Button variant="secondary" onClick={overview.refresh}>Повторить</Button></div>;
  }

  if (lessons.length === 0) {
    const hasRange = node.source_page_ranges.length > 0;
    return (
      <div className="lesson-tab is-empty">
        <EmptyState title="Для этой темы ещё нет урока" icon={<GraduationCap size={28} />}>
          <p>Быстрый урок соберёт страницы темы из оглавления без модели. Потом его можно дополнить.</p>
          <div className="lesson-tab-empty-actions">
            {hasRange
              ? <Button onClick={() => void quickLesson()} disabled={creating}><Zap size={15} />{creating ? "Создаём…" : "Быстрый урок"}</Button>
              : <Tooltip label="У темы нет страниц из оглавления — соберите урок вручную"><span><Button disabled><Zap size={15} />Быстрый урок</Button></span></Tooltip>}
            <Link className="secondary-button" to={sectionLink}>Собрать вручную</Link>
          </div>
          {createError && <p className="inline-error" role="alert">{createError}</p>}
        </EmptyState>
      </div>
    );
  }

  const current = lessons.find((item) => item.id === selectedId) ?? lessons[0];
  return (
    <div className="lesson-tab">
      <header className="lesson-tab-head">
        {lessons.length > 1 ? (
          <Select
            ariaLabel="Урок темы"
            value={current.id}
            options={lessons.map((item) => ({ value: item.id, label: `${item.title} · ${LESSON_STATUS_LABELS[item.status]}` }))}
            onValueChange={(value) => {
              if (!value) return;
              saveChoice(projectId, node.id, value);
              setChoice(value);
            }}
          />
        ) : <strong className="lesson-tab-title">{current.title}</strong>}
        {current.status === "draft" && <StatusBadge tone="warning">Черновик</StatusBadge>}
        {current.duration_minutes && <span className="lesson-duration">≈ {current.duration_minutes} мин</span>}
        <SegmentedTabs label="Способ показа урока" value={mode} tabs={VIEW_MODE_TABS} onChange={setMode} />
        <Link className="secondary-button" to={`${sectionLink}&lesson=${current.id}`}>
          <PencilLine size={14} />{current.status === "draft" ? "Продолжить редактирование" : "Редактировать"}
        </Link>
        <Tooltip label="Появится на этапе 3 — прохождение урока"><span><Button variant="ghost" disabled><CheckCircle2 size={15} />Урок пройден</Button></span></Tooltip>
      </header>
      <div className="lesson-tab-body">
        {lesson.error
          ? <ErrorState message={lesson.error instanceof Error ? lesson.error.message : "Урок не загрузился"} />
          : lesson.data && lesson.data.id === current.id
            ? <LessonDocument projectId={projectId} lesson={lesson.data} mode={mode} hiddenHeading={node.title} />
            : <LoadingState label="Загружаем урок" />}
      </div>
    </div>
  );
}
