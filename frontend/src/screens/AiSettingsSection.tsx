import {
  KeyRound,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Star,
  Trash2,
  Wifi,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import {
  addAiCatalogModel,
  createAiProvider,
  deleteAiCredential,
  deleteAiProvider,
  getAiSettings,
  listAiRuns,
  searchAiModels,
  testAiModel,
  testAiProvider,
  updateAiDefault,
  updateAiModelFavorites,
  updateAiProvider,
  updateAiProviderFavorites,
  updateAiRole,
  updateAiSettings,
  upsertManualAiModel,
  type AiCatalogModelRead,
  type AiGlobalSettingsWrite,
  type AiModelRead,
  type AiModelSelection,
  type AiProviderRead,
  type AiProviderWrite,
  type AiRoleRead,
  type AiRunRead,
  type AiSettingsRead,
  type DecimalValue,
} from "../api/ai";
import { OfflineNotice, ProviderModelPicker } from "../components/domain";
import {
  Button,
  ConfirmDialog,
  Dialog,
  Disclosure,
  ErrorState,
  Field,
  IconButton,
  LoadingState,
  Menu,
  Select,
  StatusBadge,
  Switch,
} from "../components/ui";
import type { AiSettingsSubsection } from "./Setup";

function numberValue(value: DecimalValue | null): number | null {
  if (value === null) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function money(value: DecimalValue | null, perMillion = false): string {
  const amount = numberValue(value);
  if (amount === null) return "Цена неизвестна";
  const displayed = perMillion ? amount * 1_000_000 : amount;
  return `$${displayed.toLocaleString("ru-RU", { maximumFractionDigits: 4 })}`;
}

function dateTime(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function modelCountText(count: number): string {
  const mod100 = count % 100;
  const mod10 = count % 10;
  if (mod100 >= 11 && mod100 <= 14) return `${count} моделей`;
  if (mod10 === 1) return `${count} модель`;
  if (mod10 >= 2 && mod10 <= 4) return `${count} модели`;
  return `${count} моделей`;
}

function providerStatus(provider: AiProviderRead) {
  if (!provider.has_api_key) return { label: "Нет ключа", tone: "neutral" as const };
  if (provider.last_test_status === "connected") {
    return { label: "Отвечает", tone: "success" as const };
  }
  if (provider.last_test_status) return { label: "Ошибка", tone: "warning" as const };
  return { label: "Не проверен", tone: "neutral" as const };
}

function runStatusLabel(status: string): string {
  return {
    succeeded: "Готово",
    failed: "Ошибка",
    cached: "Из кэша",
    cancelled: "Отменено",
    queued: "В очереди",
    running: "Выполняется",
  }[status] ?? status;
}

function providerName(settings: AiSettingsRead, providerId: string | null): string {
  return settings.providers.find((provider) => provider.id === providerId)?.label
    ?? "Не выбран";
}

function modelName(settings: AiSettingsRead, selection: AiModelSelection | null): string {
  if (!selection) return "Не выбрана";
  return settings.models.find((model) => (
    model.provider_id === selection.provider_id && model.model_id === selection.model_id
  ))?.display_name ?? selection.model_id;
}

function selectionForRole(role: AiRoleRead): AiModelSelection | null {
  return role.provider_override_id && role.model_override
    ? { provider_id: role.provider_override_id, model_id: role.model_override }
    : null;
}

function SaveState({ children }: { children: string }) {
  return <span className="ai-save-state" aria-live="polite">{children}</span>;
}

function OverviewPanel({
  settings,
  runs,
  onSettings,
  navigate,
}: {
  settings: AiSettingsRead;
  runs: AiRunRead[];
  onSettings: (settings: AiSettingsRead) => void;
  navigate: (subsection: AiSettingsSubsection, providerId?: string) => void;
}) {
  const [status, setStatus] = useState("");
  const favorites = settings.models
    .filter((model) => model.favorite_order !== null)
    .sort((left, right) => (left.favorite_order ?? 0) - (right.favorite_order ?? 0));
  const connected = settings.providers.filter((provider) => (
    provider.last_test_status === "connected"
  )).length;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const todayRunCount = runs.filter((run) => new Date(run.created_at) >= today).length;

  async function toggleExternal(enabled: boolean) {
    setStatus("Сохраняем…");
    try {
      const next = await updateAiSettings({
        external_models_enabled: enabled,
        daily_limit_usd: settings.daily_limit_usd,
        operation_limit_usd: settings.operation_limit_usd,
        confirm_cost_usd: settings.confirm_cost_usd,
        confirm_input_tokens: settings.confirm_input_tokens,
        usd_rub_rate: settings.usd_rub_rate,
        usd_rub_rate_date: settings.usd_rub_rate_date,
      });
      onSettings(next);
      setStatus("Сохранено");
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : "Не сохранено");
    }
  }

  return (
    <div className="ai-panel-stack">
      <section className="ai-settings-group is-first">
        <header className="ai-group-head">
          <div><h2>Искусственный интеллект</h2><p>Подключите провайдеров, добавьте нужные модели и выберите, где их использовать.</p></div>
        </header>
        <div className="ai-global-row">
          <Switch
            checked={settings.external_models_enabled}
            onCheckedChange={(enabled) => void toggleExternal(enabled)}
            label="Разрешить функции с ИИ"
            hint="Когда настройка выключена, Tentex не отправляет запросы провайдерам. Ключи и остальные настройки сохраняются."
          />
          <SaveState>{status}</SaveState>
        </div>
        {!settings.external_models_enabled && (
          <OfflineNotice reason="disabled" alternative="Настройки ниже можно менять даже сейчас." />
        )}
      </section>

      <div className="ai-overview-grid">
        <button type="button" onClick={() => navigate("providers")}>
          <span>Провайдеры</span><strong>{settings.providers.length}</strong>
          <small>{connected === 1 ? "1 отвечает" : `${connected} отвечают`}</small>
        </button>
        <button type="button" onClick={() => navigate("models")}>
          <span>Добавленные модели</span><strong>{settings.models.filter((model) => model.is_available).length}</strong>
          <small>{favorites.length} в избранном</small>
        </button>
        <button type="button" onClick={() => navigate("usage")}>
          <span>Расход сегодня</span><strong>{money(settings.today_usage.actual_cost_usd)}</strong>
          <small>Запросов: {todayRunCount} · из кэша: {settings.today_usage.cache_hits}</small>
        </button>
      </div>

      <section className="ai-settings-group">
        <header className="ai-group-head">
          <div>
            <h3>Модели по умолчанию</h3>
            <p>Они используются там, где для функции не выбрана отдельная модель.</p>
          </div>
          <Button variant="secondary" onClick={() => navigate("defaults")}>Настроить</Button>
        </header>
        <div className="ai-default-summary">
          <div><span>Текст</span><strong>{modelName(settings, settings.default_text)}</strong><small>{providerName(settings, settings.default_text?.provider_id ?? null)}</small></div>
          <div><span>Речь</span><strong>{modelName(settings, settings.default_speech)}</strong><small>{providerName(settings, settings.default_speech?.provider_id ?? null)}</small></div>
        </div>
      </section>

      <section className="ai-settings-group">
        <header className="ai-group-head"><div><h3>Избранное</h3><p>Избранные провайдеры и модели показываются выше в списках, чтобы их было проще найти.</p></div></header>
        <div className="ai-favorite-chips">
          {settings.providers.filter((provider) => provider.is_favorite).map((provider) => (
            <button key={provider.id} type="button" onClick={() => navigate("models", provider.id)}>★ {provider.label}</button>
          ))}
          {favorites.map((model) => <span key={`${model.provider_id}:${model.model_id}`}>★ {model.display_name}</span>)}
          {!settings.providers.some((provider) => provider.is_favorite) && !favorites.length && <small>Пока ничего не добавлено.</small>}
        </div>
      </section>
    </div>
  );
}

function ProvidersPanel({
  settings,
  onSettings,
  onModels,
}: {
  settings: AiSettingsRead;
  onSettings: (settings: AiSettingsRead) => void;
  onModels: (providerId: string) => void;
}) {
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [label, setLabel] = useState("");
  const [profile, setProfile] = useState<AiProviderWrite["catalog_profile"]>("openrouter");
  const [baseUrl, setBaseUrl] = useState("https://openrouter.ai/api/v1");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<AiProviderRead | null>(null);

  function openEditor(provider?: AiProviderRead) {
    setEditing(provider?.id ?? "new");
    setLabel(provider?.label ?? "");
    setProfile(provider?.catalog_profile ?? "openrouter");
    setBaseUrl(provider?.base_url ?? "https://openrouter.ai/api/v1");
    setApiKey("");
    setMessage("");
  }

  async function run(key: string, action: () => Promise<AiSettingsRead | unknown>, done: string) {
    setBusy(key);
    setMessage("");
    try {
      const result = await action();
      onSettings(result && typeof result === "object" && "providers" in result
        ? result as AiSettingsRead
        : await getAiSettings());
      setMessage(done);
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "Действие не выполнено");
    } finally {
      setBusy(null);
    }
  }

  async function submit() {
    if (!label.trim() || !baseUrl.trim()) {
      setMessage("Укажите название и базовый URL.");
      return;
    }
    const command: AiProviderWrite = {
      label: label.trim(),
      catalog_profile: profile,
      base_url: baseUrl.trim(),
      api_key: apiKey || null,
    };
    await run("save", () => editing === "new"
      ? createAiProvider(command)
      : updateAiProvider(editing!, command), "Провайдер сохранён");
    setEditing(null);
  }

  async function toggleFavorite(provider: AiProviderRead) {
    const ids = settings.providers
      .filter((item) => item.is_favorite !== (item.id === provider.id))
      .map((item) => item.id);
    await run(provider.id, () => updateAiProviderFavorites(ids), "Избранное обновлено");
  }

  return (
    <section className="ai-settings-group is-first">
      <header className="ai-group-head">
        <div><h2>Провайдеры</h2><p>Добавьте сервис, через который Tentex будет обращаться к моделям.</p></div>
        <Button onClick={() => openEditor()}><Plus size={14} />Добавить провайдера</Button>
      </header>

      {editing && (
        <div className="ai-editor-card">
          <div className="ai-form-grid">
            <Field label="Название" required><input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Например, OpenRouter" /></Field>
            <Field label="Тип провайдера"><Select ariaLabel="Тип провайдера" value={profile} onValueChange={(value) => value && setProfile(value as AiProviderWrite["catalog_profile"])} options={[{ value: "openrouter", label: "OpenRouter" }, { value: "openai_compatible", label: "OpenAI-совместимый API" }]} /></Field>
            <Field label="Базовый URL" required><input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://…/v1" /></Field>
            <Field label={editing === "new" ? "API-ключ" : "Новый API-ключ"} hint={editing === "new" ? "Ключ хранится в зашифрованном виде на этом устройстве." : "Оставьте поле пустым, если ключ менять не нужно."}><input type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} /></Field>
          </div>
          <div className="ai-group-actions"><Button disabled={busy === "save"} onClick={() => void submit()}>Сохранить провайдера</Button><Button variant="ghost" onClick={() => setEditing(null)}>Отменить</Button></div>
        </div>
      )}

      {settings.providers.length ? (
        <div className="ai-provider-list">
          {settings.providers.map((provider) => {
            const state = providerStatus(provider);
            return <article className="ai-provider-row" key={provider.id}>
              <div className="ai-provider-identity">
                <button className="ai-star-button" type="button" aria-label={provider.is_favorite ? "Убрать провайдера из избранного" : "Добавить провайдера в избранное"} aria-pressed={provider.is_favorite} onClick={() => void toggleFavorite(provider)}><Star size={17} fill={provider.is_favorite ? "currentColor" : "none"} /></button>
                <div><strong>{provider.label}</strong><small>{provider.catalog_profile === "openrouter" ? "OpenRouter" : "OpenAI-совместимый API"}</small></div>
              </div>
              <div className="ai-provider-details">
                <div><span>API-ключ</span>{provider.has_api_key ? <StatusBadge tone="neutral">Добавлен</StatusBadge> : <StatusBadge tone="neutral">Не добавлен</StatusBadge>}</div>
                <div><span>Подключение</span><StatusBadge tone={state.tone}>{state.label}</StatusBadge><small>{provider.last_tested_at ? dateTime(provider.last_tested_at) : "Тест ещё не запускался"}</small></div>
                <div className="ai-provider-url"><span>Базовый URL</span><code>{provider.base_url}</code></div>
              </div>
              <button type="button" className="ai-model-count-button" onClick={() => onModels(provider.id)}><strong>{modelCountText(provider.model_count)}</strong><small>Открыть список</small></button>
              <div className="ai-provider-actions">
                <Button variant="secondary" disabled={busy === provider.id} onClick={() => void run(provider.id, () => testAiProvider(provider.id), "Провайдер отвечает")}><Wifi size={14} />Тест</Button>
                <Menu
                  label={`Действия с провайдером ${provider.label}`}
                  trigger={<IconButton label="Ещё действия"><MoreHorizontal size={17} /></IconButton>}
                  items={[
                    { label: "Изменить провайдера", icon: <Pencil size={14} />, onSelect: () => openEditor(provider) },
                    ...(provider.has_api_key ? [{ label: "Удалить API-ключ", icon: <KeyRound size={14} />, onSelect: () => void run(provider.id, () => deleteAiCredential(provider.id), "API-ключ удалён") }] : []),
                    { label: "Удалить провайдера", icon: <Trash2 size={14} />, onSelect: () => setDeleteTarget(provider), destructive: true },
                  ]}
                />
              </div>
            </article>;
          })}
        </div>
      ) : <div className="ai-empty-card"><strong>Провайдеров пока нет</strong><p>Добавьте OpenRouter или другой сервис с OpenAI-совместимым API.</p></div>}
      <SaveState>{busy ? "Подождите…" : message}</SaveState>
      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title={`Удалить провайдера «${deleteTarget?.label ?? ""}»?`}
        confirmLabel="Удалить провайдера"
        destructive
        onConfirm={() => {
          if (!deleteTarget) return;
          void run(deleteTarget.id, () => deleteAiProvider(deleteTarget.id), "Провайдер удалён");
          setDeleteTarget(null);
        }}
      >
        <p>Добавленные модели этого провайдера тоже будут удалены. В журнале останется его название.</p>
      </ConfirmDialog>
    </section>
  );
}

