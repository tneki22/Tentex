import katex from "katex";
import type { CSSProperties, HTMLAttributes, ReactNode } from "react";
import type { MaterialFragmentRead, MaterialPageRead } from "../../../api/materials";
import { QualityBadge } from "../QualityBadge";

interface StructuredPageProps {
  page: MaterialPageRead;
  showOcrReview?: boolean;
  /** Подсветка совпадений поиска. Пустая строка — ничего не подсвечивать. */
  query?: string;
  /** Ссылка на картинку фрагмента: у проекта и Библиотеки маршруты разные. */
  assetUrl?: (fragmentId: string) => string;
  /** Фрагмент, к которому нужно прокрутить и который выделен. */
  focusedFragmentId?: string | null;
  /** Проектный потребитель добавляет сюда привязки; в Библиотеке их нет. */
  renderFragmentOverlay?: (fragment: MaterialFragmentRead) => ReactNode;
  fragmentProps?: (fragment: MaterialFragmentRead) => HTMLAttributes<HTMLDivElement> | undefined;
  /** Ссылка на растр исходной страницы: с ней над каждым фрагментом можно
      показать вырезку оригинала, а расшифровку — под ней. */
  pageImageUrl?: string;
  /** Показывать вырезки исходной фотографии над распознанным текстом. */
  showSourceCrops?: boolean;
  className?: string;
}

/**
 * Подготовленный текст страницы со своей структурой: заголовки остаются
 * заголовками, пункт списка получает висячий отступ по уровню, таблица —
 * настоящей таблицей, картинка — картинкой на своём месте.
 *
 * Компонент нейтрален: ни привязок, ни тем, ни проекта. Проектный просмотрщик
 * навешивает своё через `renderFragmentOverlay` и `fragmentProps`.
 */
export function StructuredPage({
  page,
  showOcrReview = true,
  query = "",
  assetUrl,
  focusedFragmentId = null,
  renderFragmentOverlay,
  fragmentProps,
  pageImageUrl,
  showSourceCrops = false,
  className = "",
}: StructuredPageProps) {
  const withCrops = showSourceCrops && Boolean(pageImageUrl);
  return (
    <article className={`structured-page ${withCrops ? "with-crops" : ""} ${className}`.trim()}>
      <header className="structured-page-head">
        <span>Страница {page.page_number}</span>
        <QualityBadge quality={page.quality} showReview={showOcrReview} />
      </header>
      {page.fragments.map((fragment) => {
        const extra = fragmentProps?.(fragment) ?? {};
        const classNames = [
          "structured-fragment",
          fragment.id === focusedFragmentId ? "is-focused" : "",
          extra.className ?? "",
        ].filter(Boolean).join(" ");
        return (
          <div
            {...extra}
            className={classNames}
            data-recognition-source={fragment.recognition_source}
            key={fragment.id}
            id={`fragment-${fragment.id}`}
          >
            {renderFragmentOverlay?.(fragment)}
            {withCrops && pageImageUrl && hasArea(fragment.bbox) && (
              <SourceCrop pageImageUrl={pageImageUrl} bbox={fragment.bbox} page={page} />
            )}
            <FragmentBody
              fragment={fragment}
              query={query}
              assetUrl={assetUrl}
              suppressImage={withCrops}
            />
            <RecognitionMeta fragment={fragment} showConfidence={showOcrReview} />
          </div>
        );
      })}
      {page.fragments.length === 0 && (
        <p className="structured-page-empty">На этой странице не нашлось текста.</p>
      )}
    </article>
  );
}

