import { useEffect, useLayoutEffect, useRef, useState } from "react";
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
  retryText?: string;
}

const OFFLINE_CODES = new Set(["ai_disabled", "ai_role_disabled", "ai_model_not_configured", "ai_credentials_missing"]);
const UNREACHABLE_CODES = new Set(["ai_provider_unavailable", "ai_timeout", "ai_rate_limited"]);

interface ChatTimelineProps {
  messages: ChatMessageRead[];
  pending: PendingTurn | null;
  onAnswerAgain: () => void;
  onRetry: () => void;
  failure: StreamFailure | null;
}

function MessageBubble({
  message,
  onAnswerAgain,
  headingRef,
}: {
  message: ChatMessageRead;
  onAnswerAgain: () => void;
  headingRef: (node: HTMLHeadingElement | null) => void;
}) {
  const payload = parsePayload(message);
  if (payload.kind === "answer_form") {
    return (
      <AnswerFormCard
        mode="submitted"
        payload={payload.data}
        createdAt={message.created_at}
        onAnswerAgain={onAnswerAgain}
        headingRef={headingRef}
      />
    );
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

export function ChatTimeline({ messages, pending, onAnswerAgain, onRetry, failure }: ChatTimelineProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const followTailRef = useRef(true);
  const headingRefs = useRef(new Map<string, HTMLHeadingElement>());
  const previousAtomicIds = useRef<Set<string> | null>(null);
  const wasStreaming = useRef(false);
  const [showJump, setShowJump] = useState(false);
  const [streamAnnouncement, setStreamAnnouncement] = useState("");

  function distanceFromBottom(): number {
    const node = scrollRef.current;
    if (!node) return 0;
    return node.scrollHeight - node.scrollTop - node.clientHeight;
  }

  useLayoutEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    if (followTailRef.current) {
      node.scrollTop = node.scrollHeight;
      setShowJump(false);
    } else {
      setShowJump(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length, pending?.examinerText, pending?.userText]);

  useEffect(() => {
    const current = new Set(
      messages.filter((message) => message.payload_kind !== "none").map((message) => message.id),
    );
    const previous = previousAtomicIds.current;
    previousAtomicIds.current = current;
    if (previous === null) return;
    const inserted = [...current].filter((id) => !previous.has(id));
    headingRefs.current.get(inserted.at(-1) ?? "")?.focus();
  }, [messages]);

  const streaming = Boolean(pending?.streaming);
  useEffect(() => {
    if (streaming && !wasStreaming.current) {
      setStreamAnnouncement("Экзаменатор отвечает");
    } else if (!streaming && wasStreaming.current) {
      setStreamAnnouncement(failure ? "Ответ экзаменатора не получен" : "Ответ экзаменатора завершён");
    }
    wasStreaming.current = streaming;
  }, [failure, streaming]);

  function handleScroll() {
    const awayFromBottom = distanceFromBottom() > 80;
    followTailRef.current = !awayFromBottom;
    setShowJump(awayFromBottom);
  }

  function jumpToBottom() {
    const node = scrollRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
    followTailRef.current = true;
    setShowJump(false);
  }

  const failureView = failure && (
    OFFLINE_CODES.has(failure.code)
      ? <OfflineNotice reason="disabled" alternative="Форма ответа работает без моделей." />
      : UNREACHABLE_CODES.has(failure.code)
        ? (
            <div className="chat-offline-action">
              <OfflineNotice reason="unreachable" alternative={failure.detail} />
              {failure.retryText && <Button variant="secondary" onClick={onRetry}>Повторить</Button>}
            </div>
          )
        : <p className="inline-error" role="alert">{failure.detail}</p>
  );

  return (
    <div className="chat-timeline-wrap">
      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {streamAnnouncement}
      </p>
      <div className="chat-timeline" ref={scrollRef} onScroll={handleScroll}>
        <div className="chat-timeline-rail">
          {messages.map((message) => (
            <div className="chat-timeline-item" key={message.id}>
              <MessageBubble
                message={message}
                onAnswerAgain={onAnswerAgain}
                headingRef={(heading) => {
                  if (heading) headingRefs.current.set(message.id, heading);
                  else headingRefs.current.delete(message.id);
                }}
              />
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