function reasoningLabel(model: { reasoning: Record<string, unknown> }): string {
  const efforts = model.reasoning.supported_efforts;
  if (Array.isArray(efforts) && efforts.length) return efforts.join(" · ");
  if (model.reasoning.mandatory === true) return "обязательно";
  return Object.keys(model.reasoning).length ? "поддерживается" : "нет данных";
}

function ModelsPanel({
  settings,
  onSettings,
  providerId,
  onProvider,
}: {
  settings: AiSettingsRead;
  onSettings: (settings: AiSettingsRead) => void;
  providerId: string | null;
  onProvider: (providerId: string) => void;
}) {
  const selectedProvider = settings.providers.find((provider) => provider.id === providerId)
    ?? settings.providers.find((provider) => provider.is_favorite)
    ?? settings.providers[0]
    ?? null;
  const models = settings.models.filter((model) => model.provider_id === selectedProvider?.id);
  const [adding, setAdding] = useState(false);
  const [editingModel, setEditingModel] = useState<AiModelRead | null>(null);
  const [modelId, setModelId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [contextLength, setContextLength] = useState("");
  const [promptPrice, setPromptPrice] = useState("");
  const [completionPrice, setCompletionPrice] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [catalog, setCatalog] = useState<AiCatalogModelRead[]>([]);
  const [catalogQuery, setCatalogQuery] = useState("");
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [addingCatalogModel, setAddingCatalogModel] = useState<string | null>(null);
  const favorites = settings.models
    .filter((model) => model.favorite_order !== null)
    .sort((left, right) => (left.favorite_order ?? 0) - (right.favorite_order ?? 0));

  async function run(key: string, action: () => Promise<unknown>, done: string) {
    setBusy(key);
    setMessage("");
    try {
      const result = await action();
      onSettings(result && typeof result === "object" && "providers" in result
        ? result as AiSettingsRead
        : await getAiSettings());
      setMessage(done);
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "Действие не выполнено");
    } finally {
      setBusy(null);
    }
  }

  async function toggleFavorite(model: AiModelRead) {
    const key = `${model.provider_id}:${model.model_id}`;
    const next = model.favorite_order === null
      ? [...favorites.map(({ provider_id, model_id }) => ({ provider_id, model_id })), { provider_id: model.provider_id, model_id: model.model_id }]
      : favorites.filter((item) => item.provider_id !== model.provider_id || item.model_id !== model.model_id)
        .map(({ provider_id, model_id }) => ({ provider_id, model_id }));
    await run(key, () => updateAiModelFavorites(next), "Избранное обновлено");
  }

  function openManual(model: AiModelRead | null = null) {
    setEditingModel(model);
    setModelId(model?.model_id ?? "");
    setDisplayName(model?.display_name ?? "");
    setContextLength(String(model?.context_length ?? ""));
    setPromptPrice(model?.prompt_price_usd === null || model?.prompt_price_usd === undefined
      ? "" : String(Number(model.prompt_price_usd) * 1_000_000));
    setCompletionPrice(
      model?.completion_price_usd === null || model?.completion_price_usd === undefined
        ? "" : String(Number(model.completion_price_usd) * 1_000_000),
    );
    setAdding(true);
    setMessage("");
  }

  async function addManual() {
    if (!selectedProvider || !modelId.trim() || !displayName.trim()) {
      setMessage("Укажите ID и название модели.");
      return;
    }
    await run("manual", () => upsertManualAiModel(selectedProvider.id, {
      model_id: modelId.trim(),
      display_name: displayName.trim(),
      context_length: contextLength ? Number(contextLength) : null,
      max_completion_tokens: editingModel?.max_completion_tokens ?? null,
      supported_parameters: editingModel?.supported_parameters ?? [],
      input_modalities: editingModel?.input_modalities ?? ["text"],
      output_modalities: editingModel?.output_modalities ?? ["text"],
      reasoning: editingModel?.reasoning ?? {},
      default_parameters: editingModel?.default_parameters ?? {},
      prompt_price_usd: promptPrice ? Number(promptPrice) / 1_000_000 : null,
      completion_price_usd: completionPrice ? Number(completionPrice) / 1_000_000 : null,
      knowledge_cutoff: editingModel?.knowledge_cutoff ?? null,
      expiration_date: editingModel?.expiration_date ?? null,
    }), editingModel ? "Параметры модели сохранены" : "Модель добавлена");
    setAdding(false);
    setEditingModel(null);
    setModelId("");
    setDisplayName("");
  }

  async function openCatalogSearch() {
    if (!selectedProvider) return;
    setSearchOpen(true);
    setCatalog([]);
    setCatalogQuery("");
    setCatalogError("");
    setCatalogLoading(true);
    try {
      setCatalog(await searchAiModels(selectedProvider.id));
    } catch (caught) {
      setCatalogError(caught instanceof Error
        ? caught.message
        : "Не удалось получить список моделей. Проверьте подключение и попробуйте снова.");
    } finally {
      setCatalogLoading(false);
    }
  }

  async function addFromCatalog(model: AiCatalogModelRead) {
    if (!selectedProvider || model.is_added) return;
    setAddingCatalogModel(model.model_id);
    setCatalogError("");
    try {
      const { is_added: _isAdded, ...command } = model;
      onSettings(await addAiCatalogModel(selectedProvider.id, command));
      setCatalog((current) => current.map((item) => (
        item.model_id === model.model_id ? { ...item, is_added: true } : item
      )));
      setMessage(`Модель «${model.display_name}» добавлена`);
    } catch (caught) {
      setCatalogError(caught instanceof Error ? caught.message : "Не удалось добавить модель.");
    } finally {
      setAddingCatalogModel(null);
    }
  }

  const normalizedCatalogQuery = catalogQuery.trim().toLocaleLowerCase("ru");
  const catalogMatches = catalog.filter((model) => (
    !normalizedCatalogQuery
    || model.display_name.toLocaleLowerCase("ru").includes(normalizedCatalogQuery)
    || model.model_id.toLocaleLowerCase("ru").includes(normalizedCatalogQuery)
  ));
  const visibleCatalogMatches = catalogMatches.slice(0, 60);

  if (!selectedProvider) {
    return <section className="ai-settings-group is-first"><header className="ai-group-head"><div><h2>Модели</h2><p>Сначала добавьте провайдера — после этого здесь можно будет выбрать нужные модели.</p></div></header></section>;
  }

  return (
    <section className="ai-settings-group is-first">
      <header className="ai-group-head">
        <div><h2>Модели</h2><p>Здесь остаются только модели, которые вы добавили сами.</p></div>
        <div className="ai-group-actions"><Button onClick={() => void openCatalogSearch()}><Search size={14} />Поиск моделей</Button><Button variant="secondary" onClick={() => openManual()}><Plus size={14} />Добавить вручную</Button></div>
      </header>
      <Field label="Провайдер"><Select ariaLabel="Провайдер моделей" value={selectedProvider.id} onValueChange={(value) => value && onProvider(value)} options={settings.providers.map((provider) => ({ value: provider.id, label: `${provider.is_favorite ? "★ " : ""}${provider.label}`, description: modelCountText(provider.model_count) }))} /></Field>

      {adding && <div className="ai-editor-card">
        <div className="ai-form-grid">
          <Field label="ID модели" required><input value={modelId} disabled={editingModel !== null} onChange={(event) => setModelId(event.target.value)} placeholder="vendor/model" /></Field>
          <Field label="Название" required><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></Field>
          <Field label="Контекст, токенов"><input type="number" min="1" value={contextLength} onChange={(event) => setContextLength(event.target.value)} /></Field>
          <Field label="Вход, $ / 1 млн"><input type="number" min="0" step="0.01" value={promptPrice} onChange={(event) => setPromptPrice(event.target.value)} /></Field>
          <Field label="Выход, $ / 1 млн"><input type="number" min="0" step="0.01" value={completionPrice} onChange={(event) => setCompletionPrice(event.target.value)} /></Field>
        </div>
        <p className="ai-muted">Если цена или размер контекста неизвестны, оставьте поле пустым. Эти данные можно добавить позже.</p>
        <div className="ai-group-actions"><Button disabled={busy === "manual"} onClick={() => void addManual()}>{editingModel ? "Сохранить изменения" : "Добавить модель"}</Button><Button variant="ghost" onClick={() => { setAdding(false); setEditingModel(null); }}>Отменить</Button></div>
      </div>}

      {models.length ? <div className="ai-model-list">
        {models.map((model) => <article className={`ai-model-row ${!model.is_available ? "is-muted" : ""}`} key={`${model.provider_id}:${model.model_id}`}>
          <div className="ai-model-identity"><button className="ai-star-button" type="button" aria-label={model.favorite_order === null ? "Добавить модель в избранное" : "Убрать модель из избранного"} aria-pressed={model.favorite_order !== null} onClick={() => void toggleFavorite(model)}><Star size={17} fill={model.favorite_order === null ? "none" : "currentColor"} /></button><div><strong>{model.display_name}</strong><code>{model.model_id}</code>{model.is_manually_added && <small>Добавлена вручную</small>}</div></div>
          <div className="ai-model-facts">
            <div><span>Цена за 1 млн токенов</span><strong>Вход {money(model.prompt_price_usd, true)}</strong><small>Выход {money(model.completion_price_usd, true)}</small></div>
            <div><span>Контекст</span><strong>{model.context_length?.toLocaleString("ru-RU") ?? "Не указан"}</strong><small>{model.max_completion_tokens ? `Ответ до ${model.max_completion_tokens.toLocaleString("ru-RU")}` : "Лимит ответа не указан"}</small></div>
            <div><span>Рассуждение</span><strong>{reasoningLabel(model)}</strong></div>
            <div><span>Возможности</span><div className="ai-tag-list">{model.input_modalities.map((item) => <span key={`in-${item}`}>Вход: {item}</span>)}{model.output_modalities.map((item) => <span key={`out-${item}`}>Выход: {item}</span>)}{model.supported_parameters.slice(0, 3).map((item) => <span key={item}>{item}</span>)}</div></div>
          </div>
          <div className="ai-model-actions"><Button variant="secondary" disabled={!model.is_available || busy !== null} onClick={() => void run(model.model_id, () => testAiModel({ provider_id: model.provider_id, model_id: model.model_id }), "Модель отвечает")}><Wifi size={14} />Тест</Button><IconButton label="Изменить модель" onClick={() => openManual(model)}><Pencil size={16} /></IconButton></div>
        </article>)}
      </div> : <div className="ai-empty-card"><strong>Модели ещё не добавлены</strong><p>Найдите модель у провайдера или добавьте её по ID.</p></div>}
      <SaveState>{busy ? "Подождите…" : message}</SaveState>

      <Dialog
        open={searchOpen}
        onOpenChange={setSearchOpen}
        title={`Поиск моделей — ${selectedProvider.label}`}
        description="Найдите нужную модель и добавьте её в Tentex. Остальные модели останутся только в каталоге провайдера."
        className="ai-model-search-dialog"
      >
        <label className="ai-model-search-field">
          <span className="sr-only">Название или ID модели</span>
          <Search size={16} aria-hidden="true" />
          <input autoFocus value={catalogQuery} onChange={(event) => setCatalogQuery(event.target.value)} placeholder="Название или ID модели" />
        </label>
        {catalogLoading ? <LoadingState label="Получаем модели провайдера" /> : catalogError ? <ErrorState message={catalogError} /> : <>
          <div className="ai-search-count">Найдено: {catalogMatches.length}</div>
          {visibleCatalogMatches.length ? <div className="ai-catalog-results">
            {visibleCatalogMatches.map((model) => <article key={model.model_id} className="ai-catalog-row">
              <div><strong>{model.display_name}</strong><code>{model.model_id}</code></div>
              <div className="ai-catalog-meta"><span>{model.context_length ? `${model.context_length.toLocaleString("ru-RU")} токенов` : "Контекст не указан"}</span><span>Вход {money(model.prompt_price_usd, true)}</span><span>Выход {money(model.completion_price_usd, true)}</span><span>Рассуждение: {reasoningLabel(model)}</span></div>
              <Button variant={model.is_added ? "ghost" : "secondary"} disabled={model.is_added || addingCatalogModel !== null} onClick={() => void addFromCatalog(model)}>{model.is_added ? "Добавлена" : addingCatalogModel === model.model_id ? "Добавляем…" : "Добавить"}</Button>
            </article>)}
          </div> : <div className="ai-empty-card"><strong>Ничего не найдено</strong><p>Попробуйте другое название или ID модели.</p></div>}
          {catalogMatches.length > visibleCatalogMatches.length && <p className="ai-muted">Показаны первые 60 моделей. Уточните запрос, чтобы сократить список.</p>}
        </>}
      </Dialog>
    </section>
  );
}

