import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef } from "react";
import type { KeyboardEvent } from "react";
import { Plus, Send, Square } from "lucide-react";
import type { ChatCapability, ChatMode } from "../../../api/chat";
import { DictationButton } from "../../../components/domain";
import { Button, IconButton, SegmentedTabs } from "../../../components/ui";

export interface ChatComposerHandle {
  focus: () => void;
}

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop?: () => void;
  /** Палитра навыков — только у экзаменационного чата; без неё кнопка `+` не рендерится. */
  onOpenPalette?: () => void;
  modes?: ChatCapability[];
  currentMode?: ChatMode;
  onModeChange?: (mode: ChatMode) => void;
  /** Индикатор режима (сейчас — «Экзамен») — экзаменационная специфика. */
  showModeIndicator?: boolean;
  sending: boolean;
  disabled?: boolean;
}

/**
 * Композер: авторастущее поле, `+` и `/` открывают палитру команд,
 * Enter отправляет, Shift+Enter переносит строку (AI-CHATS.md §21.3).
 */
export const ChatComposer = forwardRef<ChatComposerHandle, ChatComposerProps>(function ChatComposer(
  {
    value, onChange, onSend, onStop, onOpenPalette, modes = [], currentMode = "exam",
    onModeChange,
    showModeIndicator = true, sending, disabled,
  },
  forwardedRef,
) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const availableModes = modes.filter((mode) => mode.available);

  useImperativeHandle(forwardedRef, () => ({ focus: () => ref.current?.focus() }), []);

  // Расшифровка приходит через секунды: за это время в поле могли дописать своё,
  // поэтому добавляем к актуальному тексту, а не к тому, что был при нажатии.
  const latestValue = useRef(value);
  useEffect(() => {
    latestValue.current = value;
  }, [value]);
  function appendDictation(text: string) {
    const current = latestValue.current.trimEnd();
    onChange(current ? `${current} ${text}` : text);
    ref.current?.focus();
  }

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
    if (event.key === "/" && value.trim() === "" && onOpenPalette) {
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
        placeholder={onOpenPalette ? "Спросите или введите / для команд" : "Спросите или предложите правку"}
        disabled={disabled}
        rows={1}
      />
      <div className="chat-composer-row">
        <div className="chat-composer-row-left">
          {onOpenPalette && (
            <IconButton label="Команды" onClick={onOpenPalette} disabled={disabled}>
              <Plus size={15} />
            </IconButton>
          )}
          {showModeIndicator && (
            <SegmentedTabs
              label="Режим чата"
              value={currentMode}
              tabs={availableModes.map((mode) => ({ value: mode.key, label: mode.title }))}
              onChange={(value) => onModeChange?.(value as ChatMode)}
            />
          )}
        </div>
        <div className="chat-composer-row-right">
          <DictationButton onText={appendDictation} disabled={disabled} />
          {sending && onStop ? (
            <Button variant="secondary" className="chat-composer-send" onClick={onStop}>
              <Square size={13} />Остановить
            </Button>
          ) : sending ? (
            <Button variant="secondary" className="chat-composer-send is-waiting" disabled aria-busy="true">
              <span className="chat-send-spinner" aria-hidden="true" />Ждём ответ
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
