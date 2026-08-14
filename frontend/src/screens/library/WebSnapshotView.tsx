import { ExternalLink, Globe } from "lucide-react";
import type { LibraryMaterialDetailRead } from "../../api/materials";

interface WebSnapshotViewProps {
  material: LibraryMaterialDetailRead;
  /** Сохранённый текст снимка. Пока грузится — null. */
  snapshot: string | null;
  loading: boolean;
}

function domainOf(url: string | null): string {
  if (!url) return "источник неизвестен";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/**
 * Сохранённый читаемый снимок веб-страницы.
 *
 * Живой сайт внутрь Tentex не встраивается: материал — это то, что сохранено
 * локально и читается без сети. Внешняя ссылка остаётся отдельным действием.
 */
export function WebSnapshotView({ material, snapshot, loading }: WebSnapshotViewProps) {
  return (
    <div className="web-snapshot">
      <header className="web-snapshot-head">
        <span className="web-snapshot-domain">
          <Globe size={15} aria-hidden="true" />
          {domainOf(material.source_url)}
        </span>
        {material.retrieved_at && (
          <span className="web-snapshot-date">
            снимок от {new Date(material.retrieved_at).toLocaleDateString("ru-RU")}
          </span>
        )}
        {material.source_url && (
          <a
            className="web-snapshot-link"
            href={material.source_url}
            target="_blank"
            rel="noreferrer"
          >
            Открыть исходную страницу
            <ExternalLink size={13} aria-hidden="true" />
          </a>
        )}
      </header>
      {material.source_url && <p className="web-snapshot-url" title={material.source_url}>{material.source_url}</p>}
      {loading
        ? <p className="structured-page-empty">Открываем сохранённый снимок…</p>
        : <pre className="source-plain">{snapshot ?? "Снимок не читается."}</pre>}
    </div>
  );
}
