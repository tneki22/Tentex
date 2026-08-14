import {
  KeyRound,
  Pencil,
  Plus,
  RefreshCw,
  Star,
  Trash2,
  Wifi,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import {
  createAiProvider,
  deleteAiCredential,
  deleteAiProvider,
  getAiSettings,
  listAiRuns,
  refreshAiModels,
  testAiModel,
  testAiProvider,
  updateAiDefault,
  updateAiModelFavorites,
  updateAiProvider,
  updateAiProviderFavorites,
  updateAiRole,
  updateAiSettings,
  upsertManualAiModel,
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
  Disclosure,
  ErrorState,
  Field,
  LoadingState,
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

function providerStatus(provider: AiProviderRead) {
  if (!provider.has_api_key) return { label: "Нет ключа", tone: "neutral" as const };
  if (provider.last_test_status === "connected") {
    return { label: "Отвечает", tone: "success" as const };
  }
  if (provider.last_test_status) return { label: "Ошибка", tone: "warning" as const };
  return { label: "Не проверен", tone: "neutral" as const };
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
          <div><h1>Искусственный интеллект</h1><p>Состояние шлюза и быстрые переходы к настройкам.</p></div>
        </header>
        <div className="ai-global-row">
          <Switch
            checked={settings.external_models_enabled}
            onCheckedChange={(enabled) => void toggleExternal(enabled)}
            label="Использовать внешние модели"
            hint="Выключение сохраняет ключи, каталог и журнал. Локальные функции продолжают работать."
          />
          <SaveState>{status}</SaveState>
        </div>
        {!settings.external_models_enabled && (
          <OfflineNotice reason="disabled" alternative="Все настройки ниже остаются доступными." />
        )}
      </section>

      <div className="ai-overview-grid">
        <button type="button" onClick={() => navigate("providers")}>
          <span>Провайдеры</span><strong>{settings.providers.length}</strong>
          <small>{connected} успешно проверено</small>
        </button>
        <button type="button" onClick={() => navigate("models")}>
          <span>Модели</span><strong>{settings.models.filter((model) => model.is_available).length}</strong>
          <small>{favorites.length} в избранном</small>
        </button>
        <button type="button" onClick={() => navigate("usage")}>
          <span>Расход сегодня</span><strong>{money(settings.today_usage.actual_cost_usd)}</strong>
          <small>{todayRunCount} вызовов, {settings.today_usage.cache_hits} из кэша</small>
        </button>
      </div>

      <section className="ai-settings-group">
        <header className="ai-group-head">
          <div>
            <h2>Явные значения по умолчанию</h2>
            <p>Их используют функции без собственного переопределения. Избранное на это не влияет.</p>
          </div>
          <Button variant="secondary" onClick={() => navigate("defaults")}>Настроить</Button>
        </header>
        <div className="ai-default-summary">
          <div><span>Текст</span><strong>{modelName(settings, settings.default_text)}</strong><small>{providerName(settings, settings.default_text?.provider_id ?? null)}</small></div>
          <div><span>Речь</span><strong>{modelName(settings, settings.default_speech)}</strong><small>{providerName(settings, settings.default_speech?.provider_id ?? null)}</small></div>
        </div>
      </section>

      <section className="ai-settings-group">
        <header className="ai-group-head"><div><h2>Избранное</h2><p>Быстрые ярлыки для выбора в чате и настройках; они не меняют поведение функций.</p></div></header>
        <div className="ai-favorite-chips">
          {settings.providers.filter((provider) => provider.is_favorite).map((provider) => (
            <button key={provider.id} type="button" onClick={() => navigate("models", provider.id)}>★ {provider.label}</button>
          ))}
          {favorites.map((model) => <span key={`${model.provider_id}:${model.model_id}`}>★ {model.display_name}</span>)}
          {!settings.providers.some((provider) => provider.is_favorite) && !favorites.length && <small>Избранного пока нет.</small>}
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
        <div><h1>Провайдеры</h1><p>Подключения и ключи хранятся отдельно от моделей и настроек функций.</p></div>
        <Button onClick={() => openEditor()}><Plus size={14} />Добавить провайдера</Button>
      </header>

      {editing && (
        <div className="ai-editor-card">
          <div className="ai-form-grid">
            <Field label="Название" required><input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Например, OpenRouter" /></Field>
            <Field label="Профиль каталога"><select value={profile} onChange={(event) => setProfile(event.target.value as AiProviderWrite["catalog_profile"])}><option value="openrouter">OpenRouter</option><option value="openai_compatible">OpenAI-совместимый</option></select></Field>
            <Field label="Базовый URL" required><input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://…/v1" /></Field>
            <Field label={editing === "new" ? "API-ключ" : "Новый API-ключ"} hint={editing === "new" ? "Сохраняется в зашифрованном виде." : "Оставьте пустым, чтобы сохранить текущий."}><input type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} /></Field>
          </div>
          <div className="ai-group-actions"><Button disabled={busy === "save"} onClick={() => void submit()}>Сохранить</Button><Button variant="ghost" onClick={() => setEditing(null)}>Отмена</Button></div>
        </div>
      )}

      {settings.providers.length ? (
        <div className="ai-table-wrap">
          <table className="ai-table">
            <thead><tr><th>Провайдер</th><th>API-ключ</th><th>Базовый URL</th><th>Статус</th><th>Модели</th><th><span className="sr-only">Действия</span></th></tr></thead>
            <tbody>{settings.providers.map((provider) => {
              const state = providerStatus(provider);
              return <tr key={provider.id}>
                <td><button className="ai-star-button" type="button" aria-label={provider.is_favorite ? "Убрать провайдера из избранного" : "Добавить провайдера в избранное"} onClick={() => void toggleFavorite(provider)}><Star size={15} fill={provider.is_favorite ? "currentColor" : "none"} /></button><strong>{provider.label}</strong><small>{provider.catalog_profile === "openrouter" ? "OpenRouter" : "OpenAI-совместимый"}</small></td>
                <td>{provider.has_api_key ? <StatusBadge tone="success">Сохранён</StatusBadge> : <span className="ai-muted">Не задан</span>}</td>
                <td><code>{provider.base_url}</code></td>
                <td><StatusBadge tone={state.tone}>{state.label}</StatusBadge><small>{dateTime(provider.last_tested_at)}</small></td>
                <td><button type="button" className="ai-link-button" onClick={() => onModels(provider.id)}>{provider.model_count} моделей</button></td>
                <td><div className="ai-row-actions">
                  <Button variant="secondary" disabled={busy === provider.id} onClick={() => void run(provider.id, () => testAiProvider(provider.id), "Подключение отвечает")}><Wifi size={14} />Тест</Button>
                  <Button variant="ghost" disabled={busy === provider.id} aria-label="Обновить каталог" onClick={() => void run(provider.id, () => refreshAiModels(provider.id), "Каталог обновлён")}><RefreshCw size={14} /></Button>
                  <Button variant="ghost" aria-label="Изменить провайдера" onClick={() => openEditor(provider)}><Pencil size={14} /></Button>
                  {provider.has_api_key && <Button variant="ghost" aria-label="Удалить API-ключ" onClick={() => void run(provider.id, () => deleteAiCredential(provider.id), "Ключ удалён")}><KeyRound size={14} /></Button>}
                  <Button variant="ghost" aria-label="Удалить провайдера" onClick={() => setDeleteTarget(provider)}><Trash2 size={14} /></Button>
                </div></td>
              </tr>;
            })}</tbody>
          </table>
        </div>
      ) : <div className="ai-empty-card"><strong>Провайдеров пока нет</strong><p>Добавьте OpenRouter или другой OpenAI-совместимый API.</p></div>}
      <SaveState>{busy ? "Выполняем…" : message}</SaveState>
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
        <p>Каталог этого провайдера будет удалён. Записи журнала сохранят его название.</p>
      </ConfirmDialog>
    </section>
  );
}

