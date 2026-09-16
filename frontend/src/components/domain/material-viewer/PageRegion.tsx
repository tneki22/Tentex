import { useState } from "react";

interface PageRegionProps {
  /** Растр страницы целиком — он уже в кэше браузера, отдельная картинка не нужна. */
  pageUrl: string;
  /** Доли листа `[x0, y0, x1, y1]`, как у `bbox` фрагмента. */
  bbox: number[];
  alt: string;
  className?: string;
}

/**
 * Прямоугольный вырез страницы: схема или таблица без окружающего текста.
 *
 * Пропорции берутся у загруженной картинки, а не у размеров страницы из базы:
 * так вырез не нужно сопровождать ещё одним запросом за метаданными листа.
 */
export function PageRegion({ pageUrl, bbox, alt, className }: PageRegionProps) {
  const [ratio, setRatio] = useState<number | null>(null);
  const [x0, y0, x1, y1] = bbox;
  const width = Math.max(0.0001, x1 - x0);
  const height = Math.max(0.0001, y1 - y0);

  return (
    <div
      className={["page-region", className].filter(Boolean).join(" ")}
      style={ratio ? { aspectRatio: String(ratio) } : undefined}
    >
      <img
        src={pageUrl}
        alt={alt}
        loading="lazy"
        style={{
          width: `${100 / width}%`,
          left: `${(-x0 / width) * 100}%`,
          top: `${(-y0 / height) * 100}%`,
        }}
        onLoad={(event) => {
          const { naturalWidth, naturalHeight } = event.currentTarget;
          if (naturalWidth && naturalHeight) {
            setRatio((width * naturalWidth) / (height * naturalHeight));
          }
        }}
      />
    </div>
  );
}
