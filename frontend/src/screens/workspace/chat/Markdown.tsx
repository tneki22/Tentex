import type { ReactNode } from "react";

// Подмножество и ничего сверх него: абзацы, ### заголовки (h3–h5), списки,
// огороженный код, **жирный**, *курсив*, `код». Модель не присылает HTML/JSX —
// рендерер сам собирает React-узлы и никогда не зовёт dangerouslySetInnerHTML.
// Решение и его причина — план вертикали «Экзамен с ИИ», задача 4.
const INLINE = /(\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`]+`)/g;
const HEADING_RE = /^(#{3,5})\s+(.*)$/;
const ORDERED_RE = /^(\d+)\.\s+(.*)$/;
const BULLET_RE = /^[-*]\s+(.*)$/;
const FENCE_RE = /^```/;

function inline(text: string, prefix: string): ReactNode[] {
  return text
    .split(INLINE)
    .filter(Boolean)
    .map((chunk, index) => {
      const key = `${prefix}-${index}`;
      if (chunk.startsWith("**") && chunk.endsWith("**")) return <strong key={key}>{chunk.slice(2, -2)}</strong>;
      if (chunk.startsWith("`") && chunk.endsWith("`")) return <code key={key}>{chunk.slice(1, -1)}</code>;
      if (chunk.startsWith("*") && chunk.endsWith("*")) return <em key={key}>{chunk.slice(1, -1)}</em>;
      return <span key={key}>{chunk}</span>;
    });
}

interface ListState {
  type: "ul" | "ol";
  items: string[];
}

function parseBlocks(text: string): ReactNode[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let list: ListState | null = null;
  let codeLines: string[] | null = null;
  let key = 0;

  function flushParagraph() {
    if (paragraph.length === 0) return;
    blocks.push(<p key={key++}>{inline(paragraph.join(" "), `p${key}`)}</p>);
    paragraph = [];
  }

  function flushList() {
    if (!list) return;
    const items = list.items.map((item, index) => <li key={index}>{inline(item, `li${key}-${index}`)}</li>);
    blocks.push(list.type === "ul" ? <ul key={key++}>{items}</ul> : <ol key={key++}>{items}</ol>);
    list = null;
  }

  for (const line of lines) {
    if (codeLines !== null) {
      if (FENCE_RE.test(line)) {
        blocks.push(<pre key={key++}><code>{codeLines.join("\n")}</code></pre>);
        codeLines = null;
      } else {
        codeLines.push(line);
      }
      continue;
    }
    if (FENCE_RE.test(line)) {
      flushParagraph();
      flushList();
      codeLines = [];
      continue;
    }
    const heading = HEADING_RE.exec(line);
    if (heading) {
      flushParagraph();
      flushList();
      const level = heading[1].length;
      const Tag = (level === 3 ? "h3" : level === 4 ? "h4" : "h5") as "h3" | "h4" | "h5";
      blocks.push(<Tag key={key++}>{inline(heading[2], `h${key}`)}</Tag>);
      continue;
    }
    const bullet = BULLET_RE.exec(line);
    if (bullet) {
      flushParagraph();
      if (!list || list.type !== "ul") {
        flushList();
        list = { type: "ul", items: [] };
      }
      list.items.push(bullet[1]);
      continue;
    }
    const ordered = ORDERED_RE.exec(line);
    if (ordered) {
      flushParagraph();
      if (!list || list.type !== "ol") {
        flushList();
        list = { type: "ol", items: [] };
      }
      list.items.push(ordered[2]);
      continue;
    }
    if (line.trim() === "") {
      flushParagraph();
      flushList();
      continue;
    }
    if (list) flushList();
    paragraph.push(line.trim());
  }
  // Незакрытый блок кода — обычное дело для потокового текста: рисуем как есть.
  if (codeLines !== null) blocks.push(<pre key={key++}><code>{codeLines.join("\n")}</code></pre>);
  flushParagraph();
  flushList();
  return blocks;
}

export function Markdown({ text }: { text: string }) {
  return <div className="chat-markdown">{parseBlocks(text)}</div>;
}
