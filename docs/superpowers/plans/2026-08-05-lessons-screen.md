# Lessons Workspace and Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить Урок как изучаемую вкладку Рабочей области и отдельный раздел «Уроки» для одиночного и массового создания и редактирования Уроков по Темам Программы.

**Architecture:** Изучение остаётся на `/projects/:projectId`: готовый Урок открывается рядом с Источником в существующих изменяемых колонках. `/projects/:projectId/lessons` — одна производственная поверхность с деревом Программы, массовым выбором, mock-сценарием ИИ и облегчённым блочным редактором. Одни demo-типы и один read-only renderer используются обеими поверхностями; API, настоящий rich-text движок, генерация и выполнение Активностей в эту фазу не входят.

**Tech Stack:** React 19, TypeScript, React Router, существующий Radix-backed UI-kit Tentex, Lucide, CSS Grid, `localStorage`, выдуманные данные этапа 1.

## Global Constraints

- Контракты двух поверхностей уже записаны в `SCREENS.md`; реализация следует им без повторного продуктового проектирования.
- Русские тексты интерфейса, английские идентификаторы.
- Создание и редактирование происходят в разделе «Уроки»; чтение и изучение — только в Рабочей области.
- Урок принадлежит проекту и связан с одной или несколькими Темами; он не заменяет Тему, Активность или Сессию.
- Цепочка предметной модели: `Тема → Урок → Активности → Попытки → Оценки`. В этой фазе Активности показаны визуально, но не исполняются.
- Модуль определяется `lessonsEnabled`, а не `isTextbook`: учебник и свободное изучение включают его по умолчанию, экзамен может включить вручную.
- В этой фазе используется один маршрут `/projects/:projectId/lessons`; выбранные Тема и Урок передаются query-параметрами `topic` и `lesson`.
- Не вводить `/lessons/new` и `/lessons/:lessonId/edit`, пока редактор не потребует отдельной поверхности.
- Не добавлять Tiptap, BlockNote, dnd-kit, Mermaid runtime, JSON Schema validator и любые npm-зависимости.
- Не реализовывать API, фоновые задачи, вызовы моделей, версии, настоящий undo/redo, настоящее выполнение SQL и загрузку медиа.
- Mock-генерация заканчивается заранее подготовленным локальным черновиком и прямо называется прототипом.
- Сохранённый Урок читается без внешней модели. Выключенная модель блокирует только «Собрать с ИИ».
- Блок без источника помечается `Знания модели · без источника`; недоступный источник не удаляет блок.
- `ocr_low` показывается через `QualityBadge`, происхождение — через `SourceChip` и обычный текст; метрики не окрашиваются.
- Использовать существующие `Button`, `Checkbox`, `ConfirmDialog`, `CostEstimate`, `Dialog`, `EmptyState`, `Field`, `IconButton`, `Menu`, `OfflineNotice`, `PanelResizeHandle`, `Popover`, `QualityBadge`, `SourceChip`, `StatusBadge`, `Tooltip`.
- Новый компонент создаётся только для повторно используемого renderer Урока; редакторские элементы, нужные одному экрану, остаются рядом с `Lessons.tsx`.
- Цвета только через токены. Новые классы начинаются с `lessons-`; `transition: all` запрещён.
- Выдуманные данные лежат рядом с экраном. Не дублировать дерево Программы: использовать `resolveWorkspaceProject(projectId).nodes`.
- В проекте нет тестовой оснастки этапа 1. Проверка: `npm run typecheck`, `npm run lint`, `npm run build`, `docker compose restart web`, браузерный проход и `git diff --check`.
- Не трогать пользовательские изменения вне перечисленных файлов и не коммитить без отдельной просьбы.

---

## File Map

