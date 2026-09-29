import assert from "node:assert/strict";
import test from "node:test";

import { guideOutline, parseGuideDocument } from "./guideDocument";

test("заголовок ## становится секцией с якорем, id задаётся вручную", () => {
  const blocks = parseGuideDocument("Вступление.\n\n## Первое {#one}\n\nТекст.\n\n## Второе\n");
  assert.deepEqual(blocks.map((block) => block.kind), ["md", "heading", "md", "heading"]);
  assert.deepEqual(guideOutline(blocks), [
    { id: "one", title: "Первое" },
    { id: "section-2", title: "Второе" },
  ]);
});

test("врезка забирает тело до закрывающих :::, название необязательно", () => {
  const [callout, bare] = parseGuideDocument(":::warning Осторожно\nТекст **важный**.\n:::\n:::info\nбез названия\n:::");
  assert.deepEqual(callout, { kind: "callout", tone: "warning", title: "Осторожно", text: "Текст **важный**." });
  assert.equal(bare.kind === "callout" && bare.title, null);
});

test("карточки: заголовок с иконкой и ссылкой, остальное — описание", () => {
  const [block] = parseGuideDocument(":::cards\n[FolderPlus] Экзамен → /projects/new\nЕсть вопросы.\nИ ответы.\n\nПросто карточка\n:::");
  assert.equal(block.kind, "cards");
  if (block.kind !== "cards") return;
  assert.deepEqual(block.cards[0], { icon: "FolderPlus", title: "Экзамен", to: "/projects/new", text: "Есть вопросы. И ответы." });
  assert.deepEqual(block.cards[1], { icon: null, title: "Просто карточка", to: null, text: "" });
});

test("рисунок: первая строка — картинка, дальше подпись", () => {
  const [figure] = parseGuideDocument(":::figure\n![Экран проектов](projects.png)\nСписок проектов.\n:::");
  assert.deepEqual(figure, { kind: "figure", alt: "Экран проектов", src: "projects.png", caption: "Список проектов." });
});

test("внутри блока кода ни заголовки, ни контейнеры не разбираются", () => {
  const blocks = parseGuideDocument("```\n## не заголовок\n:::info\n```\n");
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].kind, "md");
});

test("неизвестный контейнер остаётся обычным текстом", () => {
  const blocks = parseGuideDocument(":::mystery\nтекст\n:::");
  assert.equal(blocks[0].kind, "md");
});
