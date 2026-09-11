import { useEffect, useRef, useState } from "react";
import type { ChatMessageRead } from "../api/chat";
import {
  createProgramChatSession,
  getProgramChatContext,
  getProgramChatSession,
  listProgramChatSessions,
  saveProgramChatDraft,
  sendProgramChatMessage,
  startProgramChatBuild,
  updateProgramChatContext,
  type ProgramChatBuildScenario,
  type ProgramChatContextPreview,
  type ProgramChatSessionDetail,
  type ProgramChatSessionSummary,
} from "../api/programChat";
import { useBackgroundJob } from "./useBackgroundJob";

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
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");
  const [buildJobId, setBuildJobId] = useState<string | null>(null);
  const [proposalBusyMessageId, setProposalBusyMessageId] = useState<string | null>(null);
  const [sessionsReloadKey, setSessionsReloadKey] = useState(0);
  const [detailReloadKey, setDetailReloadKey] = useState(0);

  const loadToken = useRef(0);
  const buildJob = useBackgroundJob(buildJobId);

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

  async function reloadDetail() {
    setDetailReloadKey((key) => key + 1);
  }

  async function startNewChat() {
    const created = await createProgramChatSession(projectId);
    setSessionsReloadKey((key) => key + 1);
    setActiveSessionId(created.id);
  }

  async function sendMessage(text: string) {
    if (!activeSessionId || !text.trim() || sending) return;
    setSending(true);
    setSendError("");
    try {
      await sendProgramChatMessage(projectId, activeSessionId, text.trim());
      setDraft("");
      await reloadDetail();
    } catch (error) {
      setSendError(error instanceof Error ? error.message : "Сообщение не отправилось");
    } finally {
      setSending(false);
    }
  }

  async function startBuild(scenario: ProgramChatBuildScenario, expectedProgramRevision: number) {
    if (!activeSessionId) return;
    const result = await startProgramChatBuild(
      projectId, activeSessionId, scenario, expectedProgramRevision,
    );
    setBuildJobId(result.job_id);
  }

  useEffect(() => {
    if (buildJob.job?.state === "completed") {
      setBuildJobId(null);
      void reloadDetail();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buildJob.job?.state]);

  function updateContextFlag(key: string, value: boolean) {
    if (!activeSessionId) return;
    setSession((current) => current
      ? { ...current, context_flags: { ...current.context_flags, [key]: value } }
      : current);
    void updateProgramChatContext(projectId, activeSessionId, { context_flags: { [key]: value } })
      .catch(() => void reloadDetail());
  }

  return {
    sessions, loadError, activeSessionId, setActiveSessionId,
    session, detailLoading, detailError, reloadDetail,
    contextPreview, draft, setDraft,
    sending, sendError, sendMessage,
    startNewChat,
    startBuild, buildJob: buildJob.job, buildJobError: buildJob.error,
    updateContextFlag,
    proposalBusyMessageId, setProposalBusyMessageId,
    reloadSessions: () => setSessionsReloadKey((key) => key + 1),
  };
}

export type UseProgramChatResult = ReturnType<typeof useProgramChat>;
export type { ChatMessageRead };