function DefaultsPanel({ settings, onSettings }: { settings: AiSettingsRead; onSettings: (settings: AiSettingsRead) => void }) {
  const [text, setText] = useState<AiModelSelection | null>(settings.default_text);
  const [speech, setSpeech] = useState<AiModelSelection | null>(settings.default_speech);
  const [status, setStatus] = useState("");
  useEffect(() => { setText(settings.default_text); setSpeech(settings.default_speech); }, [settings.default_text, settings.default_speech]);

  async function save(modality: "text" | "speech", selection: AiModelSelection | null) {
    setStatus("Сохраняем…");
    try {
      onSettings(await updateAiDefault(modality, selection));
      setStatus("Модель по умолчанию сохранена");
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : "Не сохранено");
    }
  }

  return <div className="ai-panel-stack">
    <section className="ai-settings-group is-first"><header className="ai-group-head"><div><h2>Модели по умолчанию</h2><p>Выберите основные модели для текста и речи.</p></div></header><div className="ai-callout">Если у функции не выбрана своя модель, она использует настройку из этого раздела. Избранное влияет только на порядок в списках.</div></section>
    <section className="ai-settings-group"><h3>Для текста</h3><p>Используется в чате, очистке текста, группировке и проверке ответов.</p><ProviderModelPicker providers={settings.providers} models={settings.models} value={text} onChange={setText} /><Button onClick={() => void save("text", text)}>Сохранить модель для текста</Button></section>
    <section className="ai-settings-group"><h3>Для речи</h3><p>Используется для распознавания голоса. В списке показываются только подходящие модели.</p><ProviderModelPicker providers={settings.providers} models={settings.models} value={speech} modality="speech" onChange={setSpeech} /><Button onClick={() => void save("speech", speech)}>Сохранить модель для речи</Button></section>
    <SaveState>{status}</SaveState>
  </div>;
}

