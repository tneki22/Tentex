import { QualityControl } from "../../preparation/QualityControl";
import type { AttemptOutcome, ChatMessageRead } from "../../../api/chat";
import { AnswerFormCard } from "./AnswerFormCard";
import { Markdown } from "./Markdown";
import { parsePayload } from "./payload";
import { ToolRunCard } from "./ToolRunCard";
import { VerdictCard } from "./VerdictCard";

interface TypedMessageProps {
  projectId: string;
  message: ChatMessageRead;
  answerText: string;
  needsCheck: boolean;
  isStreaming: boolean;
  onAnswerAgain: () => void;
  onCheckAgain: (attemptId: string) => Promise<void>;
  onSelfAssessment: (
    attemptId: string,
    outcome: Exclude<AttemptOutcome, "unscored">,
  ) => Promise<void>;
  headingRef: (node: HTMLHeadingElement | null) => void;
}

/**
 * Единая точка выбора renderer по `payload_kind` — то самое место, за которым
 * прячется read-only Markdown (AI-CHATS.md: рендерер можно будет заменить
 * после объединения с веткой конспектов, не переделывая ленту).
 */
export function TypedMessage({
  projectId, message, answerText, needsCheck, isStreaming,
  onAnswerAgain, onCheckAgain, onSelfAssessment, headingRef,
}: TypedMessageProps) {
  const payload = parsePayload(message);

  if (payload.kind === "answer_form") {
    return (
      <AnswerFormCard
        mode="submitted"
        payload={payload.data}
        createdAt={message.created_at}
        onAnswerAgain={onAnswerAgain}
        onCheckAgain={needsCheck && message.attempt_id
          ? () => onCheckAgain(message.attempt_id as string)
          : undefined}
        headingRef={headingRef}
      />
    );
  }

  if (payload.kind === "verdict" && message.grade_attempt_id) {
    return (
      <><VerdictCard
        verdict={payload.data}
        answer={answerText}
        attemptId={message.grade_attempt_id}
        onSelfAssessment={onSelfAssessment}
        headingRef={headingRef}
      /><QualityControl projectId={projectId} attemptId={message.grade_attempt_id} /></>
    );
  }

  if (payload.kind === "tool_result") {
    return <ToolRunCard projectId={projectId} payload={payload.data} headingRef={headingRef} />;
  }

  if (message.role === "system") {
    return <p className="chat-system-note">{message.text}</p>;
  }

  if (payload.kind === "unknown") {
    return (
      <div className="chat-bubble is-examiner chat-bubble-unknown">
        <p>Это сообщение сохранено в новом формате, который эта версия интерфейса ещё не понимает.</p>
        {message.text && <Markdown text={message.text} />}
      </div>
    );
  }

  return (
    <div className={`chat-bubble is-${message.role}`}>
      {message.role === "examiner" ? <Markdown text={message.text} /> : <p>{message.text}</p>}
      {isStreaming && message.stream_state === "complete" && (
        <span className="chat-typing" aria-hidden="true" />
      )}
      {message.stream_state === "stopped" && <span className="chat-stream-flag">Ответ остановлен</span>}
      {message.stream_state === "failed" && !message.text.trim() && (
        <span className="chat-stream-flag is-failed">Ответ не получен</span>
      )}
    </div>
  );
}
