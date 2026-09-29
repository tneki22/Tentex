/**
 * Разбор страницы руководства на крупные блоки.
 *
 * Весь связный текст — абзацы, списки, таблицы, формулы, код — читает общий
 * `MarkdownView` (тот же разбор, что у чата и уроков). Здесь только то, чего в
 * общем Markdown нет: заголовки-якоря секций и контейнеры `:::имя … :::`
 * (врезки, карточки, схемы, рисунки, шаги). Тело контейнера снова уходит в общий
 * разбор, поэтому внутри врезки работают жирный, код и списки.
 *
 * Формат страницы описан в `GUIDE.md` в корне проекта.
 */

export type CalloutTone = "info" | "tip" | "success" | "warning" | "danger";

const CALLOUT_TONES: readonly string[] = ["info", "tip", "success", "warning", "danger"];

export interface GuideCardData {
  icon: string | null;
  title: string;
  /** Маршрут приложения: другая страница руководства или экран Tentex. */
  to: string | null;
  text: string;
}

export type GuideBlock =
  | { kind: "md"; text: string }
  | { kind: "heading"; id: string; title: string }
  | { kind: "callout"; tone: CalloutTone; title: string | null; text: string }
  | { kind: "cards"; cards: GuideCardData[] }
  | { kind: "steps"; text: string }
  | { kind: "diagram"; name: string; caption: string }
  | { kind: "figure"; alt: string; src: string; caption: string };

const FENCE = /^\s*(```|~~~)/;
const HEADING = /^##[ \t]+(.+?)[ \t]*$/;
const HEADING_ID = /\s*\{#([\w-]+)\}\s*$/;
const CONTAINER_OPEN = /^:::[ \t]*([a-z]+)[ \t]*(.*?)[ \t]*$/;
const CONTAINER_CLOSE = /^:::[ \t]*$/;
const CARD_HEAD = /^\[(\w+)\][ \t]+(.+?)(?:[ \t]+(?:→|->)[ \t]+(\S+))?[ \t]*$/;
const FIGURE_IMAGE = /^!\[(.*?)\]\((\S+?)\)[ \t]*$/;

function parseCards(body: string[]): GuideCardData[] {
  const cards: GuideCardData[] = [];
  let group: string[] = [];
  const flush = () => {
    if (group.length === 0) return;
    const head = CARD_HEAD.exec(group[0]);
    if (head) {
      cards.push({ icon: head[1], title: head[2], to: head[3] ?? null, text: group.slice(1).join(" ").trim() });
    } else {
      // Строка без `[Иконка]` — карточка без иконки и ссылки.
      cards.push({ icon: null, title: group[0].trim(), to: null, text: group.slice(1).join(" ").trim() });
    }
    group = [];
  };
  for (const line of body) {
    if (line.trim() === "") flush();
    else group.push(line);
  }
  flush();
  return cards;
}

function container(name: string, argument: string, body: string[]): GuideBlock | null {
  const text = body.join("\n").trim();
  if (CALLOUT_TONES.includes(name)) {
    return { kind: "callout", tone: name as CalloutTone, title: argument || null, text };
  }
  switch (name) {
    case "cards":
      return { kind: "cards", cards: parseCards(body) };
    case "steps":
      return { kind: "steps", text };
    case "diagram":
      return { kind: "diagram", name: argument, caption: text };
    case "figure": {
      const image = FIGURE_IMAGE.exec(body.find((line) => line.trim() !== "")?.trim() ?? "");
      if (!image) return null;
      const captionLines = body.slice(body.findIndex((line) => line.trim() !== "") + 1);
      return { kind: "figure", alt: image[1], src: image[2], caption: captionLines.join("\n").trim() };
    }
    default:
      return null;
  }
}

export function parseGuideDocument(source: string): GuideBlock[] {
  const blocks: GuideBlock[] = [];
  let paragraph: string[] = [];
  let inFence = false;
  let headingCount = 0;

  const flushParagraph = () => {
    const text = paragraph.join("\n").trim();
    if (text) blocks.push({ kind: "md", text });
    paragraph = [];
  };

  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];

    if (FENCE.test(line)) {
      inFence = !inFence;
      paragraph.push(line);
      continue;
    }
    if (inFence) {
      paragraph.push(line);
      continue;
    }

    const open = CONTAINER_OPEN.exec(line);
    if (open) {
      const body: string[] = [];
      let end = index + 1;
      while (end < lines.length && !CONTAINER_CLOSE.test(lines[end])) {
        body.push(lines[end]);
        end += 1;
      }
      const block = container(open[1], open[2], body);
      if (block) {
        flushParagraph();
        blocks.push(block);
        index = end;
        continue;
      }
    }

    const heading = HEADING.exec(line);
    if (heading) {
      flushParagraph();
      headingCount += 1;
      const idMatch = HEADING_ID.exec(heading[1]);
      blocks.push({
        kind: "heading",
        id: idMatch?.[1] ?? `section-${headingCount}`,
        title: heading[1].replace(HEADING_ID, ""),
      });
      continue;
    }

    paragraph.push(line);
  }
  flushParagraph();
  return blocks;
}

export interface GuideOutlineItem {
  id: string;
  title: string;
}

/** Заголовки секций страницы — подпункты дерева и якоря для прокрутки. */
export function guideOutline(blocks: GuideBlock[]): GuideOutlineItem[] {
  return blocks.flatMap((block) => (block.kind === "heading" ? [{ id: block.id, title: block.title }] : []));
}
