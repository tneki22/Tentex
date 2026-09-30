import katex from "katex";
import { memo, useMemo, type ReactNode } from "react";
import { parseInline, parseMarkdown, type Block, type Inline, type SourceBlock } from "./parse";

export interface MarkdownOptions {
  /** Кнопка цитаты `[S3]`; без неё и для неизвестного ID — обычный текст. */
  renderCitation?: (id: string, key: string) => ReactNode;
  /** Картинка `![alt](url)`; по умолчанию — подпись вместо картинки. */
  renderImage?: (alt: string, url: string, key: string) => ReactNode;
}

const MATH_CACHE_LIMIT = 400;
const mathCache = new Map<string, string | null>();

/**
 * HTML формулы от KaTeX или `null`, если LaTeX не разобрался.
 *
 * Кэш нужен потоку: каждый новый кусок ответа перерисовывает сообщение, и без
 * кэша все формулы абзаца перегонялись бы через KaTeX на каждый кадр.
 */
export function renderTex(tex: string, display: boolean): string | null {
  const key = `${display ? "D" : "I"}${tex}`;
  const cached = mathCache.get(key);
  if (cached !== undefined) return cached;
  let html: string | null;
  try {
    html = katex.renderToString(tex, { displayMode: display, throwOnError: true, strict: "ignore", trust: false });
  } catch {
    html = null;
  }
  if (mathCache.size >= MATH_CACHE_LIMIT) mathCache.delete(mathCache.keys().next().value!);
  mathCache.set(key, html);
  return html;
}

/**
 * Формула KaTeX; ошибочный LaTeX остаётся читаемым исходником.
 * HTML приходит только от KaTeX с `trust: false` — `\href` и `\includegraphics` не исполняются.
 */
