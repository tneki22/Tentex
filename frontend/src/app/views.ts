import type { ComponentType } from "react";
import { Cards } from "../screens/cards/Cards";
import { CoverageMap } from "../screens/CoverageMap";
import { Library } from "../screens/Library";
import { LibraryMaterialWorkspace } from "../screens/library/LibraryMaterialWorkspace";
import { Lessons } from "../screens/lessons/Lessons";
import { Materials, SourceViewer } from "../screens/Materials";
import { Plan } from "../screens/Plan";
import { Program } from "../screens/Program";
import { ProjectWorkspace } from "../screens/ProjectWorkspace";
import { ProjectWizard } from "../screens/ProjectWizard";
import { Projects } from "../screens/Projects";
import { ProjectSettings } from "../screens/ProjectSettings";
import { Setup } from "../screens/Setup";
import { UiKit } from "../screens/UiKit";

/**
 * Экраны, которые уже сверстаны. Отсюда строятся и роутинг, и навигация:
 * пока экрана здесь нет, ссылки на него в интерфейсе не появляется.
 *
 * Список всех экранов из §21 лежит отдельно, в screens.ts, и остаётся полным:
 * там видно, что ещё предстоит. Спроектировали экран на этапе 1 — добавили
 * сюда строку, и он сам появится в навигации.
 */
export const SCREEN_VIEWS: Record<string, ComponentType> = {
  projects: Projects,
  "project-new": ProjectWizard,
  workspace: ProjectWorkspace,
  lessons: Lessons,
  materials: Materials,
  "source-viewer": SourceViewer,
  program: Program,
  plan: Plan,
  cards: Cards,
  "coverage-map": CoverageMap,
  settings: ProjectSettings,
  library: Library,
  "library-material": LibraryMaterialWorkspace,
  setup: Setup,
  "ui-kit": UiKit,
};

