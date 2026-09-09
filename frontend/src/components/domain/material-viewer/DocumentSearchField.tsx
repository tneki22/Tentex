import { Search } from "lucide-react";
import { useEffect, useRef } from "react";

export interface DocumentSearchFieldProps {
  query: string;
  /** `n / m` или «нет совпадений»; `null` — пока не искали. */
  matchLabel?: string | null;
  searching?: boolean;
  onQueryChange(query: string): void;
  /** Enter — вперёд, Shift+Enter — назад. */
  onQuerySubmit?(direction: 1 | -1): void;
}

/**
 * Поле поиска по документу: строка, счётчик совпадений, переход по Enter.
 *
 * Общее для Библиотеки и Материалов — раньше в Материалах стояла своя урезанная
 * копия без счётчика и без перехода, и одинаковое на вид поле вело себя иначе.
 */
export function DocumentSearchField({
  query,
  matchLabel = null,
  searching = false,
  onQueryChange,
  onQuerySubmit,
}: DocumentSearchFieldProps) {
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const typing = event.target instanceof HTMLElement
        && (event.target.tagName === "INPUT" || event.target.tagName === "TEXTAREA");
      if (typing) return;
      if (event.key === "/" || ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f")) {
        event.preventDefault();
        input.current?.focus();
        input.current?.select();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <label className={`viewer-search ${searching ? "is-busy" : ""}`.trim()}>
      <Search size={14} aria-hidden="true" />
      <span className="sr-only">Найти в материале</span>
      <input
        ref={input}
        type="search"
        value={query}
        placeholder="Найти в материале"
        onChange={(event) => onQueryChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== "Enter") return;
          event.preventDefault();
          onQuerySubmit?.(event.shiftKey ? -1 : 1);
        }}
      />
      {matchLabel && <span className="viewer-search-count" aria-live="polite">{matchLabel}</span>}
    </label>
  );
}
