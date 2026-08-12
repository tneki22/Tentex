import { useEffect, useRef, useState } from "react";
import { ArrowDown } from "lucide-react";
import type { ChatMessageRead } from "../../../api/chat";
import { OfflineNotice } from "../../../components/domain";
import { Button } from "../../../components/ui";
import { AnswerFormCard } from "./AnswerFormCard";
import { Markdown } from "./Markdown";
import { parsePayload } from "./payload";

export interface PendingTurn {
  userText: string;
  examinerText: string;
  streaming: boolean;
}

export interface StreamFailure {
  code: string;
  detail: string;
}

const OFFLINE_CODES = new Set(["ai_disabled", "ai_role_disabled", "ai_model_not_configured", "ai_credentials_missing"]);
const UNREACHABLE_CODES = new Set(["ai_provider_unavailable", "ai_timeout", "ai_rate_limited"]);

interface ChatTimelineProps {
  messages: ChatMessageRead[];
  pending: PendingTurn | null;
  onAnswerAgain: () => void;
  failure: StreamFailure | null;
}

function MessageBubble({ message, onAnswerAgain }: { message: ChatMessageRead; onAnswerAgain: () => void }) {
  const payload = parsePayload(message);
  if (payload.kind === "answer_form") {
    return <AnswerFormCard mode="submitted" payload={payload.data} createdAt={message.created_at} onAnswerAgain={onAnswerAgain} />;
  }
  if (message.role === "system") {
    return <p className="chat-system-note">{message.text}</p>;
  }
  return (
    <div className={`chat-bubble is-${message.role}`}>
      {message.role === "examiner" ? <Markdown text={message.text} /> : <p>{message.text}</p>}
      {message.stream_state === "stopped" && <span className="chat-stream-flag">Ответ остановлен</span>}
      {message.stream_state === "failed" && !message.text.trim() && (
        <span className="chat-stream-flag is-failed">Ответ не получен</span>
      )}
    </div>
  );
}

export function ChatTimeline({ messages, pending, onAnswerAgain, failure }: ChatTimelineProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [showJump, setShowJump] = useState(false);

  function distanceFromBottom(): number {
    const node = scrollRef.current;
    if (!node) return 0;
    return node.scrollHeight - node.scrollTop - node.clientHeight;
  }

  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    if (distanceFromBottom() <= 80) {
      node.scrollTop = node.scrollHeight;
      setShowJump(false);
    } else {
      setShowJump(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length, pending?.examinerText, pending?.userText]);

  function handleScroll() {
    setShowJump(distanceFromBottom() > 80);
  }

  function jumpToBottom() {
    const node = scrollRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
    setShowJump(false);
  }

  const failureView = failure && (
    OFFLINE_CODES.has(failure.code)
      ? <OfflineNotice reason="disabled" alternative="Форма ответа работает без моделей." />
      : UNREACHABLE_CODES.has(failure.code)
        ? <OfflineNotice reason="unreachable" alternative={failure.detail} />
        : <p className="inline-error" role="alert">{failure.detail}</p>
  );

  return (
    <div className="chat-timeline-wrap">
      <div className="chat-timeline" ref={scrollRef} onScroll={handleScroll} aria-live="polite">
        <div className="chat-timeline-rail">
          {messages.map((message) => (
            <div className="chat-timeline-item" key={message.id}>
              <MessageBubble message={message} onAnswerAgain={onAnswerAgain} />
            </div>
          ))}
          {pending && (
            <>
              <div className="chat-timeline-item">
                <div className="chat-bubble is-user"><p>{pending.userText}</p></div>
              </div>
              <div className="chat-timeline-item">
                <div className="chat-bubble is-examiner">
                  <Markdown text={pending.examinerText} />
                  {pending.streaming && <span className="chat-typing" aria-hidden="true" />}
                </div>
              </div>
            </>
          )}
          {failureView && <div className="chat-timeline-item">{failureView}</div>}
        </div>
      </div>
      {showJump && (
        <Button variant="secondary" className="chat-jump-button" onClick={jumpToBottom}>
          <ArrowDown size={14} />Новые сообщения
        </Button>
      )}
    </div>
  );
}
