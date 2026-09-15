import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import {
  AlertTriangle, Archive, ArrowDown, ArrowRightLeft, ArrowUp, CheckCircle2, ChevronDown, Combine, Dumbbell, ExternalLink,
  FilePlus2, Image, Link2, Pencil, Plus, RotateCcw, Scissors, Sparkles, Trash2, Undo2, X,
} from "lucide-react";
import {
  confirmLesson, editLessonBlocks, getLessonsOverview, LESSON_STATUS_LABELS, unbindLessonBindings, updateLesson,
  updateLessonNote, uploadLessonImage, type LessonBlockCommand, type LessonBlockRead, type LessonChangeResult,
  type LessonNoteVariant, type LessonStatus, type LessonSummaryRead, type LessonUnbindOffer,
} from "../../api/lessons";
import { undoProjectAction } from "../../api/projects";
import { LessonDocument } from "../../components/domain";
import type { LessonSplitPoint } from "../../components/domain/lesson/LessonDocument";
import { Button, Dialog, EmptyState, ErrorState, LoadingState, Menu, SegmentedTabs, Select, StatusBadge, Tooltip } from "../../components/ui";
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
  /** Изучаемые узлы программы — для «Добавить тему» в урок по нескольким темам. */
  studyNodes: ProgramTreeNode[];
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

const NOTE_VARIANTS: Array<{ value: LessonNoteVariant; label: string }> = [
  { value: "text", label: "Текст" },
  { value: "heading", label: "Заголовок" },
  { value: "explanation", label: "Пояснение" },
  { value: "important", label: "Важно" },
  { value: "example", label: "Пример" },
  { value: "definition", label: "Определение" },
  { value: "warning", label: "Предупреждение" },
];

function StageButton({ icon, label, stage }: { icon: ReactNode; label: string; stage: string }) {
  return (
    <Tooltip label={`Появится на этапе ${stage}`} side="bottom">
      <span><Button variant="ghost" disabled aria-label={label}>{icon}<span className="toolbar-label toolbar-label-stage">{label}</span></Button></span>
    </Tooltip>
  );
}

