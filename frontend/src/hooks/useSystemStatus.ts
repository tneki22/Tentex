import { useCallback, useEffect, useRef, useState } from "react";
import { ApiUnreachableError, getSystemStatus, type SystemStatus } from "../api/system";

/** Пока вкладка видна, кнопка «Состояние» освежает число замечаний. Проверки на
 *  сервере лёгкие, но опрашивать чаще незачем: сбои журнала живут до проверки,
 *  а свежесть по открытию панели и так гарантирована. */
const STATUS_POLL_MS = 30_000;

export interface SystemStatusState {
  status: SystemStatus | null;
  /** Сервер не ответил вовсе — отличается от ответа с ошибкой. */
  unreachable: boolean;
  /** Сервер ответил, но сводку не отдал. */
  error: string | null;
  checking: boolean;
  /** Была ли хоть одна завершённая проверка: до неё кнопка не говорит «в порядке». */
  checked: boolean;
  refresh: () => void;
  /** Подставить сводку, пришедшую вместе с ответом команды (проба записи). */
  apply: (status: SystemStatus) => void;
}

export function useSystemStatus(): SystemStatusState {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [checked, setChecked] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);

  const refresh = useCallback(() => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setChecking(true);
    void getSystemStatus(controller.signal)
      .then((next) => {
        if (controller.signal.aborted) return;
        setStatus(next);
        setUnreachable(false);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        // Неизвестное не подменяется прошлым зелёным: старая сводка уходит.
        setStatus(null);
        setUnreachable(reason instanceof ApiUnreachableError);
        setError(reason instanceof ApiUnreachableError ? null : reason instanceof Error ? reason.message : "Сводка не загрузилась");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setChecking(false);
        setChecked(true);
      });
  }, []);

  const apply = useCallback((next: SystemStatus) => {
    controllerRef.current?.abort();
    setStatus(next);
    setUnreachable(false);
    setError(null);
    setChecking(false);
    setChecked(true);
  }, []);

  useEffect(() => {
    const refreshIfVisible = () => {
      if (!document.hidden) refresh();
    };
    refreshIfVisible();
    const timer = window.setInterval(refreshIfVisible, STATUS_POLL_MS);
    document.addEventListener("visibilitychange", refreshIfVisible);
    // Настройки моделей меняются из панели «Модели» и из Параметров — строка
    // возможностей должна догнать их сразу, а не через полминуты.
    window.addEventListener("tentex:ai-settings-updated", refreshIfVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refreshIfVisible);
      window.removeEventListener("tentex:ai-settings-updated", refreshIfVisible);
      controllerRef.current?.abort();
    };
  }, [refresh]);

  return { status, unreachable, error, checking, checked, refresh, apply };
}
