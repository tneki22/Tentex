import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useSearchParams } from "react-router";
import { PageHead } from "../../components/ui";
import { GuideArticle } from "./GuideArticle";
import { GuideTree } from "./GuideTree";
import { guideOutline, parseGuideDocument } from "./guideDocument";
import { markGuideOpened, readLastGuidePage, writeLastGuidePage } from "./guideState";
import { DEFAULT_GUIDE_PAGE, FLAT_GUIDE_PAGES, findGuidePage } from "./guideSections";

/** Тексты страниц: `pages/<slug>.md`. Страницы без файла в дереве приглушены. */
const SOURCES = import.meta.glob<string>("./pages/*.md", { eager: true, query: "?raw", import: "default" });
const DOCUMENTS = new Map(
  Object.entries(SOURCES).flatMap(([path, source]) => {
    const slug = /\/([^/]+)\.md$/.exec(path)?.[1];
    return slug ? [[slug, source] as const] : [];
  }),
);
const WRITTEN = new Set(DOCUMENTS.keys());

/** Высота липкой верхней полосы плюс воздух: заголовок не должен уезжать под неё. */
const SPY_TOP_OFFSET = 96;

function resolveSlug(requested: string | null): string {
  if (findGuidePage(requested)) return requested!;
  const last = readLastGuidePage();
  return findGuidePage(last) ? last! : DEFAULT_GUIDE_PAGE;
}

export function Guide() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get("section");
  const slug = resolveSlug(requested);
  const item = findGuidePage(slug)!;

  // Адрес всегда называет страницу: так её можно скопировать и открыть той же.
  useEffect(() => {
    if (requested !== slug) setSearchParams({ section: slug }, { replace: true });
  }, [requested, slug, setSearchParams]);

  useEffect(() => {
    writeLastGuidePage(slug);
    markGuideOpened();
  }, [slug]);

  const blocks = useMemo(() => {
    const source = DOCUMENTS.get(slug);
    return source === undefined ? null : parseGuideDocument(source);
  }, [slug]);
  const outline = useMemo(() => (blocks ? guideOutline(blocks) : []), [blocks]);

  const [activeHeading, setActiveHeading] = useState<string | null>(null);
  const firstRender = useRef(true);

  useEffect(() => {
    setActiveHeading(null);
    // При первом показе браузер сам держит позицию; при переходе читаем новую страницу с начала.
    if (firstRender.current) firstRender.current = false;
    else window.scrollTo({ top: 0 });
  }, [slug]);

  // Ссылка вида `/guide?section=slug#якорь` ведёт к секции страницы: заголовки имеют `id` из `{#якорь}`.
  const { hash } = useLocation();
  useEffect(() => {
    const id = hash.slice(1);
    if (!id || !blocks) return;
    const frame = window.requestAnimationFrame(() => {
      document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [hash, slug, blocks]);

  // Подсветка текущей секции в дереве: первая из видимых в верхней части окна.
  useEffect(() => {
    if (outline.length < 2) return;
    const visible = new Set<string>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) visible.add(entry.target.id);
          else visible.delete(entry.target.id);
        }
        const current = outline.find((section) => visible.has(section.id));
        if (current) setActiveHeading(current.id);
      },
      { rootMargin: `-${SPY_TOP_OFFSET}px 0px -65% 0px` },
    );
    for (const section of outline) {
      const element = document.getElementById(section.id);
      if (element) observer.observe(element);
    }
    return () => observer.disconnect();
  }, [outline, slug]);

  const selectHeading = useCallback((id: string) => {
    setActiveHeading(id);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  const position = FLAT_GUIDE_PAGES.findIndex((entry) => entry.page.slug === slug);

  return (
    <div className="screen guide-screen">
      <PageHead placement="topbar" title="Руководство пользователя" />
      <div className="guide-layout">
        <GuideTree
          activeSlug={slug}
          written={WRITTEN}
          outline={outline}
          activeHeading={activeHeading}
          onSelectHeading={selectHeading}
        />
        <GuideArticle
          item={item}
          blocks={blocks}
          previous={FLAT_GUIDE_PAGES[position - 1] ?? null}
          next={FLAT_GUIDE_PAGES[position + 1] ?? null}
        />
      </div>
    </div>
  );
}
