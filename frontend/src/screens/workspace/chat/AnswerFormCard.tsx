import { useLayoutEffect, useRef } from "react";
import { RotateCcw, Send } from "lucide-react";
import type { AnswerFormPayload } from "../../../api/chat";
import { Button } from "../../../components/ui";

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
  headingRef?: (node: HTMLHeadingElement | null) => void;
}

interface ComposingAnswerCardProps {
  mode: "composing";
  question: string;
  ordinal: number;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
  busy: boolean;
}

type AnswerFormCardProps = SubmittedAnswerCardProps | ComposingAnswerCardProps;

/** Форма ответа: до отправки — черновик текущего чата, после — нередактируемая карточка. */
export function AnswerFormCard(props: AnswerFormCardProps) {
  const growRef = useAutoGrow(props.mode === "composing" ? props.value : "");

  if (props.mode === "submitted") {
    const { payload, createdAt, onAnswerAgain, headingRef } = props;
    return (
      <article className="chat-answer-card is-submitted">
        <header>
          <h3 ref={headingRef} tabIndex={-1} className="chat-answer-ordinal">
            Попытка {payload.ordinal}
          </h3>
          <span className="chat-answer-time">{timeLabel(createdAt)}</span>
        </header>
        <p className="chat-answer-question">{payload.question}</p>
        <div className="chat-answer-text" aria-readonly="true">{payload.text}</div>
        <Button variant="secondary" onClick={onAnswerAgain}>
          <RotateCcw size={14} />Ответить заново
        </Button>
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
        <Button variant="ghost" onClick={onCancel} disabled={busy}>Отменить</Button>
        <Button onClick={onSubmit} disabled={busy || !value.trim()}>
          <Send size={14} />{busy ? "Отправляем…" : "Сдать ответ"}
        </Button>
      </div>
    </article>
  );
}
