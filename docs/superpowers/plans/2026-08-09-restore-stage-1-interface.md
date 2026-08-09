# Restore Stage 1 Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Вернуть согласованную на этапе 1 структуру и визуальный язык всех уже свёрстанных экранов Tentex, не потеряв живые данные и API этапов 3–4.

**Architecture:** Коммит `ab5b456711fa22c20106c84464851eed0a559d3f` становится неизменяемым визуальным эталоном. Его JSX, CSS-классы и экранные решения переносятся вперёд, а текущие контроллеры и API подключаются к этим поверхностям. Если старый элемент опирался на ещё не реализованную функцию, он остаётся на прежнем месте как явно подписанная недоступная функция; новую компоновку вместо него не проектируем.

**Tech Stack:** React 19, TypeScript, React Router, Vite, обычный CSS на токенах Tentex, Radix Primitives, FastAPI API этапов 3–4, SQLite.

## Global Constraints

- Визуальный baseline: `ab5b456711fa22c20106c84464851eed0a559d3f`.
- Текущий живой контракт: `docs/architecture/stage-3-live-projects.md` и `docs/architecture/stage-4-reference-answers.md`.
- Не выполнять `git checkout --`, `git reset`, массовое восстановление каталога или замену всего рабочего дерева: этапы 3–4 сейчас находятся в незакоммиченных изменениях.
- Не менять backend-схему и API ради восстановления внешнего вида: существующего контракта достаточно, включая все семь типов вкладок `WorkspaceTab`.
- Не возвращать mock-факты в живые маршруты: выдуманные проценты, файлы, ответы, покрытие и занятия заменяются нейтральными заглушками в исходной компоновке.
- Не добавлять функции этапов 5–10. Файлы и OCR — этап 5, модели — этап 7, привязки и покрытие — этап 8, карточки и План — этап 9.
- Не показывать покрытие материала ниже 100% как проблему (FR-D17).
- Русский интерфейс, английские идентификаторы, цвета только через `frontend/src/styles/tokens.css`.
- Каждый восстановленный экран проверять в светлой и тёмной темах; после фронтенд-правок выполнять `docker compose restart web` перед браузерной проверкой.
- Любое намеренное отклонение от baseline сначала записывать в `docs/ui/stage-1-interface-baseline.md` с причиной и только затем реализовывать.

---

## Найденный источник и фактический объём восстановления

Исходный дизайн не потерян. Он целиком находится в Git в `ab5b456`; текущие этапы 3–4 лежат поверх него в рабочем дереве.

| Поверхность этапа 1 | Состояние относительно `ab5b456` | Действие |
| --- | --- | --- |
| Мастер: выбор пути и экзамен | `ProjectWizard.tsx` сокращён с 1259 строк до оболочки; живой экзамен вынесен в новый упрощённый экран | Вернуть исходную компоновку и подключить `useWizardDraft` |
| Мастер: учебник | `TextbookWizard.tsx` сокращён с 587 строк до упрощённой формы | Вернуть пять исходных шагов; файлы и модели оставить заглушками, ручную Программу подключить к API |
| Рабочая область | `ProjectWorkspace.tsx` сокращён с 1057 до 322 строк; семь вкладок сведены к двум | Вернуть исходную оболочку, Студию, меню вкладок и панели; реальные эталоны подключить, остальное заглушить |
| Проекты | Макеты заменены живым списком, часть карточной композиции удалена | Сохранить API и вернуть исходные карточки, hover/focus-действия и архив |
| Программа | Demo-редактор заменён живым, но упрощённым редактором | Вернуть исходную трёхзонную композицию и подключить текущие команды дерева |
| Глобальная оболочка | Убраны зоны покрытия и последних тем; mock-данные честно удалены | Вернуть зоны в прежних местах с пустыми состояниями, не с mock-числами |
| Материалы | Не изменены | Зафиксировать как сохранённый baseline; код не переписывать |
| План подготовки | Не изменён | Зафиксировать как сохранённый baseline; код не переписывать |
| Карточки | Каталог `screens/cards/` не изменён | Зафиксировать как сохранённый baseline; код не переписывать |
| Уроки | Каталог `screens/lessons/` не изменён | Зафиксировать как сохранённый baseline; код не переписывать |
| Библиотека, Параметры, Студия | Не изменены | Зафиксировать как сохранённый baseline; код не переписывать |
| Карта эталонов | В baseline полноценного экрана не было; текущий экран создан на этапе 4 | Сохранить текущий утилитарный экран, не выдавая его за окончательную Карту покрытия |