- `frontend/src/screens/lessons/lessonsDemo.ts` — типы Урока, три demo-Урока, helpers по Темам и минимальная dev-валидация.
- `frontend/src/screens/lessons/LessonDocument.tsx` — общий read-only renderer документа для Рабочей области и предпросмотра редактора.
- `frontend/src/screens/lessons/Lessons.tsx` — дерево, массовый выбор, список Уроков, mock-ИИ и облегчённый редактор.
- `frontend/src/styles/lessons.css` — только стили Уроков и editor prototype.
- `frontend/src/screens/ProjectWorkspace.tsx` — вкладка `lesson`, selector Уроков, переходы в редактор и восстановление выбора.
- `frontend/src/screens/workspaceDemo.ts` — `lessonsEnabled` в конфигурации demo-проекта.
- `frontend/src/app/screens.ts` — метаданные единственного нового маршрута `lessons`.
- `frontend/src/app/views.ts` — регистрация `Lessons`.
- `frontend/src/main.tsx` — подключение `lessons.css`.
- `REQUIREMENTS.md` — отдельное документальное выравнивание предметной модели после приёмки макета; агент-верстальщик этот файл не меняет.

---

### Task 1: Добавить общий demo-формат Урока

**Files:**
- Create: `frontend/src/screens/lessons/lessonsDemo.ts`

**Interfaces:**
- Consumes: ids `ivfflat`, `index-tuning`, `hybrid-search` из `workspaceDemo.ts`.
- Produces: `LessonDemo`, `LessonDocumentDemo`, `LessonBlockDemo`, `LESSON_DEMOS`, `lessonsForTopic(topicId)`, `lessonById(lessonId)`, `lessonCountsForNode(node)`.

- [ ] **Step 1: Объявить точные типы**

```ts
export type LessonStatus = "draft" | "ready" | "archived";
export type LessonGrounding = "project-sources" | "mixed" | "model-only";
export type LessonAuthorship = "manual" | "model" | "mixed";
export type LessonLayoutPreset =
  | "flow"
  | "media-left"
  | "media-right"
  | "two-equal"
  | "wide"
  | "full-width-practice";

export interface LessonSourceRefDemo {
  fragmentId: string | null;
  material: string | null;
  page: number | null;
  quality: "native" | "ocr" | "ocr_low" | null;
  origin: "project-fragment" | "model-knowledge";
  availability: "available" | "missing" | "review";
}

export type LessonBlockDemo =
  | { id: string; type: "rich-text"; paragraphs: string[]; sourceRefs: LessonSourceRefDemo[] }
  | { id: string; type: "callout"; tone: "neutral" | "info" | "warning"; title: string; body: string; sourceRefs: LessonSourceRefDemo[] }
  | { id: string; type: "image"; alt: string; caption: string; assetState: "available" | "missing"; sourceRefs: LessonSourceRefDemo[] }
  | { id: string; type: "diagram"; title: string; preview: string; alt: string; sourceRefs: LessonSourceRefDemo[] }
  | { id: string; type: "sql-activity"; activityId: string; prompt: string; dialect: "SQLite"; sourceRefs: LessonSourceRefDemo[] };

export interface LessonRowDemo {
  id: string;
  preset: LessonLayoutPreset;
  blocks: LessonBlockDemo[];
}

export interface LessonSectionDemo {
  id: string;
  title: string;
  objective: string;
  rows: LessonRowDemo[];
}

export interface LessonDocumentDemo {
  schemaVersion: 1;
  sections: LessonSectionDemo[];
}

export interface LessonDemo {
  id: string;
  projectId: string;
  topicIds: string[];
  title: string;
  goal: string;
  status: LessonStatus;
  difficulty: "intro" | "basic" | "advanced";
  estimatedMinutes: number;
  grounding: LessonGrounding;
  authorship: LessonAuthorship;
  requiresReview: boolean;
  document: LessonDocumentDemo;
}
```

- [ ] **Step 2: Создать основной готовый Урок**

  Для `ivfflat` создать `ivf-structure`: готовый, 18 минут, basic, `project-sources`. Документ содержит rich text, callout, цитируемый источник с `ocr_low`, media-left строку, широкую диаграмму, two-equal строку и SQL-активность на всю ширину.

