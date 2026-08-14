import { ChevronRight } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import type { OutlineItem, OutlineSource } from "../../../api/materials";
import { SegmentedTabs } from "../../ui";

interface OutlineNode {
  key: string;
  item: OutlineItem;
  children: OutlineNode[];
}

function buildTree(items: OutlineItem[]): OutlineNode[] {
  const roots: OutlineNode[] = [];
  const stack: OutlineNode[] = [];
  items.forEach((item, index) => {
    const node: OutlineNode = { key: `${index}-${item.page}`, item, children: [] };
    while (stack.length && stack[stack.length - 1].item.level >= item.level) stack.pop();
    if (stack.length === 0) roots.push(node);
    else stack[stack.length - 1].children.push(node);
    stack.push(node);
  });
  return roots;
}

interface PdfOutlineProps {
  outline: OutlineItem[];
  outlineSource: OutlineSource;
  page: number;
  pageCount: number;
  /** Ключ материала: раскрытые ветви и вкладка запоминаются для него. */
  storageKey: string;
  onPageChange(page: number): void;
}

/**
 * Левая навигация документа: дерево оглавления и компактный список страниц.
 *
 * Дерево — `tree`/`treeitem` со стрелками и `Enter`: перебор пунктов длинного
 * оглавления мышью по одному — это не навигация, а поиск глазами.
 */
export function PdfOutline({
  outline,
  outlineSource,
  page,
  pageCount,
  storageKey,
  onPageChange,
}: PdfOutlineProps) {
  const tree = useMemo(() => buildTree(outline), [outline]);
  const [tab, setTab] = useState<"outline" | "pages">(() =>
    outline.length ? (localStorage.getItem(`tentex-outline-tab:${storageKey}`) as "outline" | "pages" | null) ?? "outline" : "pages");
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const listRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    localStorage.setItem(`tentex-outline-tab:${storageKey}`, tab);
  }, [tab, storageKey]);

  /** Активен пункт с наибольшей страницей, не превышающей текущую. */
  const activeKey = useMemo(() => {
    let best: OutlineNode | null = null;
    const walk = (nodes: OutlineNode[]) => {
      for (const node of nodes) {
        if (node.item.page <= page && (!best || node.item.page >= best.item.page)) best = node;
        walk(node.children);
      }
    };
    walk(tree);
    return best ? (best as OutlineNode).key : null;
  }, [tree, page]);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeKey, tab]);

  const focusable = useRef<HTMLButtonElement[]>([]);

  function onTreeKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const items = focusable.current.filter(Boolean);
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    if (index < 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      items[Math.min(items.length - 1, index + 1)]?.focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      items[Math.max(0, index - 1)]?.focus();
    } else if (event.key === "Home") {
      event.preventDefault();
      items[0]?.focus();
    } else if (event.key === "End") {
      event.preventDefault();
      items[items.length - 1]?.focus();
    }
  }

  function renderNodes(nodes: OutlineNode[], depth: number): React.ReactNode {
    return nodes.map((node) => {
      const hasChildren = node.children.length > 0;
      // Родитель активного пункта раскрывается сам: иначе текущее место в
      // документе пряталось бы за свёрнутой ветвью.
      const containsActive = hasChildren && subtreeKeys(node).includes(activeKey ?? "");
      const isCollapsed = hasChildren && collapsed.has(node.key) && !containsActive;
      const isActive = node.key === activeKey;
      return (
        <div className="outline-branch" key={node.key} role="none">
          <div className="outline-row" role="treeitem" aria-expanded={hasChildren ? !isCollapsed : undefined} aria-selected={isActive}>
            {hasChildren ? (
              <button
                type="button"
                className={`outline-twist ${isCollapsed ? "" : "is-open"}`.trim()}
                aria-label={isCollapsed ? "Раскрыть раздел" : "Свернуть раздел"}
                onClick={() => setCollapsed((current) => {
                  const next = new Set(current);
                  if (next.has(node.key)) next.delete(node.key);
                  else next.add(node.key);
                  return next;
                })}
              >
                <ChevronRight size={13} aria-hidden="true" />
              </button>
            ) : <span className="outline-twist is-leaf" aria-hidden="true" />}
            <button
              type="button"
              ref={(element) => {
                if (element) focusable.current.push(element);
                if (isActive) activeRef.current = element;
              }}
              className={`outline-link ${isActive ? "is-active" : ""}`.trim()}
              style={{ paddingInlineStart: `${depth * 12}px` }}
              title={node.item.title}
              tabIndex={isActive || (!activeKey && depth === 0) ? 0 : -1}
              onClick={() => onPageChange(node.item.page)}
            >
              <span className="outline-title">{node.item.title}</span>
              <span className="outline-page">{node.item.page}</span>
            </button>
          </div>
          {hasChildren && !isCollapsed && (
            <div className="outline-children" role="group">{renderNodes(node.children, depth + 1)}</div>
          )}
        </div>
      );
    });
  }

  focusable.current = [];

  return (
    <nav className="viewer-outline" aria-label="Навигация по документу">
      <SegmentedTabs
        className="viewer-outline-tabs"
        label="Навигация по документу"
        value={tab}
        tabs={[
          { value: "outline", label: "Оглавление", disabled: outline.length === 0 },
          { value: "pages", label: "Страницы", disabled: pageCount <= 1 },
        ]}
        onChange={setTab}
      />
      {tab === "outline" ? (
        <>
          {outlineSource === "recognized" && (
            <p className="viewer-outline-note">По заголовкам текста</p>
          )}
          <div className="viewer-outline-tree" role="tree" ref={listRef} onKeyDown={onTreeKeyDown}>
            {renderNodes(tree, 0)}
          </div>
        </>
      ) : (
        <div className="viewer-outline-pages" role="list" aria-label="Страницы">
          {Array.from({ length: pageCount }, (_, index) => index + 1).map((number) => (
            <button
              type="button"
              role="listitem"
              key={number}
              className={`viewer-page-chip ${number === page ? "is-active" : ""}`.trim()}
              aria-current={number === page ? "page" : undefined}
              onClick={() => onPageChange(number)}
            >
              {number}
            </button>
          ))}
        </div>
      )}
    </nav>
  );
}

function subtreeKeys(node: OutlineNode): string[] {
  return [node.key, ...node.children.flatMap(subtreeKeys)];
}