---

### Task 1: Закрепить baseline и правило «оживлять, не переделывать»

**Files:**
- Create: `docs/ui/stage-1-interface-baseline.md`
- Modify: `AGENTS.md`
- Modify: `SCREENS.md`

**Interfaces:**
- Consumes: Git object `ab5b456711fa22c20106c84464851eed0a559d3f`.
- Produces: локальный тег `ui-stage-1-baseline` и документированный приоритет визуальных решений.

- [ ] **Step 1: Убедиться, что baseline доступен и рабочее дерево не очищается**

  Run:

  ```powershell
  git cat-file -t ab5b456711fa22c20106c84464851eed0a559d3f
  git status --short
  ```

  Expected: первая команда печатает `commit`; вторая показывает текущие изменения этапов 3–4, которые остаются на месте.

- [ ] **Step 2: Создать неизменяемую ссылку на исходный интерфейс**

  Run:

  ```powershell
  git tag -a ui-stage-1-baseline ab5b456711fa22c20106c84464851eed0a559d3f -m "Stage 1 approved interface baseline"
  git show --no-patch --oneline ui-stage-1-baseline
  ```

  Expected: тег указывает на `ab5b456`.

- [ ] **Step 3: Записать карту исходников**

  Создать `docs/ui/stage-1-interface-baseline.md` с четырьмя разделами:

  1. точный hash и команда чтения файла: `git show ui-stage-1-baseline:<path>`;
  2. таблица экран → исходный `.tsx` → связанные CSS-классы → утверждённый документ;
  3. приоритет разрешения противоречий: визуальная структура baseline → реализованный API этапов 3–4 → будущая функция как заглушка;
  4. журнал явно согласованных отклонений, изначально пустой с текстом `Согласованных отклонений нет`.

- [ ] **Step 4: Добавить проектное правило в `AGENTS.md`**

  Добавить в раздел правил работы точную норму:

  > При оживлении уже свёрстанного экрана визуальная структура, порядок блоков и основные взаимодействия берутся из тега `ui-stage-1-baseline`. Отсутствующий API не является причиной менять компоновку: элемент остаётся на прежнем месте как честная заглушка. Новая структура допустима только после явного согласования с пользователем и записи причины в `docs/ui/stage-1-interface-baseline.md`.

- [ ] **Step 5: Зафиксировать тот же приоритет в `SCREENS.md`**

  Добавить короткий раздел «Визуальный baseline этапа 1» перед описаниями экранов. Не переписывать текущие серверные границы этапов 3–4.

- [ ] **Step 6: Проверить документ и точность путей**

  Run:

  ```powershell
  rg -n "ui-stage-1-baseline|ab5b456|ProjectWizard|ProjectWorkspace|TextbookWizard" AGENTS.md SCREENS.md docs/ui/stage-1-interface-baseline.md
  ```

  Expected: правило встречается во всех трёх документах, а карта содержит критические экраны.

- [ ] **Step 7: Создать checkpoint-коммит только после разрешения пользователя на коммиты**

  ```powershell
  git add AGENTS.md SCREENS.md docs/ui/stage-1-interface-baseline.md
  git commit -m "docs: preserve stage 1 interface baseline"
  ```

---

### Task 2: Вернуть каркас Мастера и экран выбора пути