function RoleCard({ settings, role, onSettings }: { settings: AiSettingsRead; role: AiRoleRead; onSettings: (settings: AiSettingsRead) => void }) {
  const [status, setStatus] = useState("");
  const [maxTokens, setMaxTokens] = useState(String(role.parameters.max_output_tokens ?? ""));
  const [temperature, setTemperature] = useState(String(role.parameters.temperature ?? ""));
  const [language, setLanguage] = useState(String(role.parameters.language ?? "ru"));

  async function save(patch: { enabled?: boolean; selection?: AiModelSelection | null; parameters?: Record<string, unknown> }) {
    const selection = patch.selection === undefined ? selectionForRole(role) : patch.selection;
    setStatus("Сохраняем…");
    try {
      onSettings(await updateAiRole(role.role, {
        enabled: patch.enabled ?? role.enabled,
        provider_override_id: selection?.provider_id ?? null,
        model_override: selection?.model_id ?? null,
        parameters: patch.parameters ?? role.parameters,
      }));
      setStatus("Сохранено");
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : "Не сохранено");
    }
  }

  const inherited = role.resolved_provider_id && role.resolved_model
    ? `Сейчас используется: ${providerName(settings, role.resolved_provider_id)} — ${role.resolved_model}`
    : "Сначала выберите модель по умолчанию";
  return <article className="ai-role-card">
    <Switch checked={role.enabled} onCheckedChange={(enabled) => void save({ enabled })} label={role.title} hint={role.description} />
    <ProviderModelPicker providers={settings.providers} models={settings.models} value={selectionForRole(role)} modality={role.modality} capabilities={role.required_capabilities} inheritedLabel={inherited} disabled={!role.enabled} onChange={(selection) => void save({ selection })} />
    <Disclosure summary="Параметры функции">
      {role.modality === "speech" ? <>
        <div className="ai-form-grid compact"><Field label="Язык"><input value={language} maxLength={2} onChange={(event) => setLanguage(event.target.value)} /></Field></div>
        <Button variant="secondary" onClick={() => void save({ parameters: { language } })}>Сохранить параметры</Button>
      </> : <>
        <div className="ai-form-grid compact">
          <Field label="Максимум токенов ответа"><input type="number" min="64" value={maxTokens} onChange={(event) => setMaxTokens(event.target.value)} placeholder="По умолчанию" /></Field>
          <Field label="Температура"><input type="number" min="0" max="2" step="0.1" value={temperature} onChange={(event) => setTemperature(event.target.value)} placeholder="По умолчанию" /></Field>
        </div>
        <Button variant="secondary" onClick={() => void save({ parameters: {
          ...role.parameters,
          ...(maxTokens ? { max_output_tokens: Number(maxTokens) } : {}),
          ...(temperature ? { temperature: Number(temperature) } : {}),
        } })}>Сохранить параметры</Button>
      </>}
    </Disclosure>
    <SaveState>{status}</SaveState>
  </article>;
}

