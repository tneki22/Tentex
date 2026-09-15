import katex from "katex";
import type { ReactNode } from "react";

// Пояснение урока в режиме чтения: подмножество Markdown, которое пишет Crepe, —
// абзацы, заголовки, списки, цитаты, код, **жирный**, *курсив*, ссылки и формулы
// `$…$`, `$$…$$` и ```latex. Рендер собирает React-узлы сам; HTML приходит только
// из KaTeX с `trust: false`. Один Crepe на выбранном блоке, остальные — здесь (§3.7).
const INLINE = /(\$[^$\n]+\$|\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g;
const HEADING_RE = /^(#{1,6})\s+(.*)$/;
const ORDERED_RE = /^\d+\.\s+(.*)$/;
const BULLET_RE = /^[-*]\s+(.*)$/;
const QUOTE_RE = /^>\s?(.*)$/;
const FENCE_RE = /^```\s*(\w*)/;
const LINK_RE = /^\[([^\]]+)\]\(([^)\s]+)\)$/;

function math(latex: string, displayMode: boolean, key: string): ReactNode {
  try {
    const html = katex.renderToString(latex, { displayMode, throwOnError: true, strict: "ignore", trust: false });
    return displayMode
      ? <div key={key} className="lesson-math" dangerouslySetInnerHTML={{ __html: html }} />
      : <span key={key} dangerouslySetInnerHTML={{ __html: html }} />;
  } catch {
    return <code key={key}>{latex}</code>;
  }
}

/** Crepe экранирует знаки разметки обратной косой чертой — в чтении она не нужна. */
const unescape = (text: string) => text.replace(/\\([\\`*_{}[\]()#+\-.!$>])/g, "$1");

function inline(text: string, prefix: string): ReactNode[] {
  return text.split(INLINE).filter(Boolean).map((chunk, index) => {
    const key = `${prefix}-${index}`;
    if (chunk.length > 2 && chunk.startsWith("$") && chunk.endsWith("$")) return math(chunk.slice(1, -1), false, key);
    if (chunk.startsWith("**") && chunk.endsWith("**")) return <strong key={key}>{unescape(chunk.slice(2, -2))}</strong>;
    if (chunk.startsWith("`") && chunk.endsWith("`")) return <code key={key}>{chunk.slice(1, -1)}</code>;
    if (chunk.startsWith("*") && chunk.endsWith("*") && chunk.length > 2) return <em key={key}>{unescape(chunk.slice(1, -1))}</em>;
    const link = LINK_RE.exec(chunk);
    if (link && /^https?:\/\//.test(link[2])) {
      return <a key={key} href={link[2]} target="_blank" rel="noreferrer noopener">{unescape(link[1])}</a>;
    }
    return <span key={key}>{unescape(chunk)}</span>;
  });
}

export function LessonMarkdown({ text, className = "" }: { text: string; className?: string }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let list: { type: "ul" | "ol"; items: string[] } | null = null;
  let quote: string[] = [];
  let fence: { lang: string; lines: string[] } | null = null;
  let display: string[] | null = null;
  let key = 0;

  const flush = () => {
    if (paragraph.length) blocks.push(<p key={key++}>{inline(paragraph.join(" "), `p${key}`)}</p>);
    paragraph = [];
    if (list) {
      const items = list.items.map((item, index) => <li key={index}>{inline(item, `li${key}-${index}`)}</li>);
      blocks.push(list.type === "ul" ? <ul key={key++}>{items}</ul> : <ol key={key++}>{items}</ol>);
      list = null;
    }
    if (quote.length) blocks.push(<blockquote key={key++}>{inline(quote.join(" "), `q${key}`)}</blockquote>);
    quote = [];
  };

  for (const line of lines) {
    if (display !== null) {
      if (line.trim() === "$$") { blocks.push(math(display.join("\n"), true, `m${key++}`)); display = null; }
      else display.push(line);
      continue;
    }
    if (fence !== null) {
      if (FENCE_RE.test(line) && line.trim() === "```") {
        const body = fence.lines.join("\n");
        blocks.push(["latex", "math", "tex"].includes(fence.lang) ? math(body, true, `m${key++}`) : <pre key={key++}><code>{body}</code></pre>);
        fence = null;
      } else fence.lines.push(line);
      continue;
    }
    const trimmed = line.trim();
    const fenceOpen = FENCE_RE.exec(trimmed);
    if (fenceOpen) { flush(); fence = { lang: fenceOpen[1].toLowerCase(), lines: [] }; continue; }
    if (trimmed === "$$") { flush(); display = []; continue; }
    if (/^\$\$.+\$\$$/.test(trimmed)) { flush(); blocks.push(math(trimmed.slice(2, -2), true, `m${key++}`)); continue; }
    if (trimmed === "") { flush(); continue; }
    const heading = HEADING_RE.exec(trimmed);
    if (heading) {
      flush();
      const level = Math.min(5, Math.max(3, heading[1].length + 1));
      const Tag = `h${level}` as "h3" | "h4" | "h5";
      blocks.push(<Tag key={key++}>{inline(heading[2], `h${key}`)}</Tag>);
      continue;
    }
    const quoted = QUOTE_RE.exec(trimmed);
    if (quoted) { if (paragraph.length || list) flush(); quote.push(quoted[1]); continue; }
    const bullet = BULLET_RE.exec(trimmed);
    const ordered = ORDERED_RE.exec(trimmed);
    if (bullet || ordered) {
      const type = bullet ? "ul" : "ol";
      if (paragraph.length || quote.length || (list && list.type !== type)) flush();
      list ??= { type, items: [] };
      list.items.push((bullet ?? ordered)![1]);
      continue;
    }
    if (list || quote.length) flush();
    paragraph.push(trimmed);
  }
  if (display !== null) blocks.push(math(display.join("\n"), true, `m${key++}`));
  if (fence !== null) blocks.push(<pre key={key++}><code>{fence.lines.join("\n")}</code></pre>);
  flush();
  return <div className={`lesson-markdown ${className}`.trim()}>{blocks}</div>;
}
