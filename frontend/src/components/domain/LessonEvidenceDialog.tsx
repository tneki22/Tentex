import { useEffect, useMemo, useState } from "react";
import { BookPlus } from "lucide-react";
import type { EvidenceSummary } from "../../api/coverage";
import {
  createManualLesson,
  editLessonBlocks,
  getLesson,
  getLessonsOverview,
  type LessonRead,
  type LessonSummaryRead,
} from "../../api/lessons";
import { Button, Dialog, ErrorState, LoadingState, Select, StatusBadge } from "../ui";
import { pagesLabel } from "./EvidenceCard";

const NEW_LESSON = "__new_manual_lesson__";

type Placed = "exact" | "overlap" | null;

interface LessonEvidenceDialogProps {
  open: boolean;
  projectId: string;
  /** Куски в порядке, в котором они встанут в урок. */
  items: EvidenceSummary[];
  topicTitle: string;
  onOpenChange(open: boolean): void;
  onAdded?(lesson: LessonRead, added: number): void;
  /** Витрина кита: показать реальный диалог без обращения к проектному API. */
  preview?: boolean;
}

/** Уже есть в уроке этот же диапазон — повтор; тот же источник на тех же страницах — пересечение. */
export function placedInLesson(
  item: Pick<EvidenceSummary, "material_id" | "from_fragment_id" | "to_fragment_id" | "page_from" | "page_to">,
  refs: Array<{ material_id: string | null; from_fragment_id: string | null; to_fragment_id: string | null; page_from: number; page_to: number }>,
): Placed {
  const same = refs.filter((ref) => ref.material_id === item.material_id);
  if (same.some((ref) => ref.from_fragment_id === item.from_fragment_id && ref.to_fragment_id === item.to_fragment_id)) {
    return "exact";
  }
  return same.some((ref) => ref.page_from <= item.page_to && ref.page_to >= item.page_from) ? "overlap" : null;
}

function kusokLabel(count: number): string {
  const last = count % 10;
  const tail = count % 100;
  if (tail >= 11 && tail <= 14) return `${count} кусков`;
  if (last === 1) return `${count} кусок`;
  if (last >= 2 && last <= 4) return `${count} куска`;
  return `${count} кусков`;
}

/**
 * Вставка кусков в урок: урок, место и итог названы до сохранения. Каждый кусок —
 * один блок урока, следующий встаёт за предыдущим, порядок чтения сохраняется.
 * По умолчанию выбран последний урок темы: раньше диалог всякий раз предлагал новый
 * черновик, и десять вставок подряд давали десять уроков.
 */