**Files:**
- Create: `frontend/src/screens/project-wizard/WizardChrome.tsx`
- Modify: `frontend/src/screens/ProjectWizard.tsx`
- Modify: `frontend/src/styles/layout.css`

**Interfaces:**
- Consumes: `listWizardDrafts`, `useWizardDraft`, исходные классы `wizard-topbar`, `wizard-progress`, `wizard-main`, `wizard-track-grid`.
- Produces: `WizardChrome` с props `trackLabel`, `step`, `maxStep`, `stepLabels`, `onStepChange`, `onSaveAndExit`, `onDiscard`, `children`.

- [ ] **Step 1: Восстановить исходный landing без возврата mock-данных**

  Скопировать из `ui-stage-1-baseline:frontend/src/screens/ProjectWizard.tsx` hero, три карточки путей, типографику, иконки и исходные CSS-классы. Экзамен и Учебник запускают текущие `start("exam")` и `start("textbook")`; Свободное изучение остаётся недоступным с подписью `После этапа 7`.

- [ ] **Step 2: Встроить возобновляемые черновики в исходную структуру**

  Разместить блок `Продолжить черновик` между hero и сеткой путей. Карточка показывает реальное имя, ветку, шаг и `updated_at`; действие вызывает текущий `resume(draft)`. Загрузка использует `LoadingState`, ошибка — `ErrorState` с повтором.

- [ ] **Step 3: Извлечь старую верхнюю панель и прогресс без изменения разметки**

  `WizardChrome` должен рендерить исходные `wizard-topbar`, `wizard-step-caption`, `wizard-progress` и `wizard-main`. Переход на шаг разрешён только при `itemStep <= maxStep`. Сохранение и удаление черновика остаются текущими серверными действиями.

- [ ] **Step 4: Вернуть удалённые CSS-правила только для Мастера**

  Сравнить `layout.css` с тегом и восстановить правила `wizard-*`/`textbook-*`, которые были удалены или перекрыты упрощённой оболочкой. Не заменять весь файл: он одновременно содержит живые добавления этапов 3–4.

- [ ] **Step 5: Проверить landing и восстановление черновика**

  Run:

  ```powershell
  npm run typecheck
  npm run build
  ```

  Expected: обе команды завершаются с кодом 0; `/projects/new` визуально повторяет baseline и показывает серверные черновики.

- [ ] **Step 6: Commit**

  ```powershell
  git add frontend/src/screens/ProjectWizard.tsx frontend/src/screens/project-wizard/WizardChrome.tsx frontend/src/styles/layout.css
  git commit -m "fix: restore project wizard shell"
  ```

---

### Task 3: Подключить живой экзаменационный сценарий к старым пяти шагам

**Files:**
- Modify: `frontend/src/screens/project-wizard/ExamWizard.tsx`
- Modify: `frontend/src/hooks/useWizardDraft.ts` only if the view needs a currently hidden save/conflict state
- Modify: `frontend/src/styles/layout.css`

**Interfaces:**
- Consumes: `WizardDraftController`, `importExam`, `queueSave`, `enqueueProgramCommand`, `activate`, `reload`, `updateProgramNode`.
- Produces: пять исходных шагов `Формат → Материалы → Загрузка → Паспорт → Проверка` и экран успеха.

- [ ] **Step 1: Вернуть исходные варианты формата**

  Использовать старые `RadioCards`, пояснения и блоки `Точный список вопросов / Вопросы и задачи / Билеты`. Значение по-прежнему сохраняется как `ExamFormat`; визуальный выбор не заменять компактным `select` или одной строкой табов.

- [ ] **Step 2: Вернуть исходный выбор материалов с честными возможностями**

  Сохранить три старые карточки: список вопросов, эталонные ответы, учебные материалы. Карточка списка вопросов активна. На файловой части внутри неё показать `Загрузка файлов появится на этапе 5. Сейчас вставьте текст на следующем шаге.` Карточки ответов и материалов можно выбрать визуально, но их действия подписать `Добавить после создания проекта`; они не отправляют mock-файлы.