function FunctionsPanel({ settings, onSettings }: { settings: AiSettingsRead; onSettings: (settings: AiSettingsRead) => void }) {
  return <section className="ai-settings-group is-first"><header className="ai-group-head"><div><h2>Функции</h2><p>Для каждой функции можно оставить модель по умолчанию или выбрать другую.</p></div></header><div className="ai-role-list">{settings.roles.map((role) => <RoleCard key={role.role} settings={settings} role={role} onSettings={onSettings} />)}</div></section>;
}

function LimitsPanel({ settings, onSettings }: { settings: AiSettingsRead; onSettings: (settings: AiSettingsRead) => void }) {
  const [daily, setDaily] = useState(String(settings.daily_limit_usd ?? ""));
  const [operation, setOperation] = useState(String(settings.operation_limit_usd ?? ""));
  const [confirmCost, setConfirmCost] = useState(String(settings.confirm_cost_usd ?? ""));
  const [tokens, setTokens] = useState(String(settings.confirm_input_tokens));
  const [rate, setRate] = useState(String(settings.usd_rub_rate ?? ""));
  const [rateDate, setRateDate] = useState(settings.usd_rub_rate_date ?? "");
  const [status, setStatus] = useState("");

  async function save() {
    if (Boolean(rate) !== Boolean(rateDate)) {
      setStatus("Укажите и курс, и дату — либо оставьте оба поля пустыми.");
      return;
    }
    setStatus("Сохраняем…");
    const command: AiGlobalSettingsWrite = {
      external_models_enabled: settings.external_models_enabled,
      daily_limit_usd: daily ? Number(daily) : null,
      operation_limit_usd: operation ? Number(operation) : null,
      confirm_cost_usd: confirmCost ? Number(confirmCost) : null,
      confirm_input_tokens: Number(tokens),
      usd_rub_rate: rate ? Number(rate) : null,
      usd_rub_rate_date: rateDate || null,
    };
    try {
      onSettings(await updateAiSettings(command));
      setStatus("Лимиты сохранены");
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : "Не сохранено");
    }
  }

  return <section className="ai-settings-group is-first"><header className="ai-group-head"><div><h2>Расходы и подтверждения</h2><p>Задайте лимиты расходов и выберите, когда Tentex должен просить подтверждение.</p></div></header><div className="ai-form-grid">
    <Field label="Дневной лимит, $" hint="Пусто — без лимита"><input type="number" min="0" step="0.01" value={daily} onChange={(event) => setDaily(event.target.value)} /></Field>
    <Field label="Лимит одной операции, $" hint="Пусто — без лимита"><input type="number" min="0" step="0.01" value={operation} onChange={(event) => setOperation(event.target.value)} /></Field>
    <Field label="Просить подтверждение при цене от, $"><input type="number" min="0" step="0.01" value={confirmCost} onChange={(event) => setConfirmCost(event.target.value)} /></Field>
    <Field label="Просить подтверждение от, входных токенов"><input type="number" min="0" step="1" value={tokens} onChange={(event) => setTokens(event.target.value)} /></Field>
    <Field label="Курс доллара, ₽"><input type="number" min="0" step="0.01" value={rate} onChange={(event) => setRate(event.target.value)} /></Field>
    <Field label="Дата курса"><input type="date" value={rateDate} onChange={(event) => setRateDate(event.target.value)} /></Field>
  </div><div className="ai-group-actions"><Button onClick={() => void save()}>Сохранить настройки расходов</Button><SaveState>{status}</SaveState></div></section>;
}

