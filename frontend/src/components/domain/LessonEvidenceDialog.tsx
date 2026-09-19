import { useEffect, useMemo, useState } from "react";
import { BookPlus } from "lucide-react";
import type { EvidenceDetail } from "../../api/coverage";
import {
  createManualLesson,
  editLessonBlocks,
  getLesson,
  getLessonsOverview,
  type LessonRead,
  type LessonSummaryRead,
} from "../../api/lessons";
import { Button, Dialog, ErrorState, LoadingState, Select, StatusBadge } from "../ui";

const NEW_LESSON = "__new_manual_lesson__";

interface LessonEvidenceDialogProps {
  open: boolean;
  projectId: string;
  evidence: EvidenceDetail | null;
  onOpenChange(open: boolean): void;
  onAdded?(lesson: LessonRead): void;
  /** Витрина кита: показать реальный диалог без обращения к проектному API. */
  preview?: boolean;
}

function overlapLabel(lesson: LessonRead | null, evidence: EvidenceDetail | null): string | null {
  if (!lesson || !evidence) return null;
  const refs = lesson.blocks.flatMap((block) => block.refs)
    .filter((ref) => ref.material_id === evidence.material_id);
  if (refs.some((ref) => ref.from_fragment_id === evidence.fragment_ids[0]
    && ref.to_fragment_id === evidence.fragment_ids.at(-1))) {
    return "Этот точный диапазон уже есть в уроке.";
  }
  if (refs.some((ref) => ref.page_from <= evidence.page_to && ref.page_to >= evidence.page_from)) {
    return "В уроке уже есть пересекающийся диапазон этого источника.";
  }
  return null;
}

/** Ручная вставка точной опоры: урок, тема и место названы до сохранения. */
export function LessonEvidenceDialog({
  open,
  projectId,
  evidence,
  onOpenChange,
  onAdded,
  preview = false,
}: LessonEvidenceDialogProps) {
  const [lessons, setLessons] = useState<LessonSummaryRead[] | null>(null);
  const [lessonId, setLessonId] = useState<string>(NEW_LESSON);
  const [lesson, setLesson] = useState<LessonRead | null>(null);
  const [position, setPosition] = useState("end");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open || !evidence) return;
    const controller = new AbortController();
    setLessons(null);
    setLesson(null);
    setLessonId(NEW_LESSON);
    setPosition("end");
    setError("");
    if (preview) {
      setLessons([]);
      return;
    }
    getLessonsOverview(projectId, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) {
          setLessons(result.lessons.filter((item) => item.program_node_ids.includes(evidence.topic_id)));
        }
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Уроки не загрузились");
      });
    return () => controller.abort();
  }, [open, projectId, evidence?.id, preview]);

  useEffect(() => {
    if (!open || lessonId === NEW_LESSON) {
      setLesson(null);
      return;
    }
    const controller = new AbortController();
    getLesson(projectId, lessonId, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setLesson(result); })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Урок не открылся");
      });
    return () => controller.abort();
  }, [open, projectId, lessonId]);

  const positionOptions = useMemo(() => [
    { value: "start", label: "В начало" },
    { value: "end", label: "В конец" },
    ...(lesson?.blocks.map((block, index) => ({
      value: `after:${block.id}`,
      label: `После блока ${index + 1}`,
      description: block.kind === "source" ? block.refs[0]?.source_name : "Пояснение",
    })) ?? []),
  ], [lesson]);
  const overlap = overlapLabel(lesson, evidence);

  async function add() {
    if (!evidence) return;
    if (preview) {
      onOpenChange(false);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const target = lessonId === NEW_LESSON
        ? (await createManualLesson(projectId, evidence.topic_id)).lesson
        : lesson ?? await getLesson(projectId, lessonId);
      const firstBlock = target.blocks[0];
      const result = await editLessonBlocks(projectId, target.id, {
        expected_revision: target.revision,
        operation: "add_fragments",
        material_id: evidence.material_id,
        from_fragment_id: evidence.fragment_ids[0],
        to_fragment_id: evidence.fragment_ids.at(-1),
        program_node_id: evidence.topic_id,
        before_block_id: position === "start" ? firstBlock?.id : undefined,
        after_block_id: position.startsWith("after:") ? position.slice(6) : undefined,
      });
      onAdded?.(result.lesson);
      onOpenChange(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось добавить материал в урок");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Добавить точный диапазон в урок"
      description="Урок не перестраивается: выбранный текст появится в указанном месте."
      className="lesson-evidence-dialog"
      footer={<>
        <Button variant="ghost" disabled={busy} onClick={() => onOpenChange(false)}>Отменить</Button>
        <Button disabled={busy || !evidence || Boolean(overlap)} onClick={() => void add()}>
          <BookPlus size={14} />{busy ? "Добавляем…" : "Добавить в урок"}
        </Button>
      </>}
    >
      {!lessons && !error && <LoadingState label="Загружаем уроки" />}
      {error && <ErrorState message={error} />}
      {lessons && evidence && <div className="lesson-evidence-form">
        <div className="lesson-evidence-preview">
          <strong>{evidence.topic_title}</strong>
          <p>{evidence.material_name} · стр. {evidence.page_from}{evidence.page_to !== evidence.page_from ? `–${evidence.page_to}` : ""}</p>
          <blockquote>{evidence.text}</blockquote>
        </div>
        <label><span>Урок</span><Select
          ariaLabel="Выберите урок"
          value={lessonId}
          options={[
            { value: NEW_LESSON, label: "Новый ручной черновик" },
            ...lessons.map((item) => ({ value: item.id, label: item.title, description: item.status === "draft" ? "Черновик" : "Готов" })),
          ]}
          onValueChange={(value) => setLessonId(value ?? NEW_LESSON)}
        /></label>
        <label><span>Тема куска</span><strong>{evidence.topic_title}</strong></label>
        <label><span>Место</span><Select
          ariaLabel="Место вставки"
          value={position}
          options={positionOptions}
          disabled={lessonId !== NEW_LESSON && !lesson}
          onValueChange={(value) => setPosition(value ?? "end")}
        /></label>
        {overlap && <p className="lesson-evidence-overlap"><StatusBadge tone="warning">Пересечение</StatusBadge>{overlap}</p>}
      </div>}
    </Dialog>
  );
}
