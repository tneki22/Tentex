import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router";
import {
  Archive, ArrowRightLeft, CheckCircle2, ChevronDown, Dumbbell, ExternalLink, FilePlus2, Pencil,
  CircleHelp, Plus, RotateCcw, Scissors, Sparkles, Trash2, Undo2,
} from "lucide-react";
import { LESSON_STATUS_LABELS, updateLesson, type LessonStatus, type LessonSummaryRead } from "../../api/lessons";
import { undoProjectAction } from "../../api/projects";
import { LessonDocument } from "../../components/domain";
import { Button, EmptyState, ErrorState, IconButton, LoadingState, Menu, SegmentedTabs, StatusBadge, Tooltip } from "../../components/ui";
import { useLesson } from "../../hooks/useLessons";
import { useLessonViewMode } from "../../hooks/useLessonViewMode";
import type { ProgramTreeNode } from "../programTree";
import { VIEW_MODE_TABS } from "./LessonTab";
import { errorText } from "./lessonTree";

interface LessonTopicPaneProps {
  projectId: string;
  topic: ProgramTreeNode;
  lessons: LessonSummaryRead[];
  lessonId: string | null;
  busy: boolean;
  onSelectLesson(lessonId: string | null): void;
  onQuickLesson(): void;
  onFromSources(): void;
  onChanged(): void;
}

const STATUS_TONE: Record<LessonStatus, "warning" | "success" | "neutral"> = {
  draft: "warning",
  ready: "success",
  archived: "neutral",
};

function StageButton({ icon, label, stage }: { icon: ReactNode; label: string; stage: string }) {
  return (
    <Tooltip label={`Появится на этапе ${stage}`} side="bottom">
      <span><Button variant="ghost" disabled>{icon}{label}</Button></span>
    </Tooltip>
  );
}

