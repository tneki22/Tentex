import type { PointerEvent as ReactPointerEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

export interface PanelLayout {
  left: number;
  right: number;
}

export const DEFAULT_PANEL_LAYOUT: PanelLayout = { left: 280, right: 360 };
export const MIN_LEFT = 220;
export const MIN_CENTER = 480;
export const MIN_RIGHT = 300;
const HANDLE_SPACE = 12;
const STORAGE_KEY = "tentex:panel-layout";

export function clampPanelLayout(layout: PanelLayout, width: number): PanelLayout {
  const maxSide = Math.floor(width * 0.45);
  const left = Math.min(maxSide, Math.max(MIN_LEFT, layout.left));
  const rightLimit = Math.max(MIN_RIGHT, width - left - MIN_CENTER - HANDLE_SPACE);
  const right = Math.min(maxSide, rightLimit, Math.max(MIN_RIGHT, layout.right));
  return { left, right };
}

export function parseStoredPanelLayout(value: string | null, width: number): PanelLayout {
  if (!value) return DEFAULT_PANEL_LAYOUT;
  try {
    const parsed = JSON.parse(value) as Partial<PanelLayout>;
    if (!Number.isFinite(parsed.left) || !Number.isFinite(parsed.right)) {
      return DEFAULT_PANEL_LAYOUT;
    }
    return clampPanelLayout(
      { left: parsed.left as number, right: parsed.right as number },
      width,
    );
  } catch {
    return DEFAULT_PANEL_LAYOUT;
  }
}

/**
 * Три колонки с перетаскиваемыми границами. Ширины держатся в localStorage.
 * Нужен «Среде темы» и «Просмотрщику источника».
 */
export function usePanelLayout() {
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);
  const [layout, setLayout] = useState<PanelLayout>(() =>
    parseStoredPanelLayout(localStorage.getItem(STORAGE_KEY), window.innerWidth),
  );

  useEffect(() => {
    const handleResize = () => {
      setViewportWidth(window.innerWidth);
      setLayout((current) => clampPanelLayout(current, window.innerWidth));
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
  }, [layout]);

  const setSide = useCallback((side: keyof PanelLayout, value: number) => {
    setLayout((current) => clampPanelLayout({ ...current, [side]: value }, window.innerWidth));
  }, []);

  const startResize = useCallback((side: keyof PanelLayout, event: ReactPointerEvent) => {
    event.preventDefault();
    const startX = event.clientX;
    const startLayout = layout;

    const handleMove = (moveEvent: PointerEvent) => {
      const delta = moveEvent.clientX - startX;
      const nextValue = side === "left"
        ? startLayout.left + delta
        : startLayout.right - delta;
      setSide(side, nextValue);
    };
    const handleUp = () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
      document.body.classList.remove("is-resizing-panels");
    };

    document.body.classList.add("is-resizing-panels");
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp, { once: true });
  }, [layout, setSide]);

  const limits = useMemo(() => ({
    leftMax: Math.max(
      MIN_LEFT,
      Math.min(
        Math.floor(viewportWidth * 0.45),
        viewportWidth - layout.right - MIN_CENTER - HANDLE_SPACE,
      ),
    ),
    rightMax: Math.max(
      MIN_RIGHT,
      Math.min(
        Math.floor(viewportWidth * 0.45),
        viewportWidth - layout.left - MIN_CENTER - HANDLE_SPACE,
      ),
    ),
  }), [layout.left, layout.right, viewportWidth]);

  return {
    layout,
    limits,
    setSide,
    startResize,
    reset: () => setLayout(clampPanelLayout(DEFAULT_PANEL_LAYOUT, window.innerWidth)),
  };
}
