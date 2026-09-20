import { useMemo, useState } from "react";
import { ChevronRight, Search, Sparkles, Star } from "lucide-react";
import type { AiModelRead, AiModelSelection, AiProviderRead } from "../../api/ai";
import { ConfirmDialog, HoverCard, Popover, SegmentedTabs } from "../ui";
import {
  byFavoriteThenName,
  callCostUsd,
  findModel,
  modelKey,
  money,
  sameModel,
  smallMoney,
  supportsReasoning,
  supportsRole,
  tokensFromBytes,
} from "./modelFacts";

/** Значения совпадают с `ReasoningEffort` в `backend/app/ai/roles.py`. */
export type ReasoningEffort = "off" | "low" | "medium" | "high";

const REASONING_TABS: Array<{ value: ReasoningEffort; label: string }> = [
  { value: "off", label: "Выкл" },
  { value: "low", label: "Низкое" },
  { value: "medium", label: "Среднее" },
  { value: "high", label: "Высокое" },
];

const REASONING_SHORT: Record<ReasoningEffort, string> = {
  off: "без рассуждения",
  low: "рассуждение низкое",
  medium: "рассуждение среднее",
  high: "рассуждение высокое",
};

export interface ChatModelParameters {
  max_output_tokens?: number;
  reasoning_effort?: ReasoningEffort;
  [key: string]: unknown;
}

interface ChatModelPickerProps {
  providers: AiProviderRead[];
  models: AiModelRead[];
  value: AiModelSelection | null;
  parameters: ChatModelParameters;
  /** Возможности, без которых модель не обслужит этот чат. */
  capabilities: string[];
  /** Размер контекста чата — из предпросмотра. Без него цена вызова не считается. */
  contextBytes?: number;
  /** Сколько сообщений уже в переписке: по ним решается, спрашивать ли подтверждение. */
  messageCount: number;
  /** Потолок ответа, если параметр не задан — дефолт роли с бэкенда. */
  defaultMaxOutputTokens: number;
  disabled?: boolean;
  onChange: (
    value: AiModelSelection | null,
    parameters: ChatModelParameters,
  ) => void | Promise<void>;
}

function effortOf(parameters: ChatModelParameters): ReasoningEffort | null {
  const value = parameters.reasoning_effort;
  return REASONING_TABS.some((tab) => tab.value === value) ? (value as ReasoningEffort) : null;
}

function messageCountWord(count: number): string {
  const mod100 = count % 100;
  const mod10 = count % 10;
  if (mod100 >= 11 && mod100 <= 14) return "сообщений";
  if (mod10 === 1) return "сообщение";
  if (mod10 >= 2 && mod10 <= 4) return "сообщения";
  return "сообщений";
}

/**
 * Выбор модели прямо в композере: провайдеры свёрнутыми группами, цена в
 * строке, параметры — в карточке по наведению.
 *
 * Смена параметра у невыбранной модели выбирает её: иначе пришлось бы
 * объяснять, к какой из них относятся только что выставленные настройки.
 */