export function MathNode({ tex, display, className }: { tex: string; display: boolean; className?: string }) {
  const html = renderTex(tex, display);
  const source = display ? `$$${tex}$$` : `$${tex}$`;
  if (html === null) {
    return <code className="md-math-source is-error" title="Формула не распознана">{source}</code>;
  }
  // `$$…$$` посреди абзаца стоит внутри `<p>`, а `<div>` там недопустим: блоком
  // её делает класс `md-math-display`, а тег остаётся строчным.
  const Tag = display && !className?.includes("is-inline") ? "div" : "span";
  return (
    <Tag
      className={className ?? (display ? "md-math-display" : "md-math-inline")}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

const SAFE_URL = /^(https?:|mailto:|\/)/i;

function inlineNodes(nodes: Inline[], prefix: string, options: MarkdownOptions): ReactNode[] {
  return nodes.map((node, index) => {
    const key = `${prefix}.${index}`;
    switch (node.kind) {
      case "text":
        return node.text;
      case "strong":
        return <strong key={key}>{inlineNodes(node.children, key, options)}</strong>;
      case "em":
        return <em key={key}>{inlineNodes(node.children, key, options)}</em>;
      case "del":
        return <del key={key}>{inlineNodes(node.children, key, options)}</del>;
      case "code":
        return <code key={key}>{node.text}</code>;
      case "math":
        return <MathNode key={key} tex={node.tex} display={node.display} className={node.display ? "md-math-display is-inline" : undefined} />;
      case "link":
        return SAFE_URL.test(node.href)
          ? <a key={key} href={node.href} target="_blank" rel="noopener noreferrer">{inlineNodes(node.children, key, options)}</a>
          : <span key={key}>{inlineNodes(node.children, key, options)}</span>;
      case "image":
        return options.renderImage
          ? options.renderImage(node.alt, node.url, key)
          : <span key={key} className="md-image-alt">{node.alt || "Изображение"}</span>;
      case "citation": {
        const rendered = node.ids.map((id) => options.renderCitation?.(id, `${key}.${id}`) ?? null);
        if (rendered.every((item) => item === null)) return `[${node.ids.join(", ")}]`;
        return (
          <span key={key} className="md-citations">
            {rendered.map((item, position) => item ?? `[${node.ids[position]}]`)}
          </span>
        );
      }
    }
  });
}

function inline(text: string, key: string, options: MarkdownOptions): ReactNode[] {
  return inlineNodes(parseInline(text), key, options);
}

/** Короткая разметка внутри пункта выбора, где блочный Markdown недопустим. */
export function MarkdownInline({ text }: { text: string }) {
  return <>{inline(text, "inline", EMPTY_OPTIONS)}</>;
}

/**
 * Заголовок `#`…`######` внутри сообщения — на два уровня ниже страницы:
 * у экрана свои h1–h2, а размер задаёт класс `md-h{n}`, не тег.
 */
function headingTag(level: number): "h3" | "h4" | "h5" | "h6" {
  return `h${Math.min(6, level + 2)}` as "h3" | "h4" | "h5" | "h6";
}

function BlockNode({ block, blockKey, options, tight = false }: {
  block: Block;
  blockKey: string;
  options: MarkdownOptions;
  tight?: boolean;
}): ReactNode {
  switch (block.kind) {
    case "heading": {
      const Tag = headingTag(block.level);
      return <Tag className={`md-heading md-h${block.level}`}>{inline(block.text, blockKey, options)}</Tag>;
    }
    case "paragraph":
      return tight ? <>{inline(block.text, blockKey, options)}</> : <p>{inline(block.text, blockKey, options)}</p>;
    case "rule":
      return <hr />;
    case "code":
      return <pre className={block.open ? "is-open" : undefined}><code>{block.text}</code></pre>;
    case "math":
      return block.open
        ? <pre className="md-math-source is-open">{`$$${block.tex}`}</pre>
        : <MathNode tex={block.tex} display />;
    case "quote":
      return <blockquote><Blocks blocks={block.blocks} prefix={blockKey} options={options} /></blockquote>;
    case "table":
      return (
        <div className="md-table-scroll" role="region" aria-label="Таблица" tabIndex={0}>
          <table className="md-table">
            <thead>
              <tr>
                {block.head.map((cell, index) => (
                  <th scope="col" key={index} style={{ textAlign: block.align[index] ?? undefined }}>
                    {inline(cell, `${blockKey}.h${index}`, options)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, index) => (
                    <td key={index} style={{ textAlign: block.align[index] ?? undefined }}>
                      {inline(cell, `${blockKey}.${rowIndex}.${index}`, options)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "list": {
      const items = block.items.map((item, index) => (
        <li key={index}>
          {item.blocks.map((child, childIndex) => (
            <BlockNode
              key={childIndex}
              block={child}
              blockKey={`${blockKey}.${index}.${childIndex}`}
              options={options}
              tight={block.tight && childIndex === 0}
            />
          ))}
        </li>
      ));
      return block.ordered
        ? <ol start={block.start === 1 ? undefined : block.start}>{items}</ol>
        : <ul>{items}</ul>;
    }
  }
}

function Blocks({ blocks, prefix, options }: { blocks: Block[]; prefix: string; options: MarkdownOptions }) {
  return <>{blocks.map((block, index) => <BlockNode key={index} block={block} blockKey={`${prefix}.${index}`} options={options} />)}</>;
}

/**
 * Верхний блок перерисовывается, только если изменился его исходный текст:
 * при потоке меняется хвост ответа, а готовые абзацы, таблицы и формулы стоят.
 */
const TopBlock = memo(
  function TopBlock({ item, index, options }: { item: SourceBlock; index: number; options: MarkdownOptions }) {
    return <BlockNode block={item.block} blockKey={`b${index}`} options={options} />;
  },
  (previous, next) =>
    previous.item.source === next.item.source && previous.index === next.index && previous.options === next.options,
);

/**
 * Markdown ответа модели или пояснения урока: заголовки, вложенные списки,
 * таблицы, цитаты, код и формулы `$…$`, `$$…$$`, `\(…\)`, `\[…\]`.
 * `options` стоит мемоизировать у вызывающего: от него зависит перерисовка блоков.
 */
export function MarkdownView({ text, className, options = EMPTY_OPTIONS }: {
  text: string;
  className?: string;
  options?: MarkdownOptions;
}) {
  const blocks = useMemo(() => {
    const sources: SourceBlock[] = [];
    parseMarkdown(text, sources);
    return sources;
  }, [text]);
  return (
    <div className={`md ${className ?? ""}`.trim()}>
      {blocks.map((item, index) => <TopBlock key={index} item={item} index={index} options={options} />)}
    </div>
  );
}

const EMPTY_OPTIONS: MarkdownOptions = {};
