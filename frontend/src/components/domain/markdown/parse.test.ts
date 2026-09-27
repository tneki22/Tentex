import assert from "node:assert/strict";
import test from "node:test";

import { citedIds, parseInline, parseMarkdown, type Block, type Inline } from "./parse";

const kinds = (blocks: Block[]) => blocks.map((block) => block.kind);
const only = <T extends Block["kind"]>(blocks: Block[], kind: T) =>
  blocks.filter((block): block is Extract<Block, { kind: T }> => block.kind === kind);
const maths = (nodes: Inline[]) =>
  nodes.filter((node): node is Extract<Inline, { kind: "math" }> => node.kind === "math");
const plain = (nodes: Inline[]) => nodes.map((node) => (node.kind === "text" ? node.text : `<${node.kind}>`)).join("");

// Типичный ответ модели в режиме «Разобраться»: прежний рендер терял `#`/`##`,
// сбрасывал нумерацию после пустой строки, склеивал вложенный список с
// родителем и показывал таблицу и формулы сырым текстом.
const MODEL_ANSWER = `# Нормальные формы

## Первая нормальная форма

1. **Атомарность.** Каждое поле хранит одно значение [S1].

2. Нет повторяющихся групп:
   - строки различимы по ключу;
   - порядок строк не важен [S2, S3].

3. Функциональная зависимость $X \\to Y$ выполняется, если
   \\[ t_1[X] = t_2[X] \\Rightarrow t_1[Y] = t_2[Y] \\]

| Форма | Условие | Пример |
|:------|:-------:|-------:|
| 1НФ | атомарность | $|R| = n$ |
| 2НФ | нет частичных зависимостей | \\(A \\to B\\) |

Итог:
$$
\\sum_{i=1}^{n} x_i
$$`;

test("ответ модели: заголовки, сквозная нумерация, вложенный список, таблица, формулы", () => {
  const blocks = parseMarkdown(MODEL_ANSWER);
  assert.deepEqual(kinds(blocks), ["heading", "heading", "list", "table", "paragraph", "math"]);
  assert.deepEqual(only(blocks, "heading").map((block) => block.level), [1, 2]);

  const [list] = only(blocks, "list");
  assert.equal(list.ordered, true);
  assert.equal(list.items.length, 3, "пустые строки между пунктами не рвут список");
  assert.equal(list.tight, false);
  assert.deepEqual(kinds(list.items[1].blocks), ["paragraph", "list"]);
  const nested = list.items[1].blocks[1] as Extract<Block, { kind: "list" }>;
  assert.equal(nested.ordered, false);
  assert.equal(nested.items.length, 2);
  assert.deepEqual(kinds(list.items[2].blocks), ["paragraph", "math"], "формула \\[…\\] внутри пункта");

  const [table] = only(blocks, "table");
  assert.deepEqual(table.align, ["left", "center", "right"]);
  assert.deepEqual(table.head, ["Форма", "Условие", "Пример"]);
  assert.equal(table.rows[0][2], "$|R| = n$", "черта внутри формулы не делит ячейку");
  assert.equal(maths(parseInline(table.rows[1][2]))[0].tex, "A \\to B");

  const [display] = only(blocks, "math");
  assert.equal(display.tex, "\\sum_{i=1}^{n} x_i");
  assert.equal(display.open, false);
  assert.deepEqual([...citedIds(MODEL_ANSWER)].sort(), ["S1", "S2", "S3"]);
});

test("четыре формы формул", () => {
  const nodes = parseInline("a $x^2$ b \\(y_1\\) c $$\\frac{1}{2}$$ d \\[z\\]");
  assert.deepEqual(
    maths(nodes).map((node) => [node.tex, node.display]),
    [["x^2", false], ["y_1", false], ["\\frac{1}{2}", true], ["z", true]],
  );
  const blocks = parseMarkdown("\\[\n\\int_0^1 f\n\\]\n\n$$ a+b $$");
  assert.deepEqual(only(blocks, "math").map((block) => block.tex), ["\\int_0^1 f", "a+b"]);
});

test("доллар как валюта, экранированный доллар и доллар в коде остаются текстом", () => {
  assert.equal(maths(parseInline("стоит от 5 $ до 10 $ за штуку")).length, 0);
  assert.equal(maths(parseInline("цены $5 и $10")).length, 0);
  assert.equal(plain(parseInline("\\$x\\$ не формула")), "$x$ не формула");
  const code = parseInline("код `echo $HOME$` тут");
  assert.equal(maths(code).length, 0);
  assert.deepEqual(code[1], { kind: "code", text: "echo $HOME$" });
  const fenced = parseMarkdown("```bash\necho $x$\n```");
  assert.deepEqual(fenced, [{ kind: "code", lang: "bash", text: "echo $x$", open: false }]);
});