export function ChatModelPicker({
  providers,
  models,
  value,
  parameters,
  capabilities,
  contextBytes,
  messageCount,
  defaultMaxOutputTokens,
  disabled = false,
  onChange,
}: ChatModelPickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [pendingChoice, setPendingChoice] = useState<{
    selection: AiModelSelection | null;
    parameters: ChatModelParameters;
  } | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(value ? [value.provider_id] : []),
  );

  const current = findModel(models, value);
  const maxOutputTokens = parameters.max_output_tokens ?? defaultMaxOutputTokens;
  const inputTokens = tokensFromBytes(contextBytes ?? 0);
  const knowsContext = contextBytes !== undefined;
  const searching = query.trim().length > 0;

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return providers
      .map((provider) => ({
        provider,
        items: models
          .filter((model) => model.provider_id === provider.id)
          .filter((model) => supportsRole(model, "text", capabilities) || sameModel(model, value))
          .filter((model) => !needle
            || model.display_name.toLowerCase().includes(needle)
            || model.model_id.toLowerCase().includes(needle))
          .sort(byFavoriteThenName),
      }))
      .filter((group) => group.items.length > 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providers, models, capabilities, query, value?.provider_id, value?.model_id]);

  function toggleGroup(providerId: string) {
    setExpanded((previous) => {
      const next = new Set(previous);
      if (next.has(providerId)) next.delete(providerId);
      else next.add(providerId);
      return next;
    });
  }

  /** Пустой чат переключается молча: подтверждать и отмечать в ленте нечего. */
  function request(selection: AiModelSelection | null, next: ChatModelParameters) {
    const changed = selection === null ? value !== null : !sameModel(selection, value);
    if (messageCount > 0 && changed) {
      setPendingChoice({ selection, parameters: next });
      return;
    }
    void onChange(selection, next);
    setOpen(false);
  }

  function priceLabel(model: AiModelRead): string {
    const cost = callCostUsd(model, inputTokens, maxOutputTokens);
    if (cost !== null && knowsContext) return `≈ ${smallMoney(cost)}`;
    return money(model.prompt_price_usd, true);
  }

  return (
    <>
      <Popover
        open={open}
        onOpenChange={setOpen}
        align="start"
        side="top"
        title="Модель чата"
        className="chat-model-popover"
        trigger={
          <button type="button" className="chat-model-trigger" disabled={disabled}>
            <Sparkles size={14} aria-hidden="true" />
            <span className="chat-model-trigger-name">{current?.display_name ?? "Auto"}</span>
          </button>
        }
      >
        <div className="chat-model-search">
          <Search size={14} aria-hidden="true" />
          <input
            type="search"
            value={query}
            placeholder="Найти модель"
            aria-label="Найти модель"
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>

        <div className="chat-model-groups">
          <button
            type="button"
            className={`chat-model-row is-auto ${value === null ? "is-current" : ""}`.trim()}
            onClick={() => request(null, {})}
          >
            <span className="chat-model-row-name">Auto</span>
            <span className="chat-model-row-facts">модель из Параметров</span>
          </button>

          {groups.map((group) => {
            const isOpen = searching || expanded.has(group.provider.id);
            return (
              <section key={group.provider.id} className="chat-model-group">
                <button
                  type="button"
                  className="chat-model-group-trigger"
                  aria-expanded={isOpen}
                  onClick={() => toggleGroup(group.provider.id)}
                >
                  <ChevronRight size={14} aria-hidden="true" />
                  <span>{group.provider.label}</span>
                  <small>{group.items.length}</small>
                </button>
                {isOpen && (
                  <div className="chat-model-group-items">
                    {group.items.map((model) => {
                      const isCurrent = sameModel(model, value);
                      const effort = isCurrent ? effortOf(parameters) : null;
                      return (
                        <HoverCard
                          key={modelKey(model)}
                          side="right"
                          trigger={
                            <button
                              type="button"
                              className={`chat-model-row ${isCurrent ? "is-current" : ""}`.trim()}
                              onClick={() => request(
                                { provider_id: model.provider_id, model_id: model.model_id },
                                isCurrent ? parameters : {},
                              )}
                            >
                              <span className="chat-model-row-name">
                                {model.favorite_order !== null && (
                                  <Star size={12} fill="currentColor" aria-hidden="true" />
                                )}
                                {model.display_name}
                              </span>
                              <span className="chat-model-row-facts">
                                {priceLabel(model)}
                                {effort && <em>{REASONING_SHORT[effort]}</em>}
                              </span>
                            </button>
                          }
                        >
                          <ModelParameters
                            model={model}
                            parameters={isCurrent ? parameters : {}}
                            maxOutputTokens={isCurrent ? maxOutputTokens : defaultMaxOutputTokens}
                            inputTokens={inputTokens}
                            knowsContext={knowsContext}
                            onApply={(next) => request(
                              { provider_id: model.provider_id, model_id: model.model_id },
                              next,
                            )}
                          />
                        </HoverCard>
                      );
                    })}
                  </div>
                )}
              </section>
            );
          })}

          {groups.length === 0 && (
            <p className="chat-model-empty">
              {searching
                ? "Ничего не нашлось."
                : "Подходящих моделей нет. Добавьте их в Параметрах ИИ."}
            </p>
          )}
        </div>
      </Popover>

      <SwitchConfirm
        pending={pendingChoice}
        from={current}
        models={models}
        messageCount={messageCount}
        inputTokens={inputTokens}
        maxOutputTokens={maxOutputTokens}
        knowsContext={knowsContext}
        onCancel={() => setPendingChoice(null)}
        onConfirm={async (selection, next) => {
          await onChange(selection, next);
          setPendingChoice(null);
          setOpen(false);
        }}
      />
    </>
  );
}

