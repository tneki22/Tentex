# Визуальный baseline этапа 1

Утверждённый baseline — аннотированный тег `ui-stage-1-baseline` на коммите `ab5b456711fa22c20106c84464851eed0a559d3f` (`chore: close stage 2 and prepare stage 3`). Тег не передвигается и не переписывается.

Чтобы прочитать файл из baseline, используй шаблон команды:

```bash
git show ui-stage-1-baseline:<path>
```

Например, реестр уже свёрстанных экранов:

```bash
git show ui-stage-1-baseline:frontend/src/app/views.ts
```

| Экран или поверхность | Исходник baseline | CSS baseline и семейства классов | Документ |
| --- | --- | --- | --- |
| Каркас приложения и навигация | `frontend/src/App.tsx`, `frontend/src/app/AppLayout.tsx`, `frontend/src/app/CommandPalette.tsx`, `frontend/src/app/ThemeToggle.tsx`, `frontend/src/app/screens.ts`, `frontend/src/app/views.ts` | `base.css`, `layout.css`: `app-*`, `nav-*`, `sidebar-*`, `palette-*`, `topbar-*` | `SCREENS.md`, `DESIGN.md` |
| Проекты | `frontend/src/screens/Projects.tsx` | `layout.css`, `domain.css`: `dash-*` | `SCREENS.md` — «Проекты» |
| Мастер создания проекта | `frontend/src/screens/ProjectWizard.tsx`, `frontend/src/screens/TextbookWizard.tsx` | `layout.css`: `project-wizard`, `wizard-*`, `textbook-*` | `SCREENS.md` — «Мастер создания проекта» |
| Рабочая область | `frontend/src/screens/ProjectWorkspace.tsx`, `frontend/src/screens/StudioPanel.tsx`, `frontend/src/screens/workspaceDemo.ts` | `layout.css`: `project-workspace`, `workspace-*`, `studio-*` | `SCREENS.md` — «Рабочая область проекта» |
| Программа / вопросы экзамена | `frontend/src/screens/Program.tsx` | `layout.css`: `program-*` | `SCREENS.md` — «Вопросы экзамена» |
| Материалы | `frontend/src/screens/Materials.tsx` | `layout.css`: `materials-*`, `project-materials` | `SCREENS.md` — «Материалы проекта» |
| Уроки | `frontend/src/screens/lessons/Lessons.tsx`, `frontend/src/screens/lessons/LessonDocument.tsx`, `frontend/src/screens/lessons/lessonsDemo.ts` | `lessons.css`: `lessons-*` | `SCREENS.md` — «Уроки» |
| Карточки | `frontend/src/screens/cards/Cards.tsx`, `frontend/src/screens/cards/BankMode.tsx`, `frontend/src/screens/cards/CreationMode.tsx`, `frontend/src/screens/cards/RepetitionMode.tsx`, `frontend/src/screens/cards/SessionScreen.tsx`, `frontend/src/screens/cards/mockCards.ts` | `cards.css`: `cards-*`, `repetition-*`, `bank-*`, `creation-*`, `manual-*`, `ai-*`, `fragment-*`, `session-*`, `question-*` | `SCREENS.md` — «Карточки» |
| План подготовки | `frontend/src/screens/Plan.tsx` | `layout.css`: `plan-*` | `SCREENS.md` — «План подготовки» |
| Настройки проекта | `frontend/src/screens/ProjectSettings.tsx` | `layout.css`: `project-settings-screen`, `settings-*` | `SCREENS.md` — «Настройки проекта» |
| Библиотека | `frontend/src/screens/Library.tsx` | `layout.css`: `lib-*` | `SCREENS.md` |
| Параметры | `frontend/src/screens/Setup.tsx` | `layout.css`: `setup-*` | `SCREENS.md` |
| Витрина UI-кита | `frontend/src/screens/UiKit.tsx` | `layout.css`, `ui-kit.css`: `kit-*` | `DESIGN.md` |

## Приоритет решений

1. Визуальная структура baseline: сохраняем компоновку, порядок и взаимодействия существующего экрана.
2. Живые API этапов 3–4: подменяют демонстрационные данные и ограничивают доступные действия, не меняя каркас без согласования.
3. Заглушка будущей функции: если серверного контура ещё нет, остаётся честной на исходном месте и не притворяется рабочим сценарием.

## Журнал отклонений

Согласованных отклонений нет.
