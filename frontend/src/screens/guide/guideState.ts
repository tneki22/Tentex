import { useSyncExternalStore } from "react";

/**
 * Что руководство помнит между запусками: последнюю открытую страницу и то, что
 * его уже открывали (пока не открывали, кнопка в панели зовёт к себе). Оба
 * значения лежат в localStorage этого браузера, как и остальные настройки вида.
 */
const LAST_PAGE_KEY = "tentex-guide-last-page";
const OPENED_KEY = "tentex-guide-opened";
const OPENED_EVENT = "tentex-guide-opened";

export function readLastGuidePage(): string | null {
  try {
    return localStorage.getItem(LAST_PAGE_KEY);
  } catch {
    return null;
  }
}

export function writeLastGuidePage(slug: string): void {
  try {
    localStorage.setItem(LAST_PAGE_KEY, slug);
  } catch {
    /* Память браузера недоступна — руководство просто откроется с начала. */
  }
}

function hasOpenedGuide(): boolean {
  try {
    return localStorage.getItem(OPENED_KEY) === "1";
  } catch {
    // Без памяти подсветку не показываем: её нечем погасить, она бы мозолила глаза вечно.
    return true;
  }
}

/** Отметить, что руководство открыли: подсветка кнопки гаснет навсегда. */
export function markGuideOpened(): void {
  if (hasOpenedGuide()) return;
  try {
    localStorage.setItem(OPENED_KEY, "1");
  } catch {
    return;
  }
  window.dispatchEvent(new Event(OPENED_EVENT));
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(OPENED_EVENT, onChange);
  // Открыли руководство в другой вкладке — здесь подсветка тоже гаснет.
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(OPENED_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** `true`, пока руководство ни разу не открывали. */
export function useGuideUnopened(): boolean {
  return !useSyncExternalStore(subscribe, hasOpenedGuide, () => true);
}
