import { useEffect, useState } from "react";
import { getTopicSources, SOURCE_ROLE_LABELS, type LessonSourceRangeRead } from "../../api/lessons";
import { Button, Checkbox, Dialog, ErrorState, LoadingState } from "../../components/ui";
import { errorText } from "./lessonTree";

interface LessonSourcesDialogProps {
  projectId: string;
  nodeId: string;
  topicTitle: string;
  open: boolean;
  busy: boolean;
  onOpenChange(open: boolean): void;
  onCreate(materialIds: string[]): void;
}

export function pagesLabel(from: number, to: number): string {
  return from === to ? `стр. ${from}` : `стр. ${from}–${to}`;
}

/** «Из источников»: основной и дополнительные отмечены, справочный — нет (записка §4.2). */
export function LessonSourcesDialog({ projectId, nodeId, topicTitle, open, busy, onOpenChange, onCreate }: LessonSourcesDialogProps) {
  const [ranges, setRanges] = useState<LessonSourceRangeRead[] | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setRanges(null);
    setError("");
    getTopicSources(projectId, nodeId, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setRanges(result.ranges);
        setChecked(new Set(result.ranges.filter((item) => item.default_selected).map((item) => item.material_id)));
      })
      .catch((caught: unknown) => { if (!controller.signal.aborted) setError(errorText(caught, "Источники не загрузились")); });
    return () => controller.abort();
  }, [open, projectId, nodeId]);

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Создать урок «${topicTitle}» из источников`}
      description="Порядок: основной → дополнительные → справочные."
      footer={(
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Отмена</Button>
          <Button disabled={busy || checked.size === 0} onClick={() => onCreate(ranges?.filter((item) => checked.has(item.material_id)).map((item) => item.material_id) ?? [])}>
            {busy ? "Создаём…" : "Создать черновик"}
          </Button>
        </>
      )}
    >
      {error && <ErrorState message={error} />}
      {!error && !ranges && <LoadingState label="Загружаем источники темы" />}
      {ranges && ranges.length === 0 && <p>У темы нет страниц из оглавления — соберите урок вручную.</p>}
      {ranges && ranges.length > 0 && (
        <ul className="lessons-source-choice">
          {ranges.map((item) => (
            <li key={item.material_id}>
              <Checkbox
                label={`${item.source_name} · ${SOURCE_ROLE_LABELS[item.source_role]}`}
                checked={checked.has(item.material_id)}
                onCheckedChange={(value) => setChecked((current) => {
                  const next = new Set(current);
                  if (value) next.add(item.material_id); else next.delete(item.material_id);
                  return next;
                })}
              />
              <span>{pagesLabel(item.page_from, item.page_to)}</span>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}
