/** История: реальные занятия лентой, а не назначения календаря. */
import { useEffect, useMemo, useState } from "react";
import { BookOpen, ChevronLeft, ChevronRight, Clock, FileText, PenLine, Plus, X } from "lucide-react";
import {
  Button,
  Disclosure,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  Select,
} from "../../components/ui";
import { AnswerResultBadge, answerResultOf } from "../../components/domain";
import {
  preparation,
  errorText,
  activityLabels,
  type Activity,
  type Overview,
} from "../../api/preparation";
import { AttemptDetails } from "./AttemptDetails";
import { ManualActivityDialog } from "./ManualActivityDialog";
import { durationLabel, dateLabel } from "./dates";
import { longDateLabel, plural, WEEKDAYS_LONG, weekdayIndexOf, type DayFacts } from "./model";

const PAGE = 30;

interface HistoryTabProps {
  projectId: string;
  overview: Overview;
  days: DayFacts[];
  selected: string;
  onSelect: (date: string) => void;
  onChanged: () => void;
}

type Filters = {
  kind: string;
  outcome: string;
  section: string;
  q: string;
};

const EMPTY_FILTERS: Filters = { kind: "", outcome: "", section: "", q: "" };

const KIND_ICON: Record<string, typeof BookOpen> = {
  view: BookOpen,
  reading: BookOpen,
  material: FileText,
  conspect: FileText,
  chat: PenLine,
  answer: PenLine,
  manual: Clock,
};

/** Первое открытие и сумма времени вместо десятка одинаковых строк. */
function rollUp(items: Activity[]) {
  const seen = new Map<string, Activity>();
  const result: Activity[] = [];
  for (const item of items) {
    if (item.kind === "answer" || item.attempt_id) {
      result.push(item);
      continue;
    }
    const key = `${item.occurred_at.slice(0, 10)}:${item.node_id ?? item.title}:${item.kind}`;
    const known = seen.get(key);
    if (known) {
      known.seconds = (known.seconds ?? 0) + (item.seconds ?? 0);
      continue;
    }
    const copy = { ...item };
    seen.set(key, copy);
    result.push(copy);
  }
  return result;
}

/**
 * Лента занятий с фильтрами и постраничным просмотром.
 *
 * Повторные открытия сворачиваются: важны первое открытие и сумма времени
 * за день. Каждая сдача ответа при этом остаётся отдельным событием.
 */