- [ ] **Step 3: Подключить вставленный текст к исходному `UploadPanel`**

  Режим вставки текста работает через `controller.importExam(rawText, format)`. Drag-and-drop и file input остаются видимыми, но disabled с подписью этапа 5. Ошибки импорта показываются внутри панели; реальные `warnings` и счётчики сохраняются в draft.

- [ ] **Step 4: Вернуть исходный Паспорт цели**

  Восстановить две карточки, `RadioCards`, `SegmentedTabs`, расчёт оставшихся дней и прогноз нагрузки из baseline. Поля маппятся на существующий `GoalPassportWrite`; прогноз является вычислением из введённых значений, а не серверным фактом.

- [ ] **Step 5: Вернуть исходную Проверку проекта**

  Показывать живые `ProgramNode` в старой иерархии, реальные числа импорта, формулировку цели и ритм. Inline-редактирование вызывает `updateProgramNode` с `expected_program_revision`. Секции источников остаются в прежних местах и показывают `Ответы не добавлены` / `Материалы не добавлены`.

- [ ] **Step 6: Сохранить все серверные состояния этапа 3**

  Автосохранение выполняется через очередь с задержкой 400 мс; `stale_draft_revision` и `stale_program_revision` показывают старую композицию экрана с отдельной карточкой конфликта и кнопкой `Загрузить серверную версию`. После активации переходить в реальную Рабочую область созданного проекта.

- [ ] **Step 7: Проверить экзаменационный путь**

  В браузере пройти: выбор формата → выбор источников → вставка минимум трёх вопросов → паспорт → переименование одного вопроса → проверка → создание. Обновить страницу на шагах 3 и 5 и убедиться, что черновик восстанавливается.

- [ ] **Step 8: Commit**

  ```powershell
  git add frontend/src/screens/project-wizard/ExamWizard.tsx frontend/src/hooks/useWizardDraft.ts frontend/src/styles/layout.css
  git commit -m "fix: restore exam wizard interface"
  ```

---

### Task 4: Вернуть учебниковую ветку без имитации файлов и моделей

**Files:**
- Modify: `frontend/src/screens/TextbookWizard.tsx`
- Modify: `frontend/src/styles/layout.css`

**Interfaces:**
- Consumes: `WizardDraftController`, команды `createProgramNode`, `updateProgramNode`, `moveProgramNode`, `removeProgramNode`, `undo`.
- Produces: исходные пять шагов `Источники → Профиль → Перед построением → Редактор → Итог`.

- [ ] **Step 1: Вернуть экран Источников**

  Восстановить старую dropzone, список источников, роли, приоритет и блок `Что поняла система`. Пока этап 5 не реализован, dropzone disabled, список пуст, а вместо анализа показана точная подпись `Загрузка и анализ учебника появятся на этапе 5`. Основное живое действие — `Собрать программу вручную`.

- [ ] **Step 2: Вернуть двухколоночный Профиль проекта**

  Восстановить поля цели, охвата, текущего уровня, результата, критерия успеха, важного, исключений, срока и ритма. Сохранять их в существующие `Project` и `GoalPassport`; `scope` не сводить к одной константе.

- [ ] **Step 3: Вернуть Предпроверку**

  Сохранить исходную карточку локальной обработки, переключатель внешней модели и `OfflineNotice`. Переключатель модели disabled с подписью `Автоматическое построение программы появится на этапе 7`; ручной путь остаётся доступным.

- [ ] **Step 4: Вернуть полноразмерный редактор Программы**

  Восстановить toolbar, дерево/текст/вопросы, поиск, фильтр, панель свойств и ручные действия. Добавление, переименование, перемещение, вложенность и мягкое удаление вызывают текущие API-команды. Панель помощника остаётся справа в исходном размере, но ввод disabled и объясняет этап 7; никаких mock-предложений не показывать.

