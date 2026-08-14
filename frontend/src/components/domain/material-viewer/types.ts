import type { MaterialPresentationKind } from "../../../api/materials";

export type { MaterialPresentationKind };

/** Что показано на сцене: обе половины, только исходник или только текст. */
export type MaterialViewMode = "compare" | "source" | "text";

export type ViewerZoom = number | "fit-page" | "fit-width";

/**
 * Как называть и показывать конкретный вид источника. Одна таблица вместо
 * проверок MIME по компонентам: подпись «Оригинал» у аудиозаписи и «Страница»
 * у веб-снимка — это вранье, которое разъезжается по экрану незаметно.
 */
export interface MaterialPresentation {
  kind: MaterialPresentationKind;
  defaultMode: MaterialViewMode;
  sourceLabel: string;
  textLabel: string;
  processingTitle: string;
  supportsZoom: boolean;
  supportsOutline: boolean;
  supportsTimeline: boolean;
}
