import { useEffect, useRef, useState, type CSSProperties } from "react";
import { BookOpenCheck, FileQuestion, History, ListChecks, MessageSquare, MessageSquareText, ScrollText, Search, Sparkles, X } from "lucide-react";
import { cancelBackgroundJob } from "../../../api/backgroundJobs";
import type {
  ChatContextFlags,
  ChatContextPreview,
  ChatMessageRead,
  ChatKnowledgePolicy,
  ChatOperation,
  ChatRetrievalScope,
  ChatSendOptions,
  OralRecordingRead,
} from "../../../api/chat";
import { uploadOralDraft } from "../../../api/chat";
import type { ProgramNodeRead } from "../../../api/projects";
import { ProjectApiError } from "../../../api/projects";
import { startExhaustiveReview } from "../../../api/retrieval";
import { Button, EmptyState, ErrorState, LoadingState, Select, Switch } from "../../../components/ui";
import { useBackgroundJob } from "../../../hooks/useBackgroundJob";
import { AnswerFormCard } from "./AnswerFormCard";
import { ChatComposer } from "./ChatComposer";
import { ChatHeader } from "./ChatHeader";
import { ChatModelControl } from "./ChatModelControl";
import { ChatTimeline } from "./ChatTimeline";
import type { ChipDef } from "./ContextChips";
import { ContextChips } from "./ContextChips";
import { SkillPalette } from "./SkillPalette";
import type { PaletteCommandDef } from "./skills";
import { ChatConfirmDialog } from "./ChatConfirmDialog";
import { retrievalSources } from "./payload";
import { useExamChat } from "./useExamChat";

/** Кнопки операций учебного чата. Операция уходит полем, а не словами в тексте. */
const OPERATIONS: Array<{ key: Exclude<ChatOperation, "discuss">; label: string }> = [
  { key: "explain", label: "Объяснить" },
  { key: "find_evidence", label: "Найти подтверждения" },
  { key: "compare_sources", label: "Сравнить источники" },
  { key: "find_discrepancies", label: "Найти расхождения" },
];

// Одна выбранная модель обслуживает и реплику, и судью той же сессии —
// поэтому обе возможности сразу (как в `REQUIRED_MODEL_CAPABILITIES` на бэкенде).
const EXAM_MODEL_CAPABILITIES = ["streaming", "structured_output"];

/** Шесть чипов экзаменационного чата — вопрос/профиль/ответ/материал/попытки/история раздела. */
function buildExamContextChips(
  preview: ChatContextPreview | null,
  search: { enabled: boolean; count: number } | null,
): ChipDef[] | null {
  if (!preview) return null;
  const byKind = new Map(preview.manifest.map((entry) => [entry.kind, entry]));
  const fragmentEntries = preview.manifest.filter((entry) => entry.kind === "fragment");
  const fragmentCount = fragmentEntries.filter((entry) => entry.included).length;
  const node = byKind.get("program_node");
  const profile = byKind.get("profile");
  const reference = byKind.get("reference_answer");
  const attempts = byKind.get("attempts_digest");
  const sectionMemory = byKind.get("section_memory");

  return [
    {
      key: "question", icon: FileQuestion, title: "Вопрос", flagKey: null,
      included: true, chars: node?.chars ?? 0, count: null, reason: null,
      description: "Название текущего вопроса или темы.",
    },
    {
      key: "profile", icon: MessageSquareText, title: "Профиль", flagKey: "profile",
      included: Boolean(profile?.included), chars: profile?.chars ?? 0, count: null,
      reason: profile?.reason ?? null,
      description: "Подготовка и предпочтения из профиля проекта.",
    },
    {
      key: "reference", icon: ScrollText, title: "Ответ", flagKey: "reference",
      included: Boolean(reference?.included), chars: reference?.chars ?? 0, count: null,
      reason: reference?.reason ?? null,
      description: "Ответ, сохранённый для этого вопроса.",
    },
    {
      // Только привязки темы; найденное поиском — отдельный чип ниже.
      key: "fragments", icon: ListChecks, title: `Привязанные материалы · ${fragmentCount}`, flagKey: "fragments",
      included: fragmentCount > 0, chars: fragmentEntries.reduce((sum, e) => sum + (e.included ? e.chars : 0), 0),
      count: fragmentCount, reason: fragmentEntries.length === 0 ? null : (fragmentEntries[0]?.reason ?? null),
      description: "Фрагменты, привязанные к вопросу. Открыть их можно в «Материалах».",
    },
    ...(search ? [{
      key: "retrieval", icon: Search, title: `Поиск по материалам · ${search.count}`, flagKey: "retrieval",
      included: search.enabled, chars: 0, count: search.count,
      reason: search.enabled ? null : "excluded_by_user",
      description: "Места из материалов, найденные под вопрос. Число — сколько вошло в последний ответ.",
    }] : []),
    {
      key: "attempts", icon: History, title: "Попытки", flagKey: "attempts",
      included: false, chars: 0, count: null, reason: attempts?.reason ?? "not_implemented",
      futureNote: "Появится вместе с историей попыток раздела",
    },
    {
      key: "section_memory", icon: History, title: "История раздела", flagKey: "section_memory",
      included: false, chars: 0, count: null, reason: sectionMemory?.reason ?? "not_implemented",
      futureNote: "Появится вместе со сжатой памятью раздела",
    },
  ];
}