- [ ] **Step 5: Вернуть Итог без ложной активации**

  Показать реальный паспорт и реальные узлы. Источники отображаются как `Не добавлены`. Основная кнопка называется `Сохранить черновик и выйти`, вызывает `queueSave`, `flush` и переход на `/projects`; учебниковый проект не активируется до появления источника.

- [ ] **Step 6: Проверить учебниковый путь**

  Пройти ручной путь, добавить раздел, тему и подпункт, изменить порядок, обновить страницу, вернуться в черновик и удалить один узел с undo. Убедиться, что редактор визуально совпадает с baseline, а не с упрощённой формой этапа 3.

- [ ] **Step 7: Commit**

  ```powershell
  git add frontend/src/screens/TextbookWizard.tsx frontend/src/styles/layout.css
  git commit -m "fix: restore textbook wizard interface"
  ```

---

### Task 5: Вернуть карточки Проектов, Программу и глобальную оболочку

**Files:**
- Modify: `frontend/src/screens/Projects.tsx`
- Modify: `frontend/src/screens/Program.tsx`
- Preserve: `frontend/src/screens/programTree.ts`
- Modify: `frontend/src/app/AppLayout.tsx`
- Modify: `frontend/src/app/CommandPalette.tsx`
- Modify: `frontend/src/styles/layout.css`

**Interfaces:**
- Consumes: текущие list/order/archive/restore/delete APIs и команды дерева Программы.
- Produces: исходные композиции экранов на живых данных без демонстрационных фактов.

- [ ] **Step 1: Вернуть исходную карточку Проекта**

  Скопировать baseline-разметку `dash-card`, `ProjectChip`, drag handle и hover/focus overlay. Реальное имя, иконка, цвет и статус приходят из `ProjectSummary`. Действия `Открыть`, `Вверх`, `Вниз`, `Архивировать`, `Вернуть`, `Удалить навсегда` используют текущие обработчики. Недоступные метрики не заменять нулями: в их старом месте показывать `Показатели появятся после материалов и занятий`.

- [ ] **Step 2: Вернуть исходные empty/archive/template состояния Проектов**

  Сохранить живую загрузку и ошибки. В пустом состоянии вернуть старые карточки трёх шаблонов; Свободное изучение disabled. Архив остаётся раскрытием как в baseline, с реальными проектами.

- [ ] **Step 3: Вернуть исходную трёхзонную Программу**

  Восстановить заголовок/toolbar, иерархический центральный список и правую панель выбранного узла. Текущие операции create/update/move/target-level/remove/restore/undo сохраняются. Кнопки повторного импорта, автоматической раскладки и связей видимы в старых местах, но disabled с подписями соответствующих будущих этапов.

- [ ] **Step 4: Вернуть структуру sidebar без mock-чисел**

  В `AppLayout` вернуть `Покрытие материалов` и `Последние темы` в прежние места. Содержимое: `Покрытие появится после привязок на этапе 8` и `Здесь появятся последние изученные темы`. Фон, модели и состояние установки остаются честными текущими пустыми состояниями.

- [ ] **Step 5: Вернуть визуальную структуру палитры команд**

  Оставить живые проекты и экраны. Вернуть группу `Файлы` и исходный placeholder `Проект, экран или файл`, но до этапа 5 группа показывает ненажимаемую строку `Файлы появятся после подключения Библиотеки к API`, а не demo-файлы.

- [ ] **Step 6: Проверить операции**

  В браузере проверить reorder с мыши и кнопками, архив/возврат, открытие проекта, add → reload → undo в Программе, фильтр и пустое дерево. Ошибка одной команды должна оставлять старую композицию и показываться inline.

