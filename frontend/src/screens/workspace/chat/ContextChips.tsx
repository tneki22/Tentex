import type { LucideIcon } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Disclosure, Popover, Switch } from "../../../components/ui";

const CONTEXT_OPEN_KEY = "tentex:chat-context-open";

function bytesLabel(bytes: number): string {
  return bytes < 1024 ? `${bytes} Б` : `${(bytes / 1024).toFixed(1)} КБ`;
}

/** Один чип состава контекста. Список строит вызывающий экран (exam и
 * program-чат показывают разный набор источников контекста) — сам компонент
 * только рендерит уже готовые данные. */
export interface ChipDef {
  key: string;
  icon: LucideIcon;
  title: string;
  flagKey: string | null;
  included: boolean;
  bytes: number;
  count: number | null;
  reason: string | null;
  futureNote?: string;
}

export const CONTEXT_REASON_LABELS: Record<string, string> = {
  excluded_by_user: "Исключено вручную",
  profile_empty: "В профиле проекта эти поля не заполнены",
  reference_missing: "У темы ещё нет ответа",
  not_implemented: "Пока не реализовано",
  context_budget_exceeded: "Не поместилось в бюджет контекста",
};

interface ContextChipsProps {
  chips: ChipDef[] | null;
  contextFlags: Record<string, boolean>;
  onToggleFlag: (key: string, value: boolean) => void;
  controls?: ReactNode;
  label?: string;
}

/** Тихая строка чипов над композером — заменяет прежнюю текстовую «В запрос уходит: ...». */
export function ContextChips({ chips, contextFlags, onToggleFlag, controls, label = "Контекст" }: ContextChipsProps) {
  const [open, setOpen] = useState(() => window.localStorage.getItem(CONTEXT_OPEN_KEY) === "1");
  if (!chips) return null;
  const includedCount = chips.filter((chip) => chip.included).length;

  return (
    <Disclosure
      summary={`${label} · ${includedCount}`}
      className="chat-context-disclosure"
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        window.localStorage.setItem(CONTEXT_OPEN_KEY, next ? "1" : "0");
      }}
    >
      {controls}
      <div className="chat-context-chips" role="list" aria-label="Состав запроса">
        {chips.map((chip) => (
          <Popover
            key={chip.key}
            align="start"
            side="top"
            title={chip.title}
            trigger={
              <button
                type="button"
                role="listitem"
                className={`chat-context-chip ${chip.included ? "is-included" : "is-excluded"}`}
              >
                <chip.icon size={13} aria-hidden="true" />
                {chip.title}
              </button>
            }
          >
            <div className="chat-context-chip-detail">
              {chip.included ? (
                <p>Включено · {bytesLabel(chip.bytes)}</p>
              ) : (
                <p className="chat-context-chip-reason">
                  Не включено{chip.reason ? ` — ${CONTEXT_REASON_LABELS[chip.reason] ?? chip.reason}` : ""}
                </p>
              )}
              {chip.futureNote && <p className="chat-context-chip-future">{chip.futureNote}</p>}
              {chip.flagKey && !chip.futureNote && (
                <Switch
                  checked={contextFlags[chip.flagKey] ?? false}
                  onCheckedChange={(checked) => onToggleFlag(chip.flagKey as string, checked)}
                  label={contextFlags[chip.flagKey] ? "Включено в запрос" : "Исключено из запроса"}
                />
              )}
            </div>
          </Popover>
        ))}
      </div>
    </Disclosure>
  );
}
