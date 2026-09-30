import { useEffect, useLayoutEffect, useRef } from "react";
import { RotateCcw, Send } from "lucide-react";
import { oralAudioUrl, type AnswerFormPayload, type OralRecordingRead } from "../../../api/chat";
import { DictationButton } from "../../../components/domain";
import { Button, SegmentedTabs } from "../../../components/ui";

function timeLabel(iso: string): string {
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

function useAutoGrow(value: string) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${node.scrollHeight}px`;
  }, [value]);
  return ref;
}

interface SubmittedAnswerCardProps {
  mode: "submitted";
  payload: AnswerFormPayload;
  createdAt: string;
  onAnswerAgain: () => void;
  onCheckAgain?: () => void;
  headingRef?: (node: HTMLHeadingElement | null) => void;
  projectId: string;
}

interface ComposingAnswerCardProps {
  mode: "composing";
  projectId: string;
  question: string;
  ordinal: number;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
  busy: boolean;
  answerMode: "memory" | "supported";
  onAnswerModeChange: (value: "memory" | "supported") => void;
  responseFormat: "text" | "oral";
  onResponseFormatChange: (value: "text" | "oral") => void;
  oralDraft: OralRecordingRead | null;
  onOralRecording: (audio: Blob, durationMs: number) => Promise<string>;
}

type AnswerFormCardProps = SubmittedAnswerCardProps | ComposingAnswerCardProps;

/** Форма ответа: до отправки — черновик текущего чата, после — нередактируемая карточка. */
export function AnswerFormCard(props: AnswerFormCardProps) {
  const draft = props.mode === "composing" ? props.value : "";
  const growRef = useAutoGrow(draft);
  // Расшифровка приходит через секунды — дописываем к актуальному тексту ответа.
  const latestDraft = useRef(draft);
  useEffect(() => {
    latestDraft.current = draft;
  }, [draft]);

  if (props.mode === "submitted") {
    const { payload, createdAt, onAnswerAgain, onCheckAgain, headingRef } = props;
    const audioAvailable = payload.oral_recording_id && payload.audio_expires_at
      && new Date(payload.audio_expires_at).getTime() > Date.now();
    return (
      <article className="chat-answer-card is-submitted">
        <header>
          <h3 ref={headingRef} tabIndex={-1} className="chat-answer-ordinal">
            Попытка {payload.ordinal}
          </h3>
          <span className="chat-answer-time">{timeLabel(createdAt)}</span>
        </header>
        <p className="chat-answer-question">{payload.question}</p>
        {payload.modality === "oral" && <p className="chat-answer-modality">Устный ответ</p>}
        <div className="chat-answer-text" aria-readonly="true">{payload.text}</div>
        {audioAvailable && payload.oral_recording_id && (
          <audio controls src={oralAudioUrl(props.projectId, payload.oral_recording_id)}>
            Ваш браузер не поддерживает воспроизведение записи.
          </audio>
        )}
        {payload.modality === "oral" && payload.speech_metrics && (
          <p className="chat-answer-speech-metrics">
            Длительность {Math.round(payload.speech_metrics.duration_ms / 1000)} с
            {payload.speech_metrics.pace_wpm !== undefined
              ? ` · ${payload.speech_metrics.pace_wpm} слов/мин · пауз ${payload.speech_metrics.pause_count ?? 0}`
              : " · тайминги речи недоступны"}
          </p>
        )}
        <div className="chat-answer-actions is-submitted">
          {onCheckAgain && <Button onClick={onCheckAgain}>Проверить позже</Button>}
          <Button variant="secondary" onClick={onAnswerAgain}>
            <RotateCcw size={14} />Ответить заново
          </Button>
        </div>
      </article>
    );
  }

  const { question, ordinal, value, onChange, onSubmit, onCancel, busy } = props;
  return (
    <article className="chat-answer-card is-composing">
      <header>
        <span className="chat-answer-ordinal">Попытка {ordinal}</span>
      </header>
      <p className="chat-answer-question">{question}</p>
      <SegmentedTabs
        label="Формат ответа"
        value={props.responseFormat}
        onChange={props.onResponseFormatChange}
        tabs={[{ value: "text", label: "Текстом" }, { value: "oral", label: "Устно" }]}
      />
      <SegmentedTabs label="Как отвечаете" value={props.answerMode} onChange={props.onAnswerModeChange} tabs={[{value:"memory",label:"По памяти"},{value:"supported",label:"С опорой"}]} />
      {props.responseFormat === "oral" && (
        <div className="chat-oral-note">
          <p>Запись уйдёт выбранному внешнему сервису распознавания речи. Проверьте и при необходимости исправьте текст перед сдачей.</p>
          {props.oralDraft && (
            <>
              <audio controls src={oralAudioUrl(props.projectId, props.oralDraft.id)} />
              <p>
                Длительность {Math.round(props.oralDraft.metrics.duration_ms / 1000)} с
                {props.oralDraft.metrics.pace_wpm !== undefined
                  ? ` · ${props.oralDraft.metrics.pace_wpm} слов/мин · пауз ${props.oralDraft.metrics.pause_count ?? 0}`
                  : " · тайминги речи недоступны"}
              </p>
            </>
          )}
        </div>
      )}
      <textarea
        ref={growRef}
        className="chat-answer-input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Ваш ответ на вопрос билета"
        autoFocus
        disabled={busy}
      />
      <div className="chat-answer-actions">
        <DictationButton
          disabled={busy}
          onRecording={props.responseFormat === "oral" ? props.onOralRecording : undefined}
          onText={(text) => {
            if (props.responseFormat === "oral") {
              onChange(text);
              growRef.current?.focus();
              return;
            }
            const current = latestDraft.current.trimEnd();
            onChange(current ? `${current} ${text}` : text);
            growRef.current?.focus();
          }}
        />
        <Button variant="ghost" onClick={onCancel} disabled={busy}>Отменить</Button>
        <Button onClick={onSubmit} disabled={busy || !value.trim() || (props.responseFormat === "oral" && !props.oralDraft)} aria-busy={busy}>
          {busy ? <span className="chat-send-spinner" aria-hidden="true" /> : <Send size={14} />}{busy ? "Проверяем ответ…" : "Сдать ответ"}
        </Button>
      </div>
      {busy && <p className="chat-answer-progress" role="status">Сохраняем ответ и ждём разбор модели. Это может занять некоторое время.</p>}
    </article>
  );
}
