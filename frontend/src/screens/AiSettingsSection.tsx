import {
  Check,
  CircleAlert,
  CircleCheck,
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
  deleteAiModel,
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
  Checkbox,
  ConfirmDialog,
  Dialog,
  Disclosure,
  ErrorState,
  Field,
  IconButton,
  LoadingState,
  Menu,
  Popover,
  SegmentedTabs,
  Select,
  StatusBadge,
  Switch,
} from "../components/ui";
import type { AiSettingsSubsection } from "./Setup";

/** Запрос «покажи вот эту модель в списке»: nonce нужен, чтобы повторный клик тоже сработал. */
interface FocusRequest {
  selection: AiModelSelection;
  nonce: number;
}

type NoteTone = "muted" | "success" | "danger";

interface Note {
  text: string;
  tone: NoteTone;
}

interface TestOutcome {
  status: "pending" | "ok" | "fail";
  title: string;
  detail: string;
  facts?: { label: string; value: string }[];
}

const MODALITY_LABELS: Record<string, string> = {
  text: "текст",
  image: "изображение",
  audio: "аудио",
  file: "файл",
  video: "видео",
};

function modelKey(selection: { provider_id: string; model_id: string }): string {
  return `${selection.provider_id}:${selection.model_id}`;
}

function modelDomId(selection: { provider_id: string; model_id: string }): string {
  return `ai-model-${modelKey(selection)}`;
}

function sameModel(
  left: { provider_id: string; model_id: string },
  right: { provider_id: string; model_id: string } | null | undefined,
): boolean {
  return right !== null && right !== undefined
    && left.provider_id === right.provider_id && left.model_id === right.model_id;
}

function errorText(caught: unknown, fallback: string): string {
  return caught instanceof Error ? caught.message : fallback;
}

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