test("незакрытые формула и код посреди потока показываются исходником", () => {
  const stream = parseMarkdown("Считаем:\n\n$$\n\\sum_{i=1}");
  assert.deepEqual(stream.at(-1), { kind: "math", tex: "\\sum_{i=1}", open: true });
  assert.equal(maths(parseInline("начало $x^")).length, 0);
  assert.deepEqual(parseMarkdown("```python\nprint(1)").at(-1), { kind: "code", lang: "python", text: "print(1)", open: true });
  assert.deepEqual(kinds(parseMarkdown("\\[скобка без пары")), ["paragraph"]);
});

test("нумерация: номер первого пункта сохраняется, другой вид маркера — новый список", () => {
  const blocks = parseMarkdown("3. третий\n4. четвёртый\n\n- маркер\n\n5) пятый");
  const lists = only(blocks, "list");
  assert.deepEqual(lists.map((list) => [list.ordered, list.start, list.items.length]), [
    [true, 3, 2], [false, 1, 1], [true, 5, 1],
  ]);
  assert.equal(lists[0].tight, true);
});

test("вложенность списков при отступе 2, 3 и 4 пробела и табуляции", () => {
  for (const indent of ["  ", "   ", "    ", "\t"]) {
    const [list] = only(parseMarkdown(`- a\n${indent}- b\n${indent}${indent}- c\n- d`), "list");
    assert.equal(list.items.length, 2, JSON.stringify(indent));
    const inner = list.items[0].blocks[1] as Extract<Block, { kind: "list" }>;
    assert.equal(inner.items.length, 1);
    assert.equal(inner.items[0].blocks[1]?.kind, "list", `третий уровень при ${JSON.stringify(indent)}`);
  }
});

test("ленивое продолжение пункта и абзац после списка", () => {
  const blocks = parseMarkdown("1. первая строка\nпродолжение\n\nАбзац после списка.");
  assert.deepEqual(kinds(blocks), ["list", "paragraph"]);
  const [list] = only(blocks, "list");
  assert.equal((list.items[0].blocks[0] as { text: string }).text, "первая строка\nпродолжение");
});

test("цитаты S-ID во всех формах, неизвестная разметка — текст", () => {
  const nodes = parseInline("да [S1], [S2, S4]; [S5][S6] и [S7; S8] но не [см. S9]");
  assert.deepEqual(
    nodes.filter((node) => node.kind === "citation").map((node) => (node as { ids: string[] }).ids),
    [["S1"], ["S2", "S4"], ["S5"], ["S6"], ["S7", "S8"]],
  );
  assert.equal(parseInline("`[S1]`")[0].kind, "code", "внутри кода цитата не распознаётся");
  assert.equal(plain(parseInline("<script>alert(1)</script>")), "<script>alert(1)</script>");
});

test("выделение: вложенное, внутри слова подчёркивание — не курсив", () => {
  const nodes = parseInline("**жирный *курсив* внутри** и ~~зачёркнутый~~ и snake_case_name и 2 * 3 * 4");
  assert.deepEqual(nodes.map((node) => node.kind), ["strong", "text", "del", "text"]);
  const strong = nodes[0] as { children: Inline[] };
  assert.deepEqual(strong.children.map((node) => node.kind), ["text", "em", "text"]);
  assert.match(plain(nodes), /snake_case_name и 2 \* 3 \* 4/);
});

test("ссылки и картинки; цитата и горизонтальная линия", () => {
  const nodes = parseInline("[документация](https://example.com) и ![схема](/api/x.png)");
  assert.equal(nodes[0].kind, "link");
  assert.deepEqual(nodes[2], { kind: "image", alt: "схема", url: "/api/x.png" });
  const blocks = parseMarkdown("> цитата\n> вторая строка\n\n---\n\nтекст");
  assert.deepEqual(kinds(blocks), ["quote", "rule", "paragraph"]);
});

test("пояснение урока из Crepe: <br />, экранирование и выносная формула в fence", () => {
  const blocks = parseMarkdown("Первый абзац\n\n<br />\n\nВторой \\*не курсив\\* 1\\. пункт\n\n```latex\nE = mc^2\n```");
  assert.deepEqual(kinds(blocks), ["paragraph", "paragraph", "math"]);
  assert.equal(plain(parseInline((blocks[1] as { text: string }).text)), "Второй *не курсив* 1. пункт");
});
