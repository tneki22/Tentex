import { useSearchParams } from "react-router";
import { useEffect, useRef, useState } from "react";
import {
  checkAttempt,
  createChatSession,
  getChatCapabilities,
  getChatContextPreview,
  getChatSession,
  listChatSessions,
  runChatTool,
  saveChatDraft,
  setAttemptSelfAssessment,
  streamMessage,
  submitChatAnswer,
  updateChatSettings,
  type AttemptOutcome,
  type ChatCapabilities,
  type ChatContextPreview,
  type ChatMessageRead,
  type ChatSessionDetail,
  type ChatSessionSummary,
  type ChatSettingsPatch,
} from "../../../api/chat";
import { ProjectApiError, type ProgramNodeRead } from "../../../api/projects";

const DRAFT_DEBOUNCE_MS = 800;

export interface StreamFailure {
  code: string;
  detail: string;
  retryText?: string;
}

interface UseExamChatOptions {
  projectId: string;
  node: ProgramNodeRead | null;
  onAttemptsChanged?: () => void;
}

/**
 * Сетевое состояние вкладки «Чат», вынесенное из ExamChatPanel (AI-CHATS.md §21.6, задача 4).
 *
 * Сообщения хранятся нормализованно: `messagesById` + отдельный `messageOrder`.
 * `started` уже несёт message_id — экзаменаторская реплика заводится в момент
 * `started` и дальше только обновляется по месту (delta → completed), поэтому
 * лента не мигает и `completed` не требует полного перечитывания сессии.
 */
