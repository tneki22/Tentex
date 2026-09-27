/**
 * Разбор Markdown ответа модели и пояснения урока в дерево без React.
 *
 * Собственный разбор, а не remark: зависимостей не добавляем, а нужное
 * подмножество небольшое — заголовки, вложенные списки, таблицы GFM, цитаты,
 * код и четыре формы формул. HTML не распознаётся вовсе: `<script>` остаётся
 * текстом, поэтому рендер никогда не вставляет разметку модели.
 */

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "strong" | "em" | "del"; children: Inline[] }
  | { kind: "code"; text: string }
  | { kind: "math"; tex: string; display: boolean }
  | { kind: "link"; href: string; children: Inline[] }
  | { kind: "image"; alt: string; url: string }
  | { kind: "citation"; ids: string[] };

export type TableAlign = "left" | "center" | "right" | null;

export interface ListItem {
  blocks: Block[];
}

export type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; start: number; tight: boolean; items: ListItem[] }
  | { kind: "quote"; blocks: Block[] }
  /** `open` — блок кода ещё не закрыт: так бывает посреди потока. */
  | { kind: "code"; lang: string; text: string; open: boolean }
  /** `open` — выносная формула не закрыта; рисуется исходным текстом. */
  | { kind: "math"; tex: string; open: boolean }
  | { kind: "table"; align: TableAlign[]; head: string[]; rows: string[][] }
  | { kind: "rule" };

/** Верхний блок с исходным текстом — ключ мемоизации при потоке. */
export interface SourceBlock {
  block: Block;
  source: string;
}

