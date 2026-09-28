import { useEffect, useState } from "react";
import { BookOpen, Target } from "lucide-react";
import type { ChatMessageRead, ProgramChatDiffPayload } from "../../../api/chat";
import { applyProgramChatProposal, rejectProgramChatProposal } from "../../../api/programChat";
import type { ProjectChatManifestEntry } from "../../../api/projectChat";
import type { ProgramChangeResult, ProgramState } from "../../../api/projects";
import { OfflineNotice } from "../../../components/domain";
import { Button, ErrorState, LoadingState } from "../../../components/ui";
import { useAiRoleAvailability } from "../../../hooks/useAiRoleAvailability";
import { useProjectChat } from "../../../hooks/useProjectChat";
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

const FLAG_META: Record<string, { title: string; icon: typeof BookOpen; description: string }> = {
  profile: { title: "Профиль цели", icon: Target, description: "Цель и предпочтения из паспорта проекта." },
  primary_sources: { title: "Оглавления основных", icon: BookOpen, description: "Только пункты оглавлений. Посмотреть их можно в «Материалах»." },
  secondary_sources: { title: "Оглавления дополнительных", icon: BookOpen, description: "Только пункты оглавлений. Посмотреть их можно в «Материалах»." },
  reference_sources: { title: "Оглавления справочных", icon: BookOpen, description: "Только пункты оглавлений. Посмотреть их можно в «Материалах»." },
};

function buildProgramChipList(
  manifest: ProjectChatManifestEntry[] | undefined,
  contextFlags: Record<string, boolean>,
): ChipDef[] {
  // Переключатели должны оставаться доступны до загрузки предпросмотра
  // контекста: это особенно важно в мастере, где проект ещё не активирован.
  const entriesInManifest = manifest !== undefined;
  const availableEntries = manifest ?? [];
  const byFlag = new Map<string, ProjectChatManifestEntry[]>();
  for (const entry of availableEntries) {
    if (!entry.flag_key) continue;
    const list = byFlag.get(entry.flag_key) ?? [];
    list.push(entry);
    byFlag.set(entry.flag_key, list);
  }
  return Object.entries(FLAG_META).map(([flagKey, meta]) => {
    const entries = byFlag.get(flagKey) ?? [];
    const included = entriesInManifest
      ? entries.some((entry) => entry.included)
      : contextFlags[flagKey] ?? flagKey !== "reference_sources";
    const chars = entries.reduce((sum, entry) => sum + (entry.included ? entry.chars ?? 0 : 0), 0);
    const count = flagKey === "profile" ? null : entries.length;
    const reason = entries.find((entry) => !entry.included)?.reason ?? null;
    const title = count !== null && count > 0 ? `${meta.title} · ${count}` : meta.title;
    return {
      key: flagKey, icon: meta.icon, title, flagKey, included, chars, count, reason,
      description: meta.description,
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
  /** Свободный проект: программа строится от цели, источников может не быть. */
  variant?: "textbook" | "free";
  /** Материал с оглавлением — для быстрого старта «Составь по оглавлению». */
  outlineSourceName?: string | null;
  /** Переход в ручной режим редактора, когда модель недоступна. */
  onSwitchToManual?: () => void;
}

function quickStarts(variant: "textbook" | "free", outlineSourceName: string | null | undefined): string[] {
  if (variant === "textbook") return [];
  return [
    "Составь программу по моей цели",
    "Что нужно знать заранее, чтобы достичь цели?",
    ...(outlineSourceName ? [`Составь программу по оглавлению «${outlineSourceName}», оставь только нужное для цели`] : []),
  ];
}

/** Режим «С ИИ» шага 4 мастера и раздела «Программа»: чат построения программы

 * с дифами. Дерево-предпросмотр справа рисует вызывающая сторона
 * (`TextbookProgramEditor` в режиме `ai`) — этот компонент только чат.
 */
export function ProgramChatWorkspace({
  projectId, program, execute, onMessagesChange, variant = "textbook", outlineSourceName, onSwitchToManual,
}: ProgramChatWorkspaceProps) {
  const chat = useProjectChat({ projectId, channel: "program-chat" });
  const [proposalBusy, setProposalBusy] = useState<string | null>(null);
  const availability = useAiRoleAvailability("study_program_assistant", chat.session?.model_override);

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
        showResponseControl={false}
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
              {variant === "free" ? (
                <p>
                  Опишите, что хотите уметь, или начните с готового запроса. ИИ предложит
                  темы от вашей цели: сначала основы, потом главное. Для тем, которых нет
                  в ваших материалах, он подскажет, что и где искать. Изменения
                  применяются только после вашего согласия.
                </p>
              ) : (
                <p>
                  Опишите, какие разделы вам интересны, или просто скажите:
                  «Составь программу по моей цели». Здесь же можно попросить добавить,
                  уточнить или убрать темы. ИИ сначала покажет изменения — вы сами
                  решите, какие из них принять.
                </p>
              )}
              {availability.state === "disabled" && (
                <OfflineNotice reason="disabled" alternative="Программу можно собрать вручную." />
              )}
              {availability.state === "unavailable" && (
                <p className="program-chat-unavailable" role="status">{availability.reason}</p>
              )}
              {(availability.state === "disabled" || availability.state === "unavailable") && onSwitchToManual && (
                <Button variant="secondary" onClick={onSwitchToManual}>Собрать вручную</Button>
              )}
              {availability.state === "ready" && quickStarts(variant, outlineSourceName).length > 0 && (
                <div className="program-chat-quick-starts" aria-label="Быстрый старт">
                  {quickStarts(variant, outlineSourceName).map((text) => (
                    <Button key={text} variant="secondary" disabled={chat.sending} onClick={() => void chat.sendMessage(text)}>
                      {text}
                    </Button>
                  ))}
                </div>
              )}
              <p className="chat-empty-context-note">
                {variant === "free"
                  ? "В контекст входят цель, оглавления подключённых материалов, если они есть, и текущее дерево программы. Полный текст материалов не передаётся."
                  : "По умолчанию в контекст входят паспорт цели, оглавления подключённых источников и текущее дерево программы. Полный текст учебников не передаётся."}
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
            chips={buildProgramChipList(chat.contextPreview?.manifest, chat.session.context_flags)}
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