function duration(ms: number): string {
  return ms < 1000 ? `${ms} мс` : `${(ms / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} с`;
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

function profileLabel(profile: AiProviderRead["catalog_profile"]): string {
  return profile === "openrouter" ? "OpenRouter" : "OpenAI-совместимый API";
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
  return settings.models.find((model) => sameModel(model, selection))?.display_name
    ?? selection.model_id;
}

function selectionForRole(role: AiRoleRead): AiModelSelection | null {
  return role.provider_override_id && role.model_override
    ? { provider_id: role.provider_override_id, model_id: role.model_override }
    : null;
}

/**
 * Итог действия: «Сохранено» зелёным, отказ — красным. Раньше это была серая
 * строчка в 12px, которую пользователь просто не замечал.
 */
function StatusNote({ note }: { note: Note | null }) {
  if (!note?.text) return <span className="ai-save-state" role="status" aria-live="polite" />;
  return (
    <span className={`ai-save-state is-${note.tone}`} role="status" aria-live="polite">
      {note.tone === "success" && <Check size={15} aria-hidden="true" />}
      {note.tone === "danger" && <CircleAlert size={15} aria-hidden="true" />}
      {note.text}
    </span>
  );
}

/** Результат теста: крупный блок под карточкой, а не строчка внизу раздела. */
function TestResult({ result }: { result: TestOutcome | null }) {
  if (!result) return null;
  return (
    <div className={`ai-test-result is-${result.status}`} role="status" aria-live="polite">
      {result.status === "pending" && <span className="ai-test-result-spinner" aria-hidden="true" />}
      {result.status === "ok" && <CircleCheck size={20} aria-hidden="true" />}
      {result.status === "fail" && <CircleAlert size={20} aria-hidden="true" />}
      <div>
        <strong>Результат теста: {result.title}</strong>
        {result.detail && <p>{result.detail}</p>}
        {result.facts && result.facts.length > 0 && (
          <dl className="ai-test-result-facts">
            {result.facts.map((fact) => (
              <div key={fact.label}><dt>{fact.label}</dt><dd>{fact.value}</dd></div>
            ))}
          </dl>
        )}
      </div>
    </div>
  );
}

/**
 * Возможности модели: две метки на виду, остальные — во всплывашке. Полный
 * список занимал половину карточки и мешал читать цену и контекст.
 */
function CapabilityTags({ model }: { model: AiModelRead }) {
  const tags = [
    ...model.input_modalities.map((item) => `Вход: ${MODALITY_LABELS[item] ?? item}`),
    ...model.output_modalities.map((item) => `Выход: ${MODALITY_LABELS[item] ?? item}`),
    ...model.supported_parameters,
  ];
  if (!tags.length) return <strong className="ai-capability-empty">Не указаны</strong>;
  const visible = tags.slice(0, 2);
  const hidden = tags.length - visible.length;

  return (
    <div className="ai-tag-list">
      {visible.map((tag) => <span key={tag}>{tag}</span>)}
      {hidden > 0 && (
        <Popover
          side="top"
          align="start"
          title={`Возможности — ${model.display_name}`}
          className="ai-capability-popover"
          trigger={(
            <button type="button" className="ai-tag-more">
              Ещё {hidden}
            </button>
          )}
        >
          <div className="ai-tag-list">
            {tags.map((tag) => <span key={tag}>{tag}</span>)}
          </div>
        </Popover>
      )}
    </div>
  );
}

function OverviewPanel({
  settings,
  runs,
  onSettings,
  navigate,
  onFocusModel,
}: {
  settings: AiSettingsRead;
  runs: AiRunRead[];
  onSettings: (settings: AiSettingsRead) => void;
  navigate: (subsection: AiSettingsSubsection, providerId?: string) => void;
  onFocusModel: (selection: AiModelSelection) => void;
}) {
  const [note, setNote] = useState<Note | null>(null);
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
    setNote({ text: "Сохраняем…", tone: "muted" });
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
      setNote({ text: "Сохранено", tone: "success" });
    } catch (caught) {
      setNote({ text: errorText(caught, "Не сохранено"), tone: "danger" });
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
          <StatusNote note={note} />
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
          {([
            ["Текст", settings.default_text],
            ["Речь", settings.default_speech],
          ] as const).map(([label, selection]) => (
            <button
              key={label}
              type="button"
              disabled={!selection}
              onClick={() => selection && onFocusModel(selection)}
            >
              <span>{label}</span>
              <strong>{modelName(settings, selection)}</strong>
              <small>{providerName(settings, selection?.provider_id ?? null)}</small>
            </button>
          ))}
        </div>
      </section>

      <section className="ai-settings-group">
        <header className="ai-group-head"><div><h3>Избранное</h3><p>Избранные провайдеры и модели показываются выше в списках, чтобы их было проще найти.</p></div></header>
        <div className="ai-favorite-chips">
          {settings.providers.filter((provider) => provider.is_favorite).map((provider) => (
            <button key={provider.id} type="button" onClick={() => navigate("models", provider.id)}>★ {provider.label}</button>
          ))}
          {favorites.map((model) => (
            <button key={modelKey(model)} type="button" onClick={() => onFocusModel(model)}>
              ★ {model.display_name}
            </button>
          ))}
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
  const [note, setNote] = useState<Note | null>(null);
  const [tests, setTests] = useState<Record<string, TestOutcome>>({});
  const [deleteTarget, setDeleteTarget] = useState<AiProviderRead | null>(null);

  function openEditor(provider?: AiProviderRead) {
    setEditing(provider?.id ?? "new");
    setLabel(provider?.label ?? "");
    setProfile(provider?.catalog_profile ?? "openrouter");
    setBaseUrl(provider?.base_url ?? "https://openrouter.ai/api/v1");
    setApiKey("");
    setNote(null);
  }

  async function run(key: string, action: () => Promise<AiSettingsRead | unknown>, done: string) {
    setBusy(key);
    setNote(null);
    try {
      const result = await action();
      onSettings(result && typeof result === "object" && "providers" in result
        ? result as AiSettingsRead
        : await getAiSettings());
      setNote({ text: done, tone: "success" });
    } catch (caught) {
      setNote({ text: errorText(caught, "Действие не выполнено"), tone: "danger" });
    } finally {
      setBusy(null);
    }
  }

  async function testProvider(provider: AiProviderRead) {
    setBusy(provider.id);
    setNote(null);
    setTests((current) => ({ ...current, [provider.id]: {
      status: "pending", title: "проверяем подключение…", detail: "",
    } }));
    try {
      const result = await testAiProvider(provider.id);
      onSettings(await getAiSettings());
      setTests((current) => ({ ...current, [provider.id]: {
        status: "ok",
        title: "провайдер отвечает",
        detail: `В каталоге провайдера доступно ${modelCountText(result.model_count)}.`,
      } }));
    } catch (caught) {
      onSettings(await getAiSettings());
      setTests((current) => ({ ...current, [provider.id]: {
        status: "fail",
        title: "провайдер не ответил",
        detail: errorText(caught, "Подключение не удалось"),
      } }));
    } finally {
      setBusy(null);
    }
  }

  async function submit() {
    if (!label.trim() || !baseUrl.trim()) {
      setNote({ text: "Укажите название и базовый URL.", tone: "danger" });
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
      : updateAiProvider(editing!, command), "Сохранено");
    setEditing(null);
  }

  async function toggleFavorite(provider: AiProviderRead) {
    const ids = settings.providers
      .filter((item) => item.is_favorite !== (item.id === provider.id))
      .map((item) => item.id);
    await run(
      provider.id,
      () => updateAiProviderFavorites(ids),
      provider.is_favorite ? "Убрано из избранного" : "Добавлено в избранное",
    );
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
            return <article className="ai-provider-card" key={provider.id}>
              <header className="ai-provider-card-head">
                <button className="ai-star-button" type="button" aria-label={provider.is_favorite ? "Убрать провайдера из избранного" : "Добавить провайдера в избранное"} aria-pressed={provider.is_favorite} onClick={() => void toggleFavorite(provider)}><Star size={17} fill={provider.is_favorite ? "currentColor" : "none"} /></button>
                <div className="ai-provider-card-title">
                  <strong>{provider.label}</strong>
                  <small>{profileLabel(provider.catalog_profile)}</small>
                </div>
                <div className="ai-provider-card-actions">
                  <Button variant="secondary" disabled={busy === provider.id} onClick={() => void testProvider(provider)}><Wifi size={14} />Тест</Button>
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
              </header>
              <dl className="ai-provider-card-facts">
                <div>
                  <dt>API-ключ</dt>
                  <dd><StatusBadge tone="neutral">{provider.has_api_key ? "Добавлен" : "Не добавлен"}</StatusBadge></dd>
                </div>
                <div>
                  <dt>Подключение</dt>
                  <dd><StatusBadge tone={state.tone}>{state.label}</StatusBadge></dd>
                  <small>{provider.last_tested_at ? dateTime(provider.last_tested_at) : "Тест ещё не запускался"}</small>
                </div>
                <div>
                  <dt>Модели</dt>
                  <dd>
                    <button type="button" className="ai-link-button" onClick={() => onModels(provider.id)}>
                      {modelCountText(provider.model_count)}
                    </button>
                  </dd>
                  <small>Открыть список</small>
                </div>
                <div className="ai-provider-url">
                  <dt>Базовый URL</dt>
                  <dd><code>{provider.base_url}</code></dd>
                </div>
              </dl>
              <TestResult result={tests[provider.id] ?? null} />
            </article>;
          })}
        </div>
      ) : <div className="ai-empty-card"><strong>Провайдеров пока нет</strong><p>Добавьте OpenRouter или другой сервис с OpenAI-совместимым API.</p></div>}
      <StatusNote note={busy ? { text: "Подождите…", tone: "muted" } : note} />
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

