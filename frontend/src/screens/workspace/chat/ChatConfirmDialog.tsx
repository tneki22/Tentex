import { useState } from "react";
import { Button, Checkbox, Dialog } from "../../../components/ui";
import type { ChatConfirmationDetails } from "../../../api/chat";
import type { PendingConfirmation } from "./useExamChat";

const REASONS: Record<string, string> = {
  cost_threshold: "Ответ дороже порога из Параметров ИИ.",
  unknown_price: "Цена модели неизвестна — сумму оценить нельзя.",
  large_context: "Большой контекст запроса.",
  context_over_budget: "Контекст больше предела — часть сокращена.",
};

function money(rub: string | null, usd: string | null): string {
  if (rub !== null) return `≈ ${Number(rub).toFixed(2)} ₽`;
  if (usd !== null) return `≈ $${Number(usd).toFixed(4)}`;
  return "цена неизвестна";
}

function tokens(value: number): string {
  return value.toLocaleString("ru-RU");
}

function CutList({ details }: { details: ChatConfirmationDetails }) {
  if (details.manifest.length === 0) return null;
  return (
    <ul className="chat-confirm-cuts">
      {details.manifest.map((item, index) => (
        <li key={`${item.kind}-${index}`}>
          <span>{item.title}</span>
          <small>{item.truncated ? "сокращено" : "не поместилось"} · {tokens(item.tokens)}</small>
        </li>
      ))}
    </ul>
  );
}

/**
 * Подтверждение хода чата: цена, объём и что сокращено.
 *
 * Превышение предела не режется молча: пользователь выбирает — отправить
 * сокращённым, поднять предел (с новой ценой) или отказаться; черновик при
 * отказе остаётся в поле.
 */
export function ChatConfirmDialog({
  confirmation, onConfirm, onCancel,
}: {
  confirmation: PendingConfirmation | null;
  onConfirm: (expanded: boolean, remember: boolean) => void;
  onCancel: () => void;
}) {
  const [remember, setRemember] = useState(false);
  const details = confirmation?.details;
  const over = details?.reasons.includes("context_over_budget") ?? false;
  const cost = details ? money(details.estimated_cost_rub, details.estimated_cost_usd) : "";
  const maxCost = details ? money(details.max_cost_rub, details.max_cost_usd) : "";

  return (
    <Dialog
      open={Boolean(confirmation)}
      onOpenChange={(open) => { if (!open) onCancel(); }}
      title={over ? "Контекст не помещается в предел" : "Подтвердите отправку"}
      description={details ? `${details.provider_label} · ${details.model_id}` : undefined}
      className="chat-confirm-dialog"
      footer={details && (
        <>
          <Button variant="ghost" onClick={onCancel}>Отменить</Button>
          {over && details.expanded && (
            <Button variant="secondary" onClick={() => onConfirm(true, remember)}>
              Увеличить до {tokens(details.expanded.budget_tokens)} · {money(details.expanded.estimated_cost_rub, details.expanded.estimated_cost_usd)}
            </Button>
          )}
          <Button onClick={() => onConfirm(false, false)}>{over ? "Отправить сокращённым" : "Отправить"}</Button>
        </>
      )}
    >
      {details && (
        <div className="chat-confirm-body">
          <ul className="chat-confirm-reasons">
            {details.reasons.map((reason) => <li key={reason}>{REASONS[reason] ?? reason}</li>)}
          </ul>
          <p className="chat-confirm-cost">
            {cost}
            <small> · до {maxCost}, если модель придётся попросить исправить ссылки</small>
          </p>
          {over && (
            <>
              <p className="chat-confirm-budget">
                Нужно {tokens(details.budget.needed)} токенов, предел {tokens(details.budget.limit)}.
                {!details.expanded && " Больше не помещается в окно модели — выберите модель с большим окном."}
              </p>
              <CutList details={details} />
              {details.expanded && (
                <Checkbox checked={remember} onCheckedChange={setRemember} label="Запомнить предел для этого чата" />
              )}
            </>
          )}
        </div>
      )}
    </Dialog>
  );
}
