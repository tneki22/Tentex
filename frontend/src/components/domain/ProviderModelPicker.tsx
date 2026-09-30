import { useMemo } from "react";
import type {
  AiModality,
  AiModelRead,
  AiModelSelection,
  AiProviderRead,
} from "../../api/ai";
import { Select } from "../ui";
import { byFavoriteThenName, supportsRole } from "./modelFacts";

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
  const eligible = useMemo(
    () => models.filter((model) => (
      supportsRole(model, modality, capabilities)
      || (model.provider_id === value?.provider_id && model.model_id === value.model_id)
    )),
    [models, modality, capabilities, value?.model_id, value?.provider_id],
  );
  const availableProviders = providers.filter((provider) => (
    eligible.some((model) => model.provider_id === provider.id)
  ));
  const providerId = value?.provider_id ?? null;
  const providerModels = eligible
    .filter((model) => model.provider_id === providerId)
    .sort(byFavoriteThenName);

  return (
    <div className="provider-model-picker">
      <div>
        <span className="provider-model-picker-label">Провайдер</span>
        <Select
          ariaLabel="Провайдер"
          value={providerId}
          disabled={disabled}
          emptyOption={inheritedLabel !== undefined ? "Использовать модель по умолчанию" : "Не выбран"}
          options={availableProviders.map((provider) => ({
            value: provider.id,
            label: `${provider.is_favorite ? "★ " : ""}${provider.label}`,
          }))}
          onValueChange={(nextProvider) => {
            if (!nextProvider) {
              onChange(null);
              return;
            }
            const first = eligible
              .filter((model) => model.provider_id === nextProvider)
              .sort(byFavoriteThenName)[0];
            onChange(first ? { provider_id: nextProvider, model_id: first.model_id } : null);
          }}
        />
      </div>
      <div>
        <span className="provider-model-picker-label">Модель</span>
        <Select
          ariaLabel="Модель"
          value={value?.model_id ?? null}
          disabled={disabled || !providerId}
          emptyOption="Не выбрана"
          options={providerModels.map((model) => ({
            value: model.model_id,
            label: `${model.favorite_order !== null ? "★ " : ""}${model.display_name}`,
            description: model.is_available ? model.model_id : `${model.model_id} — недоступна`,
          }))}
          onValueChange={(nextModel) => onChange(nextModel && providerId
            ? { provider_id: providerId, model_id: nextModel }
            : null)}
        />
      </div>
      {inheritedLabel && !value && <small>{inheritedLabel}</small>}
    </div>
  );
}