/** Что модель умеет: то, что нельзя вычитать из ID и приходится задавать руками. */
interface ModelCapabilities {
  text: boolean;
  image: boolean;
  audio: boolean;
  file: boolean;
  output: boolean;
  structured: boolean;
}

function capabilitiesOf(model: AiModelRead | null): ModelCapabilities {
  return {
    text: model ? model.input_modalities.includes("text") : true,
    image: model?.input_modalities.includes("image") ?? false,
    audio: model?.input_modalities.includes("audio") ?? false,
    file: model?.input_modalities.includes("file") ?? false,
    output: model ? model.output_modalities.includes("text") : true,
    structured: model?.supported_parameters.includes("response_format") ?? false,
  };
}

function ModelCard({
  model,
  provider,
  busy,
  focused,
  testResult,
  onToggleFavorite,
  onEdit,
  onTest,
  onDelete,
}: {
  model: AiModelRead;
  provider: AiProviderRead;
  busy: boolean;
  focused: boolean;
  testResult: TestOutcome | null;
  onToggleFavorite: () => void;
  onEdit: () => void;
  onTest: () => void;
  onDelete: () => void;
}) {
  return (
    <article
      id={modelDomId(model)}
      className={`ai-model-row ${!model.is_available ? "is-muted" : ""} ${focused ? "is-focused" : ""}`.trim()}
    >
      <div className="ai-model-identity">
        <button
          className="ai-star-button"
          type="button"
          aria-label={model.favorite_order === null ? "Добавить модель в избранное" : "Убрать модель из избранного"}
          aria-pressed={model.favorite_order !== null}
          onClick={onToggleFavorite}
        >
          <Star size={17} fill={model.favorite_order === null ? "none" : "currentColor"} />
        </button>
        <div>
          <strong>{model.display_name}</strong>
          <code>{model.model_id}</code>
          {model.is_manually_added && <small>Добавлена вручную</small>}
        </div>
      </div>
      <div className="ai-model-facts">
        <div><span>Цена за 1 млн токенов</span><strong>Вход {money(model.prompt_price_usd, true)}</strong><small>Выход {money(model.completion_price_usd, true)}</small></div>
        <div><span>Контекст</span><strong>{model.context_length?.toLocaleString("ru-RU") ?? "Не указан"}</strong><small>{model.max_completion_tokens ? `Ответ до ${model.max_completion_tokens.toLocaleString("ru-RU")}` : "Лимит ответа не указан"}</small></div>
        <div><span>Рассуждение</span><strong>{reasoningLabel(model)}</strong></div>
        <div><span>Возможности</span><CapabilityTags model={model} /></div>
      </div>
      <div className="ai-model-actions">
        <Button variant="secondary" disabled={!model.is_available || busy} onClick={onTest}>
          <Wifi size={14} />Тест
        </Button>
        <IconButton label="Изменить модель" onClick={onEdit}><Pencil size={16} /></IconButton>
        <Menu
          label={`Действия с моделью ${model.display_name}`}
          trigger={<IconButton label="Ещё действия"><MoreHorizontal size={17} /></IconButton>}
          items={[
            { label: "Изменить модель", icon: <Pencil size={14} />, onSelect: onEdit },
            {
              label: model.favorite_order === null ? "В избранное" : "Убрать из избранного",
              icon: <Star size={14} />,
              onSelect: onToggleFavorite,
            },
            { label: "Удалить модель", icon: <Trash2 size={14} />, onSelect: onDelete, destructive: true },
          ]}
        />
      </div>
      <TestResult result={testResult} />
      {!model.is_available && <p className="ai-model-warning">Модели нет в актуальном каталоге {provider.label}.</p>}
    </article>
  );
}

