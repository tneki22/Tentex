import { useEffect, useMemo, useState } from "react";
import type { KeyboardEvent } from "react";
import { Dialog as RadixDialog } from "radix-ui";
import { Search } from "lucide-react";
import type { ChatCapabilities } from "../../../api/chat";
import { Kbd } from "../../../components/ui";
import {
  PALETTE_COMMANDS,
  PALETTE_GROUP_LABELS,
  PALETTE_GROUP_ORDER,
  type PaletteCommandDef,
} from "./skills";

function normalize(text: string): string {
  return text.toLowerCase().replaceAll("ё", "е");
}

const UNAVAILABLE_REASON_LABELS: Record<string, string> = {
  chat_mode_unavailable: "Появится вместе с режимом «Разобраться»",
  skill_not_implemented: "Позже",
  tool_not_implemented: "Позже",
};

interface ResolvedCommand {
  def: PaletteCommandDef;
  available: boolean;
  reason: string | null;
}

interface SkillPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  capabilities: ChatCapabilities | null;
  onSelect: (command: PaletteCommandDef) => void;
}

/** Палитра команд чата: `+` в композере или клавиша `/` (AI-CHATS.md §21.3/§21.6). */
export function SkillPalette({ open, onOpenChange, capabilities, onSelect }: SkillPaletteProps) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  useEffect(() => {
    if (open) setQuery("");
  }, [open]);
  useEffect(() => setActive(0), [query]);

  const resolved: ResolvedCommand[] = useMemo(() => {
    const availability = new Map<string, { available: boolean; reason: string | null }>();
    for (const capability of [...(capabilities?.skills ?? []), ...(capabilities?.tools ?? [])]) {
      availability.set(capability.key, {
        available: capability.available,
        reason: capability.unavailable_reason,
      });
    }
    return PALETTE_COMMANDS.map((def) => {
      const info = availability.get(def.key);
      return { def, available: info?.available ?? false, reason: info?.reason ?? null };
    });
  }, [capabilities]);

  const results = useMemo(() => {
    const needle = normalize(query.trim());
    const matched = needle
      ? resolved.filter((item) => (
          normalize(item.def.label).includes(needle)
          || normalize(item.def.command).includes(needle)
          || normalize(item.def.description).includes(needle)
        ))
      : resolved;
    return PALETTE_GROUP_ORDER.flatMap((group) => matched.filter((item) => item.def.group === group));
  }, [query, resolved]);

  function choose(item: ResolvedCommand) {
    if (!item.available) return;
    onOpenChange(false);
    onSelect(item.def);
  }

  function onInputKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((prev) => (results.length === 0 ? 0 : (prev + 1) % results.length));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((prev) => (results.length === 0 ? 0 : (prev - 1 + results.length) % results.length));
    } else if (event.key === "Enter" && results[active]) {
      event.preventDefault();
      choose(results[active]);
    }
  }

  let lastGroup: string | null = null;

  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="dialog-overlay" />
        <RadixDialog.Content className="palette chat-skill-palette" aria-label="Команды чата">
          <RadixDialog.Title hidden>Команды чата</RadixDialog.Title>
          <RadixDialog.Description hidden>
            Навыки экзамена, работа с материалами и поиск источников
          </RadixDialog.Description>

          <div className="palette-input">
            <Search size={16} aria-hidden="true" />
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={onInputKeyDown}
              placeholder="Название команды"
              aria-label="Найти команду"
            />
            <Kbd>Esc</Kbd>
          </div>

          <div className="palette-list" role="listbox" aria-label="Команды">
            {results.length === 0 && <p className="palette-empty">Ничего не найдено</p>}
            {results.map((item, index) => {
              const header = item.def.group !== lastGroup ? PALETTE_GROUP_LABELS[item.def.group] : null;
              lastGroup = item.def.group;
              return (
                <div key={item.def.key}>
                  {header && <p className="palette-group">{header}</p>}
                  <button
                    type="button"
                    role="option"
                    aria-selected={index === active}
                    aria-disabled={!item.available}
                    className={`palette-item chat-skill-palette-item ${index === active ? "is-active" : ""} ${!item.available ? "is-disabled" : ""}`.trim()}
                    onMouseEnter={() => setActive(index)}
                    onClick={() => choose(item)}
                  >
                    <span className="chat-skill-palette-command">{item.def.command}</span>
                    <span className="palette-item-label">{item.def.label}</span>
                    <span className="palette-item-hint">
                      {item.available ? item.def.description : (item.reason ? UNAVAILABLE_REASON_LABELS[item.reason] ?? "Позже" : "Позже")}
                    </span>
                    {!item.available && <span className="chat-skill-palette-badge">Позже</span>}
                  </button>
                </div>
              );
            })}
          </div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