function FragmentBody({
  fragment,
  query,
  assetUrl,
  suppressImage = false,
}: {
  fragment: MaterialFragmentRead;
  query: string;
  assetUrl?: (fragmentId: string) => string;
  /** Вырезку оригинала уже показывает `SourceCrop` — свои картинки не дублируем. */
  suppressImage?: boolean;
}) {
  if (fragment.element_kind === "image") {
    const transcript = fragment.text.trim();
    const hasTranscript = fragment.recognition_source !== "native"
      && transcript.length > 0
      && !/^\[?(изображение|image)\]?$/iu.test(transcript);
    if (suppressImage) {
      // Фото фрагмента уже над текстом — здесь только расшифровка, если есть.
      return hasTranscript ? <p>{renderInlineMath(transcript, query)}</p> : null;
    }
    if (!fragment.has_asset || !assetUrl) {
      return hasTranscript ? <p>{renderInlineMath(transcript, query)}</p> : null;
    }
    return (
      <figure className="structured-figure">
        <img
          className="structured-image"
          src={assetUrl(fragment.id)}
          alt="Изображение из документа"
          loading="lazy"
        />
        {hasTranscript && (
          <details className="structured-transcript">
            <summary>Распознанный текст</summary>
            <p className="structured-transcript-note">Может содержать ошибки, особенно в формулах.</p>
            <p>{renderInlineMath(transcript, query)}</p>
          </details>
        )}
      </figure>
    );
  }
  if (fragment.element_kind === "heading") {
    const level = fragment.structure_level ?? 1;
    if (level <= 1) return <h2>{renderInlineMath(fragment.text, query)}</h2>;
    if (level === 2) return <h3>{renderInlineMath(fragment.text, query)}</h3>;
    return <h4>{renderInlineMath(fragment.text, query)}</h4>;
  }
  if (fragment.element_kind === "list") {
    return (
      <p
        className="structured-list-item"
        style={{ "--list-level": fragment.structure_level ?? 1 } as CSSProperties}
      >
        {renderInlineMath(fragment.text, query)}
      </p>
    );
  }
  if (fragment.element_kind === "formula") {
    return <Formula fragment={fragment} assetUrl={suppressImage ? undefined : assetUrl} />;
  }
  if (fragment.element_kind === "table") {
    return (
      <>
        <MarkdownTable markdown={fragment.text} />
        {!suppressImage && fragment.has_asset && assetUrl && (
          <details className="structured-source-crop">
            <summary>Оригинальный фрагмент таблицы</summary>
            <img src={assetUrl(fragment.id)} alt="Оригинальный фрагмент таблицы" loading="lazy" />
          </details>
        )}
      </>
    );
  }
  return <p>{renderInlineMath(fragment.text, query)}</p>;
}

function RecognitionMeta({ fragment, showConfidence }: { fragment: MaterialFragmentRead; showConfidence: boolean }) {
  if (fragment.recognition_source === "native") return null;
  const label = {
    ocr: "OCR",
    vl: "Учебник",
    manual: "исправлено вручную",
  }[fragment.recognition_source];
  const lowConfidence = showConfidence && fragment.confidence !== null && fragment.confidence < 0.75;
  return (
    <small className={`structured-recognition ${lowConfidence ? "is-low" : ""}`.trim()}>
      {label}
      {lowConfidence ? ` · уверенность ${Math.round(fragment.confidence! * 100)}%` : ""}
    </small>
  );
}

/** У фрагмента есть, что вырезать: непустая площадь бокса. */
function hasArea(bbox: number[]): boolean {
  const [x0, y0, x1, y1] = bbox;
  return x1 - x0 > 0.01 && y1 - y0 > 0.005;
}

/**
 * Вырезка исходной фотографии под один фрагмент: тот же кадр страницы, обрезанный
 * по нормализованному боксу. Растр один на страницу, кроим его через background —
 * лишних сетевых запросов на каждый фрагмент нет.
 */
function SourceCrop({
  pageImageUrl,
  bbox,
  page,
}: {
  pageImageUrl: string;
  bbox: number[];
  page: MaterialPageRead;
}) {
  const [x0, y0, x1, y1] = bbox;
  const width = Math.min(1, Math.max(0.0001, x1 - x0));
  const height = Math.min(1, Math.max(0.0001, y1 - y0));
  const ratio = (width * page.width) / (height * page.height);
  const style: CSSProperties = {
    backgroundImage: `url("${pageImageUrl}")`,
    backgroundSize: `${100 / width}% ${100 / height}%`,
    backgroundPosition: `${width >= 1 ? 0 : (x0 / (1 - width)) * 100}% ${
      height >= 1 ? 0 : (y0 / (1 - height)) * 100
    }%`,
    aspectRatio: Number.isFinite(ratio) && ratio > 0 ? `${ratio}` : undefined,
  };
  return (
    <div
      className="structured-source-photo"
      style={style}
      role="img"
      aria-label="Вырезка исходной страницы"
    />
  );
}

