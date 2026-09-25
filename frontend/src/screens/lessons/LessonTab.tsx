import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { CheckCircle2, GraduationCap, PencilLine, RotateCcw, Search, Zap } from "lucide-react";
import {
  createQuickLesson,
  LESSON_STATUS_LABELS,
  saveLessonPosition,
  setLessonCompleted,
  type LessonRead,
  type LessonSummaryRead,
} from "../../api/lessons";
import type { ProgramNodeRead } from "../../api/projects";
import { LessonDocument } from "../../components/domain/lesson/LessonDocument";
import { Button, EmptyState, ErrorState, LoadingState, SegmentedTabs, Select, StatusBadge } from "../../components/ui";
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
  onLessonsChanged?: () => void;
}

/** Вкладка «Урок» Рабочей области: чтение урока темы (записка «Уроки» §4.6). */
export function LessonTab({ projectId, node, preferredLessonId, onLessonsChanged }: LessonTabProps) {
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
  const progress = useLessonProgress(projectId, lesson.data, () => {
    overview.refresh();
    onLessonsChanged?.();
  });

  async function quickLesson() {
    setCreating(true);
    setCreateError("");
    try {
      const result = await createQuickLesson(projectId, node.id);
      saveChoice(projectId, node.id, result.lesson.id);
      setChoice(result.lesson.id);
      overview.refresh();
      onLessonsChanged?.();
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
          <p>{hasRange
            ? "Быстрый урок соберёт страницы темы из оглавления без модели. Потом его можно дополнить."
            : "У темы нет страниц из оглавления. Найдите её в материалах проекта и отметьте подходящие страницы — из них соберётся урок."}</p>
          <div className="lesson-tab-empty-actions">
            {hasRange
              ? <Button onClick={() => void quickLesson()} disabled={creating}><Zap size={15} />{creating ? "Создаём…" : "Быстрый урок"}</Button>
              : <Link className="primary-button" to={`${sectionLink}&panel=search`}><Search size={15} />Найти в материалах</Link>}
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
        {progress.completed
          ? (
            <Button variant="ghost" onClick={() => void progress.setCompleted(false)} disabled={progress.busy}>
              <RotateCcw size={15} />Пройден · снять отметку
            </Button>
          )
          : (
            <Button variant="secondary" onClick={() => void progress.setCompleted(true)} disabled={progress.busy || !lesson.data}>
              <CheckCircle2 size={15} />{progress.busy ? "Отмечаем…" : "Урок пройден"}
            </Button>
          )}
      </header>
      {progress.error && <p className="inline-error" role="alert">{progress.error}</p>}
      <div className="lesson-tab-body">
        {lesson.error
          ? <ErrorState message={lesson.error instanceof Error ? lesson.error.message : "Урок не загрузился"} />
          : lesson.data && lesson.data.id === current.id
            ? (
              <LessonDocument
                projectId={projectId}
                lesson={lesson.data}
                mode={mode}
                hiddenHeading={node.title}
                startBlockId={progress.startBlockId}
                onReadBlock={progress.onReadBlock}
              />
            )
            : <LoadingState label="Загружаем урок" />}
      </div>
    </div>
  );
}

/**
 * Прохождение урока: позиция чтения и «Урок пройден».
 *
 * Позиция сохраняется не чаще раза в пять секунд и только при смене блока —
 * прокрутка не должна бить в сервер на каждый кадр.
 */
function useLessonProgress(projectId: string, lesson: LessonRead | null, onCompletedChanged: () => void) {
  const [completedAt, setCompletedAt] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [startBlockId, setStartBlockId] = useState<string | null>(null);
  const saved = useRef<{ lessonId: string; blockId: string; at: number } | null>(null);

  const lessonId = lesson?.id ?? null;
  useEffect(() => {
    setCompletedAt(lesson?.completed_at ?? null);
    setStartBlockId(lesson?.last_block_id ?? null);
    setError("");
  }, [lessonId]); // eslint-disable-line react-hooks/exhaustive-deps

  const onReadBlock = useCallback((blockId: string) => {
    if (!lessonId) return;
    const previous = saved.current;
    const now = Date.now();
    if (previous && previous.lessonId === lessonId
      && (previous.blockId === blockId || now - previous.at < 5000)) return;
    saved.current = { lessonId, blockId, at: now };
    // Позиция чтения — удобство: сорвавшийся запрос не стоит показывать ошибкой.
    void saveLessonPosition(projectId, lessonId, blockId).catch(() => undefined);
  }, [projectId, lessonId]);

  async function setCompleted(completed: boolean) {
    if (!lessonId) return;
    setBusy(true);
    setError("");
    try {
      const result = await setLessonCompleted(projectId, lessonId, completed);
      setCompletedAt(result.lesson.completed_at);
      onCompletedChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось отметить урок");
    } finally {
      setBusy(false);
    }
  }

  return { completed: Boolean(completedAt), busy, error, startBlockId, onReadBlock, setCompleted };
}
