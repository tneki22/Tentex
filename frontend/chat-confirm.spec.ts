/** Подтверждение хода: цена, предел контекста, отмена без потери черновика. */
import { expect, test } from "@playwright/test";
import { BASE, PROJECT, installChatStub, source, sse } from "./chat-stub";

const DETAILS = {
  request_hash: "hash-trimmed",
  reasons: ["context_over_budget", "cost_threshold"],
  model_id: "test/model",
  provider_label: "Тестовый провайдер",
  estimated_input_tokens: 9000,
  estimated_output_tokens: 3000,
  estimated_cost_usd: "0.0120",
  estimated_cost_rub: "1.08",
  max_cost_usd: "0.0240",
  max_cost_rub: "2.16",
  budget: { limit: 12000, needed: 16500, maximum: 40000 },
  manifest: [
    { kind: "retrieval_source", title: "S5 · Учебник", tokens: 1200, included: true, truncated: true, reason: null },
    { kind: "history_pair", title: "Реплика истории", tokens: 900, included: false, truncated: false, reason: "budget" },
  ],
  expanded: { request_hash: "hash-wide", budget_tokens: 16500, estimated_cost_usd: "0.0180", estimated_cost_rub: "1.62" },
};

let answers = 0;
function answer() {
  answers += 1;
  return sse([
    ["started", { message_id: `a${answers}`, user_message_id: `u${answers}`, run_id: "r", sources: [source("S1", "Место")] }],
    ["delta", { text: "Ответ [S1]" }],
  ]);
}

async function ask(page: import("@playwright/test").Page) {
  const composer = page.getByRole("textbox").last();
  await composer.fill("Сравни нормальные формы");
  await composer.press("Enter");
  return composer;
}

test("превышение предела: окно показывает цену, что сокращено, и «Отменить» сохраняет черновик", async ({ page }) => {
  const stub = await installChatStub(page, {
    onSend: () => ({ status: 409, json: { code: "ai_confirmation_required", detail: "Нужно подтверждение", context: DETAILS } }),
  });
  await page.goto(`${BASE}/projects/${PROJECT}`);
  const composer = await ask(page);

  const dialog = page.getByRole("dialog", { name: "Контекст не помещается в предел" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("≈ 1.08 ₽");
  await expect(dialog).toContainText("до ≈ 2.16 ₽");
  await expect(dialog).toContainText("Нужно 16 500 токенов, предел 12 000");
  await expect(dialog).toContainText("S5 · Учебник");
  await expect(dialog).toContainText("сокращено");
  await expect(dialog.getByRole("button", { name: /Увеличить до 16 500 · ≈ 1.62 ₽/ })).toBeVisible();
  await page.screenshot({ path: "test-results/chat-confirm.png" });

  await dialog.getByRole("button", { name: "Отменить" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(composer).toHaveValue("Сравни нормальные формы");
  await expect(page.locator(".chat-bubble.is-user")).toHaveCount(0);
  expect(stub.sent).toHaveLength(1);
});

test("«Отправить сокращённым» и «Увеличить» отправляют тот же ход с нужным хешем", async ({ page }) => {
  let calls = 0;
  const stub = await installChatStub(page, {
    onSend: (body) => {
      calls += 1;
      return body.confirmed_request_hash
        ? { sse: answer() }
        : { status: 409, json: { code: "ai_confirmation_required", detail: "Нужно подтверждение", context: DETAILS } };
    },
  });
  await page.goto(`${BASE}/projects/${PROJECT}`);
  await ask(page);
  await page.getByRole("button", { name: "Отправить сокращённым" }).click();
  await expect(page.locator(".chat-bubble.is-examiner")).toContainText("Ответ");
  expect(stub.sent[1]).toMatchObject({
    client_turn_id: stub.sent[0].client_turn_id,
    confirmed_request_hash: "hash-trimmed",
    context_budget_tokens: null,
  });

  await ask(page);
  await page.getByRole("checkbox", { name: "Запомнить предел для этого чата" }).click();
  await page.getByRole("button", { name: /Увеличить до/ }).click();
  await expect(page.locator(".chat-bubble.is-examiner")).toHaveCount(2);
  expect(stub.sent[3]).toMatchObject({
    client_turn_id: stub.sent[2].client_turn_id,
    confirmed_request_hash: "hash-wide",
    context_budget_tokens: 16500,
    remember_budget: true,
  });
  expect(stub.sent[2].client_turn_id).not.toBe(stub.sent[0].client_turn_id);
  expect(calls).toBe(4);
});

test("окно модели мало: вместо увеличения предела — подсказка сменить модель", async ({ page }) => {
  await installChatStub(page, {
    onSend: () => ({
      status: 409,
      json: {
        code: "ai_confirmation_required", detail: "Нужно подтверждение",
        context: { ...DETAILS, reasons: ["context_over_budget"], expanded: null, budget: { limit: 12000, needed: 50000, maximum: 20000 } },
      },
    }),
  });
  await page.goto(`${BASE}/projects/${PROJECT}`);
  await ask(page);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("выберите модель с большим окном");
  await expect(dialog.getByRole("button", { name: /Увеличить/ })).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "Отправить сокращённым" })).toBeVisible();
});
