import { ChevronRight } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router";
import type { GuideOutlineItem } from "./guideDocument";
import { GUIDE_TREE, type GuidePage } from "./guideSections";

interface GuideTreeProps {
  activeSlug: string;
  /** Slug страниц, у которых есть текст; остальные в дереве приглушены. */
  written: ReadonlySet<string>;
  outline: GuideOutlineItem[];
  activeHeading: string | null;
  onSelectHeading: (id: string) => void;
}

function containsSlug(page: GuidePage, slug: string): boolean {
  return page.slug === slug || (page.children ?? []).some((child) => child.slug === slug);
}

/** Раскрывающийся блок: высота плавно идёт от 0 до содержимого, скрытое не берёт фокус. */
function Collapse({ open, children }: { open: boolean; children: ReactNode }) {
  return (
    <div className={`guide-collapse${open ? " is-open" : ""}`} inert={!open}>
      <div>{children}</div>
    </div>
  );
}

export function GuideTree({ activeSlug, written, outline, activeHeading, onSelectHeading }: GuideTreeProps) {
  const activeGroupId = GUIDE_TREE.find((group) => group.pages.some((page) => containsSlug(page, activeSlug)))?.id;
  const activeParentSlug = GUIDE_TREE.flatMap((group) => group.pages).find((page) => containsSlug(page, activeSlug))?.slug;

  const [openGroups, setOpenGroups] = useState<Set<string>>(() => new Set(activeGroupId ? [activeGroupId] : []));
  const [openPages, setOpenPages] = useState<Set<string>>(() => new Set(activeParentSlug ? [activeParentSlug] : []));

  // Переход по ссылке из текста или кнопками «Далее/Назад» раскрывает нужную ветку сам.
  useEffect(() => {
    if (activeGroupId) setOpenGroups((current) => (current.has(activeGroupId) ? current : new Set(current).add(activeGroupId)));
    if (activeParentSlug) setOpenPages((current) => (current.has(activeParentSlug) ? current : new Set(current).add(activeParentSlug)));
  }, [activeGroupId, activeParentSlug]);

  const toggle = (setter: typeof setOpenGroups, id: string) =>
    setter((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  function pageLink(page: GuidePage, nested: boolean) {
    const isActive = page.slug === activeSlug;
    return (
      <Link
        to={`/guide?section=${page.slug}`}
        className={`guide-tree-link${isActive ? " is-active" : ""}${nested ? " is-nested" : ""}${written.has(page.slug) ? "" : " is-draft"}`}
        aria-current={isActive ? "page" : undefined}
        title={written.has(page.slug) ? undefined : "Раздел ещё пишется"}
      >
        <span className="guide-tree-label">{page.title}</span>
      </Link>
    );
  }

  function outlineFor(page: GuidePage) {
    const isActive = page.slug === activeSlug;
    return (
      <Collapse open={isActive && outline.length > 1}>
        <div className="guide-outline" aria-label={`Содержание страницы «${page.title}»`}>
          {outline.map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              className={activeHeading === item.id ? "is-active" : ""}
              aria-current={activeHeading === item.id ? "location" : undefined}
              onClick={(event) => {
                event.preventDefault();
                onSelectHeading(item.id);
              }}
            >
              {item.title}
            </a>
          ))}
        </div>
      </Collapse>
    );
  }

  return (
    <nav className="guide-tree" aria-label="Разделы руководства">
      {GUIDE_TREE.map((group) => {
        const Icon = group.icon;
        const open = openGroups.has(group.id);
        return (
          <section className="guide-tree-group" key={group.id}>
            <button
              type="button"
              className={`guide-tree-group-head${group.id === activeGroupId ? " has-active" : ""}`}
              aria-expanded={open}
              onClick={() => toggle(setOpenGroups, group.id)}
            >
              <Icon size={15} aria-hidden="true" />
              <span>{group.title}</span>
              <ChevronRight className="guide-tree-chevron" size={14} aria-hidden="true" />
            </button>
            <Collapse open={open}>
              <ul className="guide-tree-pages">
                {group.pages.map((page) => {
                  const children = page.children ?? [];
                  const pageOpen = openPages.has(page.slug);
                  return (
                    <li key={page.slug}>
                      <div className="guide-tree-row">
                        {pageLink(page, false)}
                        {children.length > 0 && (
                          <button
                            type="button"
                            className="guide-tree-toggle"
                            aria-expanded={pageOpen}
                            aria-label={`${pageOpen ? "Свернуть" : "Развернуть"} «${page.title}»`}
                            onClick={() => toggle(setOpenPages, page.slug)}
                          >
                            <ChevronRight className="guide-tree-chevron" size={13} aria-hidden="true" />
                          </button>
                        )}
                      </div>
                      {outlineFor(page)}
                      {children.length > 0 && (
                        <Collapse open={pageOpen}>
                          <ul className="guide-tree-children">
                            {children.map((child) => (
                              <li key={child.slug}>
                                {pageLink(child, true)}
                                {outlineFor(child)}
                              </li>
                            ))}
                          </ul>
                        </Collapse>
                      )}
                    </li>
                  );
                })}
              </ul>
            </Collapse>
          </section>
        );
      })}
    </nav>
  );
}