function reasoningLabel(model: AiModelRead): string {
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

  if (!selectedProvider) {
    return <section className="ai-settings-group is-first"><header className="ai-group-head"><div><h1>Модели</h1><p>Сначала добавьте провайдера.</p></div></header></section>;
  }

  return (
    <section className="ai-settings-group is-first">
      <header className="ai-group-head">
        <div><h1>Модели</h1><p>Каталог, цены, возможности и базовые параметры выбранного провайдера.</p></div>
        <div className="ai-group-actions"><Button variant="secondary" disabled={busy === "refresh"} onClick={() => void run("refresh", () => refreshAiModels(selectedProvider.id), "Каталог обновлён")}><RefreshCw size={14} />Обновить каталог</Button><Button onClick={() => openManual()}><Plus size={14} />Добавить вручную</Button></div>
      </header>
      <Field label="Провайдер"><select value={selectedProvider.id} onChange={(event) => onProvider(event.target.value)}>{settings.providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.is_favorite ? "★ " : ""}{provider.label}</option>)}</select></Field>

      {adding && <div className="ai-editor-card">
        <div className="ai-form-grid">
          <Field label="ID модели" required><input value={modelId} disabled={editingModel !== null} onChange={(event) => setModelId(event.target.value)} placeholder="vendor/model" /></Field>
          <Field label="Название" required><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></Field>
          <Field label="Контекст, токенов"><input type="number" min="1" value={contextLength} onChange={(event) => setContextLength(event.target.value)} /></Field>
          <Field label="Вход, $ / 1 млн"><input type="number" min="0" step="0.01" value={promptPrice} onChange={(event) => setPromptPrice(event.target.value)} /></Field>
          <Field label="Выход, $ / 1 млн"><input type="number" min="0" step="0.01" value={completionPrice} onChange={(event) => setCompletionPrice(event.target.value)} /></Field>
        </div>
        <p className="ai-muted">Остальные параметры остаются безопасными значениями по умолчанию и при необходимости уточняются после добавления.</p>
        <div className="ai-group-actions"><Button disabled={busy === "manual"} onClick={() => void addManual()}>{editingModel ? "Сохранить" : "Добавить"}</Button><Button variant="ghost" onClick={() => { setAdding(false); setEditingModel(null); }}>Отмена</Button></div>
      </div>}

      {models.length ? <div className="ai-table-wrap"><table className="ai-table ai-model-table">
        <thead><tr><th>Модель</th><th>Цена / 1 млн токенов</th><th>Контекст</th><th>Рассуждение</th><th>Возможности</th><th><span className="sr-only">Действия</span></th></tr></thead>
        <tbody>{models.map((model) => <tr key={`${model.provider_id}:${model.model_id}`} className={!model.is_available ? "is-muted" : ""}>
          <td><button className="ai-star-button" type="button" aria-label={model.favorite_order === null ? "Добавить модель в избранное" : "Убрать модель из избранного"} onClick={() => void toggleFavorite(model)}><Star size={15} fill={model.favorite_order === null ? "none" : "currentColor"} /></button><strong>{model.display_name}</strong><code>{model.model_id}</code>{model.is_manually_added && <small>Добавлена вручную</small>}</td>
          <td><span>Вход {money(model.prompt_price_usd, true)}</span><small>Выход {money(model.completion_price_usd, true)}</small></td>
          <td>{model.context_length?.toLocaleString("ru-RU") ?? "—"}<small>{model.max_completion_tokens ? `ответ до ${model.max_completion_tokens.toLocaleString("ru-RU")}` : "лимит ответа не указан"}</small></td>
          <td>{reasoningLabel(model)}</td>
          <td><div className="ai-tag-list">{model.input_modalities.map((item) => <span key={`in-${item}`}>in: {item}</span>)}{model.output_modalities.map((item) => <span key={`out-${item}`}>out: {item}</span>)}{model.supported_parameters.slice(0, 3).map((item) => <span key={item}>{item}</span>)}</div></td>
          <td><div className="ai-row-actions"><Button variant="secondary" disabled={!model.is_available || busy !== null} onClick={() => void run(model.model_id, () => testAiModel({ provider_id: model.provider_id, model_id: model.model_id }), "Модель ответила")}><Wifi size={14} />Тест</Button><Button variant="ghost" aria-label="Изменить параметры модели" onClick={() => openManual(model)}><Pencil size={14} /></Button></div></td>
        </tr>)}</tbody>
      </table></div> : <div className="ai-empty-card"><strong>Каталог пуст</strong><p>Обновите каталог или добавьте модель вручную.</p></div>}
      <SaveState>{busy ? "Выполняем…" : message}</SaveState>
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
      setStatus("Значение по умолчанию сохранено");
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : "Не сохранено");
    }
  }

  return <div className="ai-panel-stack">
    <section className="ai-settings-group is-first"><header className="ai-group-head"><div><h1>По умолчанию</h1><p>Одна явная пара «провайдер + модель» для каждой модальности.</p></div></header><div className="ai-callout">Избранное — только быстрый список. Эти значения определяют реальное наследование функций.</div></section>
    <section className="ai-settings-group"><h2>Текст</h2><p>Чат, очистка текста, группировка и проверка ответов.</p><ProviderModelPicker providers={settings.providers} models={settings.models} value={text} onChange={setText} /><Button onClick={() => void save("text", text)}>Сохранить для текста</Button></section>
    <section className="ai-settings-group"><h2>Речь</h2><p>Распознавание диктовки; показываются только модели с аудиовходом.</p><ProviderModelPicker providers={settings.providers} models={settings.models} value={speech} modality="speech" onChange={setSpeech} /><Button onClick={() => void save("speech", speech)}>Сохранить для речи</Button></section>
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
    ? `Наследуется: ${providerName(settings, role.resolved_provider_id)} · ${role.resolved_model}`
    : "Общая модель не настроена";
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
  return <section className="ai-settings-group is-first"><header className="ai-group-head"><div><h1>Функции</h1><p>Наследуют общую модель или используют собственную пару провайдера и модели.</p></div></header><div className="ai-role-list">{settings.roles.map((role) => <RoleCard key={role.role} settings={settings} role={role} onSettings={onSettings} />)}</div></section>;
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
      setStatus("Курс и дата снимка задаются вместе.");
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

  return <section className="ai-settings-group is-first"><header className="ai-group-head"><div><h1>Лимиты</h1><p>Жёсткие ограничения останавливают вызов; пороги только просят подтверждение.</p></div></header><div className="ai-form-grid">
    <Field label="Дневной лимит, $" hint="Пусто — без лимита"><input type="number" min="0" step="0.01" value={daily} onChange={(event) => setDaily(event.target.value)} /></Field>
    <Field label="Лимит одной операции, $" hint="Пусто — без лимита"><input type="number" min="0" step="0.01" value={operation} onChange={(event) => setOperation(event.target.value)} /></Field>
    <Field label="Подтверждать стоимость от, $"><input type="number" min="0" step="0.01" value={confirmCost} onChange={(event) => setConfirmCost(event.target.value)} /></Field>
    <Field label="Подтверждать контекст от, токенов"><input type="number" min="0" step="1" value={tokens} onChange={(event) => setTokens(event.target.value)} /></Field>
    <Field label="Курс USD/RUB"><input type="number" min="0" step="0.01" value={rate} onChange={(event) => setRate(event.target.value)} /></Field>
    <Field label="Дата снимка курса"><input type="date" value={rateDate} onChange={(event) => setRateDate(event.target.value)} /></Field>
  </div><div className="ai-group-actions"><Button onClick={() => void save()}>Сохранить лимиты</Button><SaveState>{status}</SaveState></div></section>;
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

  return <section className="ai-settings-group is-first"><header className="ai-group-head"><div><h1>Расход и журнал</h1><p>Безопасный журнал вызовов: провайдер, модель, функция, токены, стоимость и результат.</p></div></header><div className="ai-usage-summary"><div><span>Показано</span><strong>{filtered.length}</strong></div><div><span>Стоимость</span><strong>{money(total)}</strong></div><div><span>Входные токены</span><strong>{filtered.reduce((sum, run) => sum + (run.input_tokens ?? 0), 0).toLocaleString("ru-RU")}</strong></div><div><span>Выходные токены</span><strong>{filtered.reduce((sum, run) => sum + (run.output_tokens ?? 0), 0).toLocaleString("ru-RU")}</strong></div></div><div className="ai-filter-row">
    <select aria-label="Фильтр по провайдеру" value={provider} onChange={(event) => { setProvider(event.target.value); setModel(""); }}><option value="">Все провайдеры</option>{settings.providers.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select>
    <select aria-label="Фильтр по модели" value={model} onChange={(event) => setModel(event.target.value)}><option value="">Все модели</option>{providerModels.map((item) => <option key={`${item.provider_id}:${item.model_id}`} value={item.model_id}>{item.display_name}</option>)}</select>
    <select aria-label="Фильтр по функции" value={role} onChange={(event) => setRole(event.target.value)}><option value="">Все функции</option>{settings.roles.map((item) => <option key={item.role} value={item.role}>{item.title}</option>)}</select>
    <select aria-label="Фильтр по статусу" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">Все статусы</option><option value="succeeded">Успешно</option><option value="failed">Ошибка</option><option value="cached">Из кэша</option><option value="cancelled">Отменено</option></select>
  </div>{filtered.length ? <div className="ai-table-wrap"><table className="ai-table"><thead><tr><th>Время</th><th>Функция</th><th>Провайдер и модель</th><th>Токены</th><th>Стоимость</th><th>Статус</th></tr></thead><tbody>{filtered.map((run) => <tr key={run.id}><td>{dateTime(run.created_at)}</td><td>{settings.roles.find((item) => item.role === run.role)?.title ?? run.role}</td><td><strong>{run.provider_label_snapshot}</strong><code>{run.requested_model_id}</code></td><td>{(run.input_tokens ?? 0).toLocaleString("ru-RU")} → {(run.output_tokens ?? 0).toLocaleString("ru-RU")}</td><td>{money(run.actual_cost_usd)}</td><td><StatusBadge tone={run.status === "succeeded" || run.status === "cached" ? "success" : run.status === "failed" ? "danger" : "neutral"}>{run.status}</StatusBadge></td></tr>)}</tbody></table></div> : <div className="ai-empty-card"><strong>Вызовов по этим фильтрам нет</strong></div>}<Disclosure summary="Что не попадает в журнал"><p className="ai-muted">API-ключи, полный текст страниц, вопросы и ответы модели не копируются. Хранятся только безопасный состав контекста и технические метрики.</p></Disclosure></section>;
}

