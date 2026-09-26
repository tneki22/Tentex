interface PageHighlightsProps {
  /** Растр страницы целиком. */
  pageUrl: string;
  /** Доли листа `[x0, y0, x1, y1]` выделяемых фрагментов, как у их `bbox`. */
  boxes: number[][];
  alt: string;
  className?: string;
}

/**
 * Страница с выделенными поверх неё фрагментами — где на листе лежит найденное.
 *
 * Обёртка сжимается до самой картинки: иначе при `object-fit: contain` доли
 * `bbox` отсчитывались бы от пустых полей вокруг листа, и рамки съезжали.
 */
export function PageHighlights({ pageUrl, boxes, alt, className }: PageHighlightsProps) {
  return (
    <div className={["page-highlights", className].filter(Boolean).join(" ")}>
      <img src={pageUrl} alt={alt} />
      {boxes.map(([x0, y0, x1, y1], index) => (
        <span
          key={`${index}-${x0}-${y0}`}
          className="page-highlights-mark"
          aria-hidden="true"
          style={{
            left: `${x0 * 100}%`,
            top: `${y0 * 100}%`,
            width: `${Math.max(0, x1 - x0) * 100}%`,
            height: `${Math.max(0, y1 - y0) * 100}%`,
          }}
        />
      ))}
    </div>
  );
}
