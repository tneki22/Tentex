import { useEffect, useState } from "react";
import { BookOpen, Target } from "lucide-react";
import type { ChatMessageRead, ProgramChatDiffPayload } from "../../../api/chat";
import {
  applyProgramChatProposal,
  rejectProgramChatProposal,
  type ProgramChatManifestEntry,
} from "../../../api/programChat";
import type { ProgramChangeResult, ProgramState } from "../../../api/projects";
import { Button, ErrorState, LoadingState } from "../../../components/ui";
import { useProgramChat } from "../../../hooks/useProgramChat";
import { ChatComposer } from "./ChatComposer";
import { ChatHeader } from "./ChatHeader";
import { ChatModelControl } from "./ChatModelControl";
import { ChatTimeline } from "./ChatTimeline";
import type { ChipDef } from "./ContextChips";
import { ContextChips } from "./ContextChips";
import { parsePayload } from "./payload";

// Ответ приходит одной структурированной схемой, без потока — значит и
// `streaming` требовать незачем (так же на бэкенде, `program_chat.py`).
const PROGRAM_MODEL_CAPABILITIES = ["structured_output"];

const FLAG_META: Record<string, { title: string; icon: typeof BookOpen }> = {
  profile: { title: "Профиль цели", icon: Target },
  primary_sources: { title: "Оглавления основных", icon: BookOpen },
  secondary_sources: { title: "Оглавления дополнительных", icon: BookOpen },
  reference_sources: { title: "Оглавления справочных", icon: BookOpen },
};

function buildProgramChipList(
  manifest: ProgramChatManifestEntry[] | undefined,
): ChipDef[] | null {
  if (!manifest) return null;
  const byFlag = new Map<string, typeof manifest>();
  for (const entry of manifest) {
    if (!entry.flag_key) continue;
    const list = byFlag.get(entry.flag_key) ?? [];
    list.push(entry);
    byFlag.set(entry.flag_key, list);
  }
  return Object.entries(FLAG_META).map(([flagKey, meta]) => {
    const entries = byFlag.get(flagKey) ?? [];
    const included = entries.some((entry) => entry.included);
    const bytes = entries.reduce((sum, entry) => sum + entry.bytes, 0);
    const count = flagKey === "profile" ? null : entries.length;
    const reason = entries.find((entry) => !entry.included)?.reason ?? null;
    const title = count !== null && count > 0 ? `${meta.title} · ${count}` : meta.title;
    return {
      key: flagKey, icon: meta.icon, title, flagKey, included, bytes, count, reason,
    };
  });
}

interface ProgramChatWorkspaceProps {
  projectId: string;
  program: ProgramState;
  execute: (command: (revision: number) => Promise<ProgramChangeResult>) => Promise<ProgramChangeResult>;
  /** Сообщения активной сессии — вызывающая сторона строит по ним
   * `ProgramTreePreview` рядом (последний непринятый диф), не дублируя хук. */
  onMessagesChange?: (messages: ChatMessageRead[]) => void;
}

/** Режим «С ИИ» шага 4 мастера и раздела «Программа»: чат построения программы

 * с дифами. Дерево-предпросмотр справа рисует вызывающая сторона
 * (`TextbookProgramEditor` в режиме `ai`) — этот компонент только чат.
 */
export function ProgramChatWorkspace({ projectId, program, execute, onMessagesChange }: ProgramChatWorkspaceProps) {
  const chat = useProgramChat({ projectId });
  const [proposalBusy, setProposalBusy] = useState<string | null>(null);

  useEffect(() => {
    onMessagesChange?.(chat.messages);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chat.messages]);

  if (chat.loadError) {
    return (
      <div className="chat-panel-error">
        <ErrorState title="Чат не открылся" message={chat.loadError} />
        <Button onClick={chat.reloadSessions}>Повторить</Button>
      </div>
    );
  }
  if (chat.sessions === null) return <LoadingState label="Загружаем чат" />;

  const nodeTitles = Object.fromEntries(program.nodes.map((node) => [node.id, node.title]));
  const isEmpty = chat.messages.length === 0;

  async function handleApply(messageId: string, selected: number[]) {
    setProposalBusy(messageId);
    try {
      await execute((revision) => applyProgramChatProposal(projectId, messageId, selected, revision));
      await chat.reloadDetail();
    } finally {
      setProposalBusy(null);
    }
  }

  async function handleReject(messageId: string) {
    setProposalBusy(messageId);
    try {
      await rejectProgramChatProposal(projectId, messageId);
      await chat.reloadDetail();
    } finally {
      setProposalBusy(null);
    }
  }

  return (
    <div className="program-chat-workspace">
      <ChatHeader
        sessions={chat.sessions}
        activeSessionId={chat.activeSessionId}
        onSelectSession={chat.setActiveSessionId}
        onNewChat={() => void chat.startNewChat()}
        showModelControl={false}
        historyTitle="Чаты программы"
      />

      {chat.detailLoading && <LoadingState label="Загружаем переписку" />}
      {chat.detailError && (
        <div className="chat-panel-error">
          <ErrorState title="Переписка не загрузилась" message={chat.detailError} />
          <Button onClick={chat.retryDetail}>Повторить</Button>
        </div>
      )}

      {chat.session && !chat.detailLoading && !chat.detailError && (
        <>
          {isEmpty ? (
            <div className="chat-empty-invite">
              <h2>Составьте программу вместе с ИИ</h2>
              <p>
                Опишите, какие разделы вам интересны, или просто скажите:
                «Составь программу по моей цели». Здесь же можно попросить добавить,
                уточнить или убрать темы. ИИ сначала покажет изменения — вы сами
                решите, какие из них принять.
              </p>
              <p className="chat-empty-context-note">
                По умолчанию в контекст входят паспорт цели, оглавления подключённых
                источников и текущее дерево программы. Полный текст учебников не передаётся.
              </p>
            </div>
          ) : (
            <ChatTimeline
              projectId={projectId}
              messages={chat.messages}
              streamingMessageId={null}
              preparing={chat.sending}
              failure={chat.sendError ? { code: "program_chat_send_error", detail: chat.sendError } : null}
              onRetry={() => void chat.sendMessage(chat.draft)}
              onApplyProposal={handleApply}
              onRejectProposal={handleReject}
              proposalBusy={proposalBusy !== null}
              nodeTitles={nodeTitles}
            />
          )}

          <ContextChips
            chips={buildProgramChipList(chat.contextPreview?.manifest)}
            contextFlags={chat.session.context_flags}
            onToggleFlag={chat.updateContextFlag}
          />

          <ChatComposer
            value={chat.draft}
            onChange={chat.setDraft}
            onSend={() => void chat.sendMessage(chat.draft)}
            modelPicker={
              <ChatModelControl
                role="study_program_assistant"
                capabilities={PROGRAM_MODEL_CAPABILITIES}
                value={chat.session.model_override}
                parameters={chat.session.model_parameters}
                contextBytes={chat.contextPreview?.total_bytes}
                messageCount={chat.messages.length}
                onChange={chat.updateModel}
              />
            }
            showModeIndicator={false}
            sending={chat.sending}
          />
        </>
      )}
    </div>
  );
}

/** Разбор диффа последнего непринятого предложения — вызывающая сторона
 * (`TextbookProgramEditor` в режиме `ai`) передаёт результат в `ProgramTreePreview`. */
export function lastPendingDiff(messages: ChatMessageRead[] | undefined): ProgramChatDiffPayload | null {
  if (!messages) return null;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const payload = parsePayload(messages[index]);
    if (payload.kind === "program_diff" && !payload.data.rejected) {
      return payload.data;
    }
  }
  return null;
}