const HEADING = /^(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$/;
const FENCE = /^(`{3,}|~{3,})[ \t]*([\w+-]*)/;
const RULE = /^(?:\*[ \t]*){3,}$|^(?:-[ \t]*){3,}$|^(?:_[ \t]*){3,}$/;
const QUOTE = /^[ \t]{0,3}>[ \t]?(.*)$/;
const LIST_ITEM = /^([ \t]*)([-*+]|\d{1,9}[.)])[ \t]+(.*)$/;
const EMPTY_ITEM = /^([ \t]*)([-*+]|\d{1,9}[.)])[ \t]*$/;
const TABLE_DIVIDER = /^[ \t]*\|?[ \t]*:?-+:?[ \t]*(\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$/;
/** Пустая строка, которую пишет Crepe вместо пустого абзаца. */
const CREPE_BREAK = /^<br\s*\/?>$/i;
const MATH_FENCES = new Set(["latex", "math", "tex", "katex"]);

function indentOf(line: string): number {
  let width = 0;
  for (const character of line) {
    if (character === " ") width += 1;
    else if (character === "\t") width += 4 - (width % 4);
    else break;
  }
  return width;
}

/** Снять до `width` колонок отступа, считая табуляцию по четыре. */
function dedent(line: string, width: number): string {
  let removed = 0;
  let index = 0;
  while (index < line.length && removed < width) {
    const character = line[index];
    if (character === " ") removed += 1;
    else if (character === "\t") removed += 4 - (removed % 4);
    else break;
    index += 1;
  }
  return line.slice(index);
}

const isBlank = (line: string) => line.trim() === "" || CREPE_BREAK.test(line.trim());

const TABLE_MATH = /\$\$[\s\S]+?\$\$|\$(?=\S)(?:[^$\\\n]|\\.)+?(?<=\S)\$(?!\d)/g;

/**
 * Ячейки строки Markdown-таблицы.
 *
 * Обратный слеш снимается только перед `|` (экранированная черта в ячейке):
 * прежде он снимался всегда, и `$A\wedge B$` приезжал в ячейку как
 * `$Awedge B$`. Черта внутри `$…$` — модуль или «такой, что», а не граница
 * ячейки: модели пишут `$|x|$` без экранирования. Формула узнаётся по правилу
 * Pandoc (после открывающего `$` и перед закрывающим — не пробел, за
 * закрывающим — не цифра), чтобы «Цена, $» и «$5 | $10» остались текстом.
 */
export function splitMarkdownRow(row: string): string[] {
  const cells: string[] = [];
  let cell = "";
  const source = row.trim().replace(/^\|/, "").replace(/(?<!\\)\|$/, "");
  const math: [number, number][] = [];
  for (const match of source.matchAll(TABLE_MATH)) {
    math.push([match.index, match.index + match[0].length]);
  }
  const inMath = (position: number) =>
    math.some(([start, end]) => position > start && position < end);
  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    if (character === "\\" && source[index + 1] === "|") {
      cell += "|";
      index += 1;
    } else if (character === "|" && !inMath(index)) {
      cells.push(cell.trim());
      cell = "";
    } else {
      cell += character;
    }
  }
  cells.push(cell.trim());
  return cells;
}

function tableAlign(cell: string): TableAlign {
  const left = cell.startsWith(":");
  const right = cell.endsWith(":");
  if (left && right) return "center";
  if (right) return "right";
  if (left) return "left";
  return null;
}

/** Начинает ли строка новый блок — тогда она не продолжает абзац. */
function startsBlock(line: string, next: string | undefined): boolean {
  const trimmed = line.trimStart();
  return (
    HEADING.test(trimmed) ||
    FENCE.test(trimmed) ||
    RULE.test(trimmed) ||
    QUOTE.test(line) ||
    LIST_ITEM.test(line) ||
    trimmed.startsWith("$$") ||
    trimmed.startsWith("\\[") ||
    (line.includes("|") && next !== undefined && TABLE_DIVIDER.test(next) && next.includes("-"))
  );
}

/**
 * Где закрывается выносная формула, открытая на строке `start`.
 * Возвращает индекс строки с закрывающим разделителем или -1.
 */
function findMathClose(lines: string[], start: number, rest: string, close: string): number {
  if (rest.includes(close)) return start;
  for (let index = start + 1; index < lines.length; index += 1) {
    if (lines[index].includes(close)) return index;
  }
  return -1;
}

function parseLines(lines: string[], topLevel: SourceBlock[] | null): Block[] {
  const blocks: Block[] = [];
  let index = 0;
  const push = (block: Block, from: number, to: number) => {
    blocks.push(block);
    topLevel?.push({ block, source: lines.slice(from, to).join("\n") });
  };

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();
    const from = index;

    if (isBlank(line)) {
      index += 1;
      continue;
    }

    const fence = FENCE.exec(trimmed);
    if (fence && indentOf(line) < 4) {
      const marker = fence[1];
      const lang = fence[2].toLowerCase();
      const body: string[] = [];
      index += 1;
      let open = true;
      while (index < lines.length) {
        const candidate = lines[index].trim();
        if (candidate.startsWith(marker) && candidate.replace(/[`~]/g, "") === "") {
          open = false;
          index += 1;
          break;
        }
        body.push(lines[index]);
        index += 1;
      }
      const text = body.join("\n");
      push(
        MATH_FENCES.has(lang) ? { kind: "math", tex: text, open } : { kind: "code", lang, text, open },
        from,
        index,
      );
      continue;
    }

    // Выносная формула: `$$…$$` и `\[…\]` — на одной строке или на нескольких.
    const displayOpen = trimmed.startsWith("$$") ? "$$" : trimmed.startsWith("\\[") ? "\\[" : null;
    if (displayOpen) {
      const close = displayOpen === "$$" ? "$$" : "\\]";
      const rest = trimmed.slice(2);
      const end = findMathClose(lines, index, rest, close);
      // Незакрытый `\[` чаще экранированная скобка, чем формула; `$$` — поток.
      if (end === -1 && displayOpen === "\\[") {
        index = parseParagraph(lines, index, push);
        continue;
      }
      if (end === -1) {
        push({ kind: "math", tex: [rest, ...lines.slice(index + 1)].join("\n").trim(), open: true }, from, lines.length);
        index = lines.length;
        continue;
      }
      const joined = end === index ? rest : [rest, ...lines.slice(index + 1, end + 1)].join("\n");
      const closeAt = joined.lastIndexOf(close);
      const after = joined.slice(closeAt + close.length).trim();
      // `$$a$$ и $$b$$` в одной строке — это текст абзаца с формулами, не блок.
      if (end === index && after) {
        index = parseParagraph(lines, index, push);
        continue;
      }
      push({ kind: "math", tex: joined.slice(0, closeAt).trim(), open: false }, from, end + 1);
      index = end + 1;
      continue;
    }

    const heading = HEADING.exec(trimmed);
    if (heading && indentOf(line) < 4) {
      push({ kind: "heading", level: heading[1].length, text: heading[2] }, from, index + 1);
      index += 1;
      continue;
    }

    if (RULE.test(trimmed) && indentOf(line) < 4) {
      push({ kind: "rule" }, from, index + 1);
      index += 1;
      continue;
    }

    if (QUOTE.test(line)) {
      const body: string[] = [];
      while (index < lines.length) {
        const quoted = QUOTE.exec(lines[index]);
        if (!quoted) break;
        body.push(quoted[1]);
        index += 1;
      }
      push({ kind: "quote", blocks: parseLines(body, null) }, from, index);
      continue;
    }

    const next = lines[index + 1];
    if (line.includes("|") && next !== undefined && TABLE_DIVIDER.test(next) && next.includes("-")) {
      const head = splitMarkdownRow(line);
      const align = splitMarkdownRow(next).map(tableAlign);
      if (head.length === align.length && head.length > 1) {
        const rows: string[][] = [];
        index += 2;
        while (index < lines.length && lines[index].includes("|") && !isBlank(lines[index])) {
          const cells = splitMarkdownRow(lines[index]);
          rows.push(head.map((_, cell) => cells[cell] ?? ""));
          index += 1;
        }
        push({ kind: "table", align, head, rows }, from, index);
        continue;
      }
    }

    if (LIST_ITEM.test(line) || EMPTY_ITEM.test(line)) {
      index = parseList(lines, index, push);
      continue;
    }

    index = parseParagraph(lines, index, push);
  }
  return blocks;
}

