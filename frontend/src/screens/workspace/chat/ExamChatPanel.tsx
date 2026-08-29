import { useRef, useState } from "react";
import { BookOpenCheck, MessageSquare, Search, Send } from "lucide-react";
import type { ProgramNodeRead } from "../../../api/projects";
import { Button, EmptyState, ErrorState, LoadingState } from "../../../components/ui";
import { AnswerFormCard } from "./AnswerFormCard";
import { ChatComposer, type ChatComposerHandle } from "./ChatComposer";
import { ChatHeader } from "./ChatHeader";
import { ChatTimeline } from "./ChatTimeline";
import { ContextChips } from "./ContextChips";
import { SkillPalette } from "./SkillPalette";
import type { PaletteCommandDef } from "./skills";
import { useExamChat } from "./useExamChat";

interface ExamChatPanelProps {
  projectId: string;
  node: ProgramNodeRead | null;
  onAttemptsChanged?: () => void;
}

function nextOrdinal(messages: { payload_kind: string }[]): number {
  return messages.filter((message) => message.payload_kind === "answer_form").length + 1;
}

function MaterialSearchPrompt({
  busy, onSubmit, onCancel,
}: {
  busy: boolean;
  onSubmit: (query: string) => void;
  onCancel: () => void;
}) {
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  return (
    <form
      className="chat-material-search-prompt"
      onSubmit={(event) => { event.preventDefault(); if (query.trim()) onSubmit(query.trim()); }}
    >
      <Search size={15} aria-hidden="true" />
      <input
        ref={ref}
        autoFocus
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Что искать в материалах проекта?"
        aria-label="Запрос по материалам"
        disabled={busy}
      />
      <Button variant="ghost" onClick={onCancel} disabled={busy}>Отменить</Button>
      <Button type="submit" disabled={busy || !query.trim()}>
        {busy ? "Ищем…" : "Найти"}
      </Button>
    </form>
  );
}

export function ExamChatPanel({ projectId, node, onAttemptsChanged }: ExamChatPanelProps) {
  const chat = useExamChat({ projectId, node, onAttemptsChanged });
  const [answering, setAnswering] = useState(false);
  const [answerDraft, setAnswerDraft] = useState("");
  const [searching, setSearching] = useState(false);
  const [toolBusy, setToolBusy] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const composerRef = useRef<ChatComposerHandle | null>(null);

  if (!node) {
    return <EmptyState title="Выберите вопрос слева" icon={<MessageSquare size={26} />}><p>Чат откроется для выбранного вопроса.</p></EmptyState>;
  }

  if (chat.loadError) {
    return (
      <div className="chat-panel-error">
        <ErrorState title="Чат не открылся" message={chat.loadError} />
        <Button onClick={chat.reloadSessions}>Повторить</Button>
      </div>
    );
  }

  if (chat.sessions === null) return <LoadingState label="Загружаем чат" />;

  function runCommand(def: PaletteCommandDef) {
    if (def.key === "answer") {
      setAnswerDraft(chat.draft);
      setAnswering(true);
      return;
    }
    if (def.key === "search_project_materials") {
      setSearching(true);
      return;
    }
    // Остальные ключи в палитре недоступны (available=false) и сюда не доходят —
    // SkillPalette блокирует выбор в choose().
  }

  async function submitSearch(query: string) {
    setToolBusy(true);
    try {
      await chat.runTool("search_project_materials", { query, node_id: node?.id });
    } finally {
      setToolBusy(false);
      setSearching(false);
    }
  }

  const isEmpty = chat.messages.length === 0 && !chat.preparing && !answering && !searching;

  return (
    <div className="exam-chat-panel">
      <ChatHeader
        question={node.title}
        sessions={chat.sessions}
        activeSessionId={chat.activeSessionId}
        session={chat.session}
        settingsError={chat.settingsError}
        onSelectSession={chat.setActiveSessionId}
        onNewChat={() => void chat.startNewChat()}
        onSettingsChange={chat.updateSettings}
      />

      {chat.detailLoading && <LoadingState label="Загружаем переписку" />}
      {chat.detailError && (
        <div className="chat-panel-error">
          <ErrorState title="Переписка не загрузилась" message={chat.detailError} />
          <Button onClick={chat.reloadDetail}>Повторить</Button>
        </div>
      )}

      {chat.session && !chat.detailLoading && !chat.detailError && (
        <>
          {isEmpty ? (
            <div className="chat-empty-invite">
              <p>Выберите действие или задайте вопрос</p>
              <div className="chat-empty-actions">
                <Button onClick={() => { setAnswerDraft(""); setAnswering(true); }}>
                  <BookOpenCheck size={14} />Сдать ответ
                </Button>
                <Button variant="secondary" onClick={() => composerRef.current?.focus()}>
                  <Send size={14} />Задать вопрос
                </Button>
                <Button variant="secondary" onClick={() => setSearching(true)}>
                  <Search size={14} />Найти в материалах
                </Button>
              </div>
            </div>
          ) : (
            <ChatTimeline
              projectId={projectId}
              messages={chat.messages}
              streamingMessageId={chat.streamingMessageId}
              preparing={chat.preparing}
              failure={chat.failure}
              onRetry={() => { if (chat.failure?.retryText) void chat.sendMessage(chat.failure.retryText); }}
              onAnswerAgain={() => { setAnswerDraft(""); setAnswering(true); }}
              onCheckAgain={chat.retryAttempt}
              onSelfAssessment={chat.assessAttempt}
            />
          )}

          <ContextChips
            preview={chat.contextPreview}
            contextFlags={chat.session.context_flags}
            onToggleFlag={(key, value) => void chat.updateSettings({ context_flags: { [key]: value } })}
          />

          {answering ? (
            <AnswerFormCard
              mode="composing"
              question={node.title}
              ordinal={nextOrdinal(chat.messages)}
              value={answerDraft}
              onChange={setAnswerDraft}
              onSubmit={() => { void chat.submitAnswer(answerDraft); setAnswering(false); }}
              onCancel={() => setAnswering(false)}
              busy={chat.submittingAnswer}
            />
          ) : searching ? (
            <MaterialSearchPrompt
              busy={toolBusy}
              onSubmit={(query) => void submitSearch(query)}
              onCancel={() => setSearching(false)}
            />
          ) : (
            <ChatComposer
              ref={composerRef}
              value={chat.draft}
              onChange={chat.setDraft}
              onSend={() => void chat.sendMessage()}
              onStop={chat.stopMessage}
              onOpenPalette={() => setPaletteOpen(true)}
              modes={chat.capabilities?.modes ?? []}
              sending={chat.sending}
            />
          )}
        </>
      )}

      <SkillPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        capabilities={chat.capabilities}
        onSelect={runCommand}
      />
    </div>
  );
}
