/** Рендер ответа чата: Markdown, формулы, цитаты и источники на подставленном API. */
import { expect, test } from "@playwright/test";
import { BASE, PROJECT, installChatStub, message, source, sse } from "./chat-stub";

const ANSWER = String.raw`# Нормальные формы

## Первая нормальная форма

1. **Атомарность.** Каждое поле хранит одно значение [S1].

2. Нет повторяющихся групп:
   - строки различимы по ключу;
   - порядок строк не важен [S2].

3. Зависимость $X \to Y$ и \(A \subseteq B\).

| Форма | Условие |
|:------|:-------:|
| 1НФ | $|R| = n$ |
| 2НФ | нет частичных зависимостей |

$$
\sum_{i=1}^{n} x_i = \frac{a}{b}
$$

\[ E = mc^2 \]

Цена от 5 $ до 10 $, а тут \frac{битая формула $\frac{1}{$.`;

const SOURCES = [
  source("S1", "Атомарность: значение поля неделимо."),
  source("S2", "Порядок строк в отношении не важен.", { locator: "стр. 14–15", page: 14 }),
  source("S3", "Функциональная зависимость — ограничение.", { warning: "Распознано с ошибками" }),
];

test("ответ модели: заголовки, нумерация, вложенный список, таблица и четыре формы формул", async ({ page }) => {
  await installChatStub(page, { messages: [message("user", "Что такое 1НФ?"), message("examiner", ANSWER, SOURCES)] });
  await page.goto(`${BASE}/projects/${PROJECT}`);
  const answer = page.locator(".chat-bubble.is-examiner .chat-markdown");
  await expect(answer).toBeVisible();

  await expect(answer.getByRole("heading", { name: "Нормальные формы" })).toBeVisible();
  await expect(answer.locator(".md-h2")).toHaveText("Первая нормальная форма");
  const ordered = answer.locator(":scope > ol");
  await expect(ordered).toHaveCount(1);
  await expect(ordered.locator(":scope > li")).toHaveCount(3);
  await expect(ordered.locator(":scope > li").nth(1).locator("ul > li")).toHaveCount(2);

  const table = answer.locator(".md-table");
  await expect(table.locator("th")).toHaveText(["Форма", "Условие"]);
  await expect(table.locator("tbody tr").first().locator(".katex")).toHaveCount(1);

  // $…$, \(…\), $|R|$ в таблице — строчные; $$…$$ и \[…\] — выносные.
  await expect(answer.locator(".md-math-inline .katex")).toHaveCount(3);
  await expect(answer.locator(".md-math-display .katex-display")).toHaveCount(2);
  await expect(answer).toContainText("Цена от 5 $ до 10 $");
  await expect(answer.locator(".md-math-source.is-error")).toHaveCount(1);

  // Доступное представление: у каждой формулы есть MathML.
  await expect(answer.locator(".katex-mathml math")).toHaveCount(5);
  await page.screenshot({ path: "test-results/chat-render-light.png", fullPage: true });
});

test("цитата открывает окно справа от ссылки; Escape, клик снаружи и другая цитата закрывают", async ({ page }) => {
  await installChatStub(page, { messages: [message("user", "Что такое 1НФ?"), message("examiner", ANSWER, SOURCES)] });
  await page.goto(`${BASE}/projects/${PROJECT}`);
  const first = page.getByRole("button", { name: "Источник S1: Лекции по базам данных" });
  await first.click();
  const preview = page.locator(".popover-citation");
  await expect(preview).toBeVisible();
  await expect(preview).toContainText("Атомарность: значение поля неделимо.");
  await expect(preview).toContainText("Нормальные формы · стр. 12");
  await expect(preview.getByRole("link", { name: /Открыть в просмотрщике/ })).toHaveAttribute("href", /\?page=12$/);
  const trigger = await first.boundingBox();
  const box = await preview.boundingBox();
  expect(box!.x).toBeGreaterThan(trigger!.x + trigger!.width - 1);

  await page.keyboard.press("Escape");
  await expect(preview).toHaveCount(0);

  await first.click();
  await expect(preview).toBeVisible();
  await page.getByRole("button", { name: "Источник S2: Лекции по базам данных" }).click();
  await expect(page.locator(".popover-citation")).toHaveCount(1);
  await expect(page.locator(".popover-citation")).toContainText("Порядок строк");

  await page.locator(".md-h1").click();
  await expect(page.locator(".popover-citation")).toHaveCount(0);
});

test("«Источники · N» свёрнут, раскрывается списком и отмечает использованные", async ({ page }) => {
  await installChatStub(page, { messages: [message("user", "Что такое 1НФ?"), message("examiner", ANSWER, SOURCES)] });
  await page.goto(`${BASE}/projects/${PROJECT}`);
  const block = page.locator(".chat-sources");
  await expect(block.locator("summary")).toHaveText("Источники · 3");
  await expect(block.locator("li").first()).toBeHidden();
  await block.locator("summary").click();
  await expect(block.locator("li")).toHaveCount(3);
  await expect(block.locator("li.is-cited")).toHaveCount(2);
  await expect(block.locator("li").nth(1)).toContainText("стр. 14–15");
});

test("ссылки работают во время потока: источники приходят в кадре started", async ({ page }) => {
  const streamed = source("S1", "Кадр started несёт источники.");
  await installChatStub(page, {
    messages: [],
    onSend: () => ({
      // Поток обрывается до completed — ссылки держатся только на кадре started.
      sse: sse([
        ["started", { message_id: "live-1", user_message_id: "user-1", run_id: "run-1", sources: [streamed] }],
        ["delta", { text: "Частичный ответ [S1] и формула $a^2" }],
      ]),
    }),
  });
  await page.goto(`${BASE}/projects/${PROJECT}`);
  const composer = page.getByRole("textbox").last();
  await composer.fill("Объясни");
  await composer.press("Enter");
  const citation = page.getByRole("button", { name: /Источник S1/ });
  await expect(citation).toBeVisible();
  await expect(page.locator(".chat-bubble.is-examiner")).toContainText("формула $a^2");
  await citation.click();
  await expect(page.locator(".popover-citation")).toContainText("Кадр started несёт источники.");
});

test("тёмная тема: ответ, таблица и окно цитаты читаются", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await installChatStub(page, { messages: [message("user", "Что такое 1НФ?"), message("examiner", ANSWER, SOURCES)] });
  await page.goto(`${BASE}/projects/${PROJECT}`);
  await page.getByRole("button", { name: "Источник S1: Лекции по базам данных" }).click();
  await expect(page.locator(".popover-citation")).toBeVisible();
  await page.screenshot({ path: "test-results/chat-render-dark.png", fullPage: true });
});
