import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ViewerZoom } from "../components/domain/material-viewer";
import { useViewerFullscreen } from "./useViewerFullscreen";

/** Размеры листа заданы в CSS сцены: держим их синхронно, иначе «вписать» промахнётся. */
const SHEET_WIDTH = 680;
const SHEET_HEIGHT = 900;
/* Совпадает с padding области .viewer-sheet-scroll: если вычитать больше,
   «вписать страницу» оставляет полосу пустоты по краям. */
const SHEET_PADDING = 48;

interface ViewportOptions {
  pageCount: number;
  /** Масштаб имеет смысл только там, где показана настоящая страница. */
  zoomable: boolean;
  pageAspect?: number;
  textMode?: boolean;
  navigationDisabled?: boolean;
  onPageChange?: (page: number) => void;
}

/**
 * Геометрия и клавиатура просмотрщика: замер области, «вписать страницу»,
 * «по ширине», перелистывание стрелками, полный экран.
 *
 * Вынесено из проектного экрана, чтобы Библиотека и проект вели себя одинаково:
 * два независимых расчёта «вписать» разъезжались бы на первой же правке CSS.
 */
export function useMaterialViewport({ pageCount, zoomable, pageAspect, textMode, navigationDisabled, onPageChange }: ViewportOptions) {
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState<ViewerZoom>("fit-page");
  const { fullscreen, setFullscreen } = useViewerFullscreen();
  const [showRegions, setShowRegions] = useState(false);
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const observer = useRef<ResizeObserver | null>(null);

  const measure = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    const box = { width: node.clientWidth, height: node.clientHeight };
    setViewport((current) => (
      current.width === box.width && current.height === box.height
        ? current
        : { width: box.width, height: box.height }
    ));
  }, []);

  /* Ref-колбэк, а не эффект: область прокрутки появляется позже материала, и
     эффект по id её уже не застаёт. ResizeObserver дальше ловит смену ширины. */
  const attachScroll = useCallback((node: HTMLDivElement | null) => {
    observer.current?.disconnect();
    scrollRef.current = node;
    if (!node) return;
    measure();
    const next = new ResizeObserver(measure);
    next.observe(node);
    observer.current = next;
  }, [measure]);

  useEffect(() => {
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [measure]);

  useEffect(measure, [measure, fullscreen, page]);

  const effectiveZoom = useMemo(() => {
    if (!zoomable) return 1;
    if (typeof zoom === "number") return zoom;
    if (textMode) return 1;
    if (viewport.width === 0 || viewport.height === 0) return 1;
    const byWidth = (viewport.width - SHEET_PADDING) / SHEET_WIDTH;
    if (zoom === "fit-width") return Math.min(2, Math.max(0.1, byWidth));
    const byHeight = (viewport.height - SHEET_PADDING) / (pageAspect ? SHEET_WIDTH * pageAspect : SHEET_HEIGHT);
    return Math.min(2, Math.max(0.1, Math.min(byWidth, byHeight)));
  }, [zoom, zoomable, viewport, pageAspect, textMode]);

  const goToPage = useCallback((next: number) => {
    if (navigationDisabled) return;
    setPage((current) => {
      const target = Math.min(Math.max(1, next), Math.max(1, pageCount));
      if (target !== current) {
        scrollRef.current?.scrollTo({ top: 0 });
        onPageChange?.(target);
      }
      return target;
    });
  }, [pageCount, onPageChange, navigationDisabled]);

  useEffect(() => {
    function isTyping(target: EventTarget | null): boolean {
      if (!(target instanceof HTMLElement)) return false;
      return target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;
    }
    function onKeyDown(event: KeyboardEvent) {
      if (isTyping(event.target) || event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.target instanceof HTMLElement) {
        if (event.target.closest('[role="dialog"]')) return;
        if (["ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"].includes(event.key)
          && event.target.closest('[role="separator"], [role="tablist"], [role="tree"]')) return;
      }
      switch (event.key) {
        case "ArrowLeft":
        case "PageUp":
          event.preventDefault();
          goToPage(page - 1);
          return;
        case "ArrowRight":
        case "PageDown":
          event.preventDefault();
          goToPage(page + 1);
          return;
        case "Home":
          event.preventDefault();
          goToPage(1);
          return;
        case "End":
          event.preventDefault();
          goToPage(pageCount);
          return;
        // Раскладка не переключена — «F» и «А» на одной клавише.
        case "f":
        case "F":
        case "а":
        case "А":
          event.preventDefault();
          setFullscreen((value) => !value);
          return;
        case "Escape":
          if (fullscreen) {
            event.preventDefault();
            setFullscreen(false);
          }
          return;
        default:
          return;
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [page, pageCount, fullscreen, goToPage, setFullscreen]);

  return {
    page,
    setPage,
    goToPage,
    zoom,
    setZoom,
    effectiveZoom,
    zoomPercent: Math.round(effectiveZoom * 100),
    fullscreen,
    setFullscreen,
    showRegions,
    toggleRegions: () => setShowRegions((value) => !value),
    attachScroll,
    scrollRef,
  };
}
