import { forwardRef, useImperativeHandle, useLayoutEffect, useRef } from "react";
import type { KeyboardEvent } from "react";
import { Mic, Plus, Send, Square } from "lucide-react";
import type { ChatCapability } from "../../../api/chat";
import { Button, IconButton, Tooltip } from "../../../components/ui";

export interface ChatComposerHandle {
  focus: () => void;
}

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  onOpenPalette: () => void;
  modes: ChatCapability[];
  sending: boolean;
  disabled?: boolean;
}

/**
 * Композер: авторастущее поле, `+` и `/` открывают палитру команд,
 * Enter отправляет, Shift+Enter переносит строку (AI-CHATS.md §21.3).
 */
export const ChatComposer = forwardRef<ChatComposerHandle, ChatComposerProps>(function ChatComposer(
  { value, onChange, onSend, onStop, onOpenPalette, modes, sending, disabled },
  forwardedRef,
) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const examMode = modes.find((mode) => mode.key === "exam");
  const studyMode = modes.find((mode) => mode.key === "study");

  useImperativeHandle(forwardedRef, () => ({ focus: () => ref.current?.focus() }), []);

  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 240)}px`;
  }, [value]);

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!sending && value.trim()) onSend();
      return;
    }
    // `/` в самом начале пустого поля открывает палитру и не попадает в текст —
    // фильтр по продолжению команды набирается внутри самой палитры.
    if (event.key === "/" && value.trim() === "") {
      event.preventDefault();
      onOpenPalette();
    }
  }

  return (
    <div className="chat-composer">
      <textarea
        ref={ref}
        className="chat-composer-input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Спросите или введите / для команд"
        disabled={disabled}
        rows={1}
      />
      <div className="chat-composer-row">
        <div className="chat-composer-row-left">
          <IconButton label="Команды" onClick={onOpenPalette} disabled={disabled}>
            <Plus size={15} />
          </IconButton>
          <Tooltip label={studyMode?.available ? "Разобраться" : "«Разобраться» появится позже"}>
            <span className="chat-composer-mode" aria-label="Режим чата: экзамен">
              {examMode?.title ?? "Экзамен"}
            </span>
          </Tooltip>
        </div>
        <div className="chat-composer-row-right">
          <Tooltip label="Диктовка появится вместе с распознаванием речи">
            <IconButton label="Диктовка" disabled>
              <Mic size={15} />
            </IconButton>
          </Tooltip>
          {sending ? (
            <Button variant="secondary" className="chat-composer-send" onClick={onStop}>
              <Square size={13} />Остановить
            </Button>
          ) : (
            <Button className="chat-composer-send" onClick={onSend} disabled={disabled || !value.trim()}>
              <Send size={14} />Отправить
            </Button>
          )}
        </div>
      </div>
    </div>
  );
});
