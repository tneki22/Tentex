/**
 * Нейтральные инструменты просмотра материала.
 *
 * Ни один компонент отсюда не знает про проект, привязки, темы и покрытие:
 * то, что общее у Библиотеки и проектного просмотрщика, живёт здесь, а
 * проектная композиция остаётся в проектном экране.
 */
export { DocumentStage } from "./DocumentStage";
export { PdfOutline } from "./PdfOutline";
export { StructuredPage, MarkdownTable, highlight } from "./StructuredPage";
export { TimedTranscript, formatTime } from "./TimedTranscript";
export { ViewerToolbar } from "./ViewerToolbar";
export type { ViewerToolbarProps } from "./ViewerToolbar";
export { getMaterialPresentation } from "./sourcePresentation";
export type {
  MaterialPresentation,
  MaterialPresentationKind,
  MaterialViewMode,
  ViewerZoom,
} from "./types";
