import { FileSearch } from "lucide-react";
import { Link } from "react-router";
import type { MaterialSearchResultItem } from "../../../api/chat";
import { QualityBadge } from "../../../components/domain";

interface MaterialSearchResultsProps {
  projectId: string;
  query: string;
  items: MaterialSearchResultItem[];
}

/** Результат Tool `search_project_materials` — рисуется по `output_kind`, не самой моделью. */
export function MaterialSearchResults({ projectId, query, items }: MaterialSearchResultsProps) {
  if (items.length === 0) {
    return (
      <div className="chat-tool-empty">
        <FileSearch size={18} aria-hidden="true" />
        <p>По запросу «{query}» ничего не нашлось в обработанных материалах проекта.</p>
      </div>
    );
  }
  return (
    <ul className="chat-material-search-results">
      {items.map((item) => (
        <li key={item.fragment_id}>
          <Link
            to={`/projects/${projectId}/materials/${item.material_id}?page=${item.page_from}&focus=${item.fragment_id}`}
            className="chat-material-search-item"
          >
            <p className="chat-material-search-excerpt">{item.excerpt}</p>
            <div className="chat-material-search-meta">
              <span>{item.material_name}</span>
              <span>
                {item.block_title ? `${item.block_title} · ` : ""}
                стр. {item.page_from === item.page_to ? item.page_from : `${item.page_from}–${item.page_to}`}
              </span>
              <QualityBadge quality={item.quality} showReview />
              {item.already_bound && <span className="chat-material-search-bound">Уже привязан к теме</span>}
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}
