/** Операции учебного чата: явное поле, повтор того же хода, пустая область темы. */
import { expect, test } from "@playwright/test";
import { BASE, PROJECT, installChatStub, source, sse } from "./chat-stub";

function answer(id: string, text: string) {
  return sse([
    ["started", { message_id: id, user_message_id: `u-${id}`, run_id: "run", sources: [source("S1", "Место")] }],
    ["delta", { text }],
  ]);
}

test("в учебном чате нет выбора режима, а глубина предлагает новые пределы", async ({ page }) => {
  await installChatStub(page);
  await page.goto(`${BASE}/projects/${PROJECT}`);

  await expect(page.getByRole("group", { name: "Режим чата" })).toHaveCount(0);
  await page.getByRole("button", { name: /Глубина ответа/ }).click();
  await expect(page.locator(".chat-depth-options button")).toHaveText([
    "КраткоСуть и ключевые выводы · до 1000 токенов",
    "ОбычноОбъяснение с примерами · до 2000 токенов",
    "ПодробноШаги, связи и ограничения · до 4000 токенов",
  ]);
  await page.screenshot({ path: "test-results/chat-study-controls.png" });
});

test("кнопка операции уходит полем operation, а не словами в тексте, и сбрасывается после отправки", async ({ page }) => {
  const stub = await installChatStub(page, { onSend: () => ({ sse: answer("a1", "Сравнение [S1]") }) });
  await page.goto(`${BASE}/projects/${PROJECT}`);
  await page.getByText("Контекст и поиск").click();
  const compare = page.getByRole("button", { name: "Сравнить источники" });
  await compare.click();
  await expect(compare).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".chat-composer-operation")).toHaveText("Сравнить источники");

  const composer = page.getByRole("textbox").last();
  await composer.fill("нормальные формы");
  await composer.press("Enter");
  await expect(page.locator(".chat-bubble.is-examiner")).toContainText("Сравнение");

  expect(stub.sent[0]).toMatchObject({ text: "нормальные формы", operation: "compare_sources", retrieval_scope: "project" });
  await expect(page.locator(".chat-composer-operation")).toHaveCount(0);
});

test("«Повторить» после сбоя отправляет тот же ход: операцию, область и политику", async ({ page }) => {
  let calls = 0;
  const stub = await installChatStub(page, {
    onSend: () => {
      calls += 1;
      return calls === 1
        ? { status: 503, json: { code: "ai_provider_unavailable", detail: "Провайдер недоступен" } }
        : { sse: answer("a2", "Готово [S1]") };
    },
  });
  await page.goto(`${BASE}/projects/${PROJECT}`);
  await page.getByText("Контекст и поиск").click();
  await page.getByRole("button", { name: "Найти расхождения" }).click();
  await page.getByRole("switch", { name: /Знания модели/ }).click();
  const composer = page.getByRole("textbox").last();
  await composer.fill("функциональные зависимости");
  await composer.press("Enter");

  // Сервер ход не записал: реплики в ленте нет, текст вернулся в поле.
  await expect(page.getByRole("button", { name: "Повторить" })).toBeVisible();
  await expect(page.locator(".chat-bubble.is-user")).toHaveCount(0);
  await expect(composer).toHaveValue("функциональные зависимости");

  await page.getByRole("button", { name: "Повторить" }).click();
  await expect(page.locator(".chat-bubble.is-examiner")).toContainText("Готово");
  expect(stub.sent[1]).toEqual(stub.sent[0]);
  expect(stub.sent[1]).toMatchObject({ operation: "find_discrepancies", knowledge_policy: "allow_model" });
});

test("пустая область «Связано с темой»: объяснение и переход к поиску по теме", async ({ page }) => {
  const stub = await installChatStub(page, {
    onSend: (body) => body.retrieval_scope === "topic_project"
      ? { sse: answer("a3", "По теме [S1]") }
      : { status: 409, json: { code: "retrieval_scope_empty", detail: "К теме ничего не привязано — искать в «Связано с темой» негде" } },
  });
  await page.goto(`${BASE}/projects/${PROJECT}`);
  const composer = page.getByRole("textbox").last();
  await composer.fill("что такое 3НФ");
  await composer.press("Enter");
  await expect(page.getByRole("alert")).toContainText("К теме ничего не привязано");
  await page.getByRole("button", { name: "Искать по теме" }).click();
  await expect(page.locator(".chat-bubble.is-examiner")).toContainText("По теме");
  expect(stub.sent.map((body) => body.retrieval_scope)).toEqual(["project", "topic_project"]);
});