- [ ] **Step 3: Создать второй Урок той же Темы**

  Для `ivfflat` создать `ivf-tuning-practice`: готовый, 12 минут, advanced, `mixed`. Он нужен для selector во вкладке Рабочей области и списка редактора.

- [ ] **Step 4: Создать проблемный черновик**

  Для `index-tuning` создать `index-tuning-draft`: `draft`, 15 минут, `model-only`, один источник `missing`, `requiresReview: true`. `hybrid-search` оставить без Уроков.

- [ ] **Step 5: Добавить helpers и dev-check**

  `lessonsForTopic` возвращает неархивные Уроки в порядке массива. `lessonCountsForNode` рекурсивно считает `draft/ready/total` по id узла и его потомкам. `validateLessonDemo` проверяет уникальность ids, непустые alt, непустые rows и `full-width-practice` у SQL; в `import.meta.env.DEV` бросает понятную ошибку при нарушении.

### Task 2: Зарегистрировать модуль и открыть переход из Рабочей области

**Files:**
- Modify: `frontend/src/screens/workspaceDemo.ts`
- Modify: `frontend/src/app/screens.ts`
- Modify: `frontend/src/app/views.ts`

**Interfaces:**
- Consumes: `WorkspaceProjectDemo`, `SCREEN_VIEWS`.
- Produces: `lessonsEnabled: boolean`, route id `lessons`, компонент `Lessons` в роутинге.

- [ ] **Step 1: Добавить `lessonsEnabled`**

  В `WorkspaceProjectDemo` добавить boolean. У `vector-indexes` поставить `true`, у `demo` — `false`.

- [ ] **Step 2: Добавить только один route meta**

  В `screens.ts` добавить:

```ts
{
  id: "lessons",
  path: "/projects/:projectId/lessons",
  navPath: `/projects/${DEMO_TEXTBOOK_PROJECT_ID}/lessons`,
  title: "Уроки",
  summary: "Одиночное и массовое создание Уроков по Темам Программы.",
  group: "Занятия",
  icon: GraduationCap,
  depth: "полностью",
}
```

  Не добавлять `lesson-new` и `lesson-edit`.

- [ ] **Step 3: Зарегистрировать view**

  После появления файла Task 4 импортировать `Lessons` из `../screens/lessons/Lessons` и добавить `lessons: Lessons` в `SCREEN_VIEWS`.

### Task 3: Сделать общий read-only renderer документа

**Files:**
- Create: `frontend/src/screens/lessons/LessonDocument.tsx`

**Interfaces:**
- Consumes: `LessonDocumentDemo`, `LessonRowDemo`, `LessonBlockDemo`.
- Produces: `<LessonDocument document mode onSelectBlock selectedBlockId />`.

- [ ] **Step 1: Объявить props**

```ts
interface LessonDocumentProps {
  document: LessonDocumentDemo;
  mode: "study" | "editor";
  selectedBlockId?: string | null;
  onSelectBlock?: (blockId: string) => void;
}
```

- [ ] **Step 2: Отрисовать секции и строки**

  Каждая секция имеет `h2`, objective и rows. Preset превращается в класс `lessons-row is-${preset}`. Renderer ничего не знает о дереве, массовом выборе и редакторском состоянии.

- [ ] **Step 3: Отрисовать union блоков exhaustive switch**

  Rich text — абзацы; callout — заголовок и body; image — локальный декоративный placeholder, обязательные alt и caption; diagram — безопасный статический preview из текста, без Mermaid; SQL — условие, mock textarea и disabled `Запустить`/`Проверить` с подсказкой «Будет доступно в Сессии».

- [ ] **Step 4: Показать происхождение локально**

  Для project fragment вывести `SourceChip`, имя материала, страницу, `QualityBadge`; для model knowledge — `SourceChip` с отсутствующим источником и текст `Знания модели · без источника`; `missing/review` показать внутри конкретного блока, не `ErrorState` на весь документ.

