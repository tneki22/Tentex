import type { AiModelSelection } from "../api/ai";
import { useAiCatalog } from "./useAiCatalog";

export type AiRoleAvailability =
  | { state: "loading" }
  | { state: "ready"; providerProfile: string | null }
  | { state: "disabled" }
  | { state: "unavailable"; reason: string };

/** Подсказка недоступной кнопки; `undefined`, когда роль готова или ещё неизвестно. */
export function unavailableReason(availability: AiRoleAvailability): string | undefined {
  if (availability.state === "disabled") {
    return "Внешние модели выключены — включаются в Параметрах ИИ.";
  }
  return availability.state === "unavailable" ? availability.reason : undefined;
}

/**
 * Можно ли прямо сейчас вызвать роль ИИ — до первого запроса, а не по ошибке
 * после него. Проверяет то же, что шлюз: общий тумблер, тумблер роли, выбранную
 * модель и ключ провайдера. Переопределение модели в чате побеждает роль.
 */
export function useAiRoleAvailability(
  role: string,
  override?: AiModelSelection | null,
): AiRoleAvailability {
  const catalog = useAiCatalog();
  if (!catalog) return { state: "loading" };
  if (!catalog.external_models_enabled) return { state: "disabled" };
  const setting = catalog.roles.find((item) => item.role === role);
  if (setting && !setting.enabled) {
    return { state: "unavailable", reason: `Функция «${setting.title}» выключена в Параметрах ИИ.` };
  }
  const providerId = override?.provider_id ?? setting?.resolved_provider_id ?? null;
  const modelId = override?.model_id ?? setting?.resolved_model ?? null;
  if (!providerId || !modelId) {
    return { state: "unavailable", reason: "Не выбрана модель — выберите её в Параметрах ИИ." };
  }
  const provider = catalog.providers.find((item) => item.id === providerId);
  if (provider && !provider.has_api_key) {
    return { state: "unavailable", reason: `У провайдера «${provider.label}» нет ключа.` };
  }
  return { state: "ready", providerProfile: provider?.catalog_profile ?? null };
}
