import { useLayoutEffect, useRef } from "react";
import type { KeyboardEvent } from "react";
import { BookOpenCheck, Send, Square } from "lucide-react";
import { Button } from "../../../components/ui";

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  onAnswerClick: () => void;
  sending: boolean;
  disabled?: boolean;
}

/** Композер: авторастущее поле, Enter отправляет, Shift+Enter переносит строку. */
export function ChatComposer({ value, onChange, onSend, onStop, onAnswerClick, sending, disabled }: ChatComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null);

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
        placeholder="Спросите или опишите ответ"
        disabled={disabled}
        rows={1}
      />
      <div className="chat-composer-row">
        <Button variant="secondary" onClick={onAnswerClick} disabled={disabled}>
          <BookOpenCheck size={14} />Сдать ответ
        </Button>
        {sending ? (
          <Button variant="secondary" onClick={onStop}>
            <Square size={13} />Остановить
          </Button>
        ) : (
          <Button onClick={onSend} disabled={disabled || !value.trim()}>
            <Send size={14} />Отправить
          </Button>
        )}
      </div>
    </div>
  );
}