interface ExamChatPanelProps {
  projectId: string;
  node: ProgramNodeRead | null;
  onAttemptsChanged?: () => void;
  onAnsweringChange?: (value: boolean) => void;
  takeAnswerSeconds?: () => number;
  studyOnly?: boolean;
  projectChat?: boolean;
}

/** Сколько найденных мест вошло в последний ответ модели. */
function lastSourceCount(messages: ChatMessageRead[]): number {
  const last = [...messages].reverse().find((message) => message.role === "examiner" && message.payload_kind === "none");
  return last ? retrievalSources(last).length : 0;
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

export function ExamChatPanel({ projectId, node, onAttemptsChanged, onAnsweringChange, takeAnswerSeconds, studyOnly = false, projectChat = false }: ExamChatPanelProps) {
  const chat = useExamChat({ projectId, node, onAttemptsChanged, projectChat });
  const [answering, setAnswering] = useState(false);
  const [answerMode, setAnswerMode] = useState<"memory" | "supported">("memory");
  const [responseFormat, setResponseFormat] = useState<"text" | "oral">("text");
  const [oralDraft, setOralDraft] = useState<OralRecordingRead | null>(null);
  useEffect(() => { onAnsweringChange?.(answering); return () => onAnsweringChange?.(false); }, [answering, onAnsweringChange]);
  useEffect(() => { setAnswering(false); setAnswerDraft(""); setOralDraft(null); takeAnswerSeconds?.(); }, [node?.id]);
  useEffect(() => { setOralDraft(null); }, [chat.activeSessionId]);
  const [answerDraft, setAnswerDraft] = useState("");
  const [searching, setSearching] = useState(false);
  const [toolBusy, setToolBusy] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [retrievalScope, setRetrievalScope] = useState<ChatRetrievalScope>(
    projectChat ? "project" : studyOnly ? "topic_project" : "linked_topic",
  );
  const [knowledgePolicy, setKnowledgePolicy] = useState<ChatKnowledgePolicy>("sources_only");
  const [operation, setOperation] = useState<ChatOperation>("discuss");
  const [chatZoom, setChatZoom] = useState(() => {
    const saved = Number(window.localStorage.getItem("tentex:chat-zoom"));
    return Number.isFinite(saved) && saved >= 0.8 && saved <= 1.2 ? saved : 1;
  });
  const [exhaustiveJobId, setExhaustiveJobId] = useState<string | null>(null);
  const [exhaustiveError, setExhaustiveError] = useState("");
  const completedExhaustiveJob = useRef<string | null>(null);
  const exhaustive = useBackgroundJob(exhaustiveJobId);

  useEffect(() => {
    if (
      exhaustive.job?.state === "completed"
      && completedExhaustiveJob.current !== exhaustive.job.id
    ) {
      completedExhaustiveJob.current = exhaustive.job.id;
      chat.reloadDetail();
    }
  }, [exhaustive.job?.id, exhaustive.job?.state]);

  const topicTitle = node?.title ?? "материалы проекта";

  if (!node && !projectChat) {
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
      if (studyOnly) return;
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

  async function startExhaustive() {
    if (!chat.activeSessionId) return;
    const query = chat.draft.trim() || `Сделай полный обзор: ${topicTitle}`;
    const command = {
      query,
      scope: retrievalScope,
      node_id: node?.id ?? null,
      material_ids: [],
      knowledge_policy: knowledgePolicy,
    };
    setExhaustiveError("");
    try {
      await startExhaustiveReview(projectId, chat.activeSessionId, {
        ...command,
        confirmed: false,
      });
    } catch (error) {
      if (
        !(error instanceof ProjectApiError)
        || error.code !== "retrieval_exhaustive_confirmation_required"
      ) {
        setExhaustiveError(error instanceof Error ? error.message : "Обзор не запущен");
        return;
      }
      const count = Number(error.context.material_count ?? 0);
      const bytes = Number(error.context.size_bytes ?? 0);
      const accepted = window.confirm(
        `Настроенная модель последовательно прочитает ${count} материал(а), `
        + `примерно ${(bytes / 1024 / 1024).toFixed(1)} МБ. Запустить полный обзор?`,
      );
      if (!accepted) return;
    }
    try {
      const run = await startExhaustiveReview(projectId, chat.activeSessionId, {
        ...command,
        confirmed: true,
      });
      completedExhaustiveJob.current = null;
      setExhaustiveJobId(run.job_id);
      chat.setDraft("");
      chat.reloadDetail();
    } catch (error) {
      setExhaustiveError(error instanceof Error ? error.message : "Обзор не запущен");
    }
  }

  const isEmpty = chat.messages.length === 0 && !chat.preparing && !answering && !searching;

  return (
    <div className="exam-chat-panel" style={{ "--chat-reading-zoom": chatZoom } as CSSProperties}>
      <ChatHeader
        sessions={chat.sessions}
        activeSessionId={chat.activeSessionId}
        session={chat.session}
        settingsError={chat.settingsError}
        onSelectSession={chat.setActiveSessionId}
        onNewChat={() => void chat.startNewChat()}
        onSettingsChange={chat.updateSettings}
        showResponseControl
        zoom={chatZoom}
        onZoomChange={(zoom) => { setChatZoom(zoom); window.localStorage.setItem("tentex:chat-zoom", String(zoom)); }}
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
          {/* Ошибка первого хода видна в ленте: пустое приглашение её бы спрятало. */}
          {isEmpty && !chat.failure ? (
            <div className="chat-empty-invite">
              <p>Выберите действие или напишите сообщение</p>
              <div className="chat-empty-actions">
                {!studyOnly && <Button onClick={() => { setAnswerDraft(""); setAnswering(true); }}>
                  <BookOpenCheck size={14} />Сдать ответ
                </Button>}
                {studyOnly && <Button onClick={() => { setOperation("explain"); if (node) chat.setDraft(node.title); }}>
                  <BookOpenCheck size={14} />Объяснить
                </Button>}
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
              onRetry={() => { if (chat.failure?.retryText) void chat.sendMessage(chat.failure.retryText, chat.failure.retrieval); }}
              failureAction={chat.failure?.code === "retrieval_scope_empty" && chat.failure.retryText ? (
                <Button variant="secondary" onClick={() => {
                  const retry: ChatSendOptions = { ...(chat.failure?.retrieval ?? { knowledgePolicy }), scope: "topic_project" };
                  setRetrievalScope("topic_project");
                  void chat.sendMessage(chat.failure?.retryText, retry);
                }}>Искать по теме</Button>
              ) : undefined}
              onAnswerAgain={() => { setAnswerDraft(""); setOralDraft(null); setAnswering(true); }}
              onCheckAgain={chat.retryAttempt}
              onSelfAssessment={chat.assessAttempt}
            />
          )}

          <ContextChips
            label="Контекст и поиск"
            chips={buildExamContextChips(chat.contextPreview, chat.session.mode === "study" ? {
              enabled: chat.session.context_flags.retrieval ?? true,
              count: lastSourceCount(chat.messages),
            } : null)}
            contextFlags={chat.session.context_flags}
            onToggleFlag={(key, value) => void chat.updateSettings({
              context_flags: { [key]: value } as Partial<ChatContextFlags>,
            })}
            controls={chat.session.mode === "study" ? <div className="chat-retrieval-controls">
              <span className="chat-retrieval-label">Где искать</span>
              <Select
                ariaLabel="Область поиска"
                value={retrievalScope}
                options={[
                  ...(!projectChat ? [
                    { value: "linked_topic", label: "Связано с темой" },
                    { value: "topic_project", label: "Найти по теме" },
                  ] : []),
                  { value: "project", label: "Весь проект" },
                ]}
                onValueChange={(value) => value && setRetrievalScope(value as ChatRetrievalScope)}
              />
              <Switch
                checked={knowledgePolicy === "allow_model"}
                onCheckedChange={(checked) => setKnowledgePolicy(checked ? "allow_model" : "sources_only")}
                label="Знания модели"
                hint="Отделяются от источников"
              />
              <div className="chat-retrieval-commands" aria-label="Команды тьютора">
                {OPERATIONS.map((item) => (
                  <button
                    type="button"
                    key={item.key}
                    aria-pressed={operation === item.key}
                    onClick={() => {
                      setOperation((current) => (current === item.key ? "discuss" : item.key));
                      // Поле заполняется учебным запросом, а не названием команды:
                      // его можно поправить до отправки.
                      if (!chat.draft.trim() && node) chat.setDraft(node.title);
                    }}
                  >{item.label}</button>
                ))}
                <button
                  type="button"
                  onClick={() => void startExhaustive()}
                  disabled={Boolean(exhaustive.job && ["queued", "running", "paused"].includes(exhaustive.job.state))}
                ><Sparkles size={13} />По всем источникам</button>
              </div>
              {exhaustive.job && ["queued", "running", "paused"].includes(exhaustive.job.state) && (
                <div className="chat-exhaustive-progress" role="status">
                  <span>Полный обзор · {exhaustive.job.done} из {exhaustive.job.total}</span>
                  <Button variant="ghost" onClick={() => void cancelBackgroundJob(exhaustive.job!.id)}>
                    Отменить
                  </Button>
                </div>
              )}
              {(exhaustiveError || exhaustive.error || exhaustive.job?.error) && (
                <p className="retrieval-error">{exhaustiveError || exhaustive.error || exhaustive.job?.error}</p>
              )}
            </div> : undefined}
          />

          {answering ? (
            <AnswerFormCard
              mode="composing"
              projectId={projectId}
              question={topicTitle}
              ordinal={nextOrdinal(chat.messages)}
              value={answerDraft}
              answerMode={answerMode}
              responseFormat={responseFormat}
              onResponseFormatChange={(value) => {
                setResponseFormat(value);
                setAnswerDraft("");
                setOralDraft(null);
              }}
              oralDraft={oralDraft}
              onOralRecording={async (audio, durationMs) => {
                if (!chat.activeSessionId) throw new Error("Чат ещё не готов");
                const draft = await uploadOralDraft(
                  projectId, chat.activeSessionId, audio, durationMs,
                );
                setOralDraft(draft);
                return draft.transcript;
              }}
              onAnswerModeChange={setAnswerMode}
              onChange={setAnswerDraft}
              onSubmit={() => {
                const task = responseFormat === "oral" && oralDraft
                  ? chat.submitOralAnswer(oralDraft.id, answerDraft, answerMode)
                  : chat.submitAnswer(answerDraft, {
                      answer_mode: answerMode, active_seconds: takeAnswerSeconds?.() ?? null,
                    });
                void task.then((saved) => { if (saved) { setAnswering(false); setOralDraft(null); } });
              }}
              onCancel={() => { setAnswering(false); setOralDraft(null); }}
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
              value={chat.draft}
              onChange={chat.setDraft}
              onSend={() => {
                void chat.sendMessage(undefined, { scope: retrievalScope, knowledgePolicy, operation });
                setOperation("discuss");
              }}
              operation={operation !== "discuss" ? (
                <div className="chat-composer-operation">
                  <span>{OPERATIONS.find((item) => item.key === operation)?.label}</span>
                  <button type="button" aria-label="Отменить операцию" onClick={() => setOperation("discuss")}><X size={12} /></button>
                </div>
              ) : undefined}
              onStop={chat.stopMessage}
              onOpenPalette={() => setPaletteOpen(true)}
              modelPicker={
                <ChatModelControl
                  role="exam_chat_reply"
                  capabilities={EXAM_MODEL_CAPABILITIES}
                  value={chat.session.model_override}
                  parameters={chat.session.model_parameters}
                  contextBytes={chat.contextPreview?.total_bytes}
                  messageCount={chat.messages.length}
                  onChange={(value, parameters) => chat.updateSettings({
                    model_override: value,
                    model_parameters: value ? parameters : null,
                  })}
                />
              }
              modes={chat.capabilities?.modes ?? []}
              currentMode={chat.session.mode}
              onModeChange={(mode) => void chat.updateSettings({ mode })}
              showModeIndicator={!studyOnly}
              sending={chat.sending}
            />
          )}
        </>
      )}

      <ChatConfirmDialog
        confirmation={chat.confirmation}
        onConfirm={chat.confirmSend}
        onCancel={chat.cancelConfirmation}
      />

      <SkillPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        capabilities={chat.capabilities}
        onSelect={runCommand}
      />
    </div>
  );
}
