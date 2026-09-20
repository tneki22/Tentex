import { useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessageRead } from "../api/chat";
import {
  createProgramChatSession,
  getProgramChatContext,
  getProgramChatSession,
  listProgramChatSessions,
  saveProgramChatDraft,
  sendProgramChatMessage,
  updateProgramChatContext,
  type ProgramChatContextPreview,
  type ProgramChatSessionDetail,
  type ProgramChatSessionSummary,
} from "../api/programChat";

const DRAFT_DEBOUNCE_MS = 800;

interface UseProgramChatOptions {
  projectId: string;
}

/** Сетевое состояние ИИ-чата построения программы — без стрима: каждый ход

 * модели приходит одним структурированным ответом (`send_message`), а первая
 * тяжёлая сборка идёт фоновой задачей (`useBackgroundJob`).
 */
export function useProgramChat({ projectId }: UseProgramChatOptions) {
  const [sessions, setSessions] = useState<ProgramChatSessionSummary[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [session, setSession] = useState<ProgramChatSessionDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [contextPreview, setContextPreview] = useState<ProgramChatContextPreview | null>(null);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<PendingSend | null>(null);
  const [sendError, setSendError] = useState("");
  const [sessionsReloadKey, setSessionsReloadKey] = useState(0);
  const [detailReloadKey, setDetailReloadKey] = useState(0);

  // Асинхронные ответы сверяются с текущей сессией: пока модель думала,
  // пользователь мог открыть другой чат.
  const activeSessionRef = useRef<string | null>(null);
  activeSessionRef.current = activeSessionId;

  const loadToken = useRef(0);
  useEffect(() => {
    const controller = new AbortController();
    const token = ++loadToken.current;
    setLoadError("");
    setSessions(null);
    (async () => {
      try {
        const list = await listProgramChatSessions(projectId, controller.signal);
        if (loadToken.current !== token) return;
        if (list.length === 0) {
          const created = await createProgramChatSession(projectId);
          if (loadToken.current !== token) return;
          setSessions([{
            id: created.id,
            project_id: created.project_id,
            title: created.title,
            updated_at: created.updated_at,
            message_count: 0,
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
  }, [projectId, sessionsReloadKey]);

  function applySessionDetail(value: ProgramChatSessionDetail) {
    setSession(value);
    setDraft(value.draft_text);
  }

  useEffect(() => {
    if (!activeSessionId) {
      setSession(null);
      return;
    }
    const controller = new AbortController();
    setDetailLoading(true);
    setDetailError("");
    getProgramChatSession(projectId, activeSessionId, controller.signal)
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
    getProgramChatContext(projectId, activeSessionId, controller.signal)
      .then(setContextPreview)
      .catch(() => undefined);
    return () => controller.abort();
  }, [projectId, activeSessionId, session?.context_flags]);

  useEffect(() => {
    if (!activeSessionId) return;
    const timer = window.setTimeout(() => {
      void saveProgramChatDraft(projectId, activeSessionId, draft).catch(() => undefined);
    }, DRAFT_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, activeSessionId]);

  /** Полная перезагрузка с индикатором — для кнопки «Повторить» после ошибки открытия. */
  function retryDetail() {
    setDetailReloadKey((key) => key + 1);
  }

  /** Тихо перечитать переписку: без `detailLoading`, чтобы поле ввода и лента не
   * пропадали, и без перезаписи черновика — пользователь мог уже печатать следующее. */
  async function fetchDetail(sessionId: string): Promise<ProgramChatSessionDetail | null> {
    try {
      return await getProgramChatSession(projectId, sessionId);
    } catch {
      return null;
    }
  }

  async function reloadDetail() {
    const sessionId = activeSessionRef.current;
    if (!sessionId) return;
    const fresh = await fetchDetail(sessionId);
    if (fresh && activeSessionRef.current === sessionId) setSession(fresh);
  }

  async function startNewChat() {
    const created = await createProgramChatSession(projectId);
    setSessionsReloadKey((key) => key + 1);
    setActiveSessionId(created.id);
  }

  async function sendMessage(text: string) {
    const sessionId = activeSessionId;
    const clean = text.trim();
    if (!sessionId || !clean || pending?.sessionId === sessionId) return;

    // Сообщение появляется в ленте, а поле очищается до похода на сервер:
    // ответ модели идёт десятки секунд, ждать его ради этого нельзя.
    const message = optimisticUserMessage(sessionId, clean, session?.messages ?? []);
    setSendError("");
    setDraft("");
    setPending({ sessionId, message });

    let failure = "";
    try {
      await sendProgramChatMessage(projectId, sessionId, clean);
    } catch (error) {
      failure = error instanceof Error ? error.message : "Сообщение не отправилось";
    }

    // Пользовательская реплика на сервере сохраняется до вызова модели, поэтому
    // перечитать переписку нужно и после ошибки.
    const fresh = await fetchDetail(sessionId);
    if (activeSessionRef.current === sessionId) {
      if (fresh) {
        setSession(fresh);
      } else {
        setSession((current) => current
          ? { ...current, messages: [...current.messages, message] }
          : current);
      }
      if (failure) {
        setSendError(failure);
        setDraft((current) => current || clean);
      }
    }
    setPending((current) => (current?.message.id === message.id ? null : current));
  }

  function updateContextFlag(key: string, value: boolean) {
    if (!activeSessionId) return;
    setSession((current) => current
      ? { ...current, context_flags: { ...current.context_flags, [key]: value } }
      : current);
    void updateProgramChatContext(projectId, activeSessionId, { context_flags: { [key]: value } })
      .catch(() => void reloadDetail());
  }

  const sending = pending !== null && pending.sessionId === activeSessionId;
  const messages = useMemo(() => {
    const saved = session?.messages ?? [];
    return sending && pending ? [...saved, pending.message] : saved;
  }, [session?.messages, sending, pending]);

  return {
    sessions, loadError, activeSessionId, setActiveSessionId,
    session, messages, detailLoading, detailError, reloadDetail, retryDetail,
    contextPreview, draft, setDraft,
    sending, sendError, sendMessage,
    startNewChat,
    updateContextFlag,
    reloadSessions: () => setSessionsReloadKey((key) => key + 1),
  };
}

interface PendingSend {
  sessionId: string;
  message: ChatMessageRead;
}

function optimisticUserMessage(
  sessionId: string,
  text: string,
  saved: ChatMessageRead[],
): ChatMessageRead {
  const now = new Date().toISOString();
  return {
    id: `pending-${crypto.randomUUID()}`,
    session_id: sessionId,
    sequence: saved.reduce((max, item) => Math.max(max, item.sequence), 0) + 1,
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
  };
}

export type UseProgramChatResult = ReturnType<typeof useProgramChat>;
export type { ChatMessageRead };
