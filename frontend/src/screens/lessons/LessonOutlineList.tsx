import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Search } from "lucide-react";
import type { OutlineItem } from "../../api/materials";

/** Пункт оглавления вместе с диапазоном страниц, который он занимает. */
export interface OutlineSection {
  index: number;
  item: OutlineItem;
  pageFrom: number;
  pageTo: number;
}

/**
 * Диапазон пункта оглавления: от его страницы до страницы следующего пункта
 * того же или более высокого уровня. Подпункты остаются внутри родителя —
 * «Добавить раздел» берёт раздел целиком, а не до первого подзаголовка.
 */
export function outlineSections(items: OutlineItem[], pageCount: number): OutlineSection[] {
  return items.map((item, index) => {
    const next = items.findIndex((candidate, position) => position > index && candidate.level <= item.level);
    const pageTo = next < 0 ? pageCount : Math.max(item.page, items[next].page - 1);
    return { index, item, pageFrom: item.page, pageTo: Math.min(pageTo, pageCount) };
  });
}

interface LessonOutlineListProps {
  sections: OutlineSection[];
  /** Текущая страница: пункт, в который она попадает, подсвечен. */
  page: number;
  onPick(page: number): void;
  /** Действие справа от пункта — «Добавить раздел» там, где это уместно. */
  renderAction?: (section: OutlineSection) => ReactNode;
  /** Поле фильтра: у учебника оглавление в сотни строк, листать его нечем. */
  filterable?: boolean;
}

/**
 * Оглавление источника списком с отступом по уровню.
 *
 * Дерево со сворачиванием живёт в просмотрщике материала; здесь панель узкая,
 * а задача одна — быстро дойти до нужной страницы, поэтому отступ и фильтр.
 */
export function LessonOutlineList({ sections, page, onPick, renderAction, filterable = true }: LessonOutlineListProps) {
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();
  const visible = useMemo(
    () => (needle ? sections.filter((section) => section.item.title.toLowerCase().includes(needle)) : sections),
    [sections, needle],
  );
  const listRef = useRef<HTMLUListElement>(null);
  const activeIndex = useMemo(() => {
    let best = -1;
    for (const section of sections) {
      if (section.item.page <= page && (best < 0 || section.item.page >= sections[best].item.page)) best = section.index;
    }
    return best;
  }, [sections, page]);

  // Оглавление учебника — сотни строк: открывать его на «От авторов», когда
  // тема в середине книги, бессмысленно. Прокручивается только сам список:
  // `scrollIntoView` увёл бы заодно всю панель.
  useEffect(() => {
    const box = listRef.current;
    const active = box?.querySelector<HTMLElement>("button.is-active");
    if (!box || !active) return;
    box.scrollTop += active.getBoundingClientRect().top - box.getBoundingClientRect().top - box.clientHeight / 3;
  }, [sections]);

  if (sections.length === 0) {
    return <p className="lessons-panel-hint">У источника нет оглавления — перейдите по номеру страницы.</p>;
  }

  return (
    <div className="lessons-outline-nav">
      {filterable && (
        <label className="workspace-tree-search">
          <Search size={15} />
          <span className="sr-only">Найти пункт оглавления</span>
          <input
            type="search"
            placeholder="Найти пункт оглавления"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
        </label>
      )}
      <ul className="lessons-outline-rows" ref={listRef}>
        {visible.map((section) => (
          <li key={`${section.index}-${section.item.page}`}>
            <button
              type="button"
              className={section.index === activeIndex ? "is-active" : ""}
              style={{ paddingInlineStart: `${Math.min(4, section.item.level) * 10}px` }}
              onClick={() => onPick(section.item.page)}
            >
              <span>{section.item.title}</span>
              <small>{section.item.page}</small>
            </button>
            {renderAction?.(section)}
          </li>
        ))}
      </ul>
      {visible.length === 0 && <p className="lessons-panel-hint">Ни один пункт не подошёл.</p>}
    </div>
  );
}