- [ ] **Step 7: Commit**

  ```powershell
  git add frontend/src/screens/Projects.tsx frontend/src/screens/Program.tsx frontend/src/app/AppLayout.tsx frontend/src/app/CommandPalette.tsx frontend/src/styles/layout.css
  git commit -m "fix: restore projects and program layouts"
  ```

---

### Task 6: Вернуть Рабочую область и все семь вкладок

**Files:**
- Modify: `frontend/src/screens/ProjectWorkspace.tsx`
- Preserve: `frontend/src/screens/StudioPanel.tsx`
- Preserve: `frontend/src/screens/workspaceDemo.ts` as historical reference only, never as live fallback
- Modify: `frontend/src/styles/layout.css`

**Interfaces:**
- Consumes: `ProjectDetail`, `WorkspaceLayout`, `WorkspaceTab`, `saveWorkspaceState`, API эталонного ответа этапа 4.
- Produces: исходная полнооконная Рабочая область с вкладками `answer`, `source`, `lesson`, `conspect`, `history`, `chat`, `summary`.

- [ ] **Step 1: Вернуть исходную оболочку**

  Перенести из baseline дерево, toolbar, нижнюю проектную навигацию, question bar, рабочую сетку, resizers и `StudioPanel`. Название, дедлайн, дерево и выбранная тема берутся только из `ProjectDetail`.

- [ ] **Step 2: Убрать текущее искусственное сужение вкладок**

  `sanitizeLayout` должен принимать все значения существующего `WorkspaceTab`, а `allowedTabs` — возвращать экзаменационный и учебниковый наборы из baseline. Сохранение по-прежнему идёт через `WorkspaceState`, не через `localStorage`.

- [ ] **Step 3: Вернуть управление панелями**

  Восстановить меню открытия вкладки, закрытие вкладки, добавление до трёх панелей, закрытие пустой панели и изменение весов соседних панелей. На сервер отправляются `selected_node_id`, `expanded_node_ids`, `tree_width`, `groups`, `group_weights`; resize сохраняется с debounce 400 мс.

- [ ] **Step 4: Подключить реальный эталонный ответ**

  Вкладка `answer` показывает текущий `ReferenceAnswerSlot`, статусы `manual`, `auto_matched`, `confirmed`, `needs_review`, а при отсутствии — старое пустое состояние с переходом в Карту эталонов. Никакой текст из `workspaceDemo.ts` не попадает в живой маршрут.

- [ ] **Step 5: Вернуть остальные вкладки как функциональные заглушки**

  Сохранить исходные заголовки, иконки и размеры, используя точные тексты:

  - `source`: `Материалы и привязанные фрагменты появятся на этапе 5 и этапе 8.`
  - `lesson`: `Уроки пока доступны только в прототипном разделе.`
  - `conspect`: `Личный конспект пока не подключён к хранилищу.`
  - `history`: `История появится после первых учебных активностей.`
  - `chat`: `Помощник будет подключён вместе со шлюзом моделей на этапе 7.`
  - `summary`: `Сводный конспект появится после сохранения личных конспектов.`

  Быстрые действия внутри этих панелей disabled; вкладки при этом открываются, закрываются и сохраняют раскладку.

- [ ] **Step 6: Вернуть Студию как постоянную поверхность**

  Подключить существующий `StudioPanel` в свёрнутом и развёрнутом состоянии. Кнопки будущих действий disabled с честными пояснениями; ширина и общий layout совпадают с baseline.

- [ ] **Step 7: Проверить восстановление состояния**

  Открыть эталонный ответ, добавить вторую и третью панель, открыть `chat` и `conspect`, изменить ширину дерева и панелей, раскрыть раздел, выбрать другой вопрос и обновить страницу. Все поддерживаемые layout-поля должны восстановиться из SQLite.

- [ ] **Step 8: Commit**

  ```powershell
  git add frontend/src/screens/ProjectWorkspace.tsx frontend/src/styles/layout.css
  git commit -m "fix: restore project workspace interface"
  ```