function parseParagraph(
  lines: string[],
  start: number,
  push: (block: Block, from: number, to: number) => void,
): number {
  const body = [lines[start].trim()];
  let index = start + 1;
  while (index < lines.length && !isBlank(lines[index]) && !startsBlock(lines[index], lines[index + 1])) {
    body.push(lines[index].trim());
    index += 1;
  }
  push({ kind: "paragraph", text: body.join("\n") }, start, index);
  return index;
}

/**
 * Список одного уровня: пункты с тем же отступом маркера и того же вида.
 *
 * Всё, что отступлено глубже маркера, принадлежит текущему пункту и
 * разбирается рекурсивно — так вложенные списки, код и формулы внутри пункта
 * получаются сами. Пустые строки между пунктами список не рвут: раньше каждый
 * пункт после пустой строки начинал новый `<ol>` и нумерация сбрасывалась в 1.
 */
function parseList(
  lines: string[],
  start: number,
  push: (block: Block, from: number, to: number) => void,
): number {
  const first = LIST_ITEM.exec(lines[start]) ?? EMPTY_ITEM.exec(lines[start])!;
  const markerIndent = indentOf(first[1]);
  const ordered = /\d/.test(first[2]);
  const startNumber = ordered ? Number.parseInt(first[2], 10) : 1;
  const items: ListItem[] = [];
  let tight = true;
  let index = start;

  while (index < lines.length) {
    const match = LIST_ITEM.exec(lines[index]) ?? EMPTY_ITEM.exec(lines[index]);
    if (!match || indentOf(match[1]) !== markerIndent || /\d/.test(match[2]) !== ordered) break;
    const contentIndent = Math.min(markerIndent + match[2].length + 1, markerIndent + 4);
    const body = [match[3] ?? ""];
    index += 1;
    let sawBlank = false;
    while (index < lines.length) {
      const line = lines[index];
      if (isBlank(line)) {
        sawBlank = true;
        body.push("");
        index += 1;
        continue;
      }
      const indent = indentOf(line);
      if (indent > markerIndent) {
        body.push(dedent(line, Math.min(indent, contentIndent)));
        sawBlank = false;
        index += 1;
        continue;
      }
      // Ленивое продолжение: строка без отступа сразу после текста пункта.
      if (!sawBlank && !startsBlock(line, lines[index + 1])) {
        body.push(line.trim());
        index += 1;
        continue;
      }
      break;
    }
    while (body.length && !body[body.length - 1].trim()) body.pop();
    items.push({ blocks: parseLines(body, null) });
    if (sawBlank && index < lines.length) {
      const nextItem = LIST_ITEM.exec(lines[index]);
      if (nextItem && indentOf(nextItem[1]) === markerIndent && /\d/.test(nextItem[2]) === ordered) tight = false;
    }
  }
  push({ kind: "list", ordered, start: startNumber, tight, items }, start, index);
  return index;
}

