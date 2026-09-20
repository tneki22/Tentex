import type { AiModality, AiModelRead, AiModelSelection, DecimalValue } from "../../api/ai";

/** Примерно столько байт текста приходится на один токен — для оценки до вызова. */
const BYTES_PER_TOKEN = 4;

export function modelKey(selection: { provider_id: string; model_id: string }): string {
  return `${selection.provider_id}:${selection.model_id}`;
}

export function sameModel(
  left: { provider_id: string; model_id: string },
  right: { provider_id: string; model_id: string } | null | undefined,
): boolean {
  return right !== null && right !== undefined
    && left.provider_id === right.provider_id && left.model_id === right.model_id;
}

export function numberValue(value: DecimalValue | null): number | null {
  if (value === null) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function money(value: DecimalValue | null, perMillion = false): string {
  const amount = numberValue(value);
  if (amount === null) return "Цена неизвестна";
  const displayed = perMillion ? amount * 1_000_000 : amount;
  return `$${displayed.toLocaleString("ru-RU", { maximumFractionDigits: 4 })}`;
}

/** Мелкая сумма за один вызов: четырёх знаков после запятой ей не хватает. */
export function smallMoney(amount: number): string {
  return `$${amount.toLocaleString("ru-RU", { maximumFractionDigits: 5 })}`;
}

export function tokensFromBytes(bytes: number): number {
  return Math.round(bytes / BYTES_PER_TOKEN);
}

/**
 * Во сколько обойдётся один вызов: вход по размеру контекста, выход — по
 * заданному потолку ответа. `null`, если каталог не знает хотя бы одной цены
 * (в том числе у роутеров OpenRouter, где она зависит от выбранной ими модели).
 */
export function callCostUsd(
  model: AiModelRead,
  inputTokens: number,
  outputTokens: number,
): number | null {
  const prompt = numberValue(model.prompt_price_usd);
  const completion = numberValue(model.completion_price_usd);
  if (prompt === null || completion === null) return null;
  return prompt * inputTokens + completion * outputTokens;
}

/** Уровни рассуждения, заявленные каталогом. Пусто — модель о нём не сообщила. */
export function supportsReasoning(model: AiModelRead): boolean {
  return Object.keys(model.reasoning).length > 0;
}

export function reasoningLabel(model: { reasoning: Record<string, unknown> }): string {
  const efforts = model.reasoning.supported_efforts;
  if (Array.isArray(efforts) && efforts.length) return efforts.join(", ");
  if (model.reasoning.mandatory === true) return "обязательно";
  return Object.keys(model.reasoning).length ? "поддерживается" : "нет данных";
}

/**
 * Годится ли модель роли. Единственный фильтр на весь проект: и выбор в
 * Параметрах, и выбор в чате обязаны видеть один и тот же список, иначе
 * «в настройках была, в чате пропала».
 */
export function supportsRole(
  model: AiModelRead,
  modality: AiModality,
  capabilities: string[],
): boolean {
  if (!model.is_available) return false;
  if (modality === "text" && model.output_modalities.length
    && !model.output_modalities.includes("text")) return false;
  if (modality === "speech" && !model.input_modalities.includes("audio")) return false;
  return capabilities.every((capability) => {
    if (capability === "structured_output") {
      return model.supported_parameters.includes("response_format");
    }
    if (capability === "audio_transcription") return model.input_modalities.includes("audio");
    return capability === "streaming";
  });
}

/** Избранные вперёд, остальные по алфавиту — порядок один во всех списках моделей. */
export function byFavoriteThenName(left: AiModelRead, right: AiModelRead): number {
  return (left.favorite_order ?? Number.MAX_SAFE_INTEGER)
    - (right.favorite_order ?? Number.MAX_SAFE_INTEGER)
    || left.display_name.localeCompare(right.display_name, "ru");
}

export function findModel(
  models: AiModelRead[],
  selection: AiModelSelection | null,
): AiModelRead | null {
  if (!selection) return null;
  return models.find((model) => sameModel(model, selection)) ?? null;
}