- [ ] **Step 5: Различить study и editor**

  В `study` блоки не выглядят выбираемыми. В `editor` блок получает кнопку выбора, `aria-pressed`, рамку выбранного состояния и короткие локальные действия; содержимое одинаковое в обоих режимах.

### Task 4: Добавить Урок во вкладки Рабочей области

**Files:**
- Modify: `frontend/src/screens/ProjectWorkspace.tsx`

**Interfaces:**
- Consumes: `LessonDocument`, `lessonsForTopic`, `lessonById`, `project.lessonsEnabled`.
- Produces: `WorkspaceTab = ... | "lesson"`, сохранённый `selectedLessonIds`, query-вход `topic/tab/lesson`.

- [ ] **Step 1: Добавить вкладку и иконку**

  Добавить `lesson` в `WorkspaceTab`, `TAB_KINDS` и `TAB_ICONS`; label — `Урок`. Базовые `EXAM_TABS` и `TEXTBOOK_TABS` оставить без `lesson`, а helper заменить на `allowedTabs(variant, lessonsEnabled)`, который добавляет `lesson` при `lessonsEnabled === true`. Передать этот флаг в `parseGroups` и загрузку сохранённого состояния. Не связывать доступность вкладки с `isTextbook`.

- [ ] **Step 2: Сохранить выбор Урока по Темам**

  В `StoredWorkspaceState` добавить `selectedLessonIds: Record<string, string>`. Парсить через существующий `stringRecord`; при отсутствии брать первый неархивный Урок Темы.

- [ ] **Step 3: Отрисовать вкладку**

  Ноль Уроков → `EmptyState` с `Создать урок`, ведущим в `/lessons?topic=${selectedNode.id}`. Один → сразу `LessonDocument mode="study"`. Несколько → обычный `<select>` над документом. Черновик получает `StatusBadge` и `Продолжить редактирование`; готовый — `Редактировать`.

- [ ] **Step 4: Открывать Урок рядом с Источником**

  Обычное меню «Открыть» позволяет выбрать `Урок` в пустой или активной колонке. При query `?topic=:topicId&tab=lesson&lesson=:lessonId` выбрать Тему, оставить Источник в первой группе и открыть Урок во второй группе; если групп уже больше, заменить только пустую или последнюю группу.

- [ ] **Step 5: Добавить раздел в проектную навигацию**

  В обеих ветках `renderProjectNav()` рисовать Link `Уроки` только при `project.lessonsEnabled`. Учебный demo показывает число `3`; при false пункт отсутствует полностью.

### Task 5: Сверстать дерево и режимы раздела «Уроки»

**Files:**
- Create: `frontend/src/screens/lessons/Lessons.tsx`

**Interfaces:**
- Consumes: `resolveWorkspaceProject`, `lessonCountsForNode`, `lessonsForTopic`, UI-kit.
- Produces: полноэкранный экран с `section | single | batch` режимами.

- [ ] **Step 1: Прочитать route и защитить модуль**

  Получить `projectId`, `topic`, `lesson`. При `lessonsEnabled === false` вернуть `<Navigate to={`/projects/${project.id}`} replace />`.

- [ ] **Step 2: Собрать состояние экрана**

```ts
type LessonsMode = "section" | "single" | "batch";

interface BatchSelection {
  topicIds: string[];
  actionByTopic: Record<string, "manual" | "ai" | "skip">;
  durationByTopic: Record<string, number>;
}
```

  Хранить текущий node, раскрытые sections, query, batch selection, current lesson, draft lessons, selected block, inspector width/open, save state. Сохранять UI под `tentex:lessons:${project.id}`.

- [ ] **Step 3: Сверстать левую панель**

  Взять данные дерева из `project.nodes`. Шеврон раскрывает, название выбирает, Checkbox темы добавляет в batch, Checkbox раздела выбирает изучаемых потомков. Строка показывает `нет урока / 1 черновик / N уроков`, а не доменный статус освоения.

