import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { AlertTriangle, BookOpen, ChevronDown, ChevronRight, ExternalLink, FileText, Scissors } from "lucide-react";
import {
  checkStudyTaskAttempt, lessonMediaUrl, submitStudyTaskAttempt, type LessonBlockRead, type LessonRead, type LessonRefRead,
} from "../../../api/lessons";
import {
  getMaterialPage,
  materialFragmentAssetUrl,
  materialPageImageUrl,
  type MaterialPageRead,
} from "../../../api/materials";
import { ContextMenu, ErrorState, type ContextMenuItem } from "../../ui";
import { PageRegion, StructuredPage } from "../material-viewer";
import { MachineMark } from "../MachineMark";
import { QualityBadge } from "../QualityBadge";
import { LessonMarkdown, refPages } from "./LessonMarkdown";
import { LessonProposalCard, type LessonProposalView } from "./LessonProposalCard";
import { TaskCard } from "./tasks/TaskCard";

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
  onSelectBlock?: (blockId: string | null) => void;
  /** Действия над блоком по правой кнопке мыши. */
  blockMenuItems?: (block: LessonBlockRead) => ContextMenuItem[];
  /** Действия на пустом месте под уроком — вставка блока в конец. */
  tailMenuItems?: ContextMenuItem[];
  renderNoteEditor?: (block: LessonBlockRead) => ReactNode;
  /** Кусок, в котором сейчас выбирают место разреза. */
  splitBlockId?: string | null;
  onSplit?: (blockId: string, point: LessonSplitPoint) => void;
  /** Позиция чтения: куда прокрутить при открытии и кому сообщать о новой. */
  startBlockId?: string | null;
  onReadBlock?: (blockId: string) => void;
  /** Предложение модели: его изменения стоят на своих местах среди блоков. */
  proposal?: LessonProposalView | null;
  /** В Рабочей области служебное происхождение пояснений скрыто. */
  showOrigin?: boolean;
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
export function LessonDocument({ projectId, lesson, mode, hiddenHeading, selectedBlockId, onSelectBlock, blockMenuItems, tailMenuItems, renderNoteEditor, splitBlockId, onSplit, startBlockId, onReadBlock, proposal, showOrigin = true }: LessonDocumentProps) {
  const topicTitles = useMemo(
    () => new Map(lesson.topics.map((topic) => [topic.program_node_id, topic.current_title ?? topic.title_snapshot])),
    [lesson.topics],
  );
  const multiTopic = lesson.topics.length > 1;
  const blockRefs = useRef(new Map<string, HTMLElement>());
  useReadingPosition(lesson.id, blockRefs, startBlockId, onReadBlock);

  if (lesson.blocks.length === 0 && !tailMenuItems) {
    return <p className="lesson-document-empty">В уроке пока нет блоков.</p>;
  }

  return (
    <div
      className={`lesson-document is-${mode}`}
      // Средняя кнопка снимает выбор; preventDefault убирает автопрокрутку Windows.
      onMouseDown={onSelectBlock && ((event) => { if (event.button === 1) event.preventDefault(); })}
      onAuxClick={onSelectBlock && ((event) => { if (event.button === 1) onSelectBlock(null); })}
    >
      {proposal?.proposal.ops.filter((op) => op.block_id === null).map((op) => (
        <LessonProposalCard key={op.id} op={op} view={proposal} />
      ))}
      {lesson.blocks.map((block) => {
        const cards = proposal?.proposal.ops
          .filter((op) => op.block_id === block.id)
          .map((op) => <LessonProposalCard key={op.id} op={op} view={proposal} />);
        const body = (
          <section
            key={block.id}
            data-block-id={block.id}
            ref={(node) => {
              if (node) blockRefs.current.set(block.id, node);
              else blockRefs.current.delete(block.id);
            }}
            className={`lesson-edit-block${selectedBlockId === block.id ? " is-selected" : ""}${onSelectBlock ? " is-pickable" : ""}`}
            tabIndex={onSelectBlock ? 0 : undefined}
            aria-label={onSelectBlock ? `Блок ${block.sort_order + 1}` : undefined}
            onClick={onSelectBlock && (() => onSelectBlock(block.id))}
            onContextMenu={onSelectBlock && (() => onSelectBlock(block.id))}
            // Пробел и стрелки нужны редактору пояснения внутри — берём только свой Enter.
            onKeyDown={onSelectBlock && ((event) => {
              if (event.key === "Enter" && event.target === event.currentTarget) onSelectBlock(block.id);
            })}
          >
            {block.kind === "note" && selectedBlockId === block.id && renderNoteEditor
              ? renderNoteEditor(block)
              : <LessonBlockView
                  projectId={projectId}
                  lessonId={lesson.id}
                  block={block}
                  mode={mode}
                  hiddenHeading={hiddenHeading}
                  topicTitle={multiTopic && block.bound_program_node_id ? topicTitles.get(block.bound_program_node_id) : undefined}
                  showOrigin={showOrigin}
                  onSplit={splitBlockId === block.id && onSplit ? (point) => onSplit(block.id, point) : undefined}
                />}
            {block.kind === "media" && selectedBlockId === block.id && renderNoteEditor?.(block)}
          </section>
        );
        const wrapped = blockMenuItems
          ? <ContextMenu key={block.id} label={`Действия над блоком ${block.sort_order + 1}`} items={blockMenuItems(block)} trigger={body} />
          : body;
        if (!cards?.length) return wrapped;
        return <Fragment key={block.id}>{wrapped}{cards}</Fragment>;
      })}
      {tailMenuItems && (
        <ContextMenu
          label="Действия на пустом месте урока"
          items={tailMenuItems}
          trigger={
            <div className="lesson-document-tail" onClick={() => onSelectBlock?.(null)}>
              {lesson.blocks.length === 0 ? "В уроке пока нет блоков — правая кнопка мыши добавит первый." : "Правая кнопка мыши добавит блок в конец урока."}
            </div>
          }
        />
      )}
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
  showOrigin: boolean;
}

/** Пустой абзац Crepe пишет как `<br />`: без этого пустой блок считался заполненным. */
function noteBody(body: string | null): string {
  return (body ?? "").replace(/^[ \t]*<br\s*\/?>[ \t]*$/gim, "").replace(/\n{3,}/g, "\n\n").trim();
}

/**
 * Что показать в блоке оформления «Заголовок».
 *
 * Crepe пишет обычный абзац, пока пользователь сам не сделает его заголовком,
 * поэтому блок с выбранным оформлением выглядел рядовым пояснением. Уровень
 * берётся из `#`, а без решёток заголовком становится первая строка.
 */
function headingOf(body: string): { text: string; level: 2 | 3 | 4; rest: string } | null {
  const lines = body.split("\n");
  const first = lines.findIndex((line) => line.trim() !== "");
  if (first < 0) return null;
  const rest = lines.slice(first + 1).join("\n").trim();
  const marked = /^(#{1,6})\s+(.*)$/.exec(lines[first].trim());
  if (marked) return { text: marked[2], level: Math.min(4, Math.max(2, marked[1].length)) as 2 | 3 | 4, rest };
  return { text: lines[first].trim(), level: 3, rest };
}

function LessonBlockView({ projectId, lessonId, block, mode, hiddenHeading, topicTitle, onSplit, showOrigin }: LessonBlockViewProps) {
  if (block.kind === "note") {
    const body = noteBody(block.body_md);
    const heading = block.variant === "heading" ? headingOf(body) : null;
    if (heading) {
      if (heading.text === hiddenHeading && !heading.rest) return null;
      const Tag = `h${heading.level}` as "h2" | "h3" | "h4";
      return (
        <>
          {heading.text !== hiddenHeading && <Tag className={`lesson-note-heading is-level-${heading.level}`}>{heading.text}</Tag>}
          {heading.rest && <LessonMarkdown className="lesson-note is-text" text={heading.rest} />}
        </>
      );
    }
    if (!body) return <div className={`lesson-note is-${block.variant ?? "text"} is-empty`}>Пустое пояснение — выберите блок, чтобы написать текст.</div>;
    const supports = block.refs.filter((ref) => ref.role === "support");
    return (
      <>
        <LessonMarkdown className={`lesson-note is-${block.variant ?? "text"}`} text={body} citations={supports} projectId={projectId} />
        {showOrigin && <NoteOrigin block={block} supports={supports} />}
      </>
    );
  }
  if (block.kind === "media") return <LessonMediaView projectId={projectId} lessonId={lessonId} block={block} />;
  if (block.kind === "activity") {
    const task = block.task;
    if (!task) return <p className="lesson-note is-text is-empty">Задание удалено.</p>;
    return (
      <TaskCard
        task={task}
        showOrigin={showOrigin}
        onSubmit={(answer) => submitStudyTaskAttempt(projectId, lessonId, task.activity_id,
          task.form === "open_answer" ? { text: answer.text } : { answer })}
        onCheckPending={(attemptId) => checkStudyTaskAttempt(projectId, lessonId, task.activity_id, attemptId)}
      />
    );
  }
  if (block.kind !== "source") return null;
  const pieces = block.refs.filter((ref) => ref.role === "content");
  const view = pieces.map((ref) => (
    <LessonSourceView
      key={ref.id}
      projectId={projectId}
      sourceRef={ref}
      mode={mode}
      topicTitle={topicTitle}
      onSplit={onSplit}
    />
  ));
  // Разрез выбирают по тексту куска — свёрнутый в этот момент раскрыт.
  if (!block.collapsed || onSplit) return <>{view}</>;
  return <CollapsedSource pieces={pieces}>{view}</CollapsedSource>;
}

/**
 * Откуда пояснение: модель по материалам или из своих знаний. Метка обязательна —
 * текст модели без опоры не должен выглядеть как текст учебника (FR-L5).
 */
function NoteOrigin({ block, supports }: { block: LessonBlockRead; supports: LessonRefRead[] }) {
  if ((block.origin !== "model" && block.origin !== "mixed") || !block.basis) return null;
  const who = block.origin === "mixed" ? "ИИ, правлено вами" : "ИИ";
  if (block.basis === "model_only" || supports.length === 0) {
    return <div className="lesson-note-origin is-model"><MachineMark origin={`${who} · знания модели — не подтверждено материалами`} /></div>;
  }
  const bySource = new Map<string, LessonRefRead[]>();
  for (const ref of supports) bySource.set(ref.source_name, [...(bySource.get(ref.source_name) ?? []), ref]);
  const where = [...bySource].map(([name, refs]) => {
    const pages = [...refs].sort((a, b) => a.page_from - b.page_from || a.page_to - b.page_to)
      .map((ref) => refPages(ref).replace("стр. ", ""));
    return `${name}, с. ${[...new Set(pages)].join(", ")}`;
  }).join("; ");
  return <div className="lesson-note-origin"><MachineMark origin={`${who} · по материалам: ${where}`} /></div>;
}

/** «▸ В учебнике: Олифер, стр. 150–153» — кусок под пояснением, раскрывается по нажатию. */
function CollapsedSource({ pieces, children }: { pieces: LessonRefRead[]; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const label = pieces.map((ref) => `${ref.source_name}, ${refPages(ref)}`).join("; ");
  return (
    <div className={`lesson-source-collapsed${open ? " is-open" : ""}`}>
      <button type="button" className="lesson-source-toggle" aria-expanded={open}
        onClick={(event) => { event.stopPropagation(); setOpen((value) => !value); }}>
        {open ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
        <BookOpen size={13} aria-hidden="true" />
        <span>В учебнике: {label}</span>
        <small>{open ? "Свернуть" : "Раскрыть"}</small>
      </button>
      {open && children}
    </div>
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

/** Номер страницы у имени источника не пишется: его несёт сам лист под шапкой. */
function pagesLabel(ref: LessonRefRead): string {
  return ref.page_from === ref.page_to ? `стр. ${ref.page_from}` : `стр. ${ref.page_from}–${ref.page_to}`;
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
      <BookOpen size={12} aria-hidden="true" />
      <span>{ref.source_name}</span>
      {!ref.is_available && <small>{pagesLabel(ref)}</small>}
      {ref.from_fragment_id && <small>с абзаца</small>}
      {ref.to_fragment_id && <small>до абзаца</small>}
      {ref.region_bbox ? <small>область {pagesLabel(ref)}</small> : ref.always_pages && <small>всегда страницами</small>}
      {topicTitle && <small className="lesson-source-topic">тема: {topicTitle}</small>}
      {ref.boundary_shifted && <small className="lesson-source-shifted"><AlertTriangle size={12} aria-hidden="true" /> Разрез сдвинут</small>}
    </header>
  );

  if (!materialId || !ref.is_available) {
    // Урок пришёл файлом из другой установки: учебника здесь нет, но текст куска
    // приехал снимком — урок читается, а ссылку можно связать, когда файл появится.
    if (ref.snapshot_md) {
      return (
        <section className="lesson-source is-snapshot">
          {head}
          <p className="lesson-source-notice is-warning">
            <AlertTriangle size={14} aria-hidden="true" />
            {ref.can_relink
              ? "Показан снимок текста из файла уроков — этот учебник уже есть в проекте, кусок можно связать."
              : "Показан снимок текста из файла уроков: этого учебника нет в проекте."}
          </p>
          <LessonMarkdown className="lesson-source-snapshot" text={ref.snapshot_md} />
        </section>
      );
    }
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
          <FileText size={14} aria-hidden="true" /> {pagesLabel(ref)}: текст ещё не распознан.{" "}
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
              showNativeQuality={false}
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
