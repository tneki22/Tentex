import { useCallback, useEffect, useRef, useState } from "react";
import {
  deferCard,
  finishCardSession,
  getActiveCardSession,
  openCardSessionUnit,
  retryCardSession,
  reviewCard,
  type CardSessionRead,
} from "../api/cards";

export function useCardSession(projectId: string, initial: CardSessionRead | null) {
  const [session, setSession] = useState<CardSessionRead | null>(initial);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const openedKey = useRef("");

  useEffect(() => setSession(initial), [initial]);

  useEffect(() => {
    if (initial || !projectId) return;
    const controller = new AbortController();
    void getActiveCardSession(projectId, controller.signal)
      .then(setSession)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Активный сеанс не найден");
        }
      });
    return () => controller.abort();
  }, [initial, projectId]);

  useEffect(() => {
    if (!session || session.state !== "active" || session.position >= session.queue.length) return;
    const current = session.queue[session.position];
    const key = `${session.id}:${current.unit_id ?? "none"}`;
    if (openedKey.current === key) return;
    openedKey.current = key;
    void openCardSessionUnit(projectId, session.id, session.revision)
      .then(setSession)
      .catch((reason: unknown) => {
        if (reason instanceof Error && !reason.message.includes("уже изменён")) {
          setError(reason.message);
        }
      });
  }, [projectId, session]);

  const assess = useCallback(async (confidence: 1 | 2 | 3 | 4, activeSeconds: number) => {
    if (!session) return null;
    const current = session.queue[session.position];
    if (!current) return null;
    setSaving(true);
    setError("");
    try {
      const next = await reviewCard(projectId, session.id, current.card_id, {
        id: crypto.randomUUID(),
        expected_revision: session.revision,
        confidence,
        active_seconds: activeSeconds,
      });
      setSession(next);
      return next;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось сохранить оценку");
      return null;
    } finally {
      setSaving(false);
    }
  }, [projectId, session]);

  const defer = useCallback(async (activeSeconds: number) => {
    if (!session) return null;
    const current = session.queue[session.position];
    if (!current) return null;
    setSaving(true);
    try {
      const next = await deferCard(projectId, session.id, current.card_id, {
        id: crypto.randomUUID(),
        expected_revision: session.revision,
        active_seconds: activeSeconds,
      });
      setSession(next);
      return next;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось отложить карточку");
      return null;
    } finally {
      setSaving(false);
    }
  }, [projectId, session]);

  const finish = useCallback(async (action: "complete" | "cancel" = "complete") => {
    if (!session) return;
    setSaving(true);
    try {
      setSession(await finishCardSession(
        projectId,
        session.id,
        session.revision,
        action,
      ));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось завершить сеанс");
    } finally {
      setSaving(false);
    }
  }, [projectId, session]);

  const retry = useCallback(async () => {
    if (!session) return null;
    setSaving(true);
    setError("");
    try {
      const next = await retryCardSession(projectId, session.id, session.revision);
      openedKey.current = "";
      setSession(next);
      return next;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось начать повтор ошибок");
      return null;
    } finally {
      setSaving(false);
    }
  }, [projectId, session]);

  return { session, setSession, saving, error, assess, defer, finish, retry };
}
