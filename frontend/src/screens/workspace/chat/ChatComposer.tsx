import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { ArrowUp, Plus, Square } from "lucide-react";
import type { ChatCapability, ChatMode } from "../../../api/chat";
import { DictationButton } from "../../../components/domain";
import { IconButton } from "../../../components/ui";

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
  /** Выбор модели. Подаётся сверху: композер общий и про модели не знает. */
  modelPicker?: ReactNode;
  modes?: ChatCapability[];
  currentMode?: ChatMode;
  onModeChange?: (mode: ChatMode) => void;
  /** Индикатор режима (сейчас — «Экзамен») — экзаменационная специфика. */
  showModeIndicator?: boolean;
  sending: boolean;
  disabled?: boolean;
  placeholder?: string;
}

/**
 * Композер: авторастущее поле, `+` и `/` открывают палитру команд,
 * Enter отправляет, Shift+Enter переносит строку (AI-CHATS.md §21.3).
 */
export const ChatComposer = forwardRef<ChatComposerHandle, ChatComposerProps>(function ChatComposer(
  {
    value, onChange, onSend, onStop, onOpenPalette, modelPicker, modes = [], currentMode = "exam",
    onModeChange,
    showModeIndicator = true, sending, disabled, placeholder,
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
        placeholder={placeholder ?? (onOpenPalette ? "Спросите или введите / для команд" : "Спросите или предложите правку")}
        disabled={disabled}
        rows={1}
      />
      <div className="chat-composer-row">
        <div className="chat-composer-row-left">
          {modelPicker}
          {onOpenPalette && (
            <IconButton label="Команды" onClick={onOpenPalette} disabled={disabled}>
              <Plus size={15} />
            </IconButton>
          )}
          {showModeIndicator && <div className="chat-composer-modes" role="group" aria-label="Режим чата">
            {availableModes.map((mode) => <button
              type="button" key={mode.key} aria-label={mode.title} aria-pressed={currentMode === mode.key}
              title={mode.title} onClick={() => onModeChange?.(mode.key as ChatMode)}
            ><span className="chat-mode-full">{mode.title}</span><span className="chat-mode-short" aria-hidden="true">{mode.key === "exam" ? "Э" : "Раз"}</span></button>)}
          </div>}
        </div>
        <div className="chat-composer-row-right">
          <DictationButton onText={appendDictation} disabled={disabled} />
          {sending && onStop ? (
            <IconButton label="Остановить ответ" className="chat-composer-send" onClick={onStop}><Square size={14} /></IconButton>
          ) : sending ? (
            <IconButton label="Ожидаем ответ" className="chat-composer-send is-waiting" disabled><span className="chat-send-spinner" aria-hidden="true" /></IconButton>
          ) : (
            <IconButton label="Отправить" className="chat-composer-send" onClick={onSend} disabled={disabled || !value.trim()}><ArrowUp size={17} strokeWidth={2.2} /></IconButton>
          )}
        </div>
      </div>
    </div>
  );
});
