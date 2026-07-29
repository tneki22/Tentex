import { useCallback, useEffect, useState } from "react";

export type ThemePreference = "system" | "light" | "dark";

const STORAGE_KEY = "tentex:theme";
const ORDER: ThemePreference[] = ["system", "light", "dark"];

function readStored(): ThemePreference {
  const value = localStorage.getItem(STORAGE_KEY);
  return value === "light" || value === "dark" ? value : "system";
}

/**
 * Тема. Значения три: за системой, всегда светлая, всегда тёмная.
 * Переключение — это атрибут data-theme на <html>, всё остальное делает CSS
 * через color-scheme и light-dark() в tokens.css.
 */
export function useTheme() {
  const [preference, setPreference] = useState<ThemePreference>(readStored);

  useEffect(() => {
    const root = document.documentElement;

    // Chrome не доводит до конца transition, вызванный сменой color-scheme:
    // кнопки и метки застревают на цвете старой темы, пока по ним не проведёшь
    // мышью. Поэтому на время переключения переходы гасим и включаем обратно
    // через кадр, когда новые цвета уже применены.
    root.classList.add("is-theme-switching");

    if (preference === "system") {
      delete root.dataset.theme;
      localStorage.removeItem(STORAGE_KEY);
    } else {
      root.dataset.theme = preference;
      localStorage.setItem(STORAGE_KEY, preference);
    }

    const frame = requestAnimationFrame(() => {
      requestAnimationFrame(() => root.classList.remove("is-theme-switching"));
    });
    return () => cancelAnimationFrame(frame);
  }, [preference]);

  const cycle = useCallback(() => {
    setPreference((current) => ORDER[(ORDER.indexOf(current) + 1) % ORDER.length]);
  }, []);

  return { preference, setPreference, cycle };
}
