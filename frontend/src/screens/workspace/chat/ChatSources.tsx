import { AlertTriangle, ExternalLink } from "lucide-react";
import { Link } from "react-router";
import type { ChatRetrievalSource } from "../../../api/chat";
import { MarkdownView } from "../../../components/domain/markdown/MarkdownView";

function viewerPath(source: ChatRetrievalSource): string | null {
  if (!source.material_id) return null;
  return `/library/${source.material_id}${source.page ? `?page=${source.page}` : ""}`;
}

/** Содержимое окна цитаты: материал, локатор, фрагмент и переход в просмотрщик. */
export function CitationPreview({ source }: { source: ChatRetrievalSource }) {
  const path = viewerPath(source);
  return (
    <div className="chat-citation-preview">
      <header>
        <span className="chat-source-id">{source.id}</span>
        <div>
          <strong>{source.material}</strong>
          <small>{[source.block_title, source.locator].filter(Boolean).join(" · ")}</small>
        </div>
      </header>
      {source.also_in && source.also_in.length > 0 && (
        <p className="chat-source-also">Тот же текст: {source.also_in.join(", ")}</p>
      )}
      {source.warning && (
        <p className="chat-source-warning"><AlertTriangle size={13} aria-hidden="true" />{source.warning}</p>
      )}
      <MarkdownView className="chat-citation-text" text={source.text} />
      {path && (
        <Link to={path}>Открыть в просмотрщике <ExternalLink size={13} aria-hidden="true" /></Link>
      )}
    </div>
  );
}

/**
 * «Источники · N» под ответом: все переданные модели места, использованные в
 * тексте отмечены. Свёрнут по умолчанию — ответ читается без списка.
 */
export function ChatSourcesList({ sources, cited }: { sources: ChatRetrievalSource[]; cited: Set<string> }) {
  if (sources.length === 0) return null;
  return (
    <details className="chat-sources">
      <summary>Источники · {sources.length}</summary>
      <ol>
        {sources.map((source) => {
          const path = viewerPath(source);
          const used = cited.has(source.id);
          return (
            <li key={source.id} className={used ? "is-cited" : undefined}>
              <span className="chat-source-id">{source.id}</span>
              <span className="chat-source-name">
                {path ? <Link to={path}>{source.material}</Link> : source.material}
                <small>
                  {source.locator}
                  {source.also_in && source.also_in.length > 0 && ` · также в: ${source.also_in.join(", ")}`}
                </small>
              </span>
              {used && <span className="chat-source-used">в ответе</span>}
            </li>
          );
        })}
      </ol>
    </details>
  );
}
