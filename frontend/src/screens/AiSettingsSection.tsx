import {
  ArrowDown,
  ArrowUp,
  KeyRound,
  RefreshCw,
  Star,
  Trash2,
  Wifi,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  deleteAiCredential,
  getAiSettings,
  listAiRuns,
  refreshAiModels,
  testAiConnection,
  updateAiConnection,
  updateAiFavorites,
  updateAiRole,
  updateAiSettings,
  type AiConnectionRead,
  type AiGlobalSettingsWrite,
  type AiModality,
  type AiModelRead,
  type AiRoleRead,
  type AiRunRead,
  type AiSettingsRead,
  type DecimalValue,
} from "../api/ai";
import { OfflineNotice } from "../components/domain";
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

const ROLE_TITLES: Record<string, string> = {
  material_text_cleanup: "Прибрать текст страницы",
  exam_program_grouping: "Разложить вопросы по разделам",
  exam_chat_reply: "Ответы экзаменатора",
  exam_answer_judge: "Проверка свободного ответа",
  exam_chat_memory: "Сжатие истории раздела",
  speech_transcription: "Распознавание речи",
};

const EMPTY_STATUS = { text: "", tone: "neutral" as const };

function decimal(value: DecimalValue | null): number | null {
  if (value === null) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function money(value: DecimalValue | null, digits = 4): string {
  const amount = decimal(value);
  return amount === null ? "неизвестно" : `$${amount.toFixed(digits).replace(/0+$/, "").replace(/\.$/, ".00")}`;
}

function rubles(value: DecimalValue | null): string | null {
  const amount = decimal(value);
  return amount === null ? null : `≈ ${amount.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;
}

function dateTime(value: string | null): string {
  return value ? new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "";
}

function runWord(count: number): string {
  const lastTwo = count % 100;
  if (lastTwo >= 11 && lastTwo <= 14) return "запусков";
  if (count % 10 === 1) return "запуск";
  if (count % 10 >= 2 && count % 10 <= 4) return "запуска";
  return "запусков";
}

function modelSupports(model: AiModelRead, role: AiRoleRead): boolean {
  return role.required_capabilities.every((capability) => {
    if (capability === "structured_output") return model.supported_parameters.includes("response_format");
    if (capability === "audio_transcription") return model.input_modalities.includes("audio");
    return capability === "streaming";
  });
}

function modelMeta(model: AiModelRead): string {
  const context = model.context_length ? `${model.context_length.toLocaleString("ru-RU")} токенов` : "контекст неизвестен";
  const input = model.prompt_price_usd === null ? "цена неизвестна" : `${money(Number(model.prompt_price_usd) * 1_000_000, 2)} / 1 млн входных`;
  return `${context}, ${input}${model.is_available ? "" : ", больше не в каталоге"}`;
}

function connectionStatus(connection: AiConnectionRead) {
  if (!connection.has_api_key) return { text: "Не настроено", tone: "neutral" as const };
  if (connection.last_test_status === "connected") {
    return { text: `Проверено ${dateTime(connection.last_tested_at)}`, tone: "success" as const };
  }
  if (connection.last_test_status) return { text: "Не отвечает", tone: "warning" as const };
  return { text: "Готово", tone: "neutral" as const };
}

function SaveState({ value }: { value: string }) {
  return <span className="ai-save-state" aria-live="polite">{value}</span>;
}

function ModelSelector({
  id,
  label,
  value,
  models,
  inheritedLabel,
  disabled,
  onSelect,
}: {
  id: string;
  label: string;
  value: string | null;
  models: AiModelRead[];
  inheritedLabel?: string;
  disabled?: boolean;
  onSelect: (modelId: string | null) => void;
}) {
  const [draft, setDraft] = useState(value ?? "");
  useEffect(() => setDraft(value ?? ""), [value]);
  const selected = models.find((model) => model.model_id === value) ?? null;

  function commit(next: string) {
    const normalized = next.trim();
    if (!normalized && inheritedLabel !== undefined) {
      onSelect(null);
      return;
    }
    const exact = models.find((model) => model.model_id === normalized);
    if (exact) onSelect(exact.model_id);
    else setDraft(value ?? "");
  }

  return (
    <div className="ai-model-selector">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="search"
        list={`${id}-models`}
        value={draft}
        disabled={disabled}
        placeholder={inheritedLabel ?? "Найти модель по имени или id"}
        onChange={(event) => {
          const next = event.target.value;
          setDraft(next);
          if (models.some((model) => model.model_id === next)) onSelect(next);
        }}
        onBlur={() => commit(draft)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit(draft);
          }
        }}
      />
      <datalist id={`${id}-models`}>
        {inheritedLabel !== undefined && <option value="" label={inheritedLabel} />}
        {models.map((model) => (
          <option key={model.model_id} value={model.model_id} label={`${model.display_name} — ${modelMeta(model)}`} />
        ))}
      </datalist>
      {selected ? (
        <small><strong>{selected.display_name}</strong> · {selected.model_id}<br />{modelMeta(selected)}</small>
      ) : inheritedLabel ? <small>{inheritedLabel}</small> : <small>Начните вводить имя или полный id модели.</small>}
    </div>
  );
}

function ConnectionEditor({
  modality,
  settings,
  onSettings,
}: {
  modality: AiModality;
  settings: AiSettingsRead;
  onSettings: (value: AiSettingsRead) => void;
}) {
  const connection = settings.connections.find((item) => item.modality === modality)!;
  const models = settings.models.filter((model) => model.modality === modality);
  const [expanded, setExpanded] = useState(!connection.has_api_key);
  const [baseUrl, setBaseUrl] = useState(connection.base_url);
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [busyText, setBusyText] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [deleteOpen, setDeleteOpen] = useState(false);
  const heading = modality === "text" ? "Текстовые модели" : "Речь";
  const defaultLabel = modality === "text" ? "Модель для текста по умолчанию" : "Модель для речи по умолчанию";
  const connectionState = connectionStatus(connection);
  const refreshAge = connection.last_catalog_refresh_at
    ? Date.now() - new Date(connection.last_catalog_refresh_at).getTime()
    : null;
  const catalogStale = refreshAge !== null && refreshAge > 30 * 24 * 60 * 60 * 1000;

  useEffect(() => {
    setBaseUrl(connection.base_url);
  }, [connection.base_url]);

  async function refreshSnapshot() {
    const next = await getAiSettings();
    onSettings(next);
  }

  async function run(label: string, action: () => Promise<unknown>, progress = "Сохраняем…") {
    setBusy(true);
    setBusyText(progress);
    setStatus("");
    setError("");
    try {
      await action();
      await refreshSnapshot();
      setStatus(label);
      return true;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Операция не выполнена");
      try {
        await refreshSnapshot();
      } catch {
        // Keep the original provider error: it is the actionable one.
      }
      return false;
    } finally {
      setBusy(false);
      setBusyText("");
    }
  }

  async function saveConnection() {
    const saved = await run("Подключение сохранено", () => updateAiConnection(modality, {
      base_url: baseUrl,
      api_key: apiKey || undefined,
    }));
    if (saved) setApiKey("");
  }

  return (
    <section className="ai-settings-group" id={`connection-${modality}`}>
      <header className="ai-group-head">
        <div>
          <h2>{heading}</h2>
          <p>{modality === "text" ? "Одно OpenAI-совместимое подключение для текстовых функций." : "Отдельное подключение для будущей диктовки; текстовый ключ сюда не копируется."}</p>
        </div>
        <StatusBadge tone={connectionState.tone}>{connectionState.text}</StatusBadge>
      </header>

      <div className="ai-setting-row">
        <div><strong>Подключение</strong><small>{connection.label} · {connection.base_url || "URL не задан"}</small></div>
        <Button variant="secondary" onClick={() => setExpanded((value) => !value)}>{expanded ? "Скрыть" : "Настроить подключение"}</Button>
      </div>

      {expanded && (
        <div className="ai-connection-form">
          <Field label="OpenAI-совместимый URL" error={error && error.toLocaleLowerCase("ru").includes("url") ? error : undefined}>
            <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://openrouter.ai/api/v1" />
          </Field>
          <Field
            label="API-ключ"
            hint={connection.has_api_key && !apiKey ? "Ключ сохранён. Новый ввод заменит его; сохранённое значение сервер не возвращает." : "Ключ хранится зашифрованно только в локальной установке."}
          >
            <input type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={connection.has_api_key ? "Ключ сохранён" : "Введите ключ"} />
          </Field>
          <div className="ai-connection-actions">
            <Button disabled={busy || !baseUrl.trim()} onClick={() => void saveConnection()}><KeyRound size={14} />Сохранить подключение</Button>
            <Button variant="secondary" disabled={busy || !connection.has_api_key} onClick={() => void run("Подключение проверено", () => testAiConnection(modality), "Проверяем подключение…")}><Wifi size={14} />Проверить</Button>
            <Button variant="secondary" disabled={busy || !connection.has_api_key} onClick={() => void run("Список моделей обновлён", () => refreshAiModels(modality), "Обновляем список моделей…")}><RefreshCw size={14} />Обновить список моделей</Button>
            <Button variant="ghost" disabled={busy || !connection.has_api_key} onClick={() => setDeleteOpen(true)}><Trash2 size={14} />Удалить ключ</Button>
          </div>
        </div>
      )}

      {connection.last_test_status && connection.last_test_status !== "connected" && (
        <OfflineNotice reason="unreachable" alternative={`${error || "Проверьте URL и ключ."} Остальные настройки и локальная работа доступны.`} />
      )}
      {catalogStale && <p className="ai-inline-warning">Каталог давно не обновлялся. Снимок цен и доступность моделей могут устареть.</p>}
      {!models.length && connection.has_api_key && <p className="ai-muted">Каталог пуст. Обновите список моделей — это бесплатный запрос без тестового промпта.</p>}

      <ModelSelector
        id={`ai-default-${modality}`}
        label={defaultLabel}
        value={connection.default_model_id}
        models={models.filter((model) => model.is_available || model.model_id === connection.default_model_id)}
        disabled={busy}
        onSelect={(modelId) => {
          void run("Модель по умолчанию сохранена", () => updateAiConnection(modality, { default_model_id: modelId }));
        }}
      />
      <SaveState value={error || (busy ? busyText : status)} />

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={`Удалить ключ подключения «${heading}»?`}
        confirmLabel="Удалить ключ"
        destructive
        onConfirm={() => void run("Ключ удалён", () => deleteAiCredential(modality))}
      >
        <p>Каталог, выбранные модели и журнал расходов останутся. Функции этой модальности не заработают до сохранения нового ключа.</p>
      </ConfirmDialog>
    </section>
  );
}

function RolesEditor({ settings, onSettings }: { settings: AiSettingsRead; onSettings: (value: AiSettingsRead) => void }) {
  const [savingRole, setSavingRole] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  async function save(role: AiRoleRead, patch: Partial<Pick<AiRoleRead, "enabled" | "model_override">>) {
    setSavingRole(role.role);
    setMessage("");
    try {
      const next = await updateAiRole(role.role, {
        enabled: patch.enabled ?? role.enabled,
        model_override: patch.model_override === undefined ? role.model_override : patch.model_override,
        parameters: role.parameters,
      });
      onSettings(next);
      setMessage(`${ROLE_TITLES[role.role] ?? role.title}: сохранено`);
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "Настройка функции не сохранена");
    } finally {
      setSavingRole(null);
    }
  }

  return (
    <section className="ai-settings-group">
      <header className="ai-group-head"><div><h2>Функции</h2><p>Каждая функция наследует общую модель своей модальности или использует явное переопределение.</p></div></header>
      <div className="ai-role-list">
        {settings.roles.map((role) => {
          const models = settings.models.filter((model) => model.modality === role.modality && modelSupports(model, role) && model.is_available);
          const source = role.model_source === "role_override"
            ? "Выбрана для функции"
            : role.modality === "speech" ? "Общая модель речи" : "Общая модель текста";
          const inherited = role.resolved_model ? `По умолчанию — ${role.resolved_model}` : "По умолчанию — модель не настроена";
          const disabledGlobally = !settings.external_models_enabled;
          return (
            <article className="ai-role-row" id={`role-${role.role.replaceAll("_", "-")}`} key={role.role}>
              <div className="ai-role-copy">
                <Switch
                  checked={role.enabled}
                  onCheckedChange={(enabled) => void save(role, { enabled })}
                  disabled={savingRole === role.role}
                  label={ROLE_TITLES[role.role] ?? role.title}
                  hint={role.description}
                />
                <small className="ai-model-source">{disabledGlobally ? "Отключено глобально" : source}</small>
              </div>
              <ModelSelector
                id={`ai-role-${role.role}`}
                label="Модель функции"
                value={role.model_override}
                models={models}
                inheritedLabel={inherited}
                disabled={savingRole === role.role || !role.enabled}
                onSelect={(modelId) => void save(role, { model_override: modelId })}
              />
              {!models.length && <small className="ai-role-problem">Нет модели с нужными возможностями; выключена только эта функция.</small>}
            </article>
          );
        })}
      </div>
      <SaveState value={savingRole ? "Сохранение…" : message} />
    </section>
  );
}

function FavoritesEditor({ settings, onSettings }: { settings: AiSettingsRead; onSettings: (value: AiSettingsRead) => void }) {
  const catalogFavorites = settings.models.filter((model) => model.modality === "text" && model.is_favorite);
  const [order, setOrder] = useState<string[]>(catalogFavorites.map((model) => model.model_id));
  const [candidate, setCandidate] = useState("");
  const [status, setStatus] = useState("");
  const textModels = settings.models.filter((model) => model.modality === "text" && model.is_available);

  useEffect(() => {
    const ids = catalogFavorites.map((model) => model.model_id);
    setOrder((current) => {
      const sameMembers = current.length === ids.length && current.every((id) => ids.includes(id));
      return sameMembers ? current : ids;
    });
  }, [settings.models]);

  async function save(ids: string[], message: string) {
    setStatus("Сохранение…");
    try {
      const next = await updateAiFavorites(ids);
      setOrder(ids);
      onSettings(next);
      setStatus(message);
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : "Избранные не сохранены");
    }
  }

  function move(index: number, offset: number) {
    const target = index + offset;
    if (target < 0 || target >= order.length) return;
    const next = [...order];
    [next[index], next[target]] = [next[target], next[index]];
    void save(next, "Порядок избранных сохранён");
  }

  return (
    <div className="ai-favorites">
      <h3>Избранные для чата</h3>
      <p>Этот короткий список появится в выборе модели экзаменационного чата.</p>
      {order.length ? (
        <ol>
          {order.map((modelId, index) => {
            const model = settings.models.find((item) => item.model_id === modelId);
            return (
              <li key={modelId}>
                <Star size={14} aria-hidden="true" />
                <span><strong>{model?.display_name ?? modelId}</strong><small>{modelId}</small></span>
                <Button variant="ghost" aria-label="Поднять модель" disabled={index === 0} onClick={() => move(index, -1)}><ArrowUp size={13} /></Button>
                <Button variant="ghost" aria-label="Опустить модель" disabled={index === order.length - 1} onClick={() => move(index, 1)}><ArrowDown size={13} /></Button>
                <Button variant="ghost" aria-label="Убрать из избранных" onClick={() => void save(order.filter((id) => id !== modelId), "Модель убрана из избранных")}><Trash2 size={13} /></Button>
              </li>
            );
          })}
        </ol>
      ) : <p className="ai-muted">Избранных моделей пока нет.</p>}
      <div className="ai-favorite-add">
        <input type="search" list="ai-favorite-models" value={candidate} onChange={(event) => setCandidate(event.target.value)} placeholder="Найти модель для избранного" aria-label="Модель для избранного" />
        <datalist id="ai-favorite-models">{textModels.filter((model) => !order.includes(model.model_id)).map((model) => <option key={model.model_id} value={model.model_id} label={model.display_name} />)}</datalist>
        <Button variant="secondary" disabled={!textModels.some((model) => model.model_id === candidate) || order.includes(candidate)} onClick={() => { void save([...order, candidate], "Модель добавлена в избранные"); setCandidate(""); }}><Star size={14} />Добавить</Button>
      </div>
      <SaveState value={status} />
    </div>
  );
}

function LimitsEditor({ settings, onSettings }: { settings: AiSettingsRead; onSettings: (value: AiSettingsRead) => void }) {
  const [daily, setDaily] = useState(settings.daily_limit_usd?.toString() ?? "");
  const [operation, setOperation] = useState(settings.operation_limit_usd?.toString() ?? "");
  const [threshold, setThreshold] = useState(String(settings.confirm_input_tokens));
  const [rate, setRate] = useState(settings.usd_rub_rate?.toString() ?? "");
  const [rateDate, setRateDate] = useState(settings.usd_rub_rate_date ?? "");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setDaily(settings.daily_limit_usd?.toString() ?? "");
    setOperation(settings.operation_limit_usd?.toString() ?? "");
    setThreshold(String(settings.confirm_input_tokens));
    setRate(settings.usd_rub_rate?.toString() ?? "");
    setRateDate(settings.usd_rub_rate_date ?? "");
  }, [settings.daily_limit_usd, settings.operation_limit_usd, settings.confirm_input_tokens, settings.usd_rub_rate, settings.usd_rub_rate_date]);

  const rateNumber = rate ? Number(rate) : null;
  const dailyRub = daily && rateNumber ? Number(daily) * rateNumber : null;
  const operationRub = operation && rateNumber ? Number(operation) * rateNumber : null;

  async function save() {
    const values = [daily, operation, rate].filter(Boolean).map(Number);
    if (values.some((value) => !Number.isFinite(value) || value <= 0)) {
      setError("Лимиты и курс должны быть больше нуля; пустое поле означает «Без лимита».");
      return;
    }
    if (!Number.isInteger(Number(threshold)) || Number(threshold) < 0) {
      setError("Порог подтверждения должен быть целым неотрицательным числом.");
      return;
    }
    if (Boolean(rate) !== Boolean(rateDate)) {
      setError("Курс USD/RUB и дата снимка задаются вместе.");
      return;
    }
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const next = await updateAiSettings({
        external_models_enabled: settings.external_models_enabled,
        daily_limit_usd: daily ? Number(daily) : null,
        operation_limit_usd: operation ? Number(operation) : null,
        confirm_input_tokens: Number(threshold),
        usd_rub_rate: rate ? Number(rate) : null,
        usd_rub_rate_date: rateDate || null,
      });
      onSettings(next);
      setStatus("Лимиты и локальный курс сохранены");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Настройки не сохранены");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="ai-settings-group">
      <header className="ai-group-head"><div><h2>Лимиты и рубли</h2><p>Курс вводится локально и влияет только на новые оценки и запуски.</p></div></header>
      <div className="ai-limits-grid">
        <Field label="Дневной лимит, $" hint={dailyRub === null ? "Без лимита" : `≈ ${dailyRub.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`}><input type="number" min="0.000001" step="0.01" value={daily} onChange={(event) => setDaily(event.target.value)} placeholder="Без лимита" /></Field>
        <Field label="Лимит одной операции, $" hint={operationRub === null ? "Без лимита" : `≈ ${operationRub.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`}><input type="number" min="0.000001" step="0.01" value={operation} onChange={(event) => setOperation(event.target.value)} placeholder="Без лимита" /></Field>
        <Field label="Подтверждать контекст от, токенов"><input type="number" min="0" step="1" value={threshold} onChange={(event) => setThreshold(event.target.value)} /></Field>
        <Field label="Курс USD/RUB" hint={rate ? "Локальный снимок; внешний источник не вызывается." : "Без курса интерфейс показывает только $."}><input type="number" min="0.000001" step="0.01" value={rate} onChange={(event) => setRate(event.target.value)} placeholder="Не задан" /></Field>
        <Field label="Дата снимка"><input type="date" value={rateDate} onChange={(event) => setRateDate(event.target.value)} /></Field>
      </div>
      {error && <p className="inline-error" role="alert">{error}</p>}
      <div className="ai-group-actions"><Button disabled={busy} onClick={() => void save()}>{busy ? "Сохраняем…" : "Сохранить лимиты и курс"}</Button><SaveState value={status} /></div>
    </section>
  );
}

export function AiSettingsSection() {
  const [settings, setSettings] = useState<AiSettingsRead | null>(null);
  const [todayRuns, setTodayRuns] = useState<AiRunRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [globalStatus, setGlobalStatus] = useState<{
    text: string;
    tone: "neutral" | "success" | "warning";
  }>(EMPTY_STATUS);

  function acceptSettings(next: AiSettingsRead) {
    setSettings(next);
    window.dispatchEvent(new Event("tentex:ai-settings-updated"));
  }

  async function load(signal?: AbortSignal) {
    setLoading(true);
    setError("");
    try {
      const since = new Date();
      since.setHours(0, 0, 0, 0);
      const [nextSettings, runs] = await Promise.all([
        getAiSettings(signal),
        listAiRuns({ from: since.toISOString() }, signal),
      ]);
      setSettings(nextSettings);
      setTodayRuns(runs);
    } catch (caught) {
      if (!signal?.aborted) setError(caught instanceof Error ? caught.message : "Параметры ИИ не загрузились");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!settings || !window.location.hash) return;
    requestAnimationFrame(() => document.querySelector(window.location.hash)?.scrollIntoView({ block: "start" }));
  }, [settings]);

  const runUsage = useMemo(() => todayRuns.reduce((total, run) => ({
    reasoningTokens: total.reasoningTokens + (run.reasoning_tokens ?? 0),
    providerCachedTokens: total.providerCachedTokens + (run.provider_cached_tokens ?? 0),
  }), { reasoningTokens: 0, providerCachedTokens: 0 }), [todayRuns]);

  const hasUsage = useMemo(() => settings ? todayRuns.length > 0
    || settings.today_usage.input_tokens > 0
    || settings.today_usage.output_tokens > 0
    || decimal(settings.today_usage.actual_cost_usd) !== 0
    || settings.today_usage.cache_hits > 0 : false, [settings, todayRuns.length]);

  if (loading) return <LoadingState label="Загружаем безопасный снимок настроек ИИ" />;
  if (error) return <><ErrorState message={error} /><Button onClick={() => void load()}>Повторить</Button></>;
  if (!settings) return null;

  async function toggleExternal(enabled: boolean) {
    if (!settings) return;
    setGlobalStatus({ text: "Сохранение…", tone: "neutral" });
    const command: AiGlobalSettingsWrite = {
      external_models_enabled: enabled,
      daily_limit_usd: settings.daily_limit_usd,
      operation_limit_usd: settings.operation_limit_usd,
      confirm_input_tokens: settings.confirm_input_tokens,
      usd_rub_rate: settings.usd_rub_rate,
      usd_rub_rate_date: settings.usd_rub_rate_date,
    };
    try {
      const next = await updateAiSettings(command);
      acceptSettings(next);
      setGlobalStatus({ text: "Сохранено", tone: "success" });
    } catch (caught) {
      setGlobalStatus({ text: caught instanceof Error ? caught.message : "Не сохранено", tone: "warning" });
    }
  }

  return (
    <div className="ai-settings">
      <section className="ai-settings-group is-first">
        <header className="ai-group-head"><div><h1>ИИ</h1><p>Подключения, модели, функции и ограничения одной локальной установки.</p></div></header>
        <div className="ai-global-row">
          <Switch
            checked={settings.external_models_enabled}
            onCheckedChange={(enabled) => void toggleExternal(enabled)}
            label="Использовать внешние модели"
            hint="Выключение не удаляет ключи и настройки. Локальный импорт, OCR, поиск и ручная работа продолжают работать."
          />
          {globalStatus.text && <StatusBadge tone={globalStatus.tone}>{globalStatus.text}</StatusBadge>}
        </div>
        {!settings.external_models_enabled && <OfflineNotice reason="disabled" alternative="Настройки ниже остаются доступными." />}
        <div className="ai-today-usage">
          <strong>Расход сегодня</strong>
          {hasUsage ? (
            <span>
              {todayRuns.length.toLocaleString("ru-RU")} {runWord(todayRuns.length)} · {settings.today_usage.cache_hits.toLocaleString("ru-RU")} из exact-кэша<br />
              {settings.today_usage.input_tokens.toLocaleString("ru-RU")} входных и {settings.today_usage.output_tokens.toLocaleString("ru-RU")} выходных токенов<br />
              {runUsage.reasoningTokens ? `${runUsage.reasoningTokens.toLocaleString("ru-RU")} reasoning · ` : ""}
              {runUsage.providerCachedTokens ? `${runUsage.providerCachedTokens.toLocaleString("ru-RU")} provider-cache · ` : ""}
              {money(settings.today_usage.actual_cost_usd, 4)}{rubles(settings.today_usage.actual_cost_rub) ? `, ${rubles(settings.today_usage.actual_cost_rub)}` : ""}
            </span>
          ) : <span>Сегодня внешних вызовов не было</span>}
        </div>
      </section>

      <ConnectionEditor modality="text" settings={settings} onSettings={acceptSettings} />
      <FavoritesEditor settings={settings} onSettings={acceptSettings} />
      <ConnectionEditor modality="speech" settings={settings} onSettings={acceptSettings} />
      <RolesEditor settings={settings} onSettings={acceptSettings} />
      <LimitsEditor settings={settings} onSettings={acceptSettings} />

      <Disclosure summary="Что сохраняется в журнале">
        <p className="ai-muted">Журнал хранит роль, модель, безопасный состав контекста, токены, стоимость и состояние вызова. Ключи, полный текст страницы, вопросы и ответы модели туда не копируются.</p>
      </Disclosure>
    </div>
  );
}
