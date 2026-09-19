import { useEffect, useState } from "react";
import type { EvidenceDetail } from "../../api/coverage";
import { getMaterialPage, materialFragmentAssetUrl, type MaterialPageRead } from "../../api/materials";
import { ErrorState, LoadingState } from "../ui";
import { StructuredPage } from "./material-viewer";

interface EvidenceStructuredReaderProps {
  projectId: string;
  evidence: EvidenceDetail;
}

/** Связный диапазон опоры тем же рендерером, что и просмотрщик материала. */
export function EvidenceStructuredReader({ projectId, evidence }: EvidenceStructuredReaderProps) {
  const [pages, setPages] = useState<MaterialPageRead[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setPages(null);
    setError("");
    const numbers = Array.from(
      { length: evidence.page_to - evidence.page_from + 1 },
      (_, index) => evidence.page_from + index,
    );
    Promise.all(numbers.map((page) => getMaterialPage(
      projectId,
      evidence.material_id,
      page,
      controller.signal,
    )))
      .then((result) => { if (!controller.signal.aborted) setPages(result); })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Страницы не открылись");
      });
    return () => controller.abort();
  }, [projectId, evidence.id, evidence.material_id, evidence.page_from, evidence.page_to]);

  if (error) return <ErrorState message={error} />;
  if (!pages) return <LoadingState label="Загружаем страницы опоры" />;
  const selected = new Set(evidence.fragment_ids);
  return <div className="evidence-structured-reader">{pages.map((page) => (
    <StructuredPage
      key={page.id}
      page={{ ...page, fragments: page.fragments.filter((fragment) => selected.has(fragment.id)) }}
      focusedFragmentId={evidence.fragment_ids[0]}
      showOcrReview={false}
      assetUrl={(fragmentId) => materialFragmentAssetUrl(projectId, evidence.material_id, fragmentId)}
    />
  ))}</div>;
}
