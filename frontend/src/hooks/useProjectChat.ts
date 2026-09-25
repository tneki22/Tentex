import { useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessageRead, ChatModelOverride } from "../api/chat";
import {
  projectChatApi,
  type ProjectChatChannel,
  type ProjectChatContextPreview,
  type ProjectChatSessionDetail,
  type ProjectChatSessionSummary,
} from "../api/projectChat";

const DRAFT_DEBOUNCE_MS = 800;

interface UseProjectChatOptions {
  projectId: string | null;
  channel: ProjectChatChannel;
  /** Ход потоком: этапы видны в ленте, ход можно остановить (поиск в интернете). */
  streaming?: boolean;
}

/** Данные этапов текущего хода, слитые по мере прихода кадров `progress`. */
export type ProjectChatProgress = { stage: string } & Record<string, unknown>;

const STOPPED_TEXT = "Поиск остановлен.";

/** Сетевое состояние проектного ИИ-чата (построение программы, поиск в интернете).
 * Ответ модели — один структурированный результат; поиск дополнительно присылает
 * этапы хода потоком.
 */
export function useProjectChat({ projectId, channel, streaming = false }: UseProjectChatOptions) {
  const api = useMemo(() => projectChatApi(projectId, channel), [projectId, channel]);
  const [sessions, setSessions] = useState<ProjectChatSessionSummary[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [session, setSession] = useState<ProjectChatSessionDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [contextPreview, setContextPreview] = useState<ProjectChatContextPreview | null>(null);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<PendingSend | null>(null);
  const [sendError, setSendError] = useState("");
  const [progress, setProgress] = useState<ProjectChatProgress | null>(null);
  const abortRef = useRef<AbortController | null>(null);
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
        const list = await api.list(controller.signal);
        if (loadToken.current !== token) return;
        if (list.length === 0) {
          const created = await api.create();
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
  }, [api, sessionsReloadKey]);

  function applySessionDetail(value: ProjectChatSessionDetail) {
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
    api.get(activeSessionId, controller.signal)
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
  }, [api, activeSessionId, detailReloadKey]);

  useEffect(() => {
    if (!activeSessionId) {
      setContextPreview(null);
      return;
    }
    const controller = new AbortController();
    api.getContext(activeSessionId, controller.signal)
      .then(setContextPreview)
      .catch(() => undefined);
    return () => controller.abort();
  }, [api, activeSessionId, session?.context_flags]);

  useEffect(() => {
    if (!activeSessionId) return;
    const timer = window.setTimeout(() => {
      void api.saveDraft(activeSessionId, draft).catch(() => undefined);
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
  async function fetchDetail(sessionId: string): Promise<ProjectChatSessionDetail | null> {
    try {
      return await api.get(sessionId);
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
    const created = await api.create();
    setSessionsReloadKey((key) => key + 1);
    setActiveSessionId(created.id);
  }

  async function sendMessage(text: string) {
    const sessionId = activeSessionId;
    const clean = text.trim();
    if (!sessionId || !clean || pending?.sessionId === sessionId) return;

    // Сообщение появляется в ленте, а поле очищается до похода на сервер:
    // ответ модели идёт десятки секунд, ждать его ради этого нельзя.
    const message = localMessage(sessionId, "user", clean, session?.messages ?? []);
    setSendError("");
    setDraft("");
    setPending({ sessionId, message });

    setProgress(null);

    let failure = "";
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      if (streaming) failure = await streamTurn(sessionId, clean, controller.signal);
      else await api.send(sessionId, clean);
    } catch (error) {
      if (!controller.signal.aborted) {
        failure = error instanceof Error ? error.message : "Сообщение не отправилось";
      }
    } finally {
      abortRef.current = null;
    }
    const stopped = controller.signal.aborted;

    // Пользовательская реплика на сервере сохраняется до вызова модели, поэтому
    // перечитать переписку нужно и после ошибки.
    const fresh = await fetchDetail(sessionId);
    if (activeSessionRef.current === sessionId) {
      if (fresh) {
        // Отметку об остановке сервер пишет, когда заметит обрыв соединения, —
        // это может случиться чуть позже нашего чтения.
        const last = fresh.messages.at(-1);
        const needsMark = stopped && last?.role === "user";
        setSession(needsMark
          ? { ...fresh, messages: [...fresh.messages, localMessage(sessionId, "assistant", STOPPED_TEXT, fresh.messages)] }
          : fresh);
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
    setProgress(null);
  }

  /** Читает поток хода; возвращает текст ошибки или пустую строку. */
  async function streamTurn(sessionId: string, text: string, signal: AbortSignal): Promise<string> {
    for await (const event of api.stream(sessionId, text, signal)) {
      if (event.type === "progress") {
        if (activeSessionRef.current === sessionId) {
          setProgress((current) => ({ ...current, ...event.data }));
        }
      } else if (event.type === "error") {
        return event.detail || "Поиск не удался";
      } else {
        return "";
      }
    }
    return "Соединение закрылось до ответа. Повторите запрос.";
  }

  /** Остановить ход: обрыв соединения отменяет его на сервере, в том числе вызов модели. */
  function stopMessage() {
    abortRef.current?.abort();
  }

  function updateContextFlag(key: string, value: boolean) {
    if (!activeSessionId) return;
    setSession((current) => current
      ? { ...current, context_flags: { ...current.context_flags, [key]: value } }
      : current);
    void api.updateContext(activeSessionId, { context_flags: { [key]: value } })
      .catch(() => void reloadDetail());
  }

  /** Смена модели дописывает в ленту системную отметку, поэтому перечитываем деталь. */
  async function updateModel(
    value: ChatModelOverride | null,
    parameters: Record<string, unknown>,
  ) {
    if (!activeSessionId) return;
    const detail = await api.updateSettings(activeSessionId, {
      model_override: value,
      model_parameters: value ? parameters : null,
    });
    setSession(detail);
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
    sending, sendError, sendMessage, stopMessage,
    progress: sending ? progress : null,
    startNewChat,
    updateContextFlag,
    updateModel,
    reloadSessions: () => setSessionsReloadKey((key) => key + 1),
  };
}

interface PendingSend {
  sessionId: string;
  message: ChatMessageRead;
}

/** Сообщение, которого на сервере ещё нет: своя реплика до ответа или отметка об остановке. */
function localMessage(
  sessionId: string,
  role: "user" | "assistant",
  text: string,
  saved: ChatMessageRead[],
): ChatMessageRead {
  const now = new Date().toISOString();
  return {
    id: `pending-${crypto.randomUUID()}`,
    session_id: sessionId,
    sequence: saved.reduce((max, item) => Math.max(max, item.sequence), 0) + 1,
    role,
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

export type UseProjectChatResult = ReturnType<typeof useProjectChat>;
export type { ChatMessageRead };
