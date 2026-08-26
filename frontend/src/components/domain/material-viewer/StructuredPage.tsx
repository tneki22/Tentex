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
  className = "",
}: StructuredPageProps) {
  return (
    <article className={`structured-page ${className}`.trim()}>
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
            <FragmentBody fragment={fragment} query={query} assetUrl={assetUrl} />
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
}: {
  fragment: MaterialFragmentRead;
  query: string;
  assetUrl?: (fragmentId: string) => string;
}) {
  if (fragment.element_kind === "image" && fragment.has_asset && assetUrl) {
    const transcript = fragment.text.trim();
    const hasTranscript = fragment.recognition_source !== "native"
      && transcript.length > 0
      && !/^\[?(изображение|image)\]?$/iu.test(transcript);
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
            <p>{highlight(transcript, query)}</p>
          </details>
        )}
      </figure>
    );
  }
  if (fragment.element_kind === "heading") {
    const level = fragment.structure_level ?? 1;
    if (level <= 1) return <h2>{highlight(fragment.text, query)}</h2>;
    if (level === 2) return <h3>{highlight(fragment.text, query)}</h3>;
    return <h4>{highlight(fragment.text, query)}</h4>;
  }
  if (fragment.element_kind === "list") {
    return (
      <p
        className="structured-list-item"
        style={{ "--list-level": fragment.structure_level ?? 1 } as CSSProperties}
      >
        {highlight(fragment.text, query)}
      </p>
    );
  }
  if (fragment.element_kind === "formula") {
    return <Formula fragment={fragment} assetUrl={assetUrl} />;
  }
  if (fragment.element_kind === "table") {
    return (
      <>
        <MarkdownTable markdown={fragment.text} />
        {fragment.has_asset && assetUrl && (
          <details className="structured-source-crop">
            <summary>Оригинальный фрагмент таблицы</summary>
            <img src={assetUrl(fragment.id)} alt="Оригинальный фрагмент таблицы" loading="lazy" />
          </details>
        )}
      </>
    );
  }
  return <p>{highlight(fragment.text, query)}</p>;
}

function RecognitionMeta({ fragment, showConfidence }: { fragment: MaterialFragmentRead; showConfidence: boolean }) {
  if (fragment.recognition_source === "native") return null;
  const label = {
    ocr: "OCR",
    vl: "PaddleOCR-VL",
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

function Formula({
  fragment,
  assetUrl,
}: {
  fragment: MaterialFragmentRead;
  assetUrl?: (fragmentId: string) => string;
}) {
  try {
    const html = katex.renderToString(fragment.text, {
      displayMode: true,
      throwOnError: true,
      strict: "warn",
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
