import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import {
  Archive, ArrowRightLeft, CheckCircle2, ChevronDown, Dumbbell, ExternalLink, FilePlus2, Pencil,
  Plus, RotateCcw, Scissors, Sparkles, Trash2, Undo2,
} from "lucide-react";
import { editLessonBlocks, getLessonsOverview, LESSON_STATUS_LABELS, updateLesson, updateLessonNote, type LessonBlockCommand, type LessonStatus, type LessonSummaryRead } from "../../api/lessons";
import { undoProjectAction } from "../../api/projects";
import { LessonDocument } from "../../components/domain";
import { Button, EmptyState, ErrorState, LoadingState, Menu, SegmentedTabs, StatusBadge, Tooltip } from "../../components/ui";
import { useLesson } from "../../hooks/useLessons";
import { useLessonViewMode } from "../../hooks/useLessonViewMode";
import type { ProgramTreeNode } from "../programTree";
import { VIEW_MODE_TABS } from "./LessonTab";
import { errorText } from "./lessonTree";

const LessonNoteEditor = lazy(() => import("../../components/domain/lesson/LessonNoteEditor")
  .then((module) => ({ default: module.LessonNoteEditor })));

interface LessonTopicPaneProps {
  projectId: string;
  topic: ProgramTreeNode;
  lessons: LessonSummaryRead[];
  lessonId: string | null;
  busy: boolean;
  onSelectLesson(lessonId: string | null): void;
  onQuickLesson(): void;
  onFromSources(): void;
  onManual(): void;
  onChanged(): void;
  refreshKey: number;
  selectedBlockId: string | null;
  onSelectBlock(blockId: string | null): void;
  /** Кнопка свёртки правой панели — встраивается в тулбар урока, а не висит отдельной пустой строкой. */
  panelToggle: ReactNode;
  actionError: string;
}

const STATUS_TONE: Record<LessonStatus, "warning" | "success" | "neutral"> = {
  draft: "warning",
  ready: "success",
  archived: "neutral",
};

function StageButton({ icon, label, stage }: { icon: ReactNode; label: string; stage: string }) {
  return (
    <Tooltip label={`Появится на этапе ${stage}`} side="bottom">
      <span><Button variant="ghost" disabled aria-label={label}>{icon}<span className="toolbar-label">{label}</span></Button></span>
    </Tooltip>
  );
}