export function AiSettingsSection({ subsection }: { subsection: AiSettingsSubsection }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [settings, setSettings] = useState<AiSettingsRead | null>(null);
  const [runs, setRuns] = useState<AiRunRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  function acceptSettings(next: AiSettingsRead) {
    setSettings(next);
    window.dispatchEvent(new Event("tentex:ai-settings-updated"));
  }

  function navigate(next: AiSettingsSubsection, providerId?: string) {
    const params = new URLSearchParams({ section: "ai", subsection: next });
    if (providerId) params.set("provider", providerId);
    setSearchParams(params);
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

  const providerId = searchParams.get("provider");
  const content = useMemo(() => {
    if (!settings) return null;
    if (subsection === "overview") return <OverviewPanel settings={settings} runs={runs} onSettings={acceptSettings} navigate={navigate} />;
    if (subsection === "providers") return <ProvidersPanel settings={settings} onSettings={acceptSettings} onModels={(id) => navigate("models", id)} />;
    if (subsection === "models") return <ModelsPanel settings={settings} onSettings={acceptSettings} providerId={providerId} onProvider={(id) => navigate("models", id)} />;
    if (subsection === "defaults") return <DefaultsPanel settings={settings} onSettings={acceptSettings} />;
    if (subsection === "functions") return <FunctionsPanel settings={settings} onSettings={acceptSettings} />;
    if (subsection === "limits") return <LimitsPanel settings={settings} onSettings={acceptSettings} />;
    return <UsagePanel settings={settings} runs={runs} />;
  }, [providerId, runs, settings, subsection]);

  if (loading) return <LoadingState label="Загружаем настройки ИИ" placement="page" />;
  if (error) return <><ErrorState message={error} /><Button onClick={() => window.location.reload()}>Повторить</Button></>;
  return <div className="ai-settings">{content}</div>;
}