export function LessonEvidenceDialog({
  open,
  projectId,
  items,
  topicTitle,
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
  const topicId = items[0]?.topic_id;
  const itemsKey = items.map((item) => item.id).join(",");

  useEffect(() => {
    if (!open || !topicId) return;
    const controller = new AbortController();
    setLessons(null);
    setLesson(null);
    setPosition("end");
    setError("");
    if (preview) {
      setLessons([]);
      setLessonId(NEW_LESSON);
      return;
    }
    getLessonsOverview(projectId, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        const own = result.lessons
          .filter((item) => item.program_node_ids.includes(topicId))
          .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
        setLessons(own);
        setLessonId(own[0]?.id ?? NEW_LESSON);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Уроки не загрузились");
      });
    return () => controller.abort();
  }, [open, projectId, topicId, itemsKey, preview]);

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
    { value: "end", label: "В конец" },
    { value: "start", label: "В начало" },
    ...(lesson?.blocks.map((block, index) => ({
      value: `after:${block.id}`,
      label: `После блока ${index + 1}`,
      description: block.kind === "source" ? block.refs[0]?.source_name : "Пояснение",
    })) ?? []),
  ], [lesson]);
  const refs = lesson?.blocks.flatMap((block) => block.refs) ?? [];
  const placed = items.map((item) => placedInLesson(item, refs));
  const fresh = items.filter((_, index) => placed[index] !== "exact");
  const repeats = items.length - fresh.length;
  const overlaps = placed.filter((value) => value === "overlap").length;

  async function add() {
    if (fresh.length === 0) return;
    if (preview) {
      onOpenChange(false);
      return;
    }
    setBusy(true);
    setError("");
    try {
      let target = lessonId === NEW_LESSON
        ? (await createManualLesson(projectId, fresh[0].topic_id)).lesson
        : lesson ?? await getLesson(projectId, lessonId);
      let after = position.startsWith("after:") ? position.slice(6) : undefined;
      let before = position === "start" ? target.blocks[0]?.id : undefined;
      for (const item of fresh) {
        const known = new Set(target.blocks.map((block) => block.id));
        const result = await editLessonBlocks(projectId, target.id, {
          expected_revision: target.revision,
          operation: "add_fragments",
          material_id: item.material_id,
          from_fragment_id: item.from_fragment_id,
          to_fragment_id: item.to_fragment_id,
          program_node_id: item.topic_id,
          before_block_id: before,
          after_block_id: after,
        });
        target = result.lesson;
        // Следующий кусок встаёт за только что добавленным: порядок чтения сохраняется.
        const added = target.blocks.find((block) => !known.has(block.id));
        if (added) {
          after = added.id;
          before = undefined;
        }
      }
      onAdded?.(target, fresh.length);
      onOpenChange(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось добавить материал в урок");
    } finally {
      setBusy(false);
    }
  }

  const single = items.length === 1 ? items[0] : null;
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={single ? "Добавить кусок в урок" : `Добавить ${kusokLabel(items.length)} в урок`}
      description="Урок не перестраивается: каждый кусок станет отдельным блоком в выбранном месте, в порядке чтения."
      className="lesson-evidence-dialog"
      footer={<>
        <Button variant="ghost" disabled={busy} onClick={() => onOpenChange(false)}>Отменить</Button>
        <Button disabled={busy || fresh.length === 0 || (lessonId !== NEW_LESSON && !lesson)} onClick={() => void add()}>
          <BookPlus size={14} />{busy ? "Добавляем…" : fresh.length > 1 ? `Добавить ${kusokLabel(fresh.length)}` : "Добавить в урок"}
        </Button>
      </>}
    >
      {!lessons && !error && <LoadingState label="Загружаем уроки" />}
      {error && <ErrorState message={error} />}
      {lessons && items.length > 0 && <div className="lesson-evidence-form">
        <div className="lesson-evidence-preview">
          <strong>{topicTitle}</strong>
          {single
            ? <>
              <p>{single.title ? `${single.title} · ` : ""}{single.material_name} · {pagesLabel(single.page_from, single.page_to)}</p>
              <blockquote>{single.quote}</blockquote>
            </>
            : <ol>{items.map((item, index) => (
              <li key={item.id} className={placed[index] === "exact" ? "is-repeat" : undefined}>
                <span>{item.title || item.quote.slice(0, 80)}</span>
                <small>{item.material_name} · {pagesLabel(item.page_from, item.page_to)}</small>
              </li>
            ))}</ol>}
        </div>
        <label><span>Урок</span><Select
          ariaLabel="Выберите урок"
          value={lessonId}
          options={[
            ...lessons.map((item) => ({ value: item.id, label: item.title, description: item.status === "draft" ? "Черновик" : "Готов" })),
            { value: NEW_LESSON, label: "Новый ручной черновик" },
          ]}
          onValueChange={(value) => setLessonId(value ?? NEW_LESSON)}
        /></label>
        <label><span>Место</span><Select
          ariaLabel="Место вставки"
          value={position}
          options={positionOptions}
          disabled={lessonId !== NEW_LESSON && !lesson}
          onValueChange={(value) => setPosition(value ?? "end")}
        /></label>
        {repeats > 0 && <p className="lesson-evidence-overlap"><StatusBadge tone="success">Уже в уроке</StatusBadge>{repeats === items.length ? "Всё выбранное уже есть в этом уроке." : `Уже есть в уроке и будет пропущено: ${kusokLabel(repeats)}.`}</p>}
        {overlaps > 0 && <p className="lesson-evidence-overlap"><StatusBadge tone="warning">Пересечение</StatusBadge>В уроке уже есть текст с этих страниц — проверьте, что кусок не повторится.</p>}
      </div>}
    </Dialog>
  );
}