/** Центр для одной темы: формулировка, уроки темы и открытый урок (записка §2, бриф §12). */
export function LessonTopicPane({ projectId, topic, lessons, lessonId, busy, onSelectLesson, onQuickLesson, onFromSources, onManual, onChanged, refreshKey, selectedBlockId, onSelectBlock, panelToggle, actionError }: LessonTopicPaneProps) {
  const topicLessons = lessons.filter((lesson) => lesson.program_node_ids.includes(topic.id));
  const defaultLesson = topicLessons.find((lesson) => lesson.status !== "archived") ?? topicLessons[0];
  const openId = topicLessons.some((lesson) => lesson.id === lessonId) ? lessonId : defaultLesson?.id ?? null;
  const openLesson = topicLessons.find((lesson) => lesson.id === openId) ?? null;
  const lesson = useLesson(projectId, openId);
  const { mode, setMode } = useLessonViewMode(projectId);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [noteDraft, setNoteDraft] = useState<{ blockId: string; body: string } | null>(null);
  const revisionRef = useRef(1);
  const saveQueue = useRef<Promise<void>>(Promise.resolve());
  const hasRange = topic.source_page_ranges.length > 0;
  const data = lesson.data && lesson.data.id === openId ? lesson.data : null;

  useEffect(() => { lesson.refresh(); }, [refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (data && data.revision > revisionRef.current) revisionRef.current = data.revision;
  }, [data]);
  useEffect(() => { revisionRef.current = data?.revision ?? 1; setNoteDraft(null); }, [openId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!noteDraft) return;
    const timer = window.setTimeout(() => {
      saveQueue.current = saveQueue.current.then(async () => {
        try {
          const result = await updateLessonNote(projectId, openId ?? "", noteDraft.blockId, {
            expected_revision: revisionRef.current, body_md: noteDraft.body,
          });
          revisionRef.current = result.lesson.revision;
          lesson.refresh();
        } catch (caught) {
          setError(errorText(caught, "Пояснение не сохранилось"));
          lesson.refresh();
        }
      });
    }, 700);
    return () => window.clearTimeout(timer);
  }, [noteDraft, projectId, openId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setError("");
  }, [openId]);

  async function change(command: { title?: string; status?: LessonStatus }) {
    if (!data) return;
    setSaving(true);
    setError("");
    try {
      await saveQueue.current;
      const result = await updateLesson(projectId, data.id, { ...command, expected_revision: revisionRef.current });
      revisionRef.current = result.lesson.revision;
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
      onSelectBlock(null);
      const overview = await getLessonsOverview(projectId);
      if (overview.lessons.some((item) => item.id === data.id)) lesson.refresh();
      else onSelectLesson(null);
      onChanged();
    } catch (caught) {
      setError(errorText(caught, "Отменить не удалось"));
    } finally {
      setSaving(false);
    }
  }

  async function edit(command: Omit<LessonBlockCommand, "expected_revision">) {
    if (!data) return;
    setSaving(true);
    setError("");
    try {
      await saveQueue.current;
      const result = await editLessonBlocks(projectId, data.id, {
        ...command, expected_revision: revisionRef.current,
      });
      revisionRef.current = result.lesson.revision;
      if (command.operation === "delete") onSelectBlock(null);
      lesson.refresh();
      onChanged();
    } catch (caught) {
      setError(errorText(caught, "Блок не изменился"));
      lesson.refresh();
    } finally { setSaving(false); }
  }

  const newLessonMenu = (
    <Menu
      label="Новый урок"
      trigger={<Button disabled={busy}><Plus size={15} />Новый урок<ChevronDown size={14} /></Button>}
      items={[
        { label: hasRange ? "Быстрый урок" : "Быстрый урок — у темы нет страниц из оглавления", icon: <FilePlus2 size={14} />, disabled: !hasRange, onSelect: onQuickLesson },
        { label: "Из источников…", icon: <ArrowRightLeft size={14} />, disabled: !hasRange, onSelect: onFromSources },
        { label: "Вручную", icon: <Pencil size={14} />, onSelect: onManual },
        { label: "Собрать с ИИ — этап 7", icon: <Sparkles size={14} />, disabled: true, onSelect: () => undefined },
      ]}
    />
  );

  return (
    <div className="lessons-center-scroll">
      <header className="lessons-center-head">
        <div className="lessons-topic-meta-row">
          <span className="lessons-eyebrow">{topic.node_type === "subpoint" ? "Подпункт" : "Тема"} {topic.number}</span>
          <div className="lessons-topic-summary">
            <span>{topic.basis_kind === "outline" ? "из оглавления" : "вручную"}</span>
            {openLesson && <StatusBadge tone={STATUS_TONE[openLesson.status]}>{LESSON_STATUS_LABELS[openLesson.status]}</StatusBadge>}
            {openLesson?.needs_review && <StatusBadge tone="warning">Требует проверки</StatusBadge>}
            {openLesson?.duration_minutes && <span>≈ {openLesson.duration_minutes} мин</span>}
          </div>
        </div>
        <div className="lessons-topic-title-row">
          <h1>{topic.title}</h1>
          {newLessonMenu}
          {!data && <span className="lessons-toolbar-end">{panelToggle}</span>}
        </div>
        {actionError && <p className="inline-error" role="alert">{actionError}</p>}
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
          <p>{hasRange ? "Быстрый урок соберёт страницы темы из оглавления без модели." : "У темы нет страниц из оглавления — соберите урок вручную."}</p>
          <Button variant="secondary" disabled={busy} onClick={onManual}><Pencil size={15} />Собрать вручную</Button>
          {hasRange && <div className="lessons-topic-actions"><Button onClick={onQuickLesson} disabled={busy}><FilePlus2 size={15} />Быстрый урок</Button></div>}
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
                  {data.status === "draft" && <Button variant="secondary" aria-label="Готов" disabled={saving} onClick={() => void change({ status: "ready" })}><CheckCircle2 size={14} /><span className="toolbar-label">Готов</span></Button>}
                  {data.status !== "draft" && <Button variant="secondary" aria-label="Вернуть в черновики" disabled={saving} onClick={() => void change({ status: "draft" })}><RotateCcw size={14} /><span className="toolbar-label">Вернуть в черновики</span></Button>}
                  {data.status !== "archived" && <Button variant="ghost" aria-label="В архив" disabled={saving} onClick={() => void change({ status: "archived" })}><Archive size={14} /><span className="toolbar-label">В архив</span></Button>}
                  {data.undo_sequence
                    ? <Button variant="ghost" aria-label="Отменить" disabled={saving} onClick={() => void undoCreate()}><Undo2 size={14} /><span className="toolbar-label">Отменить</span></Button>
                    : <Tooltip label="Отменить можно только последнее действие проекта" side="bottom"><span><Button variant="ghost" disabled aria-label="Отменить"><Undo2 size={14} /><span className="toolbar-label">Отменить</span></Button></span></Tooltip>}
                  <Link className="secondary-button" aria-label="Открыть в Рабочей области" to={`/projects/${projectId}?topic=${topic.id}&tab=lesson&lesson=${data.id}`}><ExternalLink size={14} /><span className="toolbar-label toolbar-label-link">Открыть в Рабочей области</span></Link>
                  <span className="lessons-toolbar-end">{panelToggle}</span>
                </div>
                <div className="lessons-block-toolbar" aria-label="Действия над блоком">
                  <Menu label="Добавить пояснение" trigger={<Button variant="ghost" disabled={saving} aria-label="Добавить пояснение"><Plus size={14} /><span className="toolbar-label">Добавить пояснение</span></Button>} items={[
                    { label: "Текст", onSelect: () => void edit({ operation: "add_note", after_block_id: selectedBlockId ?? undefined, variant: "text" }) },
                    { label: "Пояснение", onSelect: () => void edit({ operation: "add_note", after_block_id: selectedBlockId ?? undefined, variant: "explanation" }) },
                    { label: "Важно", onSelect: () => void edit({ operation: "add_note", after_block_id: selectedBlockId ?? undefined, variant: "important" }) },
                    { label: "Пример", onSelect: () => void edit({ operation: "add_note", after_block_id: selectedBlockId ?? undefined, variant: "example" }) },
                    { label: "Заголовок", onSelect: () => void edit({ operation: "add_note", after_block_id: selectedBlockId ?? undefined, variant: "heading" }) },
                  ]} />
                  <Button variant="ghost" aria-label="Выше" disabled={!selectedBlockId || saving || data.blocks[0]?.id === selectedBlockId} onClick={() => void edit({ operation: "move_up", block_id: selectedBlockId ?? undefined })}><ArrowRightLeft size={14} /><span className="toolbar-label">Выше</span></Button>
                  <Button variant="ghost" aria-label="Ниже" disabled={!selectedBlockId || saving || data.blocks.at(-1)?.id === selectedBlockId} onClick={() => void edit({ operation: "move_down", block_id: selectedBlockId ?? undefined })}><ArrowRightLeft size={14} /><span className="toolbar-label">Ниже</span></Button>
                  <StageButton icon={<Scissors size={14} />} label="Разрезать" stage="2 — ручной редактор" />
                  <Button variant="ghost" aria-label="Удалить" disabled={!selectedBlockId || saving} onClick={() => void edit({ operation: "delete", block_id: selectedBlockId ?? undefined })}><Trash2 size={14} /><span className="toolbar-label">Удалить</span></Button>
                  <StageButton icon={<Sparkles size={14} />} label="Дополнить с ИИ" stage="5 — ИИ «Дополнить урок»" />
                  <StageButton icon={<Dumbbell size={14} />} label="Добавить практику" stage="6 — задания" />
                </div>
                {error && <p className="inline-error" role="alert">{error}</p>}
              </header>
              <LessonDocument projectId={projectId} lesson={data} mode={mode} hiddenHeading={topic.title}
                selectedBlockId={selectedBlockId} onSelectBlock={onSelectBlock}
                renderNoteEditor={(block) => <Suspense fallback={<LoadingState label="Открываем редактор" />}>
                  <LessonNoteEditor key={block.id} blockId={block.id} markdown={block.body_md ?? ""}
                    onChange={(body) => { if (body !== block.body_md) setNoteDraft({ blockId: block.id, body }); }} />
                </Suspense>}
              />
            </>
          )}
        </section>
      )}
    </div>
  );
}
