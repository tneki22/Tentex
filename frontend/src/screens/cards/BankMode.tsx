import { useEffect, useMemo, useState } from "react";
import { Pencil, Plus, Search, Trash2, Undo2 } from "lucide-react";
import { Link } from "react-router";
import { bulkCards, updateCard, type CardFilters, type CardRead } from "../../api/cards";
import { useCardBank } from "../../hooks/useCardBank";
import {
  Button,
  Checkbox,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHead,
} from "../../components/ui";
import { CardEditor } from "./CardEditor";

interface BankModeProps {
  projectId: string;
  initialCardId?: string | null;
  onCreate: (unitId?: string | null) => void;
  onChanged: () => void;
}

type QuickFilter = "all" | "unrated" | "hard" | "recalled" | "lost" | "deleted";

const FILTERS: Array<{ value: QuickFilter; label: string }> = [
  { value: "all", label: "Все" },
  { value: "unrated", label: "Без оценок" },
  { value: "hard", label: "Сложные" },
  { value: "recalled", label: "Вспомненные" },
  { value: "lost", label: "Источник потерян" },
  { value: "deleted", label: "Удалённые" },
];

function relativeTime(value: string | null): string {
  if (!value) return "ещё не повторялась";
  const utc = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`;
  const seconds = Math.max(0, (Date.now() - new Date(utc).getTime()) / 1000);
  if (seconds < 60) return "только что";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} мин назад`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} ч назад`;
  return `${Math.floor(seconds / 86400)} дн назад`;
}

function cardCountLabel(count: number): string {
  const form = new Intl.PluralRules("ru").select(count);
  return `${count} ${form === "one" ? "карточка" : form === "few" ? "карточки" : "карточек"} в выборке`;
}

function apiFilters(
  query: string,
  filter: QuickFilter,
  unitId: string,
  source: string,
): CardFilters {
  return {
    query: query || undefined,
    unitId: unitId || undefined,
    source:
      source && source !== "all"
        ? (source as CardFilters["source"])
        : undefined,
    rating:
      ["unrated", "hard", "recalled", "lost"].includes(filter)
        ? (filter as CardFilters["rating"])
        : undefined,
    includeDeleted: filter === "deleted",
  };
}

export function BankMode({
  projectId,
  initialCardId = null,
  onCreate,
  onChanged,
}: BankModeProps) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<QuickFilter>("all");
  const [unitId, setUnitId] = useState("");
  const [source, setSource] = useState("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(initialCardId);
  const [editing, setEditing] = useState(false);
  const filters = useMemo(
    () => apiFilters(query, filter, unitId, source),
    [filter, query, source, unitId],
  );
  const { data, loading, error, refresh } = useCardBank(projectId, filters);
  const visible = data?.items.filter((card) =>
    filter === "deleted" ? card.deleted_at : !card.deleted_at,
  ) ?? [];
  const active = data?.items.find((card) => card.id === activeId) ?? null;

  useEffect(() => {
    if (initialCardId) setActiveId(initialCardId);
  }, [initialCardId]);

  useEffect(() => {
    if (!activeId && visible[0]) setActiveId(visible[0].id);
  }, [activeId, visible]);

  async function applyBulk(action: "delete" | "restore", cards?: CardRead[]) {
    const targets = cards ?? visible.filter((card) => selected.has(card.id));
    if (!targets.length) return;
    await bulkCards(projectId, {
      action,
      items: targets.map((card) => ({
        id: card.id,
        expected_revision: card.revision,
      })),
    });
    setSelected(new Set());
    setEditing(false);
    refresh();
    onChanged();
  }

  return (
    <div className="bank-mode">
      <PageHead
        eyebrow={data ? cardCountLabel(data.total) : "Банк проекта"}
        title="Банк карточек"
        actions={<Button onClick={() => onCreate(null)}><Plus size={15} /> Создать</Button>}
      />
      <section className="bank-toolbar">
        <label className="bank-search">
          <Search size={16} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Обе стороны, вопрос или раздел"
            aria-label="Найти карточку"
          />
        </label>
        <select value={unitId} onChange={(event) => setUnitId(event.target.value)} aria-label="Вопрос или билет">
          <option value="">Все вопросы и билеты</option>
          {data?.units.map((unit) => <option key={unit.id} value={unit.id}>{unit.title}</option>)}
        </select>
        <select value={source} onChange={(event) => setSource(event.target.value)} aria-label="Источник">
          <option value="all">Любой источник</option>
          <option value="none">Без источника</option>
          <option value="fragment">Фрагмент</option>
          <option value="reference">Готовый ответ</option>
        </select>
      </section>
      <nav className="bank-filter-tabs" aria-label="Фильтры карточек">
        {FILTERS.map((item) => (
          <button
            type="button"
            className={filter === item.value ? "is-active" : ""}
            key={item.value}
            onClick={() => setFilter(item.value)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {selected.size > 0 && (
        <div className="bank-bulk-bar">
          <strong>Выбрано: {selected.size}</strong>
          {filter === "deleted" ? (
            <Button variant="ghost" onClick={() => void applyBulk("restore")}>
              <Undo2 size={14} /> Восстановить
            </Button>
          ) : (
            <>
              <Button variant="ghost" className="is-destructive" onClick={() => void applyBulk("delete")}>
                <Trash2 size={14} /> Удалить
              </Button>
            </>
          )}
        </div>
      )}

      {loading && !data ? <LoadingState label="Загружаем Банк…" /> : error ? (
        <ErrorState title="Не удалось загрузить Банк" message={error}>
          <Button variant="secondary" onClick={refresh}>Повторить</Button>
        </ErrorState>
      ) : visible.length === 0 ? (
        <EmptyState title="В этой выборке карточек нет">
          <p>Измените фильтры или создайте первую карточку вручную.</p>
          <Button onClick={() => onCreate(unitId || null)}>Создать карточку</Button>
        </EmptyState>
      ) : (
        <div className="bank-layout">
          <section className="bank-table" aria-label="Карточки">
            <header className="bank-table-head">
              <Checkbox
                checked={visible.every((card) => selected.has(card.id))}
                onCheckedChange={(checked) =>
                  setSelected(checked ? new Set(visible.map((card) => card.id)) : new Set())
                }
                label="Выбрать все"
              />
            </header>
            {visible.map((card) => (
              <article
                key={card.id}
                className={`bank-row ${activeId === card.id ? "is-active" : ""}`}
                onClick={() => { setActiveId(card.id); setEditing(false); }}
              >
                <Checkbox
                  checked={selected.has(card.id)}
                  onCheckedChange={(checked) => {
                    setSelected((current) => {
                      const next = new Set(current);
                      if (checked) next.add(card.id); else next.delete(card.id);
                      return next;
                    });
                  }}
                  label={`Выбрать: ${card.front}`}
                />
                <div>
                  <small>{card.unit?.path.join(" · ") || (card.unit ? "Билет" : "Без вопроса")}</small>
                  <strong>{card.front}</strong>
                  <span>{card.unit?.title ?? "Без вопроса"}</span>
                </div>
                <span className={card.source.lost ? "is-lost" : ""}>
                  {card.source.kind === "reference" ? "Готовый ответ" : card.source.label}
                </span>
                <div>
                  <small>
                    {card.last_confidence ? `Оценка ${card.last_confidence} · ` : ""}
                    {card.attempt_count} попыток · {relativeTime(card.last_reviewed_at)}
                  </small>
                </div>
              </article>
            ))}
          </section>

          {active && (
            <aside className="bank-inspector">
              {editing ? (
                <CardEditor
                  projectId={projectId}
                  units={data?.units ?? []}
                  card={active}
                  onCancel={() => setEditing(false)}
                  onSaved={() => {
                    setEditing(false);
                    refresh();
                    onChanged();
                  }}
                />
              ) : (
                <>
                  <header>
                    <div>
                      <small>{active.unit?.path.join(" · ") || (active.unit ? "Билет" : "Без вопроса")}</small>
                      <h2>{active.front}</h2>
                    </div>
                    <Button variant="ghost" onClick={() => setEditing(true)}><Pencil size={15} /> Править</Button>
                  </header>
                  <div className="bank-inspector-answer">{active.back}</div>
                  {active.hint && <p><strong>Подсказка:</strong> {active.hint}</p>}
                  <dl>
                    <div><dt>Вопрос</dt><dd>{active.unit?.title ?? "Без вопроса"}</dd></div>
                    <div><dt>Источник</dt><dd>{active.source.kind === "reference" ? "Готовый ответ" : active.source.label}</dd></div>
                    <div><dt>Последняя оценка</dt><dd>{active.last_confidence ?? "—"}</dd></div>
                    <div><dt>Попыток</dt><dd>{active.attempt_count}</dd></div>
                  </dl>
                  {active.source.lost && (
                    <div className="bank-lost-source">
                      <strong>Источник больше недоступен</strong>
                      <p>Снимок текста сохранён. Можно выбрать новый Фрагмент или оставить карточку личной.</p>
                      <Link to={`/projects/${projectId}/materials`}>Выбрать новый Фрагмент</Link>
                      <Button
                        variant="ghost"
                        onClick={() => {
                          void updateCard(projectId, active.id, {
                              expected_revision: active.revision,
                              source: { kind: "none", fragment_id: null, reference_revision: null },
                            }).then(() => { refresh(); onChanged(); });
                        }}
                      >
                        Оставить личной
                      </Button>
                    </div>
                  )}
                  {!active.deleted_at && (
                    <footer>
                      <Button variant="ghost" className="is-destructive" onClick={() => void applyBulk("delete", [active])}>
                        <Trash2 size={14} /> Удалить
                      </Button>
                    </footer>
                  )}
                </>
              )}
            </aside>
          )}
        </div>
      )}
    </div>
  );
}
