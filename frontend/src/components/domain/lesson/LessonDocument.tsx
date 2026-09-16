import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { AlertTriangle, BookOpen, ExternalLink, FileText, Scissors } from "lucide-react";
import { lessonMediaUrl, type LessonBlockRead, type LessonRead, type LessonRefRead } from "../../../api/lessons";
import {
  getMaterialPage,
  materialFragmentAssetUrl,
  materialPageImageUrl,
  type MaterialPageRead,
} from "../../../api/materials";
import { ErrorState } from "../../ui";
import { PageRegion, StructuredPage } from "../material-viewer";
import { QualityBadge } from "../QualityBadge";
import { LessonMarkdown } from "./LessonMarkdown";

export type LessonDocumentMode = "pages" | "text";

/** Место разреза: после абзаца (режим «Текст») или после страницы (режим «Страницы»). */
export type LessonSplitPoint = { fragmentId: string } | { afterPage: number };

interface LessonDocumentProps {
  projectId: string;
  lesson: LessonRead;
  mode: LessonDocumentMode;
  /** Название текущей темы уже показано шапкой поверхности, второй раз не нужно. */
  hiddenHeading?: string;
  selectedBlockId?: string | null;
  onSelectBlock?: (blockId: string) => void;
  renderNoteEditor?: (block: LessonBlockRead) => ReactNode;
  /** Кусок, в котором сейчас выбирают место разреза. */
  splitBlockId?: string | null;
  onSplit?: (blockId: string, point: LessonSplitPoint) => void;
  /** Позиция чтения: куда прокрутить при открытии и кому сообщать о новой. */
  startBlockId?: string | null;
  onReadBlock?: (blockId: string) => void;
}

function pageRange(ref: LessonRefRead): number[] {
  return Array.from({ length: ref.page_to - ref.page_from + 1 }, (_, index) => ref.page_from + index);
}

/**
 * Один документ урока — два способа показа (записка «Уроки» §3.3).
 *
 * «Страницы» рисуют оригинал: какой лист рисует какая ссылка, решает сервер
 * (`pages_shown`), поэтому разрез внутри страницы её не дублирует. «Текст» —
 * фрагменты активной ревизии с отсечением по граничным фрагментам; служебные
 * блоки скрыты.
 */
export function LessonDocument({ projectId, lesson, mode, hiddenHeading, selectedBlockId, onSelectBlock, renderNoteEditor, splitBlockId, onSplit, startBlockId, onReadBlock }: LessonDocumentProps) {
  const topicTitles = useMemo(
    () => new Map(lesson.topics.map((topic) => [topic.program_node_id, topic.current_title ?? topic.title_snapshot])),
    [lesson.topics],
  );
  const multiTopic = lesson.topics.length > 1;
  const blockRefs = useRef(new Map<string, HTMLElement>());
  useReadingPosition(lesson.id, blockRefs, startBlockId, onReadBlock);

  if (lesson.blocks.length === 0) {
    return <p className="lesson-document-empty">В уроке пока нет блоков.</p>;
  }

  return (
    <div className={`lesson-document is-${mode}`}>
      {lesson.blocks.map((block) => (
        <section
          key={block.id}
          data-block-id={block.id}
          ref={(node) => {
            if (node) blockRefs.current.set(block.id, node);
            else blockRefs.current.delete(block.id);
          }}
          className={`lesson-edit-block${selectedBlockId === block.id ? " is-selected" : ""}`}
        >
          {onSelectBlock && <button type="button" className="lesson-block-select" onClick={() => onSelectBlock(block.id)}>
            Выбрать блок {block.sort_order + 1}
          </button>}
          {block.kind === "note" && selectedBlockId === block.id && renderNoteEditor
            ? renderNoteEditor(block)
            : <LessonBlockView
                projectId={projectId}
                lessonId={lesson.id}
                block={block}
                mode={mode}
                hiddenHeading={hiddenHeading}
                topicTitle={multiTopic && block.bound_program_node_id ? topicTitles.get(block.bound_program_node_id) : undefined}
                onSplit={splitBlockId === block.id && onSplit ? (point) => onSplit(block.id, point) : undefined}
              />}
          {block.kind === "media" && selectedBlockId === block.id && renderNoteEditor?.(block)}
        </section>
      ))}
    </div>
  );
}

