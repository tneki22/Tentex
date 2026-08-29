import { useCallback, useEffect, useRef, useState } from "react";
import {
  streamAnswersLink,
  type AnswersLinkProgress,
  type AnswersLinkRead,
} from "../api/bindings";

export type AnswerAutoMatchState =
  | { status: "idle" }
  | { status: "running"; progress: AnswersLinkProgress | null }
  | { status: "complete"; result: AnswersLinkRead }
  | { status: "attention"; result: AnswersLinkRead }
  | { status: "error"; message: string };

export function useAnswerAutoMatch(
  projectId: string,
  materialId: string | null,
  onCompleted: (result: AnswersLinkRead) => void | Promise<void>,
) {
  const [state, setState] = useState<AnswerAutoMatchState>({ status: "idle" });
  const controllerRef = useRef<AbortController | null>(null);
  const onCompletedRef = useRef(onCompleted);
  onCompletedRef.current = onCompleted;

  useEffect(() => () => controllerRef.current?.abort(), []);
  useEffect(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setState({ status: "idle" });
  }, [materialId, projectId]);

  const run = useCallback(async () => {
    if (!projectId || !materialId || controllerRef.current) return;
    const controller = new AbortController();
    controllerRef.current = controller;
    setState({ status: "running", progress: null });
    let result: AnswersLinkRead | null = null;
    try {
      for await (const event of streamAnswersLink(projectId, materialId, controller.signal)) {
        if (controller.signal.aborted) return;
        if (event.type === "progress") {
          setState({ status: "running", progress: event.progress });
        } else {
          result = event.result;
        }
      }
      if (!result) throw new Error("Сервер не вернул сводку сопоставления");
      await onCompletedRef.current(result);
      if (!controller.signal.aborted) {
        setState({ status: result.complete ? "complete" : "attention", result });
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setState({
          status: "error",
          message: error instanceof Error ? error.message : "Не удалось сопоставить ответы",
        });
      }
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  }, [materialId, projectId]);

  const dismiss = useCallback(() => {
    if (!controllerRef.current) setState({ status: "idle" });
  }, []);

  return {
    state,
    run,
    dismiss,
    isRunning: state.status === "running",
  };
}
