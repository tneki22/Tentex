import type { ReactNode } from "react";
import type { SearchHighlightRead } from "../../api/search";

/** Рисует серверные диапазоны FTS-попаданий одинаково во всех выдачах источников. */
export function renderSearchHighlights(text: string, highlights: SearchHighlightRead[]): ReactNode {
  if (highlights.length === 0) return text;
  const sorted = [...highlights].sort((left, right) => left.start - right.start);
  const nodes: ReactNode[] = [];
  let cursor = 0;
  sorted.forEach((range, index) => {
    if (range.start > cursor) nodes.push(text.slice(cursor, range.start));
    nodes.push(<mark key={index}>{text.slice(range.start, range.end)}</mark>);
    cursor = Math.max(cursor, range.end);
  });
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}
