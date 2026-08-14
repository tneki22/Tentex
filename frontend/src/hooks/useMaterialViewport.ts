import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ViewerZoom } from "../components/domain/material-viewer";

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
  onPageChange?: (page: number) => void;
}

/**
 * Геометрия и клавиатура просмотрщика: замер области, «вписать страницу»,
 * «по ширине», перелистывание стрелками, полный экран.
 *
 * Вынесено из проектного экрана, чтобы Библиотека и проект вели себя одинаково:
 * два независимых расчёта «вписать» разъезжались бы на первой же правке CSS.
 */
export function useMaterialViewport({ pageCount, zoomable, onPageChange }: ViewportOptions) {
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState<ViewerZoom>("fit-page");
  const [fullscreen, setFullscreen] = useState(false);
  const [showRegions, setShowRegions] = useState(false);
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const observer = useRef<ResizeObserver | null>(null);

  const measure = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    const box = node.getBoundingClientRect();
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
    if (viewport.width === 0 || viewport.height === 0) return 1;
    const byWidth = (viewport.width - SHEET_PADDING) / SHEET_WIDTH;
    if (zoom === "fit-width") return Math.min(2, Math.max(0.5, byWidth));
    const byHeight = (viewport.height - SHEET_PADDING) / SHEET_HEIGHT;
    return Math.min(2, Math.max(0.5, Math.min(byWidth, byHeight)));
  }, [zoom, zoomable, viewport]);

  const goToPage = useCallback((next: number) => {
    setPage((current) => {
      const target = Math.min(Math.max(1, next), Math.max(1, pageCount));
      if (target !== current) {
        scrollRef.current?.scrollTo({ top: 0 });
        onPageChange?.(target);
      }
      return target;
    });
  }, [pageCount, onPageChange]);

  useEffect(() => {
    function isTyping(target: EventTarget | null): boolean {
      if (!(target instanceof HTMLElement)) return false;
      return target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;
    }
    function onKeyDown(event: KeyboardEvent) {
      if (isTyping(event.target)) return;
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
  }, [page, pageCount, fullscreen, goToPage]);

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