/** Разбор блоков; `sources` получает верхние блоки с исходным текстом. */
export function parseMarkdown(text: string, sources?: SourceBlock[]): Block[] {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  return parseLines(lines, sources ?? null);
}

// ---------------------------------------------------------------- инлайн

const ESCAPABLE = "\\`*_{}[]()#+-.!$>|~<\"'";
const CITATION = /^\[(S\d+(?:[ \t]*[,;][ \t]*S\d+)*)\]/;
const LINK = /^\[((?:[^\]\\]|\\.)*)\]\(([^)\s]+)(?:[ \t]+"[^"]*")?\)/;
const IMAGE = /^!\[((?:[^\]\\]|\\.)*)\]\(([^)\s]*)(?:[ \t]+"[^"]*")?\)/;

/** `$…$` по правилу Pandoc: не пробел после открывающего и перед закрывающим, за закрывающим не цифра. */
function inlineDollar(text: string, at: number): number {
  const first = text[at + 1];
  if (first === undefined || /\s/.test(first) || first === "$") return -1;
  for (let index = at + 1; index < text.length; index += 1) {
    const character = text[index];
    if (character === "\\") {
      index += 1;
      continue;
    }
    if (character === "\n" && text[index + 1] === "\n") return -1;
    if (character !== "$") continue;
    if (/\s/.test(text[index - 1]) || /\d/.test(text[index + 1] ?? "")) return -1;
    return index;
  }
  return -1;
}

/** Закрывающий разделитель выделения; код и формулы внутри пропускаются. */
function findClosing(text: string, from: number, marker: string): number {
  for (let index = from; index < text.length; index += 1) {
    const character = text[index];
    if (character === "\\") {
      index += 1;
      continue;
    }
    if (character === "`") {
      const end = text.indexOf("`", index + 1);
      if (end === -1) return -1;
      index = end;
      continue;
    }
    if (character === "$") {
      const end = inlineDollar(text, index);
      if (end !== -1) {
        index = end;
        continue;
      }
    }
    if (text.startsWith(marker, index) && index > from && !/\s/.test(text[index - 1])) {
      // `**` не закрывает `*`: одиночный маркер ищет одиночный.
      if (marker.length === 1 && text[index + 1] === marker) {
        index += 1;
        continue;
      }
      return index;
    }
  }
  return -1;
}

const isWordCharacter = (character: string | undefined) =>
  character !== undefined && /[\p{L}\p{N}]/u.test(character);