function ModelsPanel({
  settings,
  onSettings,
  providerId,
  onProvider,
  focusRequest,
}: {
  settings: AiSettingsRead;
  onSettings: (settings: AiSettingsRead) => void;
  providerId: string | null;
  onProvider: (providerId: string) => void;
  focusRequest: FocusRequest | null;
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
  const [capabilities, setCapabilities] = useState<ModelCapabilities>(capabilitiesOf(null));
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const [tests, setTests] = useState<Record<string, TestOutcome>>({});
  const [deleteTarget, setDeleteTarget] = useState<AiModelRead | null>(null);
  const [restOpen, setRestOpen] = useState(false);
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const lastFocusNonce = useRef<number | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [catalog, setCatalog] = useState<AiCatalogModelRead[]>([]);
  const [catalogQuery, setCatalogQuery] = useState("");
  const [catalogScope, setCatalogScope] = useState<"all" | "added" | "new">("all");
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [addingCatalogModel, setAddingCatalogModel] = useState<string | null>(null);
  const favorites = settings.models
    .filter((model) => model.favorite_order !== null)
    .sort((left, right) => (left.favorite_order ?? 0) - (right.favorite_order ?? 0));
  const favoriteModels = models.filter((model) => model.favorite_order !== null);
  const restModels = models.filter((model) => model.favorite_order === null);
  // Пока избранного нет, прятать весь список не за чем — экран выглядел бы пустым.
  const splitByFavorites = favoriteModels.length > 0;

  useEffect(() => {
    if (!focusRequest || focusRequest.nonce === lastFocusNonce.current) return;
    lastFocusNonce.current = focusRequest.nonce;
    const { selection } = focusRequest;
    const isFavorite = settings.models.some((model) => (
      sameModel(model, selection) && model.favorite_order !== null
    ));
    if (!isFavorite) setRestOpen(true);
    setHighlighted(modelKey(selection));
    // Два кадра: за первый React дорисует раскрытый список, за второй он уже в DOM.
    const frame = window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        document.getElementById(modelDomId(selection))
          ?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    });
    const timer = window.setTimeout(() => setHighlighted(null), 2600);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [focusRequest, settings.models]);

  async function run(key: string, action: () => Promise<unknown>, done: string) {
    setBusy(key);
    setNote(null);
    try {
      const result = await action();
      onSettings(result && typeof result === "object" && "providers" in result
        ? result as AiSettingsRead
        : await getAiSettings());
      setNote({ text: done, tone: "success" });
      return true;
    } catch (caught) {
      setNote({ text: errorText(caught, "Действие не выполнено"), tone: "danger" });
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function testModel(model: AiModelRead) {
    const key = modelKey(model);
    setBusy(key);
    setNote(null);
    setTests((current) => ({ ...current, [key]: { status: "pending", title: "спрашиваем модель…", detail: "" } }));
    try {
      const result = await testAiModel({ provider_id: model.provider_id, model_id: model.model_id });
      const facts = [
        { label: "Время ответа", value: duration(result.duration_ms) },
        { label: "Токены", value: `${result.input_tokens} → ${result.output_tokens}` },
      ];
      if (result.actual_model_id && result.actual_model_id !== model.model_id) {
        facts.push({ label: "Ответила модель", value: result.actual_model_id });
      }
      setTests((current) => ({ ...current, [key]: {
        status: "ok",
        title: "модель ответила",
        detail: `«${result.answer}»`,
        facts,
      } }));
      onSettings(await getAiSettings());
    } catch (caught) {
      setTests((current) => ({ ...current, [key]: {
        status: "fail",
        title: "модель не ответила",
        detail: errorText(caught, "Запрос к модели не прошёл"),
      } }));
    } finally {
      setBusy(null);
    }
  }

  async function toggleFavorite(model: AiModelRead) {
    const next = model.favorite_order === null
      ? [...favorites.map(({ provider_id, model_id }) => ({ provider_id, model_id })), { provider_id: model.provider_id, model_id: model.model_id }]
      : favorites.filter((item) => !sameModel(item, model))
        .map(({ provider_id, model_id }) => ({ provider_id, model_id }));
    await run(
      modelKey(model),
      () => updateAiModelFavorites(next),
      model.favorite_order === null
        ? `«${model.display_name}» в избранном`
        : `«${model.display_name}» убрана из избранного`,
    );
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
    setCapabilities(capabilitiesOf(model));
    setAdding(true);
    setNote(null);
  }

  async function addManual() {
    if (!selectedProvider || !modelId.trim() || !displayName.trim()) {
      setNote({ text: "Укажите ID и название модели.", tone: "danger" });
      return;
    }
    const inputModalities = (["text", "image", "audio", "file"] as const)
      .filter((item) => capabilities[item]);
    const supported = new Set(editingModel?.supported_parameters ?? []);
    if (capabilities.structured) supported.add("response_format");
    else supported.delete("response_format");
    const saved = await run("manual", () => upsertManualAiModel(selectedProvider.id, {
      model_id: modelId.trim(),
      display_name: displayName.trim(),
      context_length: contextLength ? Number(contextLength) : null,
      max_completion_tokens: editingModel?.max_completion_tokens ?? null,
      supported_parameters: [...supported],
      input_modalities: inputModalities.length ? inputModalities : ["text"],
      output_modalities: capabilities.output ? ["text"] : [],
      reasoning: editingModel?.reasoning ?? {},
      default_parameters: editingModel?.default_parameters ?? {},
      prompt_price_usd: promptPrice ? Number(promptPrice) / 1_000_000 : null,
      completion_price_usd: completionPrice ? Number(completionPrice) / 1_000_000 : null,
      knowledge_cutoff: editingModel?.knowledge_cutoff ?? null,
      expiration_date: editingModel?.expiration_date ?? null,
    }), "Сохранено");
    if (!saved) return;
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
    setCatalogScope("all");
    setCatalogError("");
    setCatalogLoading(true);
    try {
      setCatalog(await searchAiModels(selectedProvider.id));
    } catch (caught) {
      setCatalogError(errorText(
        caught,
        "Не удалось получить список моделей. Проверьте подключение и попробуйте снова.",
      ));
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
      setNote({ text: `Модель «${model.display_name}» добавлена`, tone: "success" });
    } catch (caught) {
      setCatalogError(errorText(caught, "Не удалось добавить модель."));
    } finally {
      setAddingCatalogModel(null);
    }
  }

  const normalizedCatalogQuery = catalogQuery.trim().toLocaleLowerCase("ru");
  const catalogMatches = catalog.filter((model) => (
    (!normalizedCatalogQuery
      || model.display_name.toLocaleLowerCase("ru").includes(normalizedCatalogQuery)
      || model.model_id.toLocaleLowerCase("ru").includes(normalizedCatalogQuery))
    && (catalogScope === "all"
      || (catalogScope === "added" ? model.is_added : !model.is_added))
  ));
  const visibleCatalogMatches = catalogMatches.slice(0, 60);
  const addedCount = catalog.filter((model) => model.is_added).length;

  if (!selectedProvider) {
    return <section className="ai-settings-group is-first"><header className="ai-group-head"><div><h2>Модели</h2><p>Сначала добавьте провайдера — после этого здесь можно будет выбрать нужные модели.</p></div></header></section>;
  }

  const renderModel = (model: AiModelRead) => (
    <ModelCard
      key={modelKey(model)}
      model={model}
      provider={selectedProvider}
      busy={busy === modelKey(model)}
      focused={highlighted === modelKey(model)}
      testResult={tests[modelKey(model)] ?? null}
      onToggleFavorite={() => void toggleFavorite(model)}
      onEdit={() => openManual(model)}
      onTest={() => void testModel(model)}
      onDelete={() => setDeleteTarget(model)}
    />
  );

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
        <fieldset className="ai-capability-fieldset">
          <legend>Возможности</legend>
          <p className="ai-muted">Каталог провайдера не всегда отдаёт эти данные. Отметьте вручную — иначе модель не появится там, где нужна: без «принимает аудио» её нельзя выбрать для распознавания речи.</p>
          <div className="ai-capability-grid">
            <Checkbox checked={capabilities.text} onCheckedChange={(value) => setCapabilities((current) => ({ ...current, text: value }))} label="Принимает текст" />
            <Checkbox checked={capabilities.image} onCheckedChange={(value) => setCapabilities((current) => ({ ...current, image: value }))} label="Принимает изображения" />
            <Checkbox checked={capabilities.audio} onCheckedChange={(value) => setCapabilities((current) => ({ ...current, audio: value }))} label="Принимает аудио" />
            <Checkbox checked={capabilities.file} onCheckedChange={(value) => setCapabilities((current) => ({ ...current, file: value }))} label="Принимает файлы" />
            <Checkbox checked={capabilities.output} onCheckedChange={(value) => setCapabilities((current) => ({ ...current, output: value }))} label="Отвечает текстом" />
            <Checkbox checked={capabilities.structured} onCheckedChange={(value) => setCapabilities((current) => ({ ...current, structured: value }))} label="Структурный ответ (response_format)" />
          </div>
        </fieldset>
        <p className="ai-muted">Если цена или размер контекста неизвестны, оставьте поле пустым. Эти данные можно добавить позже.</p>
        <div className="ai-group-actions"><Button disabled={busy === "manual"} onClick={() => void addManual()}>{editingModel ? "Сохранить изменения" : "Добавить модель"}</Button><Button variant="ghost" onClick={() => { setAdding(false); setEditingModel(null); }}>Отменить</Button><StatusNote note={note} /></div>
      </div>}

      {models.length ? <>
        <div className="ai-model-list">
          {(splitByFavorites ? favoriteModels : models).map(renderModel)}
        </div>
        {splitByFavorites && restModels.length > 0 && (
          <Disclosure
            summary={`Остальные модели провайдера (${restModels.length})`}
            open={restOpen}
            onOpenChange={setRestOpen}
          >
            <div className="ai-model-list">{restModels.map(renderModel)}</div>
          </Disclosure>
        )}
      </> : <div className="ai-empty-card"><strong>Модели ещё не добавлены</strong><p>Найдите модель у провайдера или добавьте её по ID.</p></div>}
      <StatusNote note={busy ? { text: "Подождите…", tone: "muted" } : note} />

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title={`Удалить модель «${deleteTarget?.display_name ?? ""}»?`}
        confirmLabel="Удалить модель"
        destructive
        onConfirm={() => {
          if (!deleteTarget) return;
          void run(
            modelKey(deleteTarget),
            () => deleteAiModel({ provider_id: deleteTarget.provider_id, model_id: deleteTarget.model_id }),
            "Модель удалена",
          );
          setDeleteTarget(null);
        }}
      >
        <p>Модель исчезнет из списков выбора. Записи в журнале использования останутся, добавить её снова можно поиском по каталогу провайдера.</p>
      </ConfirmDialog>

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
          <div className="ai-search-controls">
            <SegmentedTabs
              label="Какие модели показывать"
              value={catalogScope}
              onChange={setCatalogScope}
              tabs={[
                { value: "all", label: `Все (${catalog.length})` },
                { value: "added", label: `Добавленные (${addedCount})` },
                { value: "new", label: `Ещё не добавлены (${catalog.length - addedCount})` },
              ]}
            />
            <span className="ai-search-count">Найдено: {catalogMatches.length}</span>
          </div>
          {visibleCatalogMatches.length ? <div className="ai-catalog-results">
            {visibleCatalogMatches.map((model) => <article key={model.model_id} className={`ai-catalog-row ${model.is_added ? "is-added" : ""}`.trim()}>
              <div>
                <strong>{model.display_name}</strong>
                <code>{model.model_id}</code>
                {model.is_added && <StatusBadge tone="success">Уже добавлена</StatusBadge>}
              </div>
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
  const [note, setNote] = useState<Note | null>(null);
  useEffect(() => { setText(settings.default_text); setSpeech(settings.default_speech); }, [settings.default_text, settings.default_speech]);
  const hasSpeechModel = settings.models.some((model) => model.input_modalities.includes("audio"));

  async function save(modality: "text" | "speech", selection: AiModelSelection | null) {
    setNote({ text: "Сохраняем…", tone: "muted" });
    try {
      onSettings(await updateAiDefault(modality, selection));
      setNote({ text: "Сохранено", tone: "success" });
    } catch (caught) {
      setNote({ text: errorText(caught, "Не сохранено"), tone: "danger" });
    }
  }

  return <div className="ai-panel-stack">
    <section className="ai-settings-group is-first"><header className="ai-group-head"><div><h2>Модели по умолчанию</h2><p>Выберите основные модели для текста и речи.</p></div></header><div className="ai-callout">Если у функции не выбрана своя модель, она использует настройку из этого раздела. Избранное влияет только на порядок в списках.</div></section>
    <section className="ai-settings-group"><h3>Для текста</h3><p>Используется в чате, очистке текста, группировке и проверке ответов.</p><ProviderModelPicker providers={settings.providers} models={settings.models} value={text} onChange={setText} /><Button onClick={() => void save("text", text)}>Сохранить модель для текста</Button></section>
    <section className="ai-settings-group">
      <h3>Для речи</h3>
      <p>Используется для распознавания голоса. В списке показываются только подходящие модели.</p>
      {!hasSpeechModel && <div className="ai-callout">Ни одна добавленная модель не принимает аудио. Откройте раздел «Модели», нажмите на модели карандаш и отметьте «Принимает аудио» — каталог провайдера не всегда отдаёт это поле.</div>}
      <ProviderModelPicker providers={settings.providers} models={settings.models} value={speech} modality="speech" onChange={setSpeech} />
      <Button onClick={() => void save("speech", speech)}>Сохранить модель для речи</Button>
    </section>
    <StatusNote note={note} />
  </div>;
}

function RoleCard({ settings, role, onSettings }: { settings: AiSettingsRead; role: AiRoleRead; onSettings: (settings: AiSettingsRead) => void }) {
  const [note, setNote] = useState<Note | null>(null);
  const [maxTokens, setMaxTokens] = useState(String(role.parameters.max_output_tokens ?? ""));
  const [temperature, setTemperature] = useState(String(role.parameters.temperature ?? ""));
  const [language, setLanguage] = useState(String(role.parameters.language ?? "ru"));

  async function save(patch: { enabled?: boolean; selection?: AiModelSelection | null; parameters?: Record<string, unknown> }) {
    const selection = patch.selection === undefined ? selectionForRole(role) : patch.selection;
    setNote({ text: "Сохраняем…", tone: "muted" });
    try {
      onSettings(await updateAiRole(role.role, {
        enabled: patch.enabled ?? role.enabled,
        provider_override_id: selection?.provider_id ?? null,
        model_override: selection?.model_id ?? null,
        parameters: patch.parameters ?? role.parameters,
      }));
      setNote({ text: "Сохранено", tone: "success" });
    } catch (caught) {
      setNote({ text: errorText(caught, "Не сохранено"), tone: "danger" });
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
    <StatusNote note={note} />
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
  const [note, setNote] = useState<Note | null>(null);

  async function save() {
    if (Boolean(rate) !== Boolean(rateDate)) {
      setNote({ text: "Укажите и курс, и дату — либо оставьте оба поля пустыми.", tone: "danger" });
      return;
    }
    setNote({ text: "Сохраняем…", tone: "muted" });
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
      setNote({ text: "Сохранено", tone: "success" });
    } catch (caught) {
      setNote({ text: errorText(caught, "Не сохранено"), tone: "danger" });
    }
  }

  return <section className="ai-settings-group is-first"><header className="ai-group-head"><div><h2>Расходы и подтверждения</h2><p>Задайте лимиты расходов и выберите, когда Tentex должен просить подтверждение.</p></div></header><div className="ai-form-grid">
    <Field label="Дневной лимит, $" hint="Пусто — без лимита"><input type="number" min="0" step="0.01" value={daily} onChange={(event) => setDaily(event.target.value)} /></Field>
    <Field label="Лимит одной операции, $" hint="Пусто — без лимита"><input type="number" min="0" step="0.01" value={operation} onChange={(event) => setOperation(event.target.value)} /></Field>
    <Field label="Просить подтверждение при цене от, $"><input type="number" min="0" step="0.01" value={confirmCost} onChange={(event) => setConfirmCost(event.target.value)} /></Field>
    <Field label="Просить подтверждение от, входных токенов"><input type="number" min="0" step="1" value={tokens} onChange={(event) => setTokens(event.target.value)} /></Field>
    <Field label="Курс доллара, ₽"><input type="number" min="0" step="0.01" value={rate} onChange={(event) => setRate(event.target.value)} /></Field>
    <Field label="Дата курса"><input type="date" value={rateDate} onChange={(event) => setRateDate(event.target.value)} /></Field>
  </div><div className="ai-group-actions"><Button onClick={() => void save()}>Сохранить настройки расходов</Button><StatusNote note={note} /></div></section>;
}

const USAGE_PAGE_SIZE = 20;

function UsagePanel({ settings, runs }: { settings: AiSettingsRead; runs: AiRunRead[] }) {
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const filtered = runs.filter((run) => (
    (!provider || run.provider_id === provider)
    && (!model || run.requested_model_id === model)
    && (!role || run.role === role)
    && (!status || run.status === status)
  ));
  const total = filtered.reduce((sum, run) => sum + (numberValue(run.actual_cost_usd) ?? 0), 0);
  const providerModels = settings.models.filter((item) => !provider || item.provider_id === provider);
  const pageCount = Math.max(1, Math.ceil(filtered.length / USAGE_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pageRuns = filtered.slice((currentPage - 1) * USAGE_PAGE_SIZE, currentPage * USAGE_PAGE_SIZE);

  function setFilter(setter: (value: string) => void, value: string) {
    setter(value);
    setPage(1);
  }

  return <section className="ai-settings-group is-first"><header className="ai-group-head"><div><h2>Использование</h2><p>История запросов к ИИ: какая функция работала, сколько токенов потратила и сколько это стоило.</p></div></header><div className="ai-usage-summary"><div><span>Запросов</span><strong>{filtered.length}</strong></div><div><span>Стоимость</span><strong>{money(total)}</strong></div><div><span>Входные токены</span><strong>{filtered.reduce((sum, run) => sum + (run.input_tokens ?? 0), 0).toLocaleString("ru-RU")}</strong></div><div><span>Выходные токены</span><strong>{filtered.reduce((sum, run) => sum + (run.output_tokens ?? 0), 0).toLocaleString("ru-RU")}</strong></div></div><div className="ai-filter-row">
    <Select ariaLabel="Фильтр по провайдеру" value={provider || null} emptyOption="Все провайдеры" onValueChange={(value) => { setFilter(setProvider, value ?? ""); setModel(""); }} options={settings.providers.map((item) => ({ value: item.id, label: item.label }))} />
    <Select ariaLabel="Фильтр по модели" value={model || null} emptyOption="Все модели" onValueChange={(value) => setFilter(setModel, value ?? "")} options={providerModels.map((item) => ({ value: item.model_id, label: item.display_name, description: item.model_id }))} />
    <Select ariaLabel="Фильтр по функции" value={role || null} emptyOption="Все функции" onValueChange={(value) => setFilter(setRole, value ?? "")} options={settings.roles.map((item) => ({ value: item.role, label: item.title }))} />
    <Select ariaLabel="Фильтр по статусу" value={status || null} emptyOption="Все статусы" onValueChange={(value) => setFilter(setStatus, value ?? "")} options={[{ value: "succeeded", label: "Готово" }, { value: "failed", label: "Ошибка" }, { value: "cached", label: "Из кэша" }, { value: "cancelled", label: "Отменено" }]} />
  </div>{filtered.length ? <>
    <div className="ai-table-wrap"><table className="ai-table ai-usage-table"><thead><tr><th>Время</th><th>Функция</th><th>Провайдер и модель</th><th>Токены</th><th>Стоимость</th><th>Статус</th></tr></thead><tbody>{pageRuns.map((run) => <tr key={run.id}><td>{dateTime(run.created_at)}</td><td>{settings.roles.find((item) => item.role === run.role)?.title ?? run.role}</td><td><strong>{run.provider_label_snapshot}</strong><code>{run.requested_model_id}</code></td><td>{(run.input_tokens ?? 0).toLocaleString("ru-RU")} → {(run.output_tokens ?? 0).toLocaleString("ru-RU")}</td><td>{money(run.actual_cost_usd)}</td><td><StatusBadge tone={run.status === "succeeded" || run.status === "cached" ? "success" : run.status === "failed" ? "danger" : "neutral"}>{runStatusLabel(run.status)}</StatusBadge>{run.error_code && <small>{run.error_code}</small>}</td></tr>)}</tbody></table></div>
    {pageCount > 1 && <div className="ai-pagination">
      <Button variant="secondary" disabled={currentPage <= 1} onClick={() => setPage(currentPage - 1)}>Назад</Button>
      <span>Страница {currentPage} из {pageCount}</span>
      <Button variant="secondary" disabled={currentPage >= pageCount} onClick={() => setPage(currentPage + 1)}>Дальше</Button>
    </div>}
  </> : <div className="ai-empty-card"><strong>Подходящих запросов нет</strong><p>Измените фильтры или вернитесь сюда после первого обращения к модели.</p></div>}<Disclosure summary="Какие данные сохраняются"><p className="ai-muted">В журнал попадают провайдер, модель, функция, токены, стоимость и результат. API-ключи, вопросы, ответы модели и полный текст материалов не сохраняются.</p></Disclosure></section>;
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
  const [focusRequest, setFocusRequest] = useState<FocusRequest | null>(null);
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

  /** Клик по избранной модели или по модели по умолчанию ведёт к её карточке в списке. */
  function focusModel(selection: AiModelSelection) {
    setSelectedProviderId(selection.provider_id);
    onActiveSubsection("models");
    setFocusRequest({ selection, nonce: Date.now() });
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
        setError(errorText(caught, "Параметры ИИ не загрузились"));
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
    <div id="ai-overview" className="ai-anchor-section"><OverviewPanel settings={settings} runs={runs} onSettings={acceptSettings} navigate={navigate} onFocusModel={focusModel} /></div>
    <div id="ai-providers" className="ai-anchor-section"><ProvidersPanel settings={settings} onSettings={acceptSettings} onModels={(id) => navigate("models", id)} /></div>
    <div id="ai-models" className="ai-anchor-section"><ModelsPanel settings={settings} onSettings={acceptSettings} providerId={selectedProviderId} onProvider={setSelectedProviderId} focusRequest={focusRequest} /></div>
    <div id="ai-defaults" className="ai-anchor-section"><DefaultsPanel settings={settings} onSettings={acceptSettings} /></div>
    <div id="ai-functions" className="ai-anchor-section"><FunctionsPanel settings={settings} onSettings={acceptSettings} /></div>
    <div id="ai-limits" className="ai-anchor-section"><LimitsPanel settings={settings} onSettings={acceptSettings} /></div>
    <div id="ai-usage" className="ai-anchor-section"><UsagePanel settings={settings} runs={runs} /></div>
  </div>;
}