function UsagePanel({ settings, runs }: { settings: AiSettingsRead; runs: AiRunRead[] }) {
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const filtered = runs.filter((run) => (
    (!provider || run.provider_id === provider)
    && (!model || run.requested_model_id === model)
    && (!role || run.role === role)
    && (!status || run.status === status)
  ));
  const total = filtered.reduce((sum, run) => sum + (numberValue(run.actual_cost_usd) ?? 0), 0);
  const providerModels = settings.models.filter((item) => !provider || item.provider_id === provider);

  return <section className="ai-settings-group is-first"><header className="ai-group-head"><div><h2>Использование</h2><p>История запросов к ИИ: какая функция работала, сколько токенов потратила и сколько это стоило.</p></div></header><div className="ai-usage-summary"><div><span>Запросов</span><strong>{filtered.length}</strong></div><div><span>Стоимость</span><strong>{money(total)}</strong></div><div><span>Входные токены</span><strong>{filtered.reduce((sum, run) => sum + (run.input_tokens ?? 0), 0).toLocaleString("ru-RU")}</strong></div><div><span>Выходные токены</span><strong>{filtered.reduce((sum, run) => sum + (run.output_tokens ?? 0), 0).toLocaleString("ru-RU")}</strong></div></div><div className="ai-filter-row">
    <Select ariaLabel="Фильтр по провайдеру" value={provider || null} emptyOption="Все провайдеры" onValueChange={(value) => { setProvider(value ?? ""); setModel(""); }} options={settings.providers.map((item) => ({ value: item.id, label: item.label }))} />
    <Select ariaLabel="Фильтр по модели" value={model || null} emptyOption="Все модели" onValueChange={(value) => setModel(value ?? "")} options={providerModels.map((item) => ({ value: item.model_id, label: item.display_name, description: item.model_id }))} />
    <Select ariaLabel="Фильтр по функции" value={role || null} emptyOption="Все функции" onValueChange={(value) => setRole(value ?? "")} options={settings.roles.map((item) => ({ value: item.role, label: item.title }))} />
    <Select ariaLabel="Фильтр по статусу" value={status || null} emptyOption="Все статусы" onValueChange={(value) => setStatus(value ?? "")} options={[{ value: "succeeded", label: "Готово" }, { value: "failed", label: "Ошибка" }, { value: "cached", label: "Из кэша" }, { value: "cancelled", label: "Отменено" }]} />
  </div>{filtered.length ? <div className="ai-table-wrap"><table className="ai-table"><thead><tr><th>Время</th><th>Функция</th><th>Провайдер и модель</th><th>Токены</th><th>Стоимость</th><th>Статус</th></tr></thead><tbody>{filtered.map((run) => <tr key={run.id}><td>{dateTime(run.created_at)}</td><td>{settings.roles.find((item) => item.role === run.role)?.title ?? run.role}</td><td><strong>{run.provider_label_snapshot}</strong><code>{run.requested_model_id}</code></td><td>{(run.input_tokens ?? 0).toLocaleString("ru-RU")} → {(run.output_tokens ?? 0).toLocaleString("ru-RU")}</td><td>{money(run.actual_cost_usd)}</td><td><StatusBadge tone={run.status === "succeeded" || run.status === "cached" ? "success" : run.status === "failed" ? "danger" : "neutral"}>{runStatusLabel(run.status)}</StatusBadge></td></tr>)}</tbody></table></div> : <div className="ai-empty-card"><strong>Подходящих запросов нет</strong><p>Измените фильтры или вернитесь сюда после первого обращения к модели.</p></div>}<Disclosure summary="Какие данные сохраняются"><p className="ai-muted">В журнал попадают провайдер, модель, функция, токены, стоимость и результат. API-ключи, вопросы, ответы модели и полный текст материалов не сохраняются.</p></Disclosure></section>;
}