---

### Task 7: Проверить, что остальные прототипы не потеряны и ничего нового не вытеснило baseline

**Files:**
- Verify unchanged: `frontend/src/screens/Materials.tsx`
- Verify unchanged: `frontend/src/screens/Plan.tsx`
- Verify unchanged: `frontend/src/screens/cards/`
- Verify unchanged: `frontend/src/screens/lessons/`
- Verify unchanged: `frontend/src/screens/Library.tsx`
- Verify unchanged: `frontend/src/screens/Setup.tsx`
- Verify unchanged: `frontend/src/screens/StudioPanel.tsx`
- Modify only if route registration is missing: `frontend/src/app/views.ts`
- Modify: `docs/ui/stage-1-interface-baseline.md`

**Interfaces:**
- Consumes: `ui-stage-1-baseline` and `SCREEN_VIEWS`.
- Produces: доказуемый список сохранённых экранов и полный browser-smoke.

- [ ] **Step 1: Сравнить сохранённые экраны с baseline**

  Run:

  ```powershell
  git diff --exit-code ui-stage-1-baseline -- frontend/src/screens/Materials.tsx frontend/src/screens/Plan.tsx frontend/src/screens/cards frontend/src/screens/lessons frontend/src/screens/Library.tsx frontend/src/screens/Setup.tsx frontend/src/screens/StudioPanel.tsx
  ```

  Expected: пустой diff. Если отличие появилось в ходе восстановления, откатить только собственное изменение через `apply_patch`, не через checkout.

- [ ] **Step 2: Проверить реестр экранов**

  Убедиться, что в `SCREEN_VIEWS` остаются Проекты, Мастер, Рабочая область, Материалы, Программа, План, Карточки, Уроки, Настройки, Библиотека, Параметры, UI-kit и текущая Карта эталонов. Не добавлять ссылки на ещё не свёрстанные Source Viewer, Suggestions, Inbox или Session.

- [ ] **Step 3: Выполнить все автоматические проверки**

  Run:

  ```powershell
  python backend/scripts/check_stage2.py
  python backend/scripts/check_stage3.py
  python backend/scripts/check_stage4.py
  python -m ruff check backend
  npm run typecheck
  npm run lint
  npm run build
  ```

  Expected: каждая команда завершается с кодом 0.

- [ ] **Step 4: Перезапустить web и пройти browser-smoke**

  Run:

  ```powershell
  docker compose restart web
  ```

  Проверить в светлой и тёмной темах при 1440×900 и на узком окне: `/projects`, `/projects/new`, обе ветки Мастера, живые `/projects/:id`, `/program`, `/coverage-map`, а также `/materials`, `/plan`, `/cards`, `/lessons`, `/settings`, `/library`, `/setup`, `/ui-kit`.

- [ ] **Step 5: Записать результат аудита**

  В `docs/ui/stage-1-interface-baseline.md` отметить дату проверки, commit реализации и только реально согласованные отклонения. Карта эталонов отдельно помечается как новый утилитарный экран этапа 4, у которого не было полного baseline на этапе 1.

- [ ] **Step 6: Финальный commit после разрешения пользователя**

  ```powershell
  git add frontend/src/app/views.ts docs/ui/stage-1-interface-baseline.md
  git commit -m "docs: verify restored stage 1 interfaces"
  ```

---

## Self-review

- Покрыты все файлы, которые отличаются от baseline по экранной структуре.
- Сохранены API, optimistic reorder, ревизии, конфликты, undo, эталоны и layout SQLite этапов 3–4.
- Для ещё не реализованных функций указан конкретный вид и текст заглушки; mock-данные не возвращаются.
- Неизменённые Карточки, Материалы, План, Уроки, Библиотека и Параметры проверяются сравнением с тегом, а не переписываются.
- Backend, миграции и модель данных не меняются.
- Полный откат рабочего дерева нигде не используется.

