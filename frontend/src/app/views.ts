import { lazy, type ComponentType } from "react";

/**
 * Экраны, которые уже сверстаны. Отсюда строятся и роутинг, и навигация:
 * пока экрана здесь нет, ссылки на него в интерфейсе не появляется.
 *
 * Список всех экранов из §21 лежит отдельно, в screens.ts, и остаётся полным:
 * там видно, что ещё предстоит. Спроектировали экран на этапе 1 — добавили
 * сюда строку, и он сам появится в навигации.
 */
export const SCREEN_VIEWS: Record<string, ComponentType> = {
  projects: lazy(() => import("../screens/Projects").then((module) => ({ default: module.Projects }))),
  "project-new": lazy(() => import("../screens/ProjectWizard").then((module) => ({ default: module.ProjectWizard }))),
  workspace: lazy(() => import("../screens/ProjectWorkspace").then((module) => ({ default: module.ProjectWorkspace }))),
  lessons: lazy(() => import("../screens/lessons/Lessons").then((module) => ({ default: module.Lessons }))),
  materials: lazy(() => import("../screens/Materials").then((module) => ({ default: module.Materials }))),
  "source-viewer": lazy(() => import("../screens/Materials").then((module) => ({ default: module.SourceViewer }))),
  program: lazy(() => import("../screens/Program").then((module) => ({ default: module.Program }))),
  plan: lazy(() => import("../screens/Plan").then((module) => ({ default: module.Plan }))),
  "lesson-planning": lazy(() => import("../screens/LessonPlanning").then((module) => ({ default: module.LessonPlanning }))),
  cards: lazy(() => import("../screens/cards/Cards").then((module) => ({ default: module.Cards }))),
  "coverage-map": lazy(() => import("../screens/CoverageMap").then((module) => ({ default: module.CoverageMap }))),
  "textbook-coverage": lazy(() => import("../screens/coverage/CoverageOverview").then((module) => ({ default: module.CoverageOverviewScreen }))),
  settings: lazy(() => import("../screens/ProjectSettings").then((module) => ({ default: module.ProjectSettings }))),
  library: lazy(() => import("../screens/Library").then((module) => ({ default: module.Library }))),
  "library-search": lazy(() => import("../screens/library/LibrarySearch").then((module) => ({ default: module.LibrarySearch }))),
  "library-material": lazy(() => import("../screens/library/LibraryMaterialWorkspace").then((module) => ({ default: module.LibraryMaterialWorkspace }))),
  setup: lazy(() => import("../screens/Setup").then((module) => ({ default: module.Setup }))),
  "ui-kit": lazy(() => import("../screens/UiKit").then((module) => ({ default: module.UiKit }))),
  guide: lazy(() => import("../screens/Guide").then((module) => ({ default: module.Guide }))),
};