/** Центр для одной темы: формулировка, уроки темы и открытый урок (записка §2, бриф §12). */
export function LessonTopicPane({ projectId, topic, lessons, lessonId, busy, onSelectLesson, onQuickLesson, onFromSources, onChanged }: LessonTopicPaneProps) {
  const topicLessons = lessons.filter((lesson) => lesson.program_node_ids.includes(topic.id));
  const defaultLesson = topicLessons.find((lesson) => lesson.status !== "archived") ?? topicLessons[0];
  const openId = topicLessons.some((lesson) => lesson.id === lessonId) ? lessonId : defaultLesson?.id ?? null;
  const openLesson = topicLessons.find((lesson) => lesson.id === openId) ?? null;
  const lesson = useLesson(projectId, openId);
  const { mode, setMode } = useLessonViewMode(projectId);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const hasRange = topic.source_page_ranges.length > 0;
  const data = lesson.data && lesson.data.id === openId ? lesson.data : null;

  useEffect(() => {
    setError("");
  }, [openId]);

  async function change(command: { title?: string; status?: LessonStatus }) {
    if (!data) return;
    setSaving(true);
    setError("");
    try {
      await updateLesson(projectId, data.id, { ...command, expected_revision: data.revision });
      lesson.refresh();
      onChanged();
    } catch (caught) {
      setError(errorText(caught, "Урок не сохранился"));
      lesson.refresh();
    } finally {
      setSaving(false);
    }
  }

  async function undoCreate() {
    if (!data?.undo_sequence) return;
    setSaving(true);
    setError("");
    try {
      await undoProjectAction(projectId, data.undo_sequence);
      onSelectLesson(null);
      onChanged();
    } catch (caught) {
      setError(errorText(caught, "Отменить не удалось"));
    } finally {
      setSaving(false);
    }
  }

  const newLessonMenu = (
    <Menu
      label="Новый урок"
      trigger={<Button disabled={busy}><Plus size={15} />Новый урок<ChevronDown size={14} /></Button>}
      items={[
        { label: hasRange ? "Быстрый урок" : "Быстрый урок — у темы нет страниц из оглавления", icon: <FilePlus2 size={14} />, disabled: !hasRange, onSelect: onQuickLesson },
        { label: "Из источников…", icon: <ArrowRightLeft size={14} />, disabled: !hasRange, onSelect: onFromSources },
        { label: "Вручную — этап 2", icon: <Pencil size={14} />, disabled: true, onSelect: () => undefined },
        { label: "Собрать с ИИ — этап 7", icon: <Sparkles size={14} />, disabled: true, onSelect: () => undefined },
      ]}
    />
  );

  return (
    <div className="lessons-center-scroll">
      <header className="lessons-center-head">
        <span className="lessons-eyebrow">{topic.node_type === "subpoint" ? "Подпункт" : "Тема"} {topic.number}</span>
        <div className="lessons-topic-title-row">
          <h1>{topic.title}</h1>
          <div className="lessons-topic-summary">
            <span>{topic.basis_kind === "outline" ? "из оглавления" : "вручную"}</span>
            {openLesson && <StatusBadge tone={STATUS_TONE[openLesson.status]}>{LESSON_STATUS_LABELS[openLesson.status]}</StatusBadge>}
            {openLesson?.needs_review && <StatusBadge tone="warning">Требует проверки</StatusBadge>}
            {openLesson?.duration_minutes && <span>≈ {openLesson.duration_minutes} мин</span>}
          </div>
        </div>
        <div className="lessons-topic-actions">
          {newLessonMenu}
          {hasRange && <Tooltip label="Быстрый урок берёт связанные страницы основного источника из диапазона оглавления." side="bottom"><span><IconButton label="Как составляется быстрый урок"><CircleHelp size={15} /></IconButton></span></Tooltip>}
        </div>
      </header>

      {topicLessons.length > 1 && (
        <ul className="lessons-lesson-list" aria-label="Уроки темы">
          {topicLessons.map((item) => (
            <li key={item.id}>
              <button type="button" className={item.id === openId ? "is-active" : ""} onClick={() => onSelectLesson(item.id)}>
                <strong>{item.title}</strong>
                <StatusBadge tone={STATUS_TONE[item.status]}>{LESSON_STATUS_LABELS[item.status]}</StatusBadge>
                {item.needs_review && <StatusBadge tone="warning">Требует проверки</StatusBadge>}
                <span>{item.duration_minutes ? `≈ ${item.duration_minutes} мин` : "длительность не оценена"}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {topicLessons.length === 0 && (
        <EmptyState title="У темы ещё нет урока">
          <p>{hasRange ? "Быстрый урок соберёт страницы темы из оглавления без модели." : "У темы нет страниц из оглавления — соберите урок вручную (этап 2)."}</p>
          {hasRange && <div className="lessons-topic-actions"><Button onClick={onQuickLesson} disabled={busy}><FilePlus2 size={15} />Быстрый урок</Button><Tooltip label="Быстрый урок берёт связанные страницы основного источника из диапазона оглавления." side="bottom"><span><IconButton label="Как составляется быстрый урок"><CircleHelp size={15} /></IconButton></span></Tooltip></div>}
        </EmptyState>
      )}

      {openId && (
        <section className="lessons-lesson" aria-label="Открытый урок">
          {Boolean(lesson.error) && <><ErrorState message={errorText(lesson.error, "Урок не загрузился")} /><Button variant="secondary" onClick={lesson.refresh}>Повторить</Button></>}
          {!lesson.error && !data && <LoadingState label="Загружаем урок" />}
          {data && (
            <>
              <header className="lessons-lesson-head">
                <div className="lessons-lesson-toolbar">
                  <SegmentedTabs label="Способ показа урока" value={mode} tabs={VIEW_MODE_TABS} onChange={setMode} />
                  {data.status === "draft" && <Button variant="secondary" disabled={saving} onClick={() => void change({ status: "ready" })}><CheckCircle2 size={14} />Готов</Button>}
                  {data.status !== "draft" && <Button variant="secondary" disabled={saving} onClick={() => void change({ status: "draft" })}><RotateCcw size={14} />Вернуть в черновики</Button>}
                  {data.status !== "archived" && <Button variant="ghost" disabled={saving} onClick={() => void change({ status: "archived" })}><Archive size={14} />В архив</Button>}
                  {data.undo_sequence
                    ? <Button variant="ghost" disabled={saving} onClick={() => void undoCreate()}><Undo2 size={14} />Отменить</Button>
                    : <Tooltip label="Отменить можно только последнее действие проекта" side="bottom"><span><Button variant="ghost" disabled><Undo2 size={14} />Отменить</Button></span></Tooltip>}
                  <Link className="secondary-button" to={`/projects/${projectId}?topic=${topic.id}&tab=lesson&lesson=${data.id}`}><ExternalLink size={14} />Открыть в Рабочей области</Link>
                </div>
                <div className="lessons-block-toolbar" aria-label="Действия над блоком">
                  <StageButton icon={<Plus size={14} />} label="Добавить блок" stage="2 — ручной редактор" />
                  <StageButton icon={<ArrowRightLeft size={14} />} label="Переместить" stage="2 — ручной редактор" />
                  <StageButton icon={<Scissors size={14} />} label="Разрезать" stage="2 — ручной редактор" />
                  <StageButton icon={<Trash2 size={14} />} label="Удалить" stage="2 — ручной редактор" />
                  <StageButton icon={<Sparkles size={14} />} label="Дополнить с ИИ" stage="5 — ИИ «Дополнить урок»" />
                  <StageButton icon={<Dumbbell size={14} />} label="Добавить практику" stage="6 — задания" />
                </div>
                {error && <p className="inline-error" role="alert">{error}</p>}
              </header>
              <LessonDocument projectId={projectId} lesson={data} mode={mode} hiddenHeading={topic.title} />
            </>
          )}
        </section>
      )}
    </div>
  );
}