export function AiSettingsSection({
  subsection,
  onActiveSubsection,
}: {
  subsection: AiSettingsSubsection;
  onActiveSubsection: (subsection: AiSettingsSubsection) => void;
}) {
  const [searchParams] = useSearchParams();
  const [settings, setSettings] = useState<AiSettingsRead | null>(null);
  const [runs, setRuns] = useState<AiRunRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(() => (
    searchParams.get("provider")
  ));
  const initialSubsection = useRef(subsection);
  const initialScrollDone = useRef(false);

  function acceptSettings(next: AiSettingsRead) {
    setSettings(next);
    window.dispatchEvent(new Event("tentex:ai-settings-updated"));
  }

  function navigate(next: AiSettingsSubsection, providerId?: string) {
    if (providerId) setSelectedProviderId(providerId);
    onActiveSubsection(next);
    window.requestAnimationFrame(() => {
      document.getElementById(`ai-${next}`)?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
  }

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    const since = new Date();
    since.setDate(since.getDate() - 30);
    Promise.all([
      getAiSettings(controller.signal),
      listAiRuns({ from: since.toISOString() }, controller.signal),
    ]).then(([nextSettings, nextRuns]) => {
      setSettings(nextSettings);
      setRuns(nextRuns);
    }).catch((caught: unknown) => {
      if (!controller.signal.aborted) {
        setError(caught instanceof Error ? caught.message : "Параметры ИИ не загрузились");
      }
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!settings || initialScrollDone.current) return;
    initialScrollDone.current = true;
    if (initialSubsection.current === "overview") return;
    window.requestAnimationFrame(() => {
      document.getElementById(`ai-${initialSubsection.current}`)?.scrollIntoView({
        block: "start",
      });
    });
  }, [settings]);

  useEffect(() => {
    if (!settings) return;
    const sections = ["overview", "providers", "models", "defaults", "functions", "limits", "usage"]
      .map((id) => document.getElementById(`ai-${id}`))
      .filter((section): section is HTMLElement => section !== null);
    const observer = new IntersectionObserver((entries) => {
      const active = entries
        .filter((entry) => entry.isIntersecting)
        .sort((left, right) => left.boundingClientRect.top - right.boundingClientRect.top)[0];
      if (!active) return;
      onActiveSubsection(active.target.id.replace("ai-", "") as AiSettingsSubsection);
    }, { rootMargin: "-12% 0px -72% 0px", threshold: 0 });
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, [onActiveSubsection, settings]);

  if (loading) return <LoadingState label="Загружаем настройки ИИ" placement="page" />;
  if (error) return <><ErrorState message={error} /><Button onClick={() => window.location.reload()}>Загрузить ещё раз</Button></>;
  if (!settings) return null;
  return <div className="ai-settings">
    <div id="ai-overview" className="ai-anchor-section"><OverviewPanel settings={settings} runs={runs} onSettings={acceptSettings} navigate={navigate} /></div>
    <div id="ai-providers" className="ai-anchor-section"><ProvidersPanel settings={settings} onSettings={acceptSettings} onModels={(id) => navigate("models", id)} /></div>
    <div id="ai-models" className="ai-anchor-section"><ModelsPanel settings={settings} onSettings={acceptSettings} providerId={selectedProviderId} onProvider={setSelectedProviderId} /></div>
    <div id="ai-defaults" className="ai-anchor-section"><DefaultsPanel settings={settings} onSettings={acceptSettings} /></div>
    <div id="ai-functions" className="ai-anchor-section"><FunctionsPanel settings={settings} onSettings={acceptSettings} /></div>
    <div id="ai-limits" className="ai-anchor-section"><LimitsPanel settings={settings} onSettings={acceptSettings} /></div>
    <div id="ai-usage" className="ai-anchor-section"><UsagePanel settings={settings} runs={runs} /></div>
  </div>;
}
