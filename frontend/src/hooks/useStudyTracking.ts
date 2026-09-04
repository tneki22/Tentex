/** Активное время учитывается в одной видимой вкладке; таймер не зависит от рендеров React. */
import { useEffect, useRef, useState } from "react";
import { preparation, errorText, type Interval } from "../api/preparation";
import {
  acknowledgeIntervals,
  bufferInterval,
  pendingIntervals,
} from "./studyTimeBuffer";
const IDLE_MS = 5 * 60_000;
const HEARTBEAT_MS = 30_000;
const TICK_MS = 1000;
const SESSION_KEY = "tentex-study-session";
const sessionId = () => {
  let id = sessionStorage.getItem(SESSION_KEY);
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem(SESSION_KEY, id);
  }
  return id;
};
export function useStudyTracking(
  projectId: string,
  nodeId: string | null,
  kind: Interval["kind"],
  enabled = true,
) {
  const [paused, setPaused] = useState(false);
  const [state, setState] = useState("Ожидание");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const answerSeconds = useRef(0);
  const flushRef = useRef<() => Promise<void>>(async () => undefined);
  const answerReset = () => {
    const value = Math.floor(answerSeconds.current);
    answerSeconds.current = 0;
    return value;
  };
  useEffect(() => {
    if (!enabled || !nodeId) return;
    let stopped = false;
    let ownsLock = false;
    let lockRequested = false;
    let release: (() => void) | undefined;
    let lastActivity = Date.now();
    let lastTick = Date.now();
    let started: number | null = null;
    let lastHeartbeat = Date.now();
    let sending = false;
    let chain = Promise.resolve();
    const report = (caught: unknown) => {
      setError(errorText(caught));
    };
    const active = () =>
      !stopped &&
      !paused &&
      document.visibilityState === "visible" &&
      document.hasFocus() &&
      Date.now() - lastActivity < IDLE_MS;
    const persist = (end: number) => {
      if (started === null) return;
      const start = started;
      started = null;
      if (end <= start) return;
      const interval: Interval = {
        id: crypto.randomUUID(),
        session_id: sessionId(),
        node_id: nodeId,
        kind,
        started_at: new Date(start).toISOString(),
        ended_at: new Date(Math.min(end, start + IDLE_MS)).toISOString(),
      };
      chain = chain.catch(report).then(async () => {
        await bufferInterval(projectId, interval);
      });
      void chain.catch(report);
    };
    async function send() {
      if (sending) return;
      sending = true;
      try {
        await chain;
        const rows = await pendingIntervals(projectId);
        for (let offset = 0; offset < rows.length; offset += 200) {
          const result = await preparation.time(
            projectId,
            rows.slice(offset, offset + 200),
          );
          await acknowledgeIntervals(result.accepted_ids);
        }
        if (!stopped) setError(null);
      } catch (caught) {
        report(caught);
      } finally {
        sending = false;
      }
    }
    async function flush() {
      persist(Date.now());
      await send();
    }
    flushRef.current = flush;
    const touch = () => {
      lastActivity = Date.now();
    };
    function tick() {
      const now = Date.now();
      const elapsed = Math.min(now - lastTick, TICK_MS * 2);
      lastTick = now;
      if (!active()) {
        persist(Math.min(now, lastActivity + IDLE_MS));
        release?.();
        release = undefined;
        ownsLock = false;
        setState(
          paused
            ? "Пауза"
            : now - lastActivity >= IDLE_MS
              ? "Пауза: нет активности"
              : "Пауза: окно не активно",
        );
      } else if (ownsLock) {
        if (started === null) started = now;
        setState("Время учитывается");
        setSeconds((value) => value + elapsed / 1000);
        if (kind === "answer") answerSeconds.current += elapsed / 1000;
      } else if (!lockRequested) {
        if (!navigator.locks) {
          setError(
            "Браузер не поддерживает учёт в одной вкладке. Добавьте время вручную.",
          );
          return;
        }
        lockRequested = true;
        void navigator.locks
          .request(
            "tentex-study-active-tab",
            { ifAvailable: true },
            async (lock) => {
              if (!lock || !active()) return;
              ownsLock = true;
              await new Promise<void>((resolve) => {
                release = resolve;
              });
            },
          )
          .catch(report)
          .finally(() => {
            lockRequested = false;
          });
        setState("Ожидание активной вкладки");
      }
      if (now - lastHeartbeat >= HEARTBEAT_MS) {
        lastHeartbeat = now;
        void flush();
      }
    }
    const hide = () => {
      if (!document.hasFocus() || document.hidden) {
        persist(Date.now());
        release?.();
        release = undefined;
        ownsLock = false;
        void send();
      }
    };
    const events = ["pointerdown", "pointermove", "keydown", "scroll"] as const;
    events.forEach((event) =>
      window.addEventListener(event, touch, { passive: true }),
    );
    window.addEventListener("blur", hide);
    document.addEventListener("visibilitychange", hide);
    window.addEventListener("online", send);
    const timer = window.setInterval(tick, TICK_MS);
    tick();
    void send();
    return () => {
      stopped = true;
      persist(Date.now());
      release?.();
      void send();
      clearInterval(timer);
      events.forEach((event) => window.removeEventListener(event, touch));
      window.removeEventListener("blur", hide);
      document.removeEventListener("visibilitychange", hide);
      window.removeEventListener("online", send);
    };
  }, [projectId, nodeId, kind, enabled, paused]);
  return {
    state,
    seconds: Math.floor(seconds),
    paused,
    setPaused,
    error,
    retry: () => flushRef.current(),
    answerReset,
  };
}
