/** Учёт Рабочей области включается только серверным началом учебного дня. */
import type { Interval } from "../api/preparation";
import { useStudyDayState } from "./useStudyDayState";
import { useStudyTracking } from "./useStudyTracking";

/** Связывает состояние дня с таймером, не размазывая правило по экрану. */
export function useWorkspaceStudyTracking(
  projectId: string,
  nodeId: string | null,
  kind: Interval["kind"],
  enabled: boolean,
) {
  const dayState = useStudyDayState(projectId, enabled);
  const tracking = useStudyTracking(projectId, nodeId, kind, {
    enabled: enabled && Boolean(dayState.day?.started),
    studyDate: dayState.day?.date ?? "",
    initialSeconds: nodeId ? dayState.day?.seconds_by_node?.[nodeId] ?? 0 : 0,
  });
  return { dayState, tracking };
}
