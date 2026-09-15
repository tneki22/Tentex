import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { AlertTriangle, BookOpen, FileText } from "lucide-react";
import type { LessonBlockRead, LessonRead, LessonRefRead } from "../../../api/lessons";
import {
  getMaterialPage,
  materialFragmentAssetUrl,
  materialPageImageUrl,
  type MaterialPageRead,
} from "../../../api/materials";
import { ErrorState } from "../../ui";
import { StructuredPage } from "../material-viewer";
import { QualityBadge } from "../QualityBadge";

export type LessonDocumentMode = "pages" | "text";

interface LessonDocumentProps {
  projectId: string;
  lesson: LessonRead;
  mode: LessonDocumentMode;
  /** Название текущей темы уже показано шапкой поверхности, второй раз не нужно. */
  hiddenHeading?: string;
  selectedBlockId?: string | null;
  onSelectBlock?: (blockId: string) => void;
  renderNoteEditor?: (block: LessonBlockRead) => ReactNode;
}

const pageKey = (materialId: string, page: number) => `${materialId}#${page}`;

function pageRange(ref: LessonRefRead): number[] {
  return Array.from({ length: ref.page_to - ref.page_from + 1 }, (_, index) => ref.page_from + index);
}

/**
 * Один документ урока — два способа показа (записка «Уроки» §3.3).
 *
 * «Страницы» рисуют оригинал: разрез внутри страницы не дублирует её, лист
 * показывается в первом куске, где он встретился. «Текст» — фрагменты активной
 * ревизии с отсечением по граничным фрагментам ссылки; служебные блоки скрыты.
 */
export function LessonDocument({ projectId, lesson, mode, hiddenHeading, selectedBlockId, onSelectBlock, renderNoteEditor }: LessonDocumentProps) {
  const pagesShownIn = useMemo(() => {
    const owner = new Map<string, string>();
    for (const block of lesson.blocks) {
      for (const ref of block.refs) {
        if (!ref.material_id || ref.role !== "content") continue;
        for (const page of pageRange(ref)) {
          const key = pageKey(ref.material_id, page);
          if (!owner.has(key)) owner.set(key, ref.id);
        }
      }
    }
    return owner;
  }, [lesson.blocks]);

  if (lesson.blocks.length === 0) {
    return <p className="lesson-document-empty">В уроке пока нет блоков.</p>;
  }

  return (
    <div className={`lesson-document is-${mode}`}>
      {lesson.blocks.map((block) => (
        <section key={block.id} className={`lesson-edit-block${selectedBlockId === block.id ? " is-selected" : ""}`}>
          {onSelectBlock && <button type="button" className="lesson-block-select" onClick={() => onSelectBlock(block.id)}>
            Выбрать блок {block.sort_order + 1}
          </button>}
          {block.kind === "note" && selectedBlockId === block.id && renderNoteEditor
            ? renderNoteEditor(block)
            : <LessonBlockView projectId={projectId} block={block} mode={mode} pagesShownIn={pagesShownIn} hiddenHeading={hiddenHeading} />}
        </section>
      ))}
    </div>
  );
}

interface LessonBlockViewProps {
  projectId: string;
  block: LessonBlockRead;
  mode: LessonDocumentMode;
  pagesShownIn: Map<string, string>;
  hiddenHeading?: string;
}

function LessonBlockView({ projectId, block, mode, pagesShownIn, hiddenHeading }: LessonBlockViewProps) {
  if (block.kind === "note") {
    const body = block.body_md ?? "";
    const heading = /^(#{1,6})\s+(.*)$/.exec(body);
    if (block.variant === "heading" && heading) {
      if (heading[2] === hiddenHeading) return null;
      const level = Math.min(4, Math.max(2, heading[1].length));
      const Tag = `h${level}` as "h2" | "h3" | "h4";
      return <Tag className={`lesson-note-heading is-level-${level}`}>{heading[2]}</Tag>;
    }
    return <div className={`lesson-note is-${block.variant ?? "text"}`}>{body}</div>;
  }
  if (block.kind !== "source") return null;
  return (
    <>
      {block.refs.filter((ref) => ref.role === "content").map((ref) => (
        <LessonSourceView
          key={ref.id}
          projectId={projectId}
          sourceRef={ref}
          mode={ref.always_pages ? "pages" : mode}
          pagesShownIn={pagesShownIn}
        />
      ))}
    </>
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
  pagesShownIn: Map<string, string>;
}

function LessonSourceView({ projectId, sourceRef: ref, mode, pagesShownIn }: LessonSourceViewProps) {
  const materialId = ref.material_id;
  const head = (
    <header className="lesson-source-head">
      <BookOpen size={14} aria-hidden="true" />
      <span>{refLabel(ref)}</span>
      {ref.from_fragment_id && <small>с заголовка</small>}
      {ref.to_fragment_id && <small>до следующего пункта</small>}
    </header>
  );

  if (!materialId || !ref.is_available) {
    return (
      <section className="lesson-source is-unavailable">
        {head}
        <p className="lesson-source-notice"><AlertTriangle size={14} aria-hidden="true" /> Источник недоступен: материал убран из проекта.</p>
      </section>
    );
  }

  if (mode === "pages") {
    const pages = pageRange(ref).filter((page) => pagesShownIn.get(pageKey(materialId, page)) === ref.id);
    return (
      <section className="lesson-source">
        {head}
        {pages.map((page) => (
          <figure className="lesson-page" key={page}>
            <figcaption>Страница {page}</figcaption>
            <img
              src={materialPageImageUrl(projectId, materialId, page)}
              alt={`${ref.source_name}, страница ${page}`}
              loading="lazy"
            />
          </figure>
        ))}
        {pages.length === 0 && <p className="lesson-source-notice">Страница {ref.page_from} показана выше.</p>}
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
      <LessonSourceText projectId={projectId} materialId={materialId} sourceRef={ref} />
    </section>
  );
}

function LessonSourceText({ projectId, materialId, sourceRef: ref }: { projectId: string; materialId: string; sourceRef: LessonRefRead }) {
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

  if (error) return <ErrorState message={error} />;
  if (!pages) return <p className="lesson-source-notice">Загружаем текст…</p>;

  return (
    <>
      {pages.map((page) => {
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
        fragments = fragments.filter((fragment) => !serviceBlocks.has(fragment.block_id));
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
            />
          </div>
        );
      })}
    </>
  );
}