- [ ] **Step 4: Реализовать поиск**

  Искать по названиям узлов и Уроков. Совпавший Урок оставляет в дереве родительскую Тему и разделы. Фильтры не добавлять.

- [ ] **Step 5: Реализовать три режима центра**

  Раздел → обзор Тем. Одна Тема → список Уроков и editor/empty state. Два и более checked topic ids → batch table, независимо от текущего узла.

- [ ] **Step 6: Добавить нижнюю навигацию**

  Кнопка назад ведёт в Рабочую область. `Программа` ведёт на `program?mode=textbook`; `Уроки` показаны active; остальные неподготовленные учебные разделы остаются disabled по текущему паттерну.

### Task 6: Сверстать облегчённый редактор

**Files:**
- Modify: `frontend/src/screens/lessons/Lessons.tsx`

**Interfaces:**
- Consumes: `LessonDocument mode="editor"`, `LessonDemo`, `LessonBlockDemo`.
- Produces: локально редактируемый demo-черновик без внешнего editor engine.

- [ ] **Step 1: Сверстать toolbar**

  Поля `Название` и `Цель`, `StatusBadge`, текст `Сохранение… / Сохранено`, `Открыть в Рабочей области`, `Готов`. Кнопка preview ведёт на `/${projectId}?topic=...&tab=lesson&lesson=...` через корректный `/projects/${projectId}`.

- [ ] **Step 2: Подключить renderer editor-mode**

  Клик выбирает блок. Над выбранным блоком показать `Вверх`, `Вниз`, `Дублировать`, `Удалить`; удаление подтверждать `ConfirmDialog`. Перетаскивание не делать.

- [ ] **Step 3: Добавить короткое меню блоков**

  Разрешить локально добавить `Текст`, `Определение`, `Изображение`, `Диаграмма`, `SQL-задача`. Новый блок получает конкретное demo-содержимое и уникальный id через `crypto.randomUUID()`.

- [ ] **Step 4: Сверстать инспектор**

  Показывать тип, select разрешённого preset, источники и disabled действия `Объяснить проще`, `Добавить пример`, `Сделать короче`. Не добавлять настройки шрифта, цвета, координат и пиксельных размеров.

- [ ] **Step 5: Сохранить локальный черновик**

  Использовать state + debounce в `localStorage` с ключом `tentex:lesson-drafts:${project.id}`. Не строить repository/store abstraction.

### Task 7: Сверстать ручное, mock-ИИ и массовое создание

**Files:**
- Modify: `frontend/src/screens/lessons/Lessons.tsx`

**Interfaces:**
- Consumes: selected topics, draft state, `CostEstimate`, `OfflineNotice`.
- Produces: manual draft, two-step AI dialog, batch preparation table.

- [ ] **Step 1: Реализовать ручной вход**

  `Создать вручную` создаёт локальный draft для текущей Темы с заголовком `Новый урок: ${topic.title}`, пустым flow-разделом и первым rich-text блоком-подсказкой; сразу открывает editor.

- [ ] **Step 2: Реализовать AI dialog как два состояния**

  `configure` содержит Темы, цель, сложность, длительность, grounding, Checkbox активностей и медиа. `storyboard` показывает фиксированные цели, три раздела, типы блоков, presets и `CostEstimate`. Кнопка `Собрать черновик` создаёт копию заранее подготовленного demo и status message `Прототип: модель не вызывалась`.

- [ ] **Step 3: Обработать выключенные модели**

  При demo-флаге models offline открытие диалога допускается для объяснения, но подтверждение disabled; внутри `OfflineNotice`. Ручное создание остаётся доступно.

- [ ] **Step 4: Реализовать «Выбрать темы без уроков»**

  Для текущего раздела выбрать только изучаемые узлы, у которых `ready === 0 && draft === 0`, сохранив порядок дерева.

- [ ] **Step 5: Реализовать «Создавать по порядку»**

  Выбрать такие же узлы по всему проекту. В batch table для каждой строки показать порядок, Тему, наличие материала, existing lesson count, action select и duration input.