/**
 * Распознаватель формул (PP-FormulaNet) и markdown часто оборачивают LaTeX в
 * разделители `$$…$$`, `\[…\]`, `\(…\)` или `$…$`. KaTeX ждёт голое выражение,
 * поэтому внешнюю обёртку снимаем — иначе валидная формула молча падала в
 * запасной вид сырым текстом.
 */
function latexFromFragment(text: string): string {
  let value = text.trim();
  const wrappers: [string, string][] = [
    ["$$", "$$"],
    ["\\[", "\\]"],
    ["\\(", "\\)"],
    ["$", "$"],
  ];
  for (const [open, close] of wrappers) {
    if (
      value.length >= open.length + close.length
      && value.startsWith(open)
      && value.endsWith(close)
    ) {
      return value.slice(open.length, value.length - close.length).trim();
    }
  }
  return value;
}

function Formula({
  fragment,
  assetUrl,
}: {
  fragment: MaterialFragmentRead;
  assetUrl?: (fragmentId: string) => string;
}) {
  try {
    const html = katex.renderToString(latexFromFragment(fragment.text), {
      displayMode: true,
      throwOnError: true,
      strict: "ignore",
      trust: false,
    });
    return <div className="structured-formula" dangerouslySetInnerHTML={{ __html: html }} />;
  } catch {
    return (
      <div className="structured-formula-fallback">
        <code>{fragment.text}</code>
        {fragment.has_asset && assetUrl && (
          <img src={assetUrl(fragment.id)} alt="Оригинальный фрагмент формулы" loading="lazy" />
        )}
      </div>
    );
  }
}

const INLINE_MATH = /\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$|\\\(([\s\S]+?)\\\)/g;

function renderInlineMath(text: string, query: string): ReactNode {
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const match of text.matchAll(INLINE_MATH)) {
    const start = match.index;
    if (start > cursor) parts.push(highlight(text.slice(cursor, start), query));
    const source = match[1] ?? match[2] ?? match[3] ?? "";
    try {
      const html = katex.renderToString(source, {
        displayMode: false,
        throwOnError: true,
        strict: "ignore",
        trust: false,
      });
      parts.push(
        <span
          className="structured-inline-math"
          dangerouslySetInnerHTML={{ __html: html }}
          key={`${start}-${match[0]}`}
        />,
      );
    } catch {
      parts.push(match[0]);
    }
    cursor = start + match[0].length;
  }
  if (cursor === 0) return highlight(text, query);
  if (cursor < text.length) parts.push(highlight(text.slice(cursor), query));
  return parts;
}

function splitMarkdownRow(row: string): string[] {
  const cells: string[] = [];
  let cell = "";
  let escaped = false;
  for (const character of row.trim().replace(/^\|/, "").replace(/\|$/, "")) {
    if (escaped) {
      cell += character;
      escaped = false;
    } else if (character === "\\") {
      escaped = true;
    } else if (character === "|") {
      cells.push(cell.trim());
      cell = "";
    } else {
      cell += character;
    }
  }
  cells.push(cell.trim());
  return cells;
}

export function MarkdownTable({ markdown }: { markdown: string }) {
  const lines = markdown.split("\n").filter((line) => line.trim().startsWith("|"));
  const rows = lines.map(splitMarkdownRow);
  const divider = rows.findIndex((row) => row.every((cell) => /^:?-{3,}:?$/.test(cell)));
  if (divider !== 1 || rows.length < 2) return <p>{markdown}</p>;
  const [head] = rows;
  const body = rows.slice(2);
  return (
    <div className="structured-table-scroll" role="region" aria-label="Таблица из документа" tabIndex={0}>
      <table className="structured-table">
        <thead>
          <tr>{head.map((cell, index) => <th scope="col" key={`${index}-${cell}`}>{cell}</th>)}</tr>
        </thead>
        <tbody>
          {body.map((row, rowIndex) => (
            <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function highlight(text: string, query: string) {
  const needle = query.trim().toLocaleLowerCase("ru");
  if (!needle) return text;
  const index = text.toLocaleLowerCase("ru").indexOf(needle);
  if (index < 0) return text;
  return (
    <>
      {text.slice(0, index)}
      <mark>{text.slice(index, index + needle.length)}</mark>
      {text.slice(index + needle.length)}
    </>
  );
}