/** Центр для одной темы: формулировка, уроки темы и открытый урок (записка §2, бриф §12). */
export function LessonTopicPane({ projectId, topic, studyNodes, lessons, lessonId, busy, onSelectLesson, onQuickLesson, onFromSources, onManual, onChanged, refreshKey, selectedBlockId, onSelectBlock, panelToggle, actionError }: LessonTopicPaneProps) {
  const topicLessons = lessons.filter((lesson) => lesson.program_node_ids.includes(topic.id));
  const defaultLesson = topicLessons.find((lesson) => lesson.status !== "archived") ?? topicLessons[0];
  const openId = topicLessons.some((lesson) => lesson.id === lessonId) ? lessonId : defaultLesson?.id ?? null;
  const openLesson = topicLessons.find((lesson) => lesson.id === openId) ?? null;
  const lesson = useLesson(projectId, openId);
  const { mode, setMode } = useLessonViewMode(projectId);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [noteDraft, setNoteDraft] = useState<{ blockId: string; body: string } | null>(null);
  const [splitting, setSplitting] = useState(false);
  const [offer, setOffer] = useState<LessonUnbindOffer | null>(null);
  const [linkOpen, setLinkOpen] = useState(false);
  const [link, setLink] = useState({ url: "", caption: "" });
  const imageInput = useRef<HTMLInputElement>(null);
  const revisionRef = useRef(1);
  const saveQueue = useRef<Promise<void>>(Promise.resolve());
  const hasRange = topic.source_page_ranges.length > 0;
  const data = lesson.data && lesson.data.id === openId ? lesson.data : null;
  const selected = data?.blocks.find((block) => block.id === selectedBlockId) ?? null;
  const selectedIndex = selected ? data!.blocks.indexOf(selected) : -1;
  const selectedRef = selected?.kind === "source" ? selected.refs.find((ref) => ref.role === "content") ?? null : null;
  const nextBlock = selectedIndex >= 0 ? data!.blocks[selectedIndex + 1] : undefined;
  const reviewReasons = data ? [
    ...data.topics.filter((item) => item.needs_review).map((item) => item.current_title
      ? `тема переименована: «${item.title_snapshot}» → «${item.current_title}»`
      : `тема «${item.title_snapshot}» больше не в программе`),
    ...(data.blocks.some((block) => block.refs.some((ref) => ref.boundary_shifted)) ? ["разрез сдвинут после нового распознавания"] : []),
  ] : [];

  useEffect(() => { lesson.refresh(); }, [refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (data && data.revision > revisionRef.current) revisionRef.current = data.revision;
  }, [data]);
  useEffect(() => { revisionRef.current = data?.revision ?? 1; setNoteDraft(null); setOffer(null); }, [openId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setSplitting(false); }, [selectedBlockId, openId]);

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
          setError(errorText(caught, "Текст не сохранился"));
          lesson.refresh();
        }
      });
    }, 700);
    return () => window.clearTimeout(timer);
  }, [noteDraft, projectId, openId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setError("");
  }, [openId]);

  async function run(action: () => Promise<LessonChangeResult | void>, fallback: string) {
    setSaving(true);
    setError("");
    try {
      await saveQueue.current;
      const result = await action();
      if (result) {
        revisionRef.current = result.lesson.revision;
        setOffer(result.unbind_offer);
      }
      lesson.refresh();
      onChanged();
    } catch (caught) {
      setError(errorText(caught, fallback));
      lesson.refresh();
    } finally {
      setSaving(false);
    }
  }

  const change = (command: { title?: string; status?: LessonStatus }) => data && run(
    () => updateLesson(projectId, data.id, { ...command, expected_revision: revisionRef.current }),
    "Урок не сохранился",
  );

  async function undoLast() {
    if (!data?.undo_sequence) return;
    setSaving(true);
    setError("");
    try {
      await undoProjectAction(projectId, data.undo_sequence);
      onSelectBlock(null);
      setOffer(null);
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

  const edit = (command: Omit<LessonBlockCommand, "expected_revision">) => data && run(async () => {
    const result = await editLessonBlocks(projectId, data.id, { ...command, expected_revision: revisionRef.current });
    if (command.operation === "delete" || command.operation === "merge") onSelectBlock(null);
    return result;
  }, "Блок не изменился");

  function split(blockId: string, point: LessonSplitPoint) {
    setSplitting(false);
    void edit("fragmentId" in point
      ? { operation: "split", block_id: blockId, fragment_id: point.fragmentId }
      : { operation: "split", block_id: blockId, split_after_page: point.afterPage });
  }

  function addImage(file: File | undefined) {
    if (!file || !data) return;
    void run(() => uploadLessonImage(projectId, data.id, {
      file, expected_revision: revisionRef.current, after_block_id: selectedBlockId ?? undefined,
    }), "Изображение не добавилось");
  }

  function addLink() {
    setLinkOpen(false);
    void edit({ operation: "add_link", media_url: link.url.trim(), caption: link.caption.trim(), after_block_id: selectedBlockId ?? undefined });
    setLink({ url: "", caption: "" });
  }

  function renderEditor(block: LessonBlockRead) {
    if (block.kind === "media") {
      return (
        <label className="lesson-media-caption">
          <span>Подпись</span>
          <input
            key={block.id}
            defaultValue={block.body_md ?? ""}
            placeholder={block.media_kind === "link" ? "Как назвать ссылку" : "Что на изображении"}
            onChange={(event) => setNoteDraft({ blockId: block.id, body: event.target.value })}
          />
        </label>
      );
    }
    return (
      <Suspense fallback={<LoadingState label="Открываем редактор" />}>
        <LessonNoteEditor key={block.id} blockId={block.id} markdown={block.body_md ?? ""}
          onChange={(body) => { if (body !== block.body_md) setNoteDraft({ blockId: block.id, body }); }} />
      </Suspense>
    );
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

  const lessonTopicIds = new Set(data?.topics.map((item) => item.program_node_id));
  const addableTopics = studyNodes.filter((node) => !lessonTopicIds.has(node.id));
  const after = selectedBlockId ?? undefined;

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
                    ? <Button variant="ghost" aria-label="Отменить" disabled={saving} onClick={() => void undoLast()}><Undo2 size={14} /><span className="toolbar-label">Отменить</span></Button>
                    : <Tooltip label="Отменить можно только последнее действие проекта" side="bottom"><span><Button aria-label="Отменить" variant="ghost" disabled><Undo2 size={14} /><span className="toolbar-label">Отменить</span></Button></span></Tooltip>}
                  <Link className="secondary-button" aria-label="Открыть в Рабочей области" to={`/projects/${projectId}?topic=${topic.id}&tab=lesson&lesson=${data.id}`}><ExternalLink size={14} /><span className="toolbar-label toolbar-label-link">Открыть в Рабочей области</span></Link>
                  <span className="lessons-toolbar-end">{panelToggle}</span>
                </div>

                <div className="lessons-lesson-topics" aria-label="Темы урока">
                  <span>Темы урока:</span>
                  {data.topics.map((item) => (
                    <span key={item.program_node_id} className={`lessons-topic-chip${item.needs_review ? " is-warning" : ""}`}>
                      {item.current_title ?? item.title_snapshot}
                      {data.topics.length > 1 && (
                        <button type="button" aria-label={`Убрать тему «${item.current_title ?? item.title_snapshot}» из урока`} disabled={saving}
                          onClick={() => void edit({ operation: "remove_topic", program_node_id: item.program_node_id })}><X size={12} /></button>
                      )}
                    </span>
                  ))}
                  {addableTopics.length > 0 && (
                    <Select
                      ariaLabel="Добавить тему в урок"
                      className="lessons-topic-add"
                      value={null}
                      placeholder="+ тема"
                      disabled={saving}
                      options={addableTopics.map((node) => ({ value: node.id, label: `${node.number} ${node.title}` }))}
                      onValueChange={(value) => { if (value) void edit({ operation: "add_topic", program_node_id: value }); }}
                    />
                  )}
                </div>

                {reviewReasons.length > 0 && (
                  <div className="lessons-review-notice" role="status">
                    <AlertTriangle size={15} aria-hidden="true" />
                    <span>Требует проверки: {reviewReasons.join("; ")}.</span>
                    <Button variant="secondary" disabled={saving} onClick={() => void run(() => confirmLesson(projectId, data.id, revisionRef.current), "Не удалось подтвердить")}>
                      <CheckCircle2 size={14} />Подтвердить
                    </Button>
                  </div>
                )}

                <div className="lessons-block-toolbar" aria-label="Действия над блоком">
                  <Menu label="Добавить пояснение" trigger={<Button aria-label="Пояснение" variant="ghost" disabled={saving}><Plus size={14} /><span className="toolbar-label">Пояснение</span><ChevronDown size={13} /></Button>}
                    items={NOTE_VARIANTS.map((item) => ({ label: item.label, onSelect: () => void edit({ operation: "add_note", after_block_id: after, variant: item.value }) }))} />
                  <Menu label="Добавить медиа" trigger={<Button aria-label="Медиа" variant="ghost" disabled={saving}><Image size={14} /><span className="toolbar-label">Медиа</span><ChevronDown size={13} /></Button>} items={[
                    { label: "Изображение или фото…", icon: <Image size={14} />, onSelect: () => imageInput.current?.click() },
                    { label: "Внешняя ссылка…", icon: <Link2 size={14} />, onSelect: () => setLinkOpen(true) },
                  ]} />
                  <input ref={imageInput} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden
                    onChange={(event) => { addImage(event.target.files?.[0]); event.target.value = ""; }} />
                  <Button variant="ghost" aria-label="Выше" disabled={!selected || saving || selectedIndex === 0} onClick={() => void edit({ operation: "move_up", block_id: selectedBlockId ?? undefined })}><ArrowUp size={14} /><span className="toolbar-label">Выше</span></Button>
                  <Button variant="ghost" aria-label="Ниже" disabled={!selected || saving || !nextBlock} onClick={() => void edit({ operation: "move_down", block_id: selectedBlockId ?? undefined })}><ArrowDown size={14} /><span className="toolbar-label">Ниже</span></Button>
                  <Tooltip label={selectedRef ? (mode === "text" ? "Нажмите «Разрезать после» у абзаца" : "Нажмите «Разрезать после страницы»") : "Выберите кусок материала"} side="bottom">
                    <span><Button variant={splitting ? "secondary" : "ghost"} aria-label={splitting ? "Отменить разрез" : "Разрезать"} disabled={!selectedRef?.is_available || saving} onClick={() => setSplitting((value) => !value)}>
                      <Scissors size={14} /><span className="toolbar-label">{splitting ? "Отменить разрез" : "Разрезать"}</span>
                    </Button></span>
                  </Tooltip>
                  <Button variant="ghost" aria-label="Склеить со следующим" disabled={!selectedRef || nextBlock?.kind !== "source" || saving} onClick={() => void edit({ operation: "merge", block_id: selectedBlockId ?? undefined })}><Combine size={14} /><span className="toolbar-label">Склеить</span></Button>
                  <Button variant="ghost" aria-label="Удалить" disabled={!selected || saving} onClick={() => void edit({ operation: "delete", block_id: selectedBlockId ?? undefined })}><Trash2 size={14} /><span className="toolbar-label">Удалить</span></Button>
                  <StageButton icon={<Sparkles size={14} />} label="Дополнить с ИИ" stage="5 — ИИ «Дополнить урок»" />
                  <StageButton icon={<Dumbbell size={14} />} label="Добавить практику" stage="6 — задания" />
                </div>

                {selectedRef && selected && (
                  <div className="lessons-block-settings" aria-label="Настройки куска">
                    <label className="lessons-inline-check">
                      <input type="checkbox" checked={selectedRef.always_pages} disabled={saving}
                        onChange={(event) => void edit({ operation: "set_always_pages", block_id: selected.id, always_pages: event.target.checked })} />
                      Всегда показывать страницами
                    </label>
                    {data.topics.length > 1 && (
                      <label className="lessons-inline-select">
                        <span>Тема куска</span>
                        <Select
                          ariaLabel="Тема куска"
                          value={selected.bound_program_node_id}
                          disabled={saving}
                          options={data.topics.map((item) => ({ value: item.program_node_id, label: item.current_title ?? item.title_snapshot }))}
                          onValueChange={(value) => { if (value && value !== selected.bound_program_node_id) void edit({ operation: "set_topic", block_id: selected.id, program_node_id: value }); }}
                        />
                      </label>
                    )}
                  </div>
                )}

                {offer && (
                  <div className="lessons-unbind-offer" role="status">
                    <span>У темы «{offer.topic_title}» остались привязки из этого куска: {offer.binding_ids.length}.</span>
                    <Button variant="secondary" disabled={saving} onClick={() => { const ids = offer.binding_ids; setOffer(null); void run(() => unbindLessonBindings(projectId, data.id, ids), "Привязки не сняты"); }}>
                      Снять привязки к теме ({offer.binding_ids.length})
                    </Button>
                    <Button variant="ghost" onClick={() => setOffer(null)}>Оставить</Button>
                  </div>
                )}
                {error && <p className="inline-error" role="alert">{error}</p>}
              </header>
              <LessonDocument projectId={projectId} lesson={data} mode={mode} hiddenHeading={topic.title}
                selectedBlockId={selectedBlockId} onSelectBlock={onSelectBlock}
                renderNoteEditor={renderEditor}
                splitBlockId={splitting ? selectedBlockId : null}
                onSplit={split}
              />
            </>
          )}
        </section>
      )}

      <Dialog
        open={linkOpen}
        onOpenChange={setLinkOpen}
        title="Внешняя ссылка"
        description="Карточка без предпросмотра: приложение работает офлайн и страницу не скачивает."
        footer={<>
          <Button variant="ghost" onClick={() => setLinkOpen(false)}>Отмена</Button>
          <Button disabled={!/^https?:\/\/\S+$/.test(link.url.trim())} onClick={addLink}>Добавить</Button>
        </>}
      >
        <div className="lessons-link-form">
          <label><span>Адрес</span><input type="url" placeholder="https://…" value={link.url} onChange={(event) => setLink({ ...link, url: event.target.value })} /></label>
          <label><span>Название</span><input placeholder="Стандарт IEEE 802.3" value={link.caption} onChange={(event) => setLink({ ...link, caption: event.target.value })} /></label>
        </div>
      </Dialog>
    </div>
  );
}
