import { useEffect, useRef, useState } from "react";
import { History, MessageSquare, Plus } from "lucide-react";
import {
  createChatSession,
  getChatContext,
  getChatSession,
  listChatSessions,
  saveChatDraft,
  streamMessage,
  submitChatAnswer,
  type ChatContextRead,
  type ChatMessageRead,
  type ChatSessionDetail,
  type ChatSessionSummary,
} from "../../../api/chat";
import { ProjectApiError, type ProgramNodeRead } from "../../../api/projects";
import { Button, EmptyState, ErrorState, IconButton, LoadingState, Popover } from "../../../components/ui";
import { AnswerFormCard } from "./AnswerFormCard";
import { ChatComposer } from "./ChatComposer";
import { ChatTimeline, type PendingTurn, type StreamFailure } from "./ChatTimeline";

const DRAFT_DEBOUNCE_MS = 800;

interface ExamChatPanelProps {
  projectId: string;
  node: ProgramNodeRead | null;
}

function sessionTime(iso: string): string {
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

function nextOrdinal(messages: ChatMessageRead[]): number {
  return messages.filter((message) => message.payload_kind === "answer_form").length + 1;
}

export function ExamChatPanel({ projectId, node }: ExamChatPanelProps) {
  const [sessions, setSessions] = useState<ChatSessionSummary[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ChatSessionDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [contextInfo, setContextInfo] = useState<ChatContextRead | null>(null);
  const [draft, setDraft] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [pending, setPending] = useState<PendingTurn | null>(null);
  const [failure, setFailure] = useState<StreamFailure | null>(null);
  const [answering, setAnswering] = useState(false);
  const [submittingAnswer, setSubmittingAnswer] = useState(false);
  const [sessionsReloadKey, setSessionsReloadKey] = useState(0);
  const [detailReloadKey, setDetailReloadKey] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const loadToken = useRef(0);

  // Список чатов узла: если ещё ни одного нет, первый чат создаётся сразу —
  // отдельного «пустого» состояния без сессии не вводим, черновику всё равно
  // нужна сессия, чтобы пережить закрытие вкладки.
  useEffect(() => {
    if (!node) {
      setSessions(null);
      setActiveSessionId(null);
      return;
    }
    const controller = new AbortController();
    const token = ++loadToken.current;
    setLoadError("");
    setSessions(null);
    (async () => {
      try {
        const list = await listChatSessions(projectId, node.id, controller.signal);
        if (loadToken.current !== token) return;
        if (list.length === 0) {
          const created = await createChatSession(projectId, node.id);
          if (loadToken.current !== token) return;
          setSessions([{
            id: created.id,
            project_id: created.project_id,
            program_node_id: created.program_node_id,
            title: created.title,
            updated_at: created.updated_at,
            message_count: 0,
            last_outcome: null,
          }]);
          setActiveSessionId(created.id);
        } else {
          setSessions(list);
          setActiveSessionId(list[0].id);
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        setLoadError(error instanceof Error ? error.message : "Не удалось открыть чат");
      }
    })();
    return () => controller.abort();
  }, [projectId, node?.id, sessionsReloadKey]);

  useEffect(() => {
    if (!node) {
      setContextInfo(null);
      return;
    }
    const controller = new AbortController();
    getChatContext(projectId, node.id, controller.signal).then(setContextInfo).catch(() => undefined);
    return () => controller.abort();
  }, [projectId, node?.id]);

  useEffect(() => {
    if (!activeSessionId) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    setDetailLoading(true);
    setDetailError("");
    getChatSession(projectId, activeSessionId, controller.signal)
      .then((value) => {
        setDetail(value);
        setDraft(value.draft_text);
        setAnswering(false);
        setFailure(null);
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setDetailError(error instanceof Error ? error.message : "Не удалось открыть чат");
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [projectId, activeSessionId, detailReloadKey]);

  useEffect(() => {
    if (!activeSessionId) return;
    const timer = window.setTimeout(() => {
      void saveChatDraft(projectId, activeSessionId, draft).catch(() => undefined);
    }, DRAFT_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, activeSessionId]);

  async function refreshDetail() {
    if (!activeSessionId) return;
    try {
      const value = await getChatSession(projectId, activeSessionId);
      setDetail(value);
    } catch {
      // Лента останется прежней; следующее действие пользователя попробует снова.
    }
  }

  async function sendMessage() {
    const text = draft.trim();
    if (!activeSessionId || !text || sending) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setSending(true);
    setFailure(null);
    setPending({ userText: text, examinerText: "", streaming: true });
    setDraft("");
    try {
      for await (const event of streamMessage(projectId, activeSessionId, text, controller.signal)) {
        if (event.type === "delta") {
          setPending((current) => current && { ...current, examinerText: current.examinerText + event.text });
        } else if (event.type === "error") {
          setFailure({ code: event.code, detail: event.detail });
        }
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        // Остановлено пользователем — итоговое сообщение придёт с сервера ниже.
      } else if (error instanceof ProjectApiError) {
        setFailure({ code: error.code ?? "unknown", detail: error.message });
      } else {
        setFailure({ code: "unknown", detail: "Ответ не получен" });
      }
    } finally {
      setPending(null);
      setSending(false);
      abortRef.current = null;
      await refreshDetail();
    }
  }

  function stopMessage() {
    abortRef.current?.abort();
  }

  async function submitAnswer() {
    const text = draft.trim();
    if (!activeSessionId || !text || submittingAnswer) return;
    setSubmittingAnswer(true);
    try {
      await submitChatAnswer(projectId, activeSessionId, text);
      setDraft("");
      await saveChatDraft(projectId, activeSessionId, "");
      setAnswering(false);
      await refreshDetail();
    } catch (error) {
      setFailure({
        code: error instanceof ProjectApiError ? error.code ?? "unknown" : "unknown",
        detail: error instanceof Error ? error.message : "Ответ не сохранён",
      });
    } finally {
      setSubmittingAnswer(false);
    }
  }

  async function startNewChat() {
    if (!node) return;
    setHistoryOpen(false);
    const created = await createChatSession(projectId, node.id);
    setSessions((current) => [
      { id: created.id, project_id: created.project_id, program_node_id: created.program_node_id, title: created.title, updated_at: created.updated_at, message_count: 0, last_outcome: null },
      ...(current ?? []),
    ]);
    setActiveSessionId(created.id);
  }

  if (!node) {
    return <EmptyState title="Выберите вопрос слева" icon={<MessageSquare size={26} />}><p>Чат откроется для выбранного вопроса.</p></EmptyState>;
  }

  if (loadError) {
    return (
      <div className="chat-panel-error">
        <ErrorState title="Чат не открылся" message={loadError} />
        <Button onClick={() => setSessionsReloadKey((key) => key + 1)}>Повторить</Button>
      </div>
    );
  }

  if (sessions === null) return <LoadingState label="Загружаем чат" />;

  const contextLine = contextInfo && (
    `В запрос уходит: вопрос · ${contextInfo.reference_included ? "эталон · " : ""}материал (${contextInfo.material_count}) · последние ${contextInfo.tail_limit} сообщений`
  );

  return (
    <div className="exam-chat-panel">
      <header className="chat-panel-header">
        <div className="chat-panel-heading">
          <p className="chat-panel-question">{node.title}</p>
          <span className="chat-panel-title">{detail?.title ?? "…"}</span>
        </div>
        <div className="chat-panel-header-actions">
          <Popover
            open={historyOpen}
            onOpenChange={setHistoryOpen}
            title="Чаты этого вопроса"
            trigger={<IconButton label="История чатов"><History size={15} /></IconButton>}
          >
            <div className="chat-history-list">
              {sessions.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={`chat-history-item ${item.id === activeSessionId ? "is-active" : ""}`}
                  onClick={() => { setActiveSessionId(item.id); setHistoryOpen(false); }}
                >
                  <span className="chat-history-title">{item.title}</span>
                  <span className="chat-history-meta">{sessionTime(item.updated_at)} · {item.message_count} сообщ.</span>
                </button>
              ))}
            </div>
          </Popover>
          <Button variant="secondary" onClick={() => void startNewChat()}><Plus size={14} />Новый чат</Button>
        </div>
      </header>

      {detailLoading && <LoadingState label="Загружаем переписку" />}
      {detailError && (
        <div className="chat-panel-error">
          <ErrorState title="Переписка не загрузилась" message={detailError} />
          <Button onClick={() => setDetailReloadKey((key) => key + 1)}>Повторить</Button>
        </div>
      )}

      {detail && !detailLoading && !detailError && (
        <>
          {detail.messages.length === 0 && !pending && !answering ? (
            <div className="chat-empty-invite">
              <p>Выберите действие или задайте вопрос</p>
              <Button onClick={() => setAnswering(true)}><MessageSquare size={14} />Сдать ответ</Button>
            </div>
          ) : (
            <ChatTimeline
              messages={detail.messages}
              pending={pending}
              failure={failure}
              onAnswerAgain={() => { setDraft(""); setAnswering(true); }}
            />
          )}

          {contextLine && <p className="chat-context-line">{contextLine}</p>}

          {answering ? (
            <AnswerFormCard
              mode="composing"
              question={node.title}
              ordinal={nextOrdinal(detail.messages)}
              value={draft}
              onChange={setDraft}
              onSubmit={() => void submitAnswer()}
              onCancel={() => setAnswering(false)}
              busy={submittingAnswer}
            />
          ) : (
            <ChatComposer
              value={draft}
              onChange={setDraft}
              onSend={() => void sendMessage()}
              onStop={stopMessage}
              onAnswerClick={() => setAnswering(true)}
              sending={sending}
            />
          )}
        </>
      )}
    </div>
  );
}
