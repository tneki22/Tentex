import { useRef } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";
import { BookOpen } from "lucide-react";
import { materialPageImageUrl, type MaterialFragmentRead, type MaterialPageRead } from "../../api/materials";

/**
 * Строка списка отличает абзацы на взгляд. Картинка текста не имеет, и её
 * подпись — не «[Изображение]» из распознавания, а понятное слово с пометкой.
 */
export function fragmentPreview(fragment: MaterialFragmentRead): string {
  const compact = fragment.text.replace(/\s+/g, " ").trim();
  if (!compact || compact === "[Изображение]") {
    return fragment.has_asset || fragment.element_kind === "image" ? "Рисунок или схема" : "Без текста";
  }
  return compact.length > 90 ? `${compact.slice(0, 90)}…` : compact;
}

interface LessonPageSheetProps {
  projectId: string;
  materialId: string;
  page: MaterialPageRead;
  pageNumber: number;
  foundIds: Set<string>;
  selectedIds: string[];
  drawing: boolean;
  box: number[] | null;
  onBoxChange(box: number[] | null): void;
  onToggle(fragmentId: string): void;
}

/**
 * Лист оригинала с областями абзацев поверх него.
 *
 * Абзацы выбираются щелчком по самому тексту на странице, а не по вырванной из
 * вёрстки строке списка: на листе видно, что именно берётся.
 */
export function LessonPageSheet({
  projectId, materialId, page, pageNumber, foundIds, selectedIds, drawing, box, onBoxChange, onToggle,
}: LessonPageSheetProps) {
  // Якорь рамки — ref, а не состояние: первый `pointermove` приходит до перерисовки.
  const start = useRef<[number, number] | null>(null);

  function pointAt(event: ReactPointerEvent<HTMLDivElement>): [number, number] {
    const bounds = event.currentTarget.getBoundingClientRect();
    return [
      Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width)),
      Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height)),
    ];
  }

  function stretchTo(event: ReactPointerEvent<HTMLDivElement>) {
    const from = start.current;
    if (!from) return;
    const [x, y] = pointAt(event);
    onBoxChange([
      Math.min(from[0], x), Math.min(from[1], y),
      Math.max(from[0], x), Math.max(from[1], y),
    ]);
  }

  return (
    <div className={`lesson-picker-sheet${drawing ? " is-drawing" : ""}`}>
      <img
        src={materialPageImageUrl(projectId, materialId, pageNumber)}
        alt={`Страница ${pageNumber}`}
        draggable={false}
      />
      {drawing ? (
        <div
          className="lesson-picker-draw"
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture(event.pointerId);
            start.current = pointAt(event);
            stretchTo(event);
          }}
          onPointerMove={stretchTo}
          onPointerUp={(event) => { stretchTo(event); start.current = null; }}
          onPointerCancel={() => { start.current = null; }}
        >
          {box && (
            <span
              className="lesson-picker-box"
              style={{
                left: `${box[0] * 100}%`, top: `${box[1] * 100}%`,
                width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%`,
              } as CSSProperties}
            />
          )}
        </div>
      ) : (
        <div className="lesson-picker-regions">
          {page.fragments.map((fragment) => (
            <button
              type="button"
              key={fragment.id}
              className={[foundIds.has(fragment.id) ? "is-found" : "", selectedIds.includes(fragment.id) ? "is-picked" : ""].filter(Boolean).join(" ")}
              aria-pressed={selectedIds.includes(fragment.id)}
              aria-label={`Абзац: ${fragmentPreview(fragment)}`}
              onClick={() => onToggle(fragment.id)}
              style={{
                left: `${fragment.bbox[0] * 100}%`,
                top: `${fragment.bbox[1] * 100}%`,
                width: `${(fragment.bbox[2] - fragment.bbox[0]) * 100}%`,
                height: `${(fragment.bbox[3] - fragment.bbox[1]) * 100}%`,
              } as CSSProperties}
            />
          ))}
        </div>
      )}
      <span className="lesson-picker-sheet-mark"><BookOpen size={12} aria-hidden="true" />Страница {pageNumber}</span>
    </div>
  );
}
