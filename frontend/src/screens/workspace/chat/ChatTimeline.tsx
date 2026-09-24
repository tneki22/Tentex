import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowDown } from "lucide-react";
import type { AttemptOutcome, ChatMessageRead } from "../../../api/chat";
import { OfflineNotice } from "../../../components/domain";
import { Button } from "../../../components/ui";
import { TypedMessage } from "./TypedMessage";
import { parsePayload } from "./payload";

export interface StreamFailure {
  code: string;
  detail: string;
  retryText?: string;
}

const OFFLINE_CODES = new Set(["ai_disabled", "ai_role_disabled", "ai_model_not_configured", "ai_credentials_missing"]);
const UNREACHABLE_CODES = new Set(["ai_provider_unavailable", "ai_timeout", "ai_rate_limited"]);

interface ChatTimelineProps {
  projectId: string;
  messages: ChatMessageRead[];
  streamingMessageId: string | null;
  preparing: boolean;
  onAnswerAgain?: () => void;
  onCheckAgain?: (attemptId: string) => Promise<void>;
  onSelfAssessment?: (
    attemptId: string,
    outcome: Exclude<AttemptOutcome, "unscored">,
  ) => Promise<void>;
  onApplyProposal?: (messageId: string, selected: number[]) => Promise<void>;
  onRejectProposal?: (messageId: string) => Promise<void>;
  proposalBusy?: boolean;
  nodeTitles?: Record<string, string>;
  onFollowUp?: (text: string) => void;
  /** Строка ожидания ответа: поиск в интернете идёт дольше обычного ответа. */
  preparingLabel?: string;
  onRetry: () => void;
  failure: StreamFailure | null;
}

export function ChatTimeline({
  projectId, messages, streamingMessageId, preparing,
  onAnswerAgain, onCheckAgain, onSelfAssessment,
  onApplyProposal, onRejectProposal, proposalBusy, nodeTitles, onFollowUp,
  preparingLabel = "Готовлю ответ", onRetry, failure,
}: ChatTimelineProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const followTailRef = useRef(true);
  const headingRefs = useRef(new Map<string, HTMLHeadingElement>());
  const previousAtomicIds = useRef<Set<string> | null>(null);
  const previousLength = useRef(messages.length);
  const wasStreaming = useRef(false);
  const [showJump, setShowJump] = useState(false);
  const [streamAnnouncement, setStreamAnnouncement] = useState("");
  const verdictAttemptIds = new Set(
    messages.flatMap((message) => message.grade_attempt_id ? [message.grade_attempt_id] : []),
  );
  const answerTextByAttempt = new Map(
    messages.flatMap((message) => {
      const payload = parsePayload(message);
      return payload.kind === "answer_form" && message.attempt_id
        ? [[message.attempt_id, payload.data.text] as const]
        : [];
    }),
  );

  function distanceFromBottom(): number {
    const node = scrollRef.current;
    if (!node) return 0;
    return node.scrollHeight - node.scrollTop - node.clientHeight;
  }

  useLayoutEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    // Своё только что отправленное сообщение видно всегда, даже если ленту
    // перед этим прокрутили вверх.
    const grew = messages.length > previousLength.current;
    previousLength.current = messages.length;
    if (grew && messages.at(-1)?.role === "user") followTailRef.current = true;
    if (followTailRef.current) {
      node.scrollTop = node.scrollHeight;
      setShowJump(false);
    } else {
      setShowJump(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length, messages.at(-1)?.text, preparing]);

  // Высота ленты меняется и без новых сообщений: поле ввода растёт и схлопывается
  // после отправки, раскрывается диф. Пока читатель внизу, держим его внизу.
  useEffect(() => {
    const node = scrollRef.current;
    const rail = node?.firstElementChild;
    if (!node || !rail || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(() => {
      if (followTailRef.current) node.scrollTop = node.scrollHeight;
    });
    observer.observe(node);
    observer.observe(rail);
    return () => observer.disconnect();
  }, []);

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

  const streaming = streamingMessageId !== null;
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
            <div className={`chat-timeline-item ${message.id.startsWith("pending-user-") ? "is-sending" : ""}`} key={message.id}>
              <TypedMessage
                projectId={projectId}
                message={message}
                isStreaming={message.id === streamingMessageId}
                answerText={message.grade_attempt_id
                  ? answerTextByAttempt.get(message.grade_attempt_id) ?? ""
                  : ""}
                needsCheck={Boolean(
                  message.attempt_id && !verdictAttemptIds.has(message.attempt_id),
                )}
                onAnswerAgain={onAnswerAgain}
                onCheckAgain={onCheckAgain}
                onSelfAssessment={onSelfAssessment}
                onApplyProposal={onApplyProposal}
                onRejectProposal={onRejectProposal}
                proposalBusy={proposalBusy}
                nodeTitles={nodeTitles}
                onFollowUp={onFollowUp}
                headingRef={(heading) => {
                  if (heading) headingRefs.current.set(message.id, heading);
                  else headingRefs.current.delete(message.id);
                }}
              />
            </div>
          ))}
          {preparing && (
            <div className="chat-timeline-item">
              <p className="chat-status-line" role="status">
                {preparingLabel}
                <span className="chat-thinking-dots" aria-hidden="true"><i /><i /><i /></span>
              </p>
            </div>
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