/**
 * Позиция чтения: открыть урок там, где остановились, и сообщать о новом месте.
 *
 * Верхний видимый блок, а не прокрутка в пикселях: страницы и текст дают разную
 * высоту, а блок — то же место в обоих режимах.
 */
function useReadingPosition(
  lessonId: string,
  blocks: { current: Map<string, HTMLElement> },
  startBlockId: string | null | undefined,
  onReadBlock: ((blockId: string) => void) | undefined,
) {
  const restored = useRef<string | null>(null);

  useEffect(() => {
    if (!startBlockId || restored.current === lessonId) return;
    const node = blocks.current.get(startBlockId);
    if (!node) return;
    restored.current = lessonId;
    node.scrollIntoView({ block: "start" });
  }, [lessonId, startBlockId, blocks]);

  useEffect(() => {
    if (!onReadBlock || typeof IntersectionObserver === "undefined") return;
    const visible = new Set<string>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = (entry.target as HTMLElement).dataset.blockId;
          if (!id) continue;
          if (entry.isIntersecting) visible.add(id);
          else visible.delete(id);
        }
        const first = [...blocks.current.keys()].find((id) => visible.has(id));
        if (first) onReadBlock(first);
      },
      // Узкая полоса посреди экрана промахивается по коротким блокам: берём весь экран,
      // а текущим считаем первый по порядку урока видимый блок.
      { threshold: 0 },
    );
    for (const node of blocks.current.values()) observer.observe(node);
    return () => observer.disconnect();
  }, [lessonId, onReadBlock, blocks]);
}

interface LessonBlockViewProps {
  projectId: string;
  lessonId: string;
  block: LessonBlockRead;
  mode: LessonDocumentMode;
  hiddenHeading?: string;
  topicTitle?: string;
  onSplit?: (point: LessonSplitPoint) => void;
}