export function HistoryTab({ projectId, overview, days, selected, onSelect, onChanged }: HistoryTabProps) {
  const [allDays, setAllDays] = useState(false);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ items: Activity[]; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [manual, setManual] = useState<Activity | "new" | null>(null);

  const sections = useMemo(
    () => [...new Set(overview.topics.map((topic) => topic.path[0]).filter(Boolean))] as string[],
    [overview.topics],
  );

  const query = useMemo(() => {
    const params = new URLSearchParams();
    if (!allDays) {
      params.set("date_from", selected);
      params.set("date_to", selected);
    }
    if (filters.kind) params.set("kind", filters.kind);
    if (filters.outcome) params.set("outcome", filters.outcome);
    if (filters.q) params.set("q", filters.q);
    params.set("offset", String(offset));
    params.set("limit", String(PAGE));
    return params;
  }, [allDays, selected, filters, offset]);

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    preparation
      .history(projectId, query, controller.signal)
      .then((value) => setData({ items: value.items, total: value.total }))
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorText(caught));
      });
    return () => controller.abort();
  }, [projectId, query]);

  useEffect(() => setOffset(0), [allDays, selected, filters]);

  const active = [
    filters.kind && { key: "kind", label: activityLabels[filters.kind] ?? filters.kind },
    filters.outcome && { key: "outcome", label: `результат: ${filters.outcome}` },
    filters.section && { key: "section", label: filters.section },
    filters.q && { key: "q", label: `«${filters.q}»` },
  ].filter(Boolean) as { key: keyof Filters; label: string }[];

  const visible = data
    ? rollUp(data.items).filter((item) => !filters.section || item.path[0] === filters.section)
    : [];
  const grouped = new Map<string, Activity[]>();
  for (const item of visible) {
    const date = item.occurred_at.slice(0, 10);
    grouped.set(date, [...(grouped.get(date) ?? []), item]);
  }

  return (
    <div className="prep-history">
      <aside className="prep-history-days">
        <Button variant={allDays ? "primary" : "secondary"} onClick={() => setAllDays((value) => !value)}>
          {allDays ? "Показан весь срок" : "За все дни"}
        </Button>
        <ul>
          {[...days].filter((day) => day.date <= overview.today).reverse().map((day) => (
            <li key={day.date}>
              <button
                type="button"
                className={!allDays && day.date === selected ? "is-selected" : undefined}
                onClick={() => {
                  setAllDays(false);
                  onSelect(day.date);
                }}
              >
                <span>{dateLabel(day.date)}</span>
                {durationLabel(day.seconds) && <em>{durationLabel(day.seconds)}</em>}
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <section className="prep-history-feed">
        <Disclosure summary={active.length ? `Фильтры · ${active.length}` : "Фильтры"} className="prep-filters">
          <div className="prep-form">
            <Field label="Событие">
              <Select
                ariaLabel="Событие"
                value={filters.kind || null}
                emptyOption="Любое"
                options={Object.entries(activityLabels)
                  .filter(([key]) => key !== "understood")
                  .map(([value, label]) => ({ value, label }))}
                onValueChange={(value) => setFilters({ ...filters, kind: value ?? "" })}
              />
            </Field>
            <Field label="Результат">
              <Select
                ariaLabel="Результат"
                value={filters.outcome || null}
                emptyOption="Любой"
                options={[
                  { value: "passed", label: "Хороший" },
                  { value: "partial", label: "Частично" },
                  { value: "failed", label: "Слабый" },
                  { value: "unscored", label: "Без проверки" },
                ]}
                onValueChange={(value) => setFilters({ ...filters, outcome: value ?? "" })}
              />
            </Field>
            <Field label="Раздел">
              <Select
                ariaLabel="Раздел"
                value={filters.section || null}
                emptyOption="Все разделы"
                options={sections.map((title) => ({ value: title, label: title }))}
                onValueChange={(value) => setFilters({ ...filters, section: value ?? "" })}
              />
            </Field>
            <Field label="Поиск">
              <input
                value={filters.q}
                placeholder="По названию вопроса"
                onChange={(event) => setFilters({ ...filters, q: event.target.value })}
              />
            </Field>
          </div>
        </Disclosure>

        <div className="prep-history-bar">
          <span>{data ? `${data.total} ${plural(data.total, "событие", "события", "событий")}` : "Загружаем"}</span>
          {active.map((chip) => (
            <button
              key={chip.key}
              type="button"
              className="prep-chip"
              onClick={() => setFilters({ ...filters, [chip.key]: "" })}
            >
              {chip.label} <X size={11} />
            </button>
          ))}
          {active.length > 0 && (
            <Button variant="ghost" onClick={() => setFilters(EMPTY_FILTERS)}>
              Сбросить
            </Button>
          )}
          <Button variant="secondary" onClick={() => setManual("new")} disabled={overview.readonly}>
            <Plus size={13} /> Добавить занятие
          </Button>
        </div>

        {error && <ErrorState title="История не загрузилась" message={error} />}
        {!data && !error && <LoadingState label="Загружаем историю" />}
        {data && !visible.length && (
          <EmptyState title="За выбранный период занятий нет">
            <p className="prep-note">Откройте вопрос из очереди — событие появится здесь.</p>
          </EmptyState>
        )}

        {[...grouped.entries()].map(([date, items]) => (
          <section key={date} className="prep-history-day">
            <h3>
              {longDateLabel(date)}, {WEEKDAYS_LONG[weekdayIndexOf(date)]}
            </h3>
            <ol className="prep-events">
              {items.map((item) => {
                const Icon = KIND_ICON[item.kind] ?? Clock;
                const time = new Date(item.occurred_at).toLocaleTimeString("ru-RU", {
                  hour: "2-digit",
                  minute: "2-digit",
                });
                const isAnswer = Boolean(item.attempt_id);
                return (
                  <li key={item.id} className="prep-event">
                    <span className="prep-event-time">{time}</span>
                    <span className="prep-event-icon">
                      <Icon size={14} />
                    </span>
                    <div className="prep-event-body">
                      <p className="prep-event-title">
                        {isAnswer ? "Сдал ответ" : activityLabels[item.kind] ?? "Занятие"}
                        {item.title && <> — «{item.title}»</>}
                      </p>
                      <p className="prep-event-meta">
                        {durationLabel(item.seconds ?? 0) ? `За день: ${durationLabel(item.seconds ?? 0)}` : null}
                        {item.kind === "manual" && item.note ? ` · ${item.note}` : null}
                      </p>
                      {isAnswer && (
                        <div className="prep-event-result">
                          <AnswerResultBadge result={answerResultOf(item.outcome)} />
                          <Button
                            variant="ghost"
                            onClick={() => setExpanded(expanded === item.id ? null : item.id)}
                          >
                            {expanded === item.id ? "Свернуть" : "Показать ответ"}
                          </Button>
                        </div>
                      )}
                      {expanded === item.id && (
                        <AttemptDetails
                          projectId={projectId}
                          activity={item}
                          readonly={overview.readonly}
                          onSaved={onChanged}
                          timezone={overview.settings.config.timezone}
                        />
                      )}
                      {item.kind === "manual" && !overview.readonly && (
                        <Button variant="ghost" onClick={() => setManual(item)}>
                          Исправить время
                        </Button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>
        ))}

        {data && data.total > PAGE && (
          <nav className="prep-pager" aria-label="Страницы истории">
            <Button variant="ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
              <ChevronLeft size={14} /> Раньше
            </Button>
            <span>
              {offset + 1}—{Math.min(offset + PAGE, data.total)} из {data.total}
            </span>
            <Button
              variant="ghost"
              disabled={offset + PAGE >= data.total}
              onClick={() => setOffset(offset + PAGE)}
            >
              Позже <ChevronRight size={14} />
            </Button>
          </nav>
        )}
      </section>

      {manual && (
        <ManualActivityDialog
          projectId={projectId}
          topics={overview.topics}
          activity={manual === "new" ? undefined : manual}
          onClose={() => setManual(null)}
          onSaved={() => {
            setManual(null);
            onChanged();
          }}
        />
      )}
    </div>
  );
}
