import { useEffect, useState } from "react";
import { getAiSettings, type AiSettingsRead } from "../api/ai";

/** Событие шлёт экран Параметров после каждого сохранения настроек ИИ. */
const INVALIDATE_EVENT = "tentex:ai-settings-updated";

let cache: AiSettingsRead | null = null;
let inflight: Promise<AiSettingsRead> | null = null;
const subscribers = new Set<(value: AiSettingsRead | null) => void>();

function load(): Promise<AiSettingsRead> {
  if (inflight) return inflight;
  inflight = getAiSettings()
    .then((value) => {
      cache = value;
      for (const notify of subscribers) notify(value);
      return value;
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

if (typeof window !== "undefined") {
  window.addEventListener(INVALIDATE_EVENT, () => {
    cache = null;
    for (const notify of subscribers) notify(null);
    void load();
  });
}

/**
 * Каталог моделей и провайдеров — один запрос на всё приложение.
 *
 * Композер показывает имя выбранной модели до всякого клика, поэтому ленивая
 * загрузка «при открытии всплывашки» тут не годится, а по одному запросу на
 * каждый чат и настройку — расточительно. Кэш живёт в модуле и сбрасывается
 * событием, которое Параметры уже шлют после сохранения.
 */
export function useAiCatalog(): AiSettingsRead | null {
  const [value, setValue] = useState<AiSettingsRead | null>(cache);

  useEffect(() => {
    subscribers.add(setValue);
    if (cache) setValue(cache);
    else void load().catch(() => undefined);
    return () => {
      subscribers.delete(setValue);
    };
  }, []);

  return value;
}
