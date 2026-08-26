import { useCallback, useEffect, useRef, useState, type SetStateAction } from "react";

/** Fullscreen на корне сохраняет доступ к диалогам Radix, портальным в body. */
export function useViewerFullscreen() {
  const [fullscreen, updateFullscreen] = useState(false);
  const active = useRef(false);

  const setFullscreen = useCallback((value: SetStateAction<boolean>) => {
    const next = typeof value === "function" ? value(active.current) : value;
    active.current = next;
    updateFullscreen(next);
    if (next && !document.fullscreenElement) {
      // Во встроенных браузерах API может быть запрещён: остаётся режим без панелей.
      void document.documentElement.requestFullscreen?.().catch(() => undefined);
    } else if (!next && document.fullscreenElement) {
      void document.exitFullscreen().catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    const onChange = () => {
      if (!document.fullscreenElement) {
        active.current = false;
        updateFullscreen(false);
      }
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => {
      document.removeEventListener("fullscreenchange", onChange);
      if (active.current && document.fullscreenElement) {
        void document.exitFullscreen().catch(() => undefined);
      }
    };
  }, []);

  return { fullscreen, setFullscreen };
}