function LessonBlockView({ projectId, lessonId, block, mode, hiddenHeading, topicTitle, onSplit }: LessonBlockViewProps) {
  if (block.kind === "note") {
    const body = block.body_md ?? "";
    const heading = /^(#{1,6})\s+(.*)$/.exec(body);
    if (block.variant === "heading" && heading) {
      if (heading[2] === hiddenHeading) return null;
      const level = Math.min(4, Math.max(2, heading[1].length));
      const Tag = `h${level}` as "h2" | "h3" | "h4";
      return <Tag className={`lesson-note-heading is-level-${level}`}>{heading[2]}</Tag>;
    }
    if (!body.trim()) return <div className={`lesson-note is-${block.variant ?? "text"} is-empty`}>Пустое пояснение — выберите блок, чтобы написать текст.</div>;
    return <LessonMarkdown className={`lesson-note is-${block.variant ?? "text"}`} text={body} />;
  }
  if (block.kind === "media") return <LessonMediaView projectId={projectId} lessonId={lessonId} block={block} />;
  if (block.kind !== "source") return null;
  return (
    <>
      {block.refs.filter((ref) => ref.role === "content").map((ref) => (
        <LessonSourceView
          key={ref.id}
          projectId={projectId}
          sourceRef={ref}
          mode={mode}
          topicTitle={topicTitle}
          onSplit={onSplit}
        />
      ))}
    </>
  );
}

function LessonMediaView({ projectId, lessonId, block }: { projectId: string; lessonId: string; block: LessonBlockRead }) {
  const caption = block.body_md?.trim();
  if (block.media_kind === "link" && block.media_url) {
    let host = block.media_url;
    try { host = new URL(block.media_url).host; } catch { /* покажем адрес целиком */ }
    return (
      <a className="lesson-media-link" href={block.media_url} target="_blank" rel="noreferrer noopener">
        <ExternalLink size={15} aria-hidden="true" />
        <span><strong>{caption || host}</strong><small>{block.media_url}</small></span>
      </a>
    );
  }
  return (
    <figure className="lesson-media-image">
      <img src={lessonMediaUrl(projectId, lessonId, block.id)} alt={caption || "Изображение урока"} loading="lazy" />
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}

function refLabel(ref: LessonRefRead): string {
  const pages = ref.page_from === ref.page_to ? `стр. ${ref.page_from}` : `стр. ${ref.page_from}–${ref.page_to}`;
  return `${ref.source_name} · ${pages}`;
}

interface LessonSourceViewProps {
  projectId: string;
  sourceRef: LessonRefRead;
  mode: LessonDocumentMode;
  topicTitle?: string;
  onSplit?: (point: LessonSplitPoint) => void;
}

function LessonSourceView({ projectId, sourceRef: ref, mode, topicTitle, onSplit }: LessonSourceViewProps) {
  const materialId = ref.material_id;
  const head = (
    <header className="lesson-source-head">
      <BookOpen size={14} aria-hidden="true" />
      <span>{refLabel(ref)}</span>
      {ref.from_fragment_id && <small>с абзаца</small>}
      {ref.to_fragment_id && <small>до абзаца</small>}
      {ref.region_bbox ? <small>область страницы</small> : ref.always_pages && <small>всегда страницами</small>}
      {topicTitle && <small className="lesson-source-topic">тема: {topicTitle}</small>}
      {ref.boundary_shifted && <small className="lesson-source-shifted"><AlertTriangle size={12} aria-hidden="true" /> Разрез сдвинут</small>}
    </header>
  );

  if (!materialId || !ref.is_available) {
    return (
      <section className="lesson-source is-unavailable">
        {head}
        <p className="lesson-source-notice"><AlertTriangle size={14} aria-hidden="true" /> Источник недоступен: материал убран из проекта. Остались имя и страницы.</p>
      </section>
    );
  }

  if (ref.region_bbox) {
    return (
      <section className="lesson-source is-region">
        {head}
        <PageRegion
          className="lesson-region"
          pageUrl={materialPageImageUrl(projectId, materialId, ref.page_from)}
          bbox={ref.region_bbox}
          alt={`${ref.source_name}, область страницы ${ref.page_from}`}
        />
      </section>
    );
  }

  if (mode === "pages" || ref.always_pages) {
    // В режиме «Текст» кусок «всегда страницами» рисует свой диапазон целиком.
    const pages = mode === "pages" ? ref.pages_shown : pageRange(ref);
    return (
      <section className="lesson-source">
        {head}
        {ref.boundary_shifted && <ShiftNotice />}
        {pages.map((page) => (
          <div key={page}>
            <figure className="lesson-page">
              <figcaption>Страница {page}</figcaption>
              <img
                src={materialPageImageUrl(projectId, materialId, page)}
                alt={`${ref.source_name}, страница ${page}`}
                loading="lazy"
              />
            </figure>
            {onSplit && page < ref.page_to && (
              <button type="button" className="lesson-split-marker" onClick={() => onSplit({ afterPage: page })}>
                <Scissors size={13} aria-hidden="true" /> Разрезать после страницы {page}
              </button>
            )}
          </div>
        ))}
        {pages.length === 0 && <p className="lesson-source-notice">Страница {ref.page_from} показана выше.</p>}
        {onSplit && !pages.some((page) => page < ref.page_to) && (
          <p className="lesson-source-notice">
            <Scissors size={14} aria-hidden="true" /> Между страницами этого куска резать нечего — переключитесь на «Текст» и разрежьте после нужного абзаца.
          </p>
        )}
      </section>
    );
  }

  if (!ref.is_parsed) {
    return (
      <section className="lesson-source">
        {head}
        <p className="lesson-source-notice">
          <FileText size={14} aria-hidden="true" /> Текст ещё не распознан.{" "}
          <Link to={`/projects/${projectId}/materials/${materialId}?page=${ref.page_from}`}>Открыть в материалах</Link>
        </p>
      </section>
    );
  }

  return (
    <section className="lesson-source">
      {head}
      {ref.boundary_shifted && <ShiftNotice />}
      <LessonSourceText projectId={projectId} materialId={materialId} sourceRef={ref} onSplit={onSplit} />
    </section>
  );
}

function ShiftNotice() {
  return (
    <p className="lesson-source-notice is-warning">
      <AlertTriangle size={14} aria-hidden="true" /> Материал распознан заново, и граничный абзац не нашёлся — кусок начинается или кончается на границе страницы. Проверьте и подтвердите урок.
    </p>
  );
}

function LessonSourceText({ projectId, materialId, sourceRef: ref, onSplit }: { projectId: string; materialId: string; sourceRef: LessonRefRead; onSplit?: (point: LessonSplitPoint) => void }) {
  const [pages, setPages] = useState<MaterialPageRead[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setPages(null);
    setError("");
    Promise.all(pageRange(ref).map((page) => getMaterialPage(projectId, materialId, page, controller.signal)))
      .then((loaded) => { if (!controller.signal.aborted) setPages(loaded); })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Не удалось загрузить текст");
      });
    return () => controller.abort();
  }, [projectId, materialId, ref]);

  const visible = useMemo(() => (pages ?? []).map((page) => {
    const serviceBlocks = new Set(page.blocks.filter((block) => block.block_class === "service").map((block) => block.id));
    let fragments = page.fragments;
    if (page.page_number === ref.page_from && ref.from_fragment_id) {
      const start = fragments.findIndex((fragment) => fragment.id === ref.from_fragment_id);
      if (start >= 0) fragments = fragments.slice(start);
    }
    if (page.page_number === ref.page_to && ref.to_fragment_id) {
      const end = fragments.findIndex((fragment) => fragment.id === ref.to_fragment_id);
      if (end >= 0) fragments = fragments.slice(0, end + 1);
    }
    return { page, fragments: fragments.filter((fragment) => !serviceBlocks.has(fragment.block_id)) };
  }), [pages, ref]);

  if (error) return <ErrorState message={error} />;
  if (!pages) return <p className="lesson-source-notice">Загружаем текст…</p>;
  const shownFragments = visible.flatMap((item) => item.fragments);
  const lastFragmentId = shownFragments.at(-1)?.id;

  return (
    <>
      {onSplit && shownFragments.length < 2 && (
        <p className="lesson-source-notice">
          <Scissors size={14} aria-hidden="true" /> В куске один абзац — разрезать нечего.
        </p>
      )}
      {visible.map(({ page, fragments }) => {
        if (fragments.length === 0) return null;
        const lowQuality = page.quality === "ocr_low";
        return (
          <div className="lesson-text-page" key={page.page_number}>
            {lowQuality && <p className="lesson-source-notice is-warning"><QualityBadge quality="ocr_low" /> Стр. {page.page_number}: рядом с текстом — вырезы оригинала</p>}
            <StructuredPage
              className="lesson-structured-page"
              page={{ ...page, fragments }}
              showOcrReview={false}
              pageImageUrl={lowQuality ? materialPageImageUrl(projectId, materialId, page.page_number) : undefined}
              showSourceCrops={lowQuality}
              assetUrl={(fragmentId) => materialFragmentAssetUrl(projectId, materialId, fragmentId)}
              fragmentProps={onSplit ? () => ({ className: "is-splittable" }) : undefined}
              renderFragmentOverlay={onSplit ? (fragment) => fragment.id !== lastFragmentId && (
                <button type="button" className="lesson-split-marker is-inline" onClick={() => onSplit({ fragmentId: fragment.id })}>
                  <Scissors size={12} aria-hidden="true" /> Разрезать после
                </button>
              ) : undefined}
            />
          </div>
        );
      })}
    </>
  );
}
