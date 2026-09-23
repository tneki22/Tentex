import { Search } from "lucide-react";
import type { MaterialKindHint } from "../../api/projects";

export const MATERIAL_KIND_LABELS: Record<MaterialKindHint, string> = {
  textbook: "глава учебника",
  lecture: "лекция или конспект",
  article: "статья",
  video: "видеолекция",
  problems: "задачник",
};

interface MaterialHintProps {
  queries: string[];
  kind: MaterialKindHint | null | undefined;
}

/**
 * Подсказка ИИ, где искать материал для темы без опоры в источниках:
 * «Где искать: «градиентный спуск», «backprop» · лекция или конспект».
 * Ничего не показывает, если подсказки нет, — пустая строка здесь хуже тишины.
 */
export function MaterialHint({ queries, kind }: MaterialHintProps) {
  if (queries.length === 0 && !kind) return null;
  return (
    <p className="material-hint">
      <Search size={13} aria-hidden="true" />
      <span>
        Где искать:{" "}
        {queries.map((query, index) => (
          <span key={query}>
            {index > 0 && ", "}
            <q>{query}</q>
          </span>
        ))}
        {kind && <span className="material-hint-kind">{queries.length > 0 ? " · " : ""}{MATERIAL_KIND_LABELS[kind]}</span>}
      </span>
    </p>
  );
}
