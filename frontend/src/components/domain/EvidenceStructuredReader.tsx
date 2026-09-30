import { useEffect, useState } from "react";
import type { EvidenceSummary } from "../../api/coverage";
import { getMaterialPage, materialFragmentAssetUrl, type MaterialPageRead } from "../../api/materials";
import { ErrorState, LoadingState } from "../ui";
import { StructuredPage } from "./material-viewer";

interface EvidenceStructuredReaderProps {
  projectId: string;
  evidence: Pick<EvidenceSummary, "id" | "material_id" | "page_from" | "page_to" | "from_fragment_id" | "to_fragment_id">;
}

const PAGE_NUMBER = /^\s*\d{1,4}\s*$/;

/**
 * Кусок целиком тем же рендерером, что и просмотрщик материала: от заголовка до
 * последней опоры, с рисунками и несвязанными строками между опорами. Раньше здесь
 * оставался один выбранный фрагмент, и читатель видел одну строку без контекста.
 */
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
  if (!pages) return <LoadingState label="Загружаем текст куска" />;
  const ordered = pages.flatMap((page) => page.fragments.map((fragment) => fragment.id));
  const start = Math.max(0, ordered.indexOf(evidence.from_fragment_id));
  const endIndex = ordered.indexOf(evidence.to_fragment_id);
  const inside = new Set(ordered.slice(start, endIndex < 0 ? undefined : endIndex + 1));
  return <div className="evidence-structured-reader">{pages.map((page) => {
    const fragments = page.fragments.filter((fragment) => inside.has(fragment.id) && !PAGE_NUMBER.test(fragment.text));
    return fragments.length > 0 && (
      <StructuredPage
        key={page.id}
        page={{ ...page, fragments }}
        showOcrReview={false}
        assetUrl={(fragmentId) => materialFragmentAssetUrl(projectId, evidence.material_id, fragmentId)}
      />
    );
  })}</div>;
}
