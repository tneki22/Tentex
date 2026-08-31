import { Search, X } from "lucide-react";
import type { MaterialPresentationKind } from "../../api/materials";
import { Button, Select } from "../../components/ui";

export type LibraryKindFilter = "all" | MaterialPresentationKind;
export type LibraryStatusFilter = "all" | "ready" | "processing" | "paused" | "failed";
export type LibraryQualityFilter = "all" | "needs_review";
export type LibraryUsageFilter = "all" | "attached" | "unattached";
export type LibrarySort = "updated_desc" | "name_asc" | "created_desc";

export interface LibraryFilterState {
  q: string;
  kind: LibraryKindFilter;
  status: LibraryStatusFilter;
  quality: LibraryQualityFilter;
  usage: LibraryUsageFilter;
  sort: LibrarySort;
}

export const DEFAULT_FILTERS: LibraryFilterState = {
  q: "",
  kind: "all",
  status: "all",
  quality: "all",
  usage: "all",
  sort: "created_desc",
};

const KINDS: Array<{ value: LibraryKindFilter; label: string }> = [
  { value: "all", label: "Любой вид" },
  { value: "pdf", label: "PDF" },
  { value: "image", label: "Изображения" },
  { value: "document", label: "Документы" },
  { value: "plain_text", label: "Текст" },
  { value: "web", label: "Веб-страницы" },
  { value: "youtube", label: "YouTube" },
  { value: "audio", label: "Аудио" },
];

const STATUSES: Array<{ value: LibraryStatusFilter; label: string }> = [
  { value: "all", label: "Любое состояние" },
  { value: "ready", label: "Готовы" },
  { value: "processing", label: "Обрабатываются" },
  { value: "paused", label: "На паузе" },
  { value: "failed", label: "С ошибкой" },
];

const QUALITIES: Array<{ value: LibraryQualityFilter; label: string }> = [
  { value: "all", label: "Любое качество" },
  { value: "needs_review", label: "Нужно проверить" },
];

const USAGES: Array<{ value: LibraryUsageFilter; label: string }> = [
  { value: "all", label: "Все материалы" },
  { value: "attached", label: "В проектах" },
  { value: "unattached", label: "Не подключены" },
];

const SORTS: Array<{ value: LibrarySort; label: string }> = [
  { value: "created_desc", label: "Сначала новые" },
  { value: "updated_desc", label: "Недавно изменённые" },
  { value: "name_asc", label: "По названию" },
];

interface LibraryFiltersProps {
  value: LibraryFilterState;
  total: number;
  shown: number;
  onChange: (next: Partial<LibraryFilterState>) => void;
  onReset: () => void;
}

/**
 * Одна компактная строка над списком. Отдельной пустой hero-зоны здесь нет:
 * заголовок и главное действие живут в общей верхней полосе экрана.
 */
export function LibraryFilters({ value, total, shown, onChange, onReset }: LibraryFiltersProps) {
  const dirty = value.q.trim() !== ""
    || value.kind !== "all"
    || value.status !== "all"
    || value.quality !== "all"
    || value.usage !== "all";

  return (
    <div className="lib-filters" role="search">
      <label className="lib-search">
        <Search size={15} aria-hidden="true" />
        <span className="sr-only">Найти материал по названию</span>
        <input
          type="search"
          value={value.q}
          placeholder="Найти по названию"
          onChange={(event) => onChange({ q: event.target.value })}
        />
      </label>

      <div className="lib-filter-group">
        <Select
          className="lib-filter-select"
          ariaLabel="Вид источника"
          value={value.kind}
          options={KINDS}
          onValueChange={(next) => onChange({ kind: (next ?? "all") as LibraryKindFilter })}
        />
        <Select
          className="lib-filter-select"
          ariaLabel="Состояние обработки"
          value={value.status}
          options={STATUSES}
          onValueChange={(next) => onChange({ status: (next ?? "all") as LibraryStatusFilter })}
        />
        <Select
          className="lib-filter-select"
          ariaLabel="Качество распознавания"
          value={value.quality}
          options={QUALITIES}
          onValueChange={(next) => onChange({ quality: (next ?? "all") as LibraryQualityFilter })}
        />
        <Select
          className="lib-filter-select"
          ariaLabel="Использование в проектах"
          value={value.usage}
          options={USAGES}
          onValueChange={(next) => onChange({ usage: (next ?? "all") as LibraryUsageFilter })}
        />
      </div>

      <div className="lib-filter-tail">
        <Select
          className="lib-filter-select is-sort"
          ariaLabel="Порядок списка"
          value={value.sort}
          options={SORTS}
          onValueChange={(next) => onChange({ sort: (next ?? "created_desc") as LibrarySort })}
        />
        {/* Счётчик показывается только при фильтрах: без них общее число уже
            стоит в шапке экрана, и второй раз оно ничего не сообщает. */}
        {dirty && (
          <span className="lib-filter-count" aria-live="polite">
            {shown} из {total}
          </span>
        )}
        {dirty && (
          <Button variant="ghost" onClick={onReset}>
            <X size={14} aria-hidden="true" /> Сбросить
          </Button>
        )}
      </div>
    </div>
  );
}