- [ ] **Step 6: Подготовить mock-черновики пачкой**

  Не перезаписывать существующие Уроки. Для `manual` создать пустой draft, для `ai` — demo-copy с меткой прототипа, для `skip` не менять данные. После действия таблица показывает `Черновик готов` и ссылку открыть строку в single mode.

### Task 8: Стили, адаптивность и проверка

**Files:**
- Create: `frontend/src/styles/lessons.css`
- Modify: `frontend/src/main.tsx`
- Modify if visual omissions appear: files from Tasks 3–7

**Interfaces:**
- Consumes: готовые поверхности.
- Produces: проверенный путь `Рабочая область ↔ Уроки`.

- [ ] **Step 1: Добавить CSS**

  Импортировать `lessons.css` после `domain.css` и до `cards.css/layout.css`. Использовать `lessons-screen`, `lessons-tree`, `lessons-main`, `lessons-editor`, `lessons-inspector`, `lessons-document`, `lessons-row`, `lessons-block`, `lessons-batch` как корневые классы. Все значения через tokens.

- [ ] **Step 2: Сделать узкое состояние**

  Ниже доступной ширины закрыть inspector, строки `media-left/media-right/two-equal` сложить вертикально, дерево оставить не уже 260 px, рабочую часть прокручивать. Мобильный Drawer не создавать.

- [ ] **Step 3: Проверить клавиатуру**

  Все buttons/checkbox/select доступны Tab; выбранные tree rows и blocks имеют `aria-current`/`aria-pressed`; resize handle использует готовый компонент; dialog возвращает focus.

- [ ] **Step 4: Выполнить статические проверки**

  Run: `npm run typecheck`

  Expected: exit 0.

  Run: `npm run lint`

  Expected: exit 0.

  Run: `npm run build`

  Expected: exit 0.

- [ ] **Step 5: Перезапустить web**

  Run: `docker compose restart web`

  Expected: контейнер `web` перезапущен.

- [ ] **Step 6: Пройти Рабочую область**

  Открыть `/projects/vector-indexes`, выбрать `ivfflat`, открыть `Урок` рядом с `Источник`, переключить два Урока, перейти `Редактировать`, вернуться preview-ссылкой. Проверить `hybrid-search` без Урока.

- [ ] **Step 7: Пройти раздел «Уроки»**

  Проверить section overview, single topic, два Урока, ручной draft, AI configure/storyboard/prototype, batch selection раздела, «по порядку», mock-черновики и disabled AI при offline.

- [ ] **Step 8: Проверить сохранение и diff**

  После возврата восстановлены selected topic/lesson, раскрытие дерева, batch selection, inspector и draft. Run: `git diff --check`. Expected: exit 0.

---

## Definition of Done

- В Рабочей области Источник и Урок открываются рядом для одной Темы.
- Ноль, один и несколько Уроков Темы показаны разными штатными состояниями.
- Ссылка из Рабочей области открывает `/lessons` с правильными `topic` и `lesson`; preview возвращает обратно.
- Раздел «Уроки» показывает всю Программу, одиночный выбор, поддерево и массовый выбор Тем.
- Ручное создание, mock-ИИ и «создавать по порядку» проходят мышкой без API.
- Облегчённый editor показывает будущую композицию, но не притворяется полноценным rich-text редактором.
- Сохранённые Уроки не зависят от внешних моделей; отсутствующие источники и `ocr_low` показаны честно.
- Отдельные new/edit routes, backend, реальная генерация, drag-and-drop, Mermaid runtime и SQL execution отсутствуют.
- Typecheck, lint, build, restart, браузерные сценарии и `git diff --check` пройдены.

## Handoff to Layout Agent

Готовый самодостаточный промпт лежит в `docs/superpowers/prompts/2026-08-05-lessons-layout-agent.md`. Он намеренно уже этого плана: агенту-верстальщику не поручаются изменения требований и новое продуктовое проектирование.
