import { useCallback, useEffect, useRef, useState } from "react";
import {
  getEvidence,
  getTopicEvidence,
  type EvidenceDetail,
  type TopicEvidence,
} from "../api/coverage";

/** Опоры темы и постоянный выбор: обновление данных не вырывает открытый текст. */
export function useTopicEvidence(
  projectId: string,
  topicId: string | null,
  requestedEvidenceId?: string | null,
) {
  const [groups, setGroups] = useState<TopicEvidence | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(requestedEvidenceId ?? null);
  const [evidence, setEvidence] = useState<EvidenceDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;

  const loadGroups = useCallback(async (signal?: AbortSignal, acceptUpdate = false) => {
    if (!topicId) {
      setGroups(null);
      setEvidence(null);
      return;
    }
    const next = await getTopicEvidence(projectId, topicId, signal);
    if (signal?.aborted) return;
    if (groups && groups.coverage_revision !== next.coverage_revision && !acceptUpdate) {
      setUpdateAvailable(true);
      return;
    }
    setGroups(next);
    setUpdateAvailable(false);
    const current = selectedRef.current;
    const allIds = Object.values(next)
      .filter(Array.isArray)
      .flatMap((value) => value as Array<{ id: string }>)
      .map((item) => item.id);
    setSelectedId(current && allIds.includes(current) ? current : next.best_evidence_id);
  }, [groups, projectId, topicId]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setGroups(null);
    setEvidence(null);
    setSelectedId(requestedEvidenceId ?? null);
    void loadGroups(controller.signal, true)
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : "Опоры темы не загрузились");
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [projectId, topicId, requestedEvidenceId]); // loadGroups меняется после принятия revision.

  useEffect(() => {
    if (!selectedId) {
      setEvidence(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError("");
    getEvidence(projectId, selectedId, controller.signal)
      .then((next) => { if (!controller.signal.aborted) setEvidence(next); })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : "Опора не открылась");
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [projectId, selectedId]);

  return {
    groups,
    evidence,
    selectedId,
    select: setSelectedId,
    loading,
    error,
    updateAvailable,
    refresh: () => loadGroups(undefined, true),
  };
}
