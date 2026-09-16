import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Plus, Search } from "lucide-react";
import type { LessonBlockCommand } from "../../api/lessons";
import { searchProjectMaterials } from "../../api/search";
import { QualityBadge } from "../../components/domain";
import { Button, ErrorState, LoadingState, StatusBadge } from "../../components/ui";
import { renderSearchHighlights } from "../workspace/searchHighlights";
import { toSourcePlaces, type SourcePlace } from "../workspace/sourcePlaces";
import { errorText } from "./lessonTree";
import type { LessonPickerTarget } from "./LessonSourcePicker";

export interface MaterialSearchState {
  query: string;
  setQuery(value: string): void;
  places: SourcePlace[];
  terms: string[];
  loading: boolean;
  error: string;
  /** Поиск уже выполнялся — пустой список тогда значит «ничего не нашлось». */
  searched: boolean;
  run(value: string): void;
}

/**
 * Поиск по материалам проекта для правой панели.
 *
 * Состояние живёт в панели, а не во вкладке: найденные места нужны и диалогу
 * выбора — рельс «Найдено» листает ту же выдачу, что и список.
 */
export function useMaterialSearch(
  projectId: string,
  topicId: string | undefined,
  topicTitle: string,
): MaterialSearchState {
  const [query, setQuery] = useState(topicTitle);
  const [places, setPlaces] = useState<SourcePlace[]>([]);
  const [terms, setTerms] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState("");

  const search = useCallback(async (value: string, signal?: AbortSignal) => {
    if (!value.trim()) return;
    setLoading(true);
    setError("");
    try {
      const response = await searchProjectMaterials(projectId, value.trim(), { nodeId: topicId, limit: 20 }, signal);
      if (signal?.aborted) return;
      setPlaces(toSourcePlaces(response.results));
      setTerms(response.terms);
      setSearched(true);
    } catch (caught) {
      if (!signal?.aborted) setError(errorText(caught, "Поиск не выполнился"));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [projectId, topicId]);

  useEffect(() => {
    setQuery(topicTitle);
    setPlaces([]);
    setTerms([]);
    setSearched(false);
    if (!topicTitle) return;
    const controller = new AbortController();
    void search(topicTitle, controller.signal);
    return () => controller.abort();
  }, [topicTitle, search]);

  const run = useCallback((value: string) => { void search(value); }, [search]);
  return useMemo(
    () => ({ query, setQuery, places, terms, loading, error, searched, run }),
    [query, places, terms, loading, error, searched, run],
  );
}

interface LessonSearchTabProps {
  search: MaterialSearchState;
  busy: boolean;
  lessonId: string | null;
  lessonPages: Set<string>;
  onOpenPlace(target: LessonPickerTarget): void;
  onAdd(command: Omit<LessonBlockCommand, "expected_revision">): void;
}

/**
 * Найденные места темы. Строка ведёт не к привязке, а на свою страницу в
 * диалоге выбора: по одному абзацу выдачи нельзя решить, тот ли это кусок.
 */
export function LessonSearchTab({ search, busy, lessonId, lessonPages, onOpenPlace, onAdd }: LessonSearchTabProps) {
  function submit(event: FormEvent) {
    event.preventDefault();
    search.run(search.query);
  }

  return (
    <div className="lessons-search-tab">
      <form className="lessons-search-form" onSubmit={submit}>
        <label className="workspace-tree-search">
          <Search size={15} />
          <span className="sr-only">Поиск по материалам</span>
          <input
            type="search"
            placeholder="Ethernet кадр FCS"
            value={search.query}
            onChange={(event) => search.setQuery(event.target.value)}
          />
        </label>
        <Button type="submit" variant="secondary" disabled={search.loading}>Найти</Button>
      </form>
      {search.error && <ErrorState message={search.error} />}
      {search.loading && <LoadingState label="Ищем" />}
      {search.terms.length > 0 && !search.loading && (
        <p className="lessons-panel-hint">Искали по: {search.terms.join(" · ")}</p>
      )}
      {search.searched && search.places.length === 0 && !search.loading && (
        <p className="lessons-panel-hint">Ничего не найдено.</p>
      )}
      {search.places.length > 0 && (
        <ul className="lessons-search-results">
          {search.places.map((place) => (
            <li key={place.key}>
              <button
                type="button"
                className="lessons-search-result"
                onClick={() => onOpenPlace({ materialId: place.materialId, page: place.pageNumber })}
              >
                <p>{renderSearchHighlights(place.text, place.highlights)}</p>
                <small>{place.materialName} · стр. {place.pageNumber} · {place.fragmentIds.length} совпад.</small>
              </button>
              <div className="lessons-search-result-actions">
                <QualityBadge quality={place.quality} />
                {lessonPages.has(`${place.materialId}#${place.pageNumber}`) && <StatusBadge tone="info">в уроке</StatusBadge>}
                <Button
                  variant="ghost"
                  disabled={!lessonId || busy}
                  onClick={() => onAdd({ operation: "add_page", material_id: place.materialId, page_from: place.pageNumber })}
                >
                  <Plus size={14} />Страницу
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => onOpenPlace({ materialId: place.materialId, page: place.pageNumber })}
                >
                  Открыть страницу…
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
