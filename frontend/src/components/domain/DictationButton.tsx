import { Mic, Square } from "lucide-react";
import { dictationSupported, formatDuration, useDictation } from "../../hooks/useDictation";
import { IconButton, Tooltip } from "../ui";

interface DictationButtonProps {
  /** Получает расшифровку; куда её вставить — решает вызывающий. */
  onText: (text: string) => void;
  onRecording?: (audio: Blob, durationMs: number) => Promise<string>;
  disabled?: boolean;
}

/**
 * Кнопка голосового ввода: запись с микрофона → модель речи → текст. Строка
 * состояния стоит слева от кнопки, чтобы сама кнопка оставалась на месте рядом
 * с «Отправить» и не прыгала, пока идёт запись.
 */
export function DictationButton({ onText, onRecording, disabled = false }: DictationButtonProps) {
  const dictation = useDictation(onText, onRecording);
  const supported = dictationSupported();
  const recording = dictation.state === "recording";
  const transcribing = dictation.state === "transcribing";

  const label = !supported
    ? "Браузер не умеет записывать с микрофона"
    : recording ? "Остановить запись" : transcribing ? "Распознаём речь…" : "Голосовой ввод";
  const status = recording
    ? `Запись ${formatDuration(dictation.seconds)}`
    : transcribing ? "Распознаём…" : dictation.error;

  return (
    <>
      <span
        className={`dictation-status ${dictation.error && !recording && !transcribing ? "is-error" : ""} ${recording ? "is-recording" : ""}`.trim()}
        role="status"
        aria-live="polite"
      >
        {status}
      </span>
      <Tooltip label={label}>
        <IconButton
          label={label}
          hideNativeTitle
          className={`dictation-button ${recording ? "is-recording" : ""}`.trim()}
          aria-pressed={recording}
          disabled={disabled || !supported || transcribing}
          onClick={dictation.toggle}
        >
          {transcribing
            ? <span className="dictation-spinner" aria-hidden="true" />
            : recording ? <Square size={14} /> : <Mic size={15} />}
        </IconButton>
      </Tooltip>
    </>
  );
}