function ModelParameters({
  model,
  parameters,
  maxOutputTokens,
  inputTokens,
  knowsContext,
  onApply,
}: {
  model: AiModelRead;
  parameters: ChatModelParameters;
  maxOutputTokens: number;
  inputTokens: number;
  knowsContext: boolean;
  onApply: (parameters: ChatModelParameters) => void;
}) {
  const ceiling = model.max_completion_tokens ?? 32_000;
  const cost = callCostUsd(model, inputTokens, maxOutputTokens);

  return (
    <div className="chat-model-params">
      <code>{model.model_id}</code>

      <dl className="chat-model-params-facts">
        <div>
          <dt>За 1 млн токенов</dt>
          <dd>
            вход {money(model.prompt_price_usd, true)}, выход{" "}
            {money(model.completion_price_usd, true)}
          </dd>
        </div>
        {cost !== null && knowsContext && (
          <div>
            <dt>За это сообщение</dt>
            <dd>≈ {smallMoney(cost)}</dd>
          </div>
        )}
        {model.context_length !== null && (
          <div>
            <dt>Контекст</dt>
            <dd>{model.context_length.toLocaleString("ru-RU")} токенов</dd>
          </div>
        )}
      </dl>

      {supportsReasoning(model) && (
        <SegmentedTabs
          label="Рассуждение"
          value={effortOf(parameters) ?? "off"}
          tabs={REASONING_TABS}
          onChange={(next) => onApply({ ...parameters, reasoning_effort: next })}
        />
      )}

      <label className="chat-model-params-number">
        <span>Максимум токенов ответа</span>
        <input
          type="number"
          min={64}
          max={ceiling}
          step={100}
          defaultValue={maxOutputTokens}
          onBlur={(event) => {
            const next = Number(event.target.value);
            if (!Number.isFinite(next) || next === maxOutputTokens) return;
            onApply({
              ...parameters,
              max_output_tokens: Math.min(Math.max(Math.round(next), 64), ceiling),
            });
          }}
        />
      </label>
    </div>
  );
}

function SwitchConfirm({
  pending,
  from,
  models,
  messageCount,
  inputTokens,
  maxOutputTokens,
  knowsContext,
  onCancel,
  onConfirm,
}: {
  pending: { selection: AiModelSelection | null; parameters: ChatModelParameters } | null;
  from: AiModelRead | null;
  models: AiModelRead[];
  messageCount: number;
  inputTokens: number;
  maxOutputTokens: number;
  knowsContext: boolean;
  onCancel: () => void;
  onConfirm: (
    selection: AiModelSelection | null,
    parameters: ChatModelParameters,
  ) => Promise<void>;
}) {
  const to = pending ? findModel(models, pending.selection) : null;
  const costTo = to ? callCostUsd(to, inputTokens, maxOutputTokens) : null;
  const costFrom = from ? callCostUsd(from, inputTokens, maxOutputTokens) : null;

  return (
    <ConfirmDialog
      open={pending !== null}
      onOpenChange={(next) => { if (!next) onCancel(); }}
      title="Сменить модель чата"
      confirmLabel="Сменить модель"
      pendingLabel="Меняем…"
      onConfirm={async () => {
        if (pending) await onConfirm(pending.selection, pending.parameters);
      }}
    >
      <p className="chat-model-confirm-swap">
        {from?.display_name ?? "по умолчанию"} → {to?.display_name ?? "по умолчанию"}
      </p>
      <p>
        Вся переписка уйдёт в новую модель целиком: {messageCount}{" "}
        {messageCountWord(messageCount)}
        {knowsContext && `, ≈ ${inputTokens.toLocaleString("ru-RU")} токенов входа`}.
      </p>
      {costTo !== null && costFrom !== null && knowsContext && (
        <p>
          Следующий ответ обойдётся примерно в {smallMoney(costTo)} против{" "}
          {smallMoney(costFrom)} на текущей модели.
        </p>
      )}
      <p className="chat-model-confirm-note">
        Кэш промпта у провайдера привязан к модели — у новой он начнётся с нуля.
      </p>
    </ConfirmDialog>
  );
}
