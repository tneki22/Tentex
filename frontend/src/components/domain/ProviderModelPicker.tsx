import { useId, useMemo } from "react";
import type {
  AiModality,
  AiModelRead,
  AiModelSelection,
  AiProviderRead,
} from "../../api/ai";

function supports(
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

export function ProviderModelPicker({
  providers,
  models,
  value,
  modality = "text",
  capabilities = [],
  inheritedLabel,
  disabled = false,
  onChange,
}: {
  providers: AiProviderRead[];
  models: AiModelRead[];
  value: AiModelSelection | null;
  modality?: AiModality;
  capabilities?: string[];
  inheritedLabel?: string;
  disabled?: boolean;
  onChange: (value: AiModelSelection | null) => void;
}) {
  const id = useId();
  const eligible = useMemo(
    () => models.filter((model) => (
      supports(model, modality, capabilities)
      || (model.provider_id === value?.provider_id && model.model_id === value.model_id)
    )),
    [models, modality, capabilities, value?.model_id, value?.provider_id],
  );
  const availableProviders = providers.filter((provider) => (
    eligible.some((model) => model.provider_id === provider.id)
  ));
  const providerId = value?.provider_id ?? "";
  const providerModels = eligible
    .filter((model) => model.provider_id === providerId)
    .sort((left, right) => (
      (left.favorite_order ?? Number.MAX_SAFE_INTEGER)
      - (right.favorite_order ?? Number.MAX_SAFE_INTEGER)
      || left.display_name.localeCompare(right.display_name, "ru")
    ));

  return (
    <div className="provider-model-picker">
      <div>
        <label htmlFor={`${id}-provider`}>Провайдер</label>
        <select
          id={`${id}-provider`}
          value={providerId}
          disabled={disabled}
          onChange={(event) => {
            const nextProvider = event.target.value;
            if (!nextProvider) {
              onChange(null);
              return;
            }
            const first = eligible.find((model) => model.provider_id === nextProvider);
            onChange(first ? { provider_id: nextProvider, model_id: first.model_id } : null);
          }}
        >
          {inheritedLabel !== undefined && <option value="">Наследовать</option>}
          {inheritedLabel === undefined && <option value="">Выберите провайдера</option>}
          {availableProviders.map((provider) => (
            <option key={provider.id} value={provider.id}>
              {provider.is_favorite ? "★ " : ""}{provider.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor={`${id}-model`}>Модель</label>
        <select
          id={`${id}-model`}
          value={value?.model_id ?? ""}
          disabled={disabled || !providerId}
          onChange={(event) => onChange(event.target.value
            ? { provider_id: providerId, model_id: event.target.value }
            : null)}
        >
          <option value="">Выберите модель</option>
          {providerModels.map((model) => (
            <option key={model.model_id} value={model.model_id}>
              {model.favorite_order !== null ? "★ " : ""}{model.display_name}{model.is_available ? "" : " — больше не в каталоге"}
            </option>
          ))}
        </select>
      </div>
      {inheritedLabel && !value && <small>{inheritedLabel}</small>}
    </div>
  );
}
