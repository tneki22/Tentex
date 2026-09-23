import { BookOpen, Check, ExternalLink, Plus } from "lucide-react";
import { Link } from "react-router";
import type { MaterialSuggestion } from "../../api/materialSuggestions";
import { Button, StatusBadge } from "../ui";

function plural(count: number, one: string, few: string, many: string): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

function signalsLabel(signals: MaterialSuggestion["signals"]): string {
  if (signals.includes("semantic") && signals.includes("lexical")) return "по смыслу и словам";
  return signals.includes("semantic") ? "по смыслу" : "по словам";
}

function pagesLabel(item: MaterialSuggestion): string | null {
  if (item.page_from === null) return null;
  return item.page_to !== null && item.page_to !== item.page_from
    ? `с. ${item.page_from}–${item.page_to}`
    : `с. ${item.page_from}`;
}

interface MaterialSuggestionListProps {
  items: MaterialSuggestion[];
  /** Уже подключённые в этом сеансе — вместо кнопки видна отметка. */
  attachedIds?: ReadonlySet<string>;
  busyId?: string | null;
  onAttach(item: MaterialSuggestion): void;
  /** Без фрагмента — для плотных списков по темам. */
  compact?: boolean;
}

/**
 * Материалы Библиотеки, найденные под цель или тему: почему подходит (сколько
 * совпадений и каким сигналом), лучший фрагмент со страницами и «Подключить».
 * Подбор идёт без модели, поэтому карточка показывает найденный текст, а не
 * пересказ: пользователь сам видит, о том ли материал.
 */
export function MaterialSuggestionList({
  items, attachedIds, busyId = null, onAttach, compact = false,
}: MaterialSuggestionListProps) {
  return (
    <ul className={`material-suggestions${compact ? " is-compact" : ""}`}>
      {items.map((item) => {
        const attached = attachedIds?.has(item.material_id) ?? false;
        const pages = pagesLabel(item);
        return (
          <li key={item.material_id} className="material-suggestion">
            <BookOpen className="material-suggestion-icon" size={16} aria-hidden="true" />
            <div className="material-suggestion-copy">
              <b>{item.display_name}</b>
              <span className="material-suggestion-meta">
                {item.hit_count} {plural(item.hit_count, "совпадение", "совпадения", "совпадений")} · {signalsLabel(item.signals)}
                {item.subject_match && <StatusBadge tone="info">предмет совпадает</StatusBadge>}
                {item.has_outline && <span>есть оглавление</span>}
              </span>
              {!compact && item.excerpt && (
                <blockquote className="material-suggestion-excerpt">
                  {item.block_title && <strong>{item.block_title}{pages ? ` · ${pages}` : ""}</strong>}
                  {!item.block_title && pages && <strong>{pages}</strong>}
                  <span>{item.excerpt}</span>
                </blockquote>
              )}
            </div>
            <div className="material-suggestion-actions">
              {attached
                ? <StatusBadge tone="success"><Check size={12} />Подключено</StatusBadge>
                : <Button variant="secondary" disabled={busyId !== null} onClick={() => onAttach(item)}>
                    <Plus size={14} />{busyId === item.material_id ? "Подключаем…" : "Подключить"}
                  </Button>}
              <Link className="material-suggestion-open" to={`/library/${item.material_id}`} target="_blank" rel="noreferrer" aria-label={`Открыть «${item.display_name}» в Библиотеке`}>
                <ExternalLink size={14} />
              </Link>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