export function parseInline(text: string): Inline[] {
  const result: Inline[] = [];
  let buffer = "";
  const flush = () => {
    if (buffer) result.push({ kind: "text", text: buffer });
    buffer = "";
  };
  const emit = (node: Inline) => {
    flush();
    result.push(node);
  };

  let index = 0;
  while (index < text.length) {
    const character = text[index];
    const rest = text.slice(index);

    if (character === "\\") {
      const next = text[index + 1];
      const close = next === "(" ? "\\)" : next === "[" ? "\\]" : null;
      if (close) {
        const end = text.indexOf(close, index + 2);
        if (end !== -1) {
          emit({ kind: "math", tex: text.slice(index + 2, end).trim(), display: next === "[" });
          index = end + 2;
          continue;
        }
      }
      if (next !== undefined && ESCAPABLE.includes(next)) {
        buffer += next;
        index += 2;
        continue;
      }
      if (next === "\n") {
        buffer += "\n";
        index += 2;
        continue;
      }
      buffer += character;
      index += 1;
      continue;
    }

    if (character === "`") {
      const run = /^`+/.exec(rest)![0];
      const end = text.indexOf(run, index + run.length);
      if (end !== -1) {
        emit({ kind: "code", text: text.slice(index + run.length, end).replace(/^ (.+) $/, "$1") });
        index = end + run.length;
        continue;
      }
      buffer += run;
      index += run.length;
      continue;
    }

    if (rest.startsWith("$$")) {
      const end = text.indexOf("$$", index + 2);
      if (end !== -1 && end > index + 2) {
        emit({ kind: "math", tex: text.slice(index + 2, end).trim(), display: true });
        index = end + 2;
        continue;
      }
    }

    if (character === "$") {
      const end = inlineDollar(text, index);
      if (end !== -1) {
        emit({ kind: "math", tex: text.slice(index + 1, end), display: false });
        index = end + 1;
        continue;
      }
    }

    if (character === "!" && rest.startsWith("![")) {
      const image = IMAGE.exec(rest);
      if (image) {
        emit({ kind: "image", alt: image[1].replace(/\\(.)/g, "$1"), url: image[2] });
        index += image[0].length;
        continue;
      }
    }

    if (character === "[") {
      const citation = CITATION.exec(rest);
      if (citation) {
        emit({ kind: "citation", ids: citation[1].split(/[ \t]*[,;][ \t]*/) });
        index += citation[0].length;
        continue;
      }
      const link = LINK.exec(rest);
      if (link) {
        emit({ kind: "link", href: link[2], children: parseInline(link[1]) });
        index += link[0].length;
        continue;
      }
    }

    const emphasis =
      rest.startsWith("**") ? "**" : rest.startsWith("__") ? "__" : rest.startsWith("~~") ? "~~"
        : character === "*" || character === "_" ? character : null;
    if (emphasis) {
      const opensWord = !/\s/.test(text[index + emphasis.length] ?? " ");
      // `snake_case` и `2*3*4` — не курсив: `_` внутри слова ничего не открывает.
      const intraword = emphasis.startsWith("_") && isWordCharacter(text[index - 1]);
      if (opensWord && !intraword) {
        const end = findClosing(text, index + emphasis.length, emphasis);
        const closesWord = end !== -1 && !(emphasis.startsWith("_") && isWordCharacter(text[end + emphasis.length]));
        if (end !== -1 && closesWord) {
          const kind = emphasis === "~~" ? "del" : emphasis.length === 2 ? "strong" : "em";
          emit({ kind, children: parseInline(text.slice(index + emphasis.length, end)) });
          index = end + emphasis.length;
          continue;
        }
      }
      buffer += emphasis;
      index += emphasis.length;
      continue;
    }

    buffer += character;
    index += 1;
  }
  flush();
  return result;
}

/** Все S-ID, на которые ссылается текст, — для отметки «использован в ответе». */
export function citedIds(text: string): Set<string> {
  const ids = new Set<string>();
  const visit = (nodes: Inline[]) => {
    for (const node of nodes) {
      if (node.kind === "citation") node.ids.forEach((id) => ids.add(id));
      else if (node.kind === "strong" || node.kind === "em" || node.kind === "del" || node.kind === "link") visit(node.children);
    }
  };
  const walk = (blocks: Block[]) => {
    for (const block of blocks) {
      if (block.kind === "heading" || block.kind === "paragraph") visit(parseInline(block.text));
      else if (block.kind === "list") block.items.forEach((item) => walk(item.blocks));
      else if (block.kind === "quote") walk(block.blocks);
      else if (block.kind === "table") [block.head, ...block.rows].flat().forEach((cell) => visit(parseInline(cell)));
    }
  };
  walk(parseMarkdown(text));
  return ids;
}
