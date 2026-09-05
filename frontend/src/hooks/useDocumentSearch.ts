import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export interface DocumentMatch {
  fragmentId: string;
  pageNumber: number;
  text: string;
  blockTitle: string | null;
  /** Словоформы, совпавшие с запросом: по ним подсвечивается страница. */
  matchedForms: string[];
}

type SearchProvider = (query: string, signal: AbortSignal) => Promise<DocumentMatch[]>;

const DEBOUNCE_MS = 250;

/** Одна буква совпадает почти со всем — до двух символов запрос не отправляется. */
const MIN_QUERY_LENGTH = 2;

/**
 * Поиск по документу поверх любого источника совпадений.
 *
 * Hook не знает ни про проект, ни про Библиотеку: провайдер передаётся снаружи.
 * Устаревший запрос отменяется — иначе ответ на «инд» приходил бы после ответа
 * на «индекс» и подменял результат.
 */
export function useDocumentSearch(provider: SearchProvider) {
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<DocumentMatch[]>([]);
  const [index, setIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const providerRef = useRef(provider);
  providerRef.current = provider;

  useEffect(() => {
    controller.current?.abort();
    const trimmed = query.trim();
    if (trimmed.length < MIN_QUERY_LENGTH) {
      setMatches([]);
      setIndex(0);
      setLoading(false);
      setError(null);
      return;
    }
    const next = new AbortController();
    controller.current = next;
    setLoading(true);
    const timer = window.setTimeout(() => {
      providerRef.current(trimmed, next.signal)
        .then((found) => {
          if (next.signal.aborted) return;
          setMatches(found);
          setIndex(0);
          setError(null);
        })
        .catch((caught: unknown) => {
          if (next.signal.aborted) return;
          setMatches([]);
          setError(caught instanceof Error ? caught.message : "Поиск не выполнился");
        })
        .finally(() => {
          if (!next.signal.aborted) setLoading(false);
        });
    }, DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      next.abort();
    };
  }, [query]);

  const step = useCallback((direction: 1 | -1) => {
    setIndex((current) => {
      if (matches.length === 0) return 0;
      return (current + direction + matches.length) % matches.length;
    });
  }, [matches.length]);

  const reset = useCallback(() => {
    setQuery("");
    setMatches([]);
    setIndex(0);
    setError(null);
  }, []);

  const current = matches[index] ?? null;
  const label = query.trim().length >= MIN_QUERY_LENGTH && !loading
    ? matches.length ? `${index + 1} / ${matches.length}` : "нет совпадений"
    : null;
  /** Подсвечивать надо все совпадения на странице, а не только текущее. */
  const forms = useMemo(
    () => [...new Set(matches.flatMap((match) => match.matchedForms))],
    [matches],
  );

  return { query, setQuery, matches, index, current, step, loading, error, reset, label, forms };
}