export function useExamChat({ projectId, node, onAttemptsChanged }: UseExamChatOptions) {
  const [urlParams] = useSearchParams();
  const preferredChat = urlParams.get("chat");
  const [sessions, setSessions] = useState<ChatSessionSummary[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [session, setSession] = useState<ChatSessionDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [messagesById, setMessagesById] = useState<Record<string, ChatMessageRead>>({});
  const [messageOrder, setMessageOrder] = useState<string[]>([]);
  const [capabilities, setCapabilities] = useState<ChatCapabilities | null>(null);
  const [contextPreview, setContextPreview] = useState<ChatContextPreview | null>(null);
  const [draft, setDraft] = useState("");
  const [preparing, setPreparing] = useState(false);
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
  const [failure, setFailure] = useState<StreamFailure | null>(null);
  const [submittingAnswer, setSubmittingAnswer] = useState(false);
  const [settingsError, setSettingsError] = useState("");
  const [sessionsReloadKey, setSessionsReloadKey] = useState(0);
  const [detailReloadKey, setDetailReloadKey] = useState(0);

  const abortRef = useRef<AbortController | null>(null);
  const loadToken = useRef(0);
  const deltaBuffer = useRef("");
  const flushScheduled = useRef(false);

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
          setActiveSessionId(list.find(item => item.id === preferredChat)?.id ?? list[0].id);
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        setLoadError(error instanceof Error ? error.message : "Не удалось открыть чат");
      }
    })();
    return () => controller.abort();
  }, [projectId, node?.id, sessionsReloadKey, preferredChat]);

  useEffect(() => {
    if (!node) {
      setCapabilities(null);
      return;
    }
    const controller = new AbortController();
    getChatCapabilities(projectId, node.id, controller.signal).then(setCapabilities).catch(() => undefined);
    return () => controller.abort();
  }, [projectId, node?.id]);

  function applySessionDetail(value: ChatSessionDetail) {
    setSession(value);
    setDraft(value.draft_text);
    setMessagesById(Object.fromEntries(value.messages.map((message) => [message.id, message])));
    setMessageOrder(value.messages.map((message) => message.id));
    setStreamingMessageId(null);
    setFailure(null);
  }

  useEffect(() => {
    if (!activeSessionId) {
      setSession(null);
      setMessagesById({});
      setMessageOrder([]);
      return;
    }
    const controller = new AbortController();
    setDetailLoading(true);
    setDetailError("");
    getChatSession(projectId, activeSessionId, controller.signal)
      .then(applySessionDetail)
      .catch((error) => {
        if (controller.signal.aborted) return;
        setDetailError(error instanceof Error ? error.message : "Не удалось открыть чат");
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, activeSessionId, detailReloadKey]);

  useEffect(() => {
    if (!activeSessionId) {
      setContextPreview(null);
      return;
    }
    const controller = new AbortController();
    getChatContextPreview(projectId, activeSessionId, controller.signal)
      .then(setContextPreview)
      .catch(() => undefined);
    return () => controller.abort();
  }, [projectId, activeSessionId, session?.persona, session?.strictness, session?.context_flags, session?.model_override]);

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
      applySessionDetail(value);
    } catch {
      // Лента останется прежней; следующее действие пользователя попробует снова.
    }
  }

  function upsertMessage(message: ChatMessageRead) {
    setMessagesById((current) => ({ ...current, [message.id]: message }));
    setMessageOrder((current) => (current.includes(message.id) ? current : [...current, message.id]));
  }

  function patchMessage(id: string, patch: Partial<ChatMessageRead>) {
    setMessagesById((current) => {
      const existing = current[id];
      if (!existing) return current;
      return { ...current, [id]: { ...existing, ...patch } };
    });
  }

  function flushDelta(messageId: string) {
    flushScheduled.current = false;
    const chunk = deltaBuffer.current;
    if (!chunk) return;
    deltaBuffer.current = "";
    setMessagesById((current) => {
      const existing = current[messageId];
      if (!existing) return current;
      return { ...current, [messageId]: { ...existing, text: existing.text + chunk } };
    });
  }

  function scheduleFlush(messageId: string) {
    if (flushScheduled.current) return;
    flushScheduled.current = true;
    requestAnimationFrame(() => flushDelta(messageId));
  }

  async function sendMessage(retryText?: string) {
    const text = (retryText ?? draft).trim();
    if (!activeSessionId || !text || streamingMessageId || preparing) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setFailure(null);
    setPreparing(true);
    const userId = `pending-user-${Date.now()}`;
    const now = new Date().toISOString();
    upsertMessage({
      id: userId,
      session_id: activeSessionId,
      sequence: -1,
      role: "user",
      text,
      stream_state: "complete",
      payload_kind: "none",
      payload: {},
      context_snapshot: {},
      skill: null,
      ai_run_id: null,
      attempt_id: null,
      grade_attempt_id: null,
      created_at: now,
      updated_at: now,
    });
    setDraft("");
    let examinerId: string | null = null;
    try {
      for await (const event of streamMessage(projectId, activeSessionId, text, controller.signal)) {
        if (event.type === "started") {
          examinerId = event.messageId;
          setPreparing(false);
          setStreamingMessageId(examinerId);
          upsertMessage({
            id: examinerId,
            session_id: activeSessionId,
            sequence: -1,
            role: "examiner",
            text: "",
            stream_state: "complete",
            payload_kind: "none",
            payload: {},
            context_snapshot: {},
            skill: null,
            ai_run_id: event.runId,
            attempt_id: null,
            grade_attempt_id: null,
            created_at: now,
            updated_at: now,
          });
        } else if (event.type === "delta" && examinerId) {
          deltaBuffer.current += event.text;
          scheduleFlush(examinerId);
        } else if (event.type === "completed") {
          if (examinerId) flushDelta(examinerId);
          upsertMessage(event.message);
        } else if (event.type === "error") {
          setFailure({ code: event.code, detail: event.detail, retryText: text });
          if (examinerId) patchMessage(examinerId, { stream_state: "failed" });
        }
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        if (examinerId) {
          flushDelta(examinerId);
          patchMessage(examinerId, { stream_state: "stopped" });
        }
      } else if (error instanceof ProjectApiError) {
        setFailure({ code: error.code ?? "unknown", detail: error.message, retryText: text });
      } else {
        setFailure({ code: "unknown", detail: "Ответ не получен", retryText: text });
      }
    } finally {
      setPreparing(false);
      setStreamingMessageId(null);
      abortRef.current = null;
    }
  }

  function stopMessage() {
    abortRef.current?.abort();
  }

  async function submitAnswer(text: string, tracking?: Parameters<typeof submitChatAnswer>[3]) {
    if (!activeSessionId || !text.trim() || submittingAnswer) return;
    setSubmittingAnswer(true);
    try {
      const result = await submitChatAnswer(projectId, activeSessionId, text.trim(), tracking);
      for (const message of result.messages) upsertMessage(message);
      await saveChatDraft(projectId, activeSessionId, "");
      setDraft("");
      onAttemptsChanged?.();
    } catch (error) {
      setFailure({
        code: error instanceof ProjectApiError ? error.code ?? "unknown" : "unknown",
        detail: error instanceof Error ? error.message : "Ответ не сохранён",
      });
      // Дорогая ступень может упасть уже после фиксации Attempt. Перечитываем
      // ленту, чтобы сохранённая форма сразу предложила «Проверить ещё раз».
      await refreshDetail();
      onAttemptsChanged?.();
    } finally {
      setSubmittingAnswer(false);
    }
  }

  async function retryAttempt(attemptId: string) {
    setFailure(null);
    try {
      await checkAttempt(projectId, attemptId);
      await refreshDetail();
      onAttemptsChanged?.();
    } catch (error) {
      setFailure({
        code: error instanceof ProjectApiError ? error.code ?? "unknown" : "unknown",
        detail: error instanceof Error ? error.message : "Проверка не завершена",
      });
    }
  }

  async function assessAttempt(attemptId: string, outcome: Exclude<AttemptOutcome, "unscored">) {
    try {
      await setAttemptSelfAssessment(projectId, attemptId, outcome);
      await refreshDetail();
      onAttemptsChanged?.();
    } catch (error) {
      setFailure({
        code: error instanceof ProjectApiError ? error.code ?? "unknown" : "unknown",
        detail: error instanceof Error ? error.message : "Самооценка не сохранилась",
      });
    }
  }

  async function startNewChat() {
    if (!node) return;
    const created = await createChatSession(projectId, node.id);
    setSessions((current) => [
      {
        id: created.id, project_id: created.project_id, program_node_id: created.program_node_id,
        title: created.title, updated_at: created.updated_at, message_count: 0, last_outcome: null,
      },
      ...(current ?? []),
    ]);
    setActiveSessionId(created.id);
  }

  async function updateSettings(patch: ChatSettingsPatch) {
    if (!activeSessionId || !session) return;
    const previous = session;
    setSession({
      ...session,
      ...patch,
      context_flags: patch.context_flags
        ? { ...session.context_flags, ...patch.context_flags }
        : session.context_flags,
      model_override: patch.model_override !== undefined ? patch.model_override : session.model_override,
    } as ChatSessionDetail);
    setSettingsError("");
    try {
      const updated = await updateChatSettings(projectId, activeSessionId, patch);
      setSession((current) => (current ? { ...current, ...updated, messages: current.messages } : updated));
    } catch (error) {
      setSession(previous);
      setSettingsError(
        error instanceof Error ? error.message : "Не удалось сохранить настройки. Проверьте подключение и повторите.",
      );
    }
  }

  async function runTool(toolKey: string, input: Record<string, unknown>) {
    if (!activeSessionId) return;
    await runChatTool(projectId, activeSessionId, toolKey, input);
    await refreshDetail();
  }

  const messages = messageOrder.map((id) => messagesById[id]).filter(Boolean);

  return {
    sessions,
    loadError,
    activeSessionId,
    setActiveSessionId,
    session,
    detailLoading,
    detailError,
    messages,
    capabilities,
    contextPreview,
    draft,
    setDraft,
    preparing,
    streaming: streamingMessageId !== null,
    streamingMessageId,
    sending: preparing || streamingMessageId !== null,
    failure,
    submittingAnswer,
    settingsError,
    sendMessage,
    stopMessage,
    submitAnswer,
    retryAttempt,
    assessAttempt,
    startNewChat,
    updateSettings,
    runTool,
    reloadSessions: () => setSessionsReloadKey((key) => key + 1),
    reloadDetail: () => setDetailReloadKey((key) => key + 1),
  };
}
