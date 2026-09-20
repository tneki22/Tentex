import { useState } from "react";
import { ExternalLink, X } from "lucide-react";
import { Link } from "react-router";
import { QualityControl } from "../../preparation/QualityControl";
import type { AttemptOutcome, ChatMessageRead } from "../../../api/chat";
import { AnswerFormCard } from "./AnswerFormCard";
import { Markdown } from "./Markdown";
import { parsePayload } from "./payload";
import { ProgramDiffCard } from "./ProgramDiffCard";
import { ToolRunCard } from "./ToolRunCard";
import { VerdictCard } from "./VerdictCard";

interface TypedMessageProps {
  projectId: string;
  message: ChatMessageRead;
  answerText: string;
  needsCheck: boolean;
  isStreaming: boolean;
  /** Экзаменационный чат — форма ответа и вердикт. Program-чат их не показывает. */
  onAnswerAgain?: () => void;
  onCheckAgain?: (attemptId: string) => Promise<void>;
  onSelfAssessment?: (
    attemptId: string,
    outcome: Exclude<AttemptOutcome, "unscored">,
  ) => Promise<void>;
  /** Чат построения программы — карточка предложения. */
  onApplyProposal?: (messageId: string, selected: number[]) => Promise<void>;
  onRejectProposal?: (messageId: string) => Promise<void>;
  proposalBusy?: boolean;
  nodeTitles?: Record<string, string>;
  headingRef: (node: HTMLHeadingElement | null) => void;
}

/**
 * Единая точка выбора renderer по `payload_kind` — то самое место, за которым
 * прячется read-only Markdown (AI-CHATS.md: рендерер можно будет заменить
 * после объединения с веткой конспектов, не переделывая ленту).
 */
export function TypedMessage({
  projectId, message, answerText, needsCheck, isStreaming,
  onAnswerAgain, onCheckAgain, onSelfAssessment,
  onApplyProposal, onRejectProposal, proposalBusy = false, nodeTitles,
  headingRef,
}: TypedMessageProps) {
  const payload = parsePayload(message);
  const sources = (message.context_snapshot.retrieval_sources ?? []) as Array<{
    id: string;
    material: string;
    material_id: string;
    locator: string;
    page: number | null;
    text: string;
  }>;
  const [activeCitation, setActiveCitation] = useState<string | null>(null);
  const citation = sources.find((source) => source.id === activeCitation);

  if (payload.kind === "answer_form" && onAnswerAgain) {
    return (
      <AnswerFormCard
        mode="submitted"
        payload={payload.data}
        createdAt={message.created_at}
        onAnswerAgain={onAnswerAgain}
        onCheckAgain={needsCheck && message.attempt_id && onCheckAgain
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

  if (payload.kind === "program_diff") {
    return (
      <ProgramDiffCard
        summary={message.text}
        diff={payload.data}
        busy={proposalBusy}
        onApply={onApplyProposal ? (selected) => onApplyProposal(message.id, selected) : undefined}
        onReject={onRejectProposal ? () => onRejectProposal(message.id) : undefined}
        nodeTitles={nodeTitles}
        headingRef={headingRef}
      />
    );
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
      {message.role === "examiner" || message.role === "assistant"
        ? <Markdown
          text={message.text}
          citationIds={sources.map((source) => source.id)}
          onCitation={setActiveCitation}
        />
        : <p>{message.text}</p>}
      {citation && (
        <aside className="chat-citation-preview" aria-label={`Источник ${citation.id}`}>
          <header>
            <div><strong>{citation.material}</strong><small>{citation.locator}</small></div>
            <button type="button" onClick={() => setActiveCitation(null)} aria-label="Закрыть источник"><X size={14} /></button>
          </header>
          <p>{citation.text}</p>
          <Link to={`/library/${citation.material_id}${citation.page ? `?page=${citation.page}` : ""}`}>
            Открыть в просмотрщике <ExternalLink size={13} />
          </Link>
        </aside>
      )}
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
