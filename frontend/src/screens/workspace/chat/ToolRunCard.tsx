import { AlertTriangle, Search } from "lucide-react";
import type { ToolResultPayload } from "../../../api/chat";
import { MaterialSearchResults } from "./MaterialSearchResults";

const TOOL_TITLES: Record<string, string> = {
  search_project_materials: "Найти в материалах",
};

// output_kind второй ветки объединения типизирован как `string` (заведомо
// неизвестные Tools будущего), поэтому обычное сужение по `===` не сработает —
// нужен явный предикат через Extract.
function isMaterialSearchResult(
  payload: ToolResultPayload,
): payload is Extract<ToolResultPayload, { output_kind: "material_search_results" }> {
  return payload.output_kind === "material_search_results";
}

interface ToolRunCardProps {
  projectId: string;
  payload: ToolResultPayload;
  headingRef?: (node: HTMLHeadingElement | null) => void;
}

/** Карточка результата Tool — состояние выполнения плюс типизированный вывод по `output_kind`. */
export function ToolRunCard({ projectId, payload, headingRef }: ToolRunCardProps) {
  const title = TOOL_TITLES[payload.tool_key] ?? payload.tool_key;

  return (
    <article className={`chat-tool-card is-${payload.state}`}>
      <header className="chat-tool-card-header">
        <Search size={14} aria-hidden="true" />
        <h3 ref={headingRef} tabIndex={-1}>{title}</h3>
        {payload.query && <span className="chat-tool-card-query">«{payload.query}»</span>}
      </header>
      {payload.state === "failed" ? (
        <p className="chat-tool-card-failed">
          <AlertTriangle size={14} aria-hidden="true" />Поиск не выполнен. Попробуйте ещё раз.
        </p>
      ) : isMaterialSearchResult(payload) ? (
        <MaterialSearchResults projectId={projectId} query={payload.query} items={payload.result.items} />
      ) : (
        <p className="chat-tool-card-unknown">Результат получен, но пока не показывается в интерфейсе.</p>
      )}
    </article>
  );
}
