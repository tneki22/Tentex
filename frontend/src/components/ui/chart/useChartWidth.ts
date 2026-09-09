/** Диаграммы рисуются в пикселях, поэтому ширину меряем, а не растягиваем viewBox. */
import { useEffect, useRef, useState } from "react";

/**
 * Ширина контейнера диаграммы.
 *
 * `viewBox` с `preserveAspectRatio="none"` растянул бы вместе с фигурами
 * и подписи, поэтому ширина берётся у DOM и передаётся в разметку числом.
 *
 * @returns ссылка на контейнер и его текущая ширина в пикселях.
 */
export function useChartWidth<T extends HTMLElement = HTMLDivElement>() {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect;
      if (box) setWidth(Math.round(box.width));
    });
    observer.observe(node);
    setWidth(Math.round(node.getBoundingClientRect().width));
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}
