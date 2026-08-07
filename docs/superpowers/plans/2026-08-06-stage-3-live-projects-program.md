# Stage 3 Live Projects and Program Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить демонстрационные данные в создании проекта, списке проектов, Программе и базовой Рабочей области на единое серверное состояние, чтобы экзаменационный проект проходил путь «вставленный список → возобновляемый черновик → импортированная программа → активация → рабочая область» и переживал перезапуск.

**Architecture:** React расширяет уже созданный перед этапом 3 небольшой клиент над нативным `fetch`; сервер остаётся синхронным FastAPI + SQLAlchemy + SQLite WAL. Экранные действия вызывают узкие доменные ручки, импорт списка выполняется одной транзакцией, а изменения активной программы записываются в один журнал с обратными данными. Канонические проект, паспорт, программа и раскладка не копируются в `localStorage` или `WizardDraft.state`.

**Tech Stack:** React 19 · TypeScript 5.9 · Vite 8 · нативный `fetch` · FastAPI · Pydantic 2 · SQLAlchemy 2 · Alembic · SQLite WAL · стандартные `re`, `urllib`, `uuid`, `datetime`

## Global Constraints

- Tentex работает локально, офлайн и для одного пользователя на установку.
- Целевая версия Python — **3.13**; локальная 3.14 допустима для этапов 0–4.
- Все русские тексты интерфейса остаются русскими; идентификаторы и JSON API — английскими.
- SQLite остаётся в WAL; миграции Alembic — единственный способ менять схему.
- Не добавлять зависимости фронтенда или бэкенда: HTTP — нативный `fetch`, импорт текста — стандартная библиотека Python.
- Не добавлять загрузку или чтение файлов, OCR, страницы, фрагменты, привязки, ответы, Уроки, занятия, карточки, План, фонового воркера или внешние модели.
- Не хранить на фронтенде параллельную копию Project, GoalPassport, ProgramNode или WorkspaceState. `localStorage` остаётся только для темы и сворачивания глобальной панели.
- Пустое состояние не является ошибкой. Программа без материалов корректна; темы без материала показываются нейтрально.
- Покрытие не изображается полосой прогресса и не окрашивается как проблема (FR-D17).
- TDD и новый тестовый фреймворк не вводятся. Остаются сквозные исполняемые проверки `check_stage2.py` и `check_stage3.py` плюс ручной браузерный маршрут.
- После любой правки фронтенда перед браузерной проверкой выполнить `docker compose restart web`.
- Не восстанавливать и не перезаписывать посторонние изменения в грязном worktree.

---

## 0. Обязательная подготовительная вертикаль

До запуска этого плана должна быть выполнена задача из `docs/superpowers/prompts/2026-08-06-pre-stage-3-project-settings.md`. Её результат — настоящий `/projects/:projectId/settings`, `PUT /api/projects/{project_id}/settings`, базовый `frontend/src/api/projects.ts`, единые типы `Project.color` и `TargetOutcome`, проектные ссылки и обновлённая документация.

Этап 3 не переписывает этот экран и не создаёт второй клиент. Он только расширяет существующий `projects.ts`, сохраняет рабочие ссылки на Настройки и проверяет, что готовая вертикаль не сломалась. Если любой из перечисленных результатов отсутствует, сначала выполняется подготовительная задача; временная заглушка внутри этапа 3 не допускается.

---

## 1. Критика исходной формулировки этапа и принятые решения

| Противоречие или риск | Почему это сломает следующий этап | Решение в этом плане |
|---|---|---|
| Этап требует сохранить источники учебниковой ветки, но одновременно запрещает загрузку файлов до этапа 5 | `File` браузера не переживает перезапуск; метаданные без сохранённого файла — фиктивный Material | На этапе 3 учебниковая ветка сохраняет настоящий черновик, паспорт, модули и ручную программу, но не создаёт активный проект. Источники и финальная активация этой ветки переходят в этап 5 |
| Настройки проекта раньше находились внутри этапа 3, хотя их форма и контракт нужны всем живым проектным экранам | Этап смешивал отдельную вертикаль формы с мастером, списком, деревом и рабочей областью; общий клиент и типы появлялись слишком поздно | Выполнить Настройки отдельной подготовительной задачей; этап 3 только переиспользует готовые экран, PUT-контракт, API-клиент и типы |
| Критерий говорит «удаление темы», а FR-G9.1/FR-G11 запрещают терять накопленную работу | Физический `DELETE` позже оборвёт привязки, карточки, конспекты и историю | «Удалить из списка» меняет `is_in_current_program=false` для поддерева. Возврат и undo восстанавливают прежние значения; строка из БД не удаляется |
| Текущий Program выбирает экзамен/учебник по `?mode=textbook` | URL может открыть экзаменационный интерфейс для учебникового проекта и наоборот | Вариант Программы и Рабочей области берётся только из `project.workspace_variant`; параметр `mode` удаляется |
| Рабочая область сохраняет заметки, конспекты и снятые привязки в `localStorage` | Это скрытая вторая база без миграций, ссылочной целостности и будущего общего undo | На этапе 3 сервер хранит только выбранный узел, раскрытые ветви, ширину дерева, группы вкладок и веса. Неподдержанные доменные вкладки показывают честное пустое состояние или недоступны |
| Карточка проекта и `Project.color` используют разные типы: UI ждёт `1..8`, API хранит произвольную строку | Реальный ответ API создаст несуществующий CSS-токен и потеряет знак проекта | Миграцией привести `Project.color` к `int | null` с диапазоном 1–8; для старых неизвестных строк поставить `1` |
| Текущий Program меняет только один `sort_order` и допускает дубликаты позиций | Перетаскивание и изменение вложенности быстро дадут нестабильный порядок | Отдельное действие move атомарно нормализует старых и новых соседей и повторно проверяет глубину/цикл |
| Автосохранение мастера может отправить несколько PUT одновременно | Более медленный старый ответ способен затереть новую локальную ревизию или породить ложный 409 | Сохранения идут через одну очередь, каждое использует последнюю серверную `revision`; импорт и активация сначала дожидаются очереди |
| Глобальная панель и реальные экраны продолжают показывать mock-покрытие, задачи, темы, ответы и материалы | Пользователь не отличит сохранённое состояние от демонстрации | На поверхностях этапа 3 все mock-массивы удаляются. Данные будущих этапов скрываются или заменяются нейтральным пустым состоянием с точным следующим шагом |

После согласования первая реализационная правка уточняет эти границы в `PLAN.md`, `SCREENS.md` и `docs/architecture/stage-2-core.md`; до согласования исходные документы не переписываются.

## 2. Что считается готовым

### 2.1. Основной сквозной путь

1. Пользователь открывает `/projects/new`, выбирает экзамен и вставляет текст списка.
2. После первого осмысленного ввода создаётся серверный черновик; шаг, паспорт и сырой текст сохраняются с ревизией.
3. Сервер распознаёт вопросы, задачи или билеты и одной транзакцией создаёт ProgramNode с `origin_kind=import`.
4. Перезагрузка страницы возобновляет тот же шаг с тем же импортированным деревом.
5. «Создать проект» дожидается автосохранения, активирует черновик и открывает первый изучаемый узел в `/projects/:projectId`.
6. `/projects` показывает реальный активный проект; порядок, архив и восстановление переживают перезапуск.
7. `/projects/:projectId/program` добавляет, переименовывает, перемещает и меняет уровень узлов; удаление из программы отменяется после перезагрузки.
8. Рабочая область показывает то же дерево и восстанавливает только серверную раскладку.

Готовые до этапа 3 Настройки продолжают открываться из Программы и Рабочей области и служат регрессионной проверкой общего `ProjectDetail`.

### 2.2. Честная граница учебниковой ветки

- `/projects/new` позволяет создать или возобновить учебниковый черновик, заполнить паспорт, выбрать модули и собрать ручную программу.
- В источниках нет demo-файлов и кнопки, притворяющейся загрузкой.
- Итоговая кнопка сохраняет черновик и возвращает к Проектам; рядом прямо сказано, что подключение источников и активация появятся вместе с загрузкой на этапе 5.
- Черновик не попадает в список активных проектов, но предлагается для возобновления при следующем входе в мастер.

### 2.3. Явно не входит

- чтение TXT/DOCX/CSV/MD как файлов: на этапе 3 импортируется только вставленный текст;
- готовые ответы и сопоставление `вопрос → ответ`: этап 4;
- загрузка учебных материалов, быстрый анализ и ProjectMaterial: этап 5;
- построение по оглавлению и проход 1: этап 7;
- модельная группировка, помощник и диф программы: этап 7;
- покрытие, привязки, источники темы: этап 8;
- конспекты, попытки, повторения и План: этап 9;
- redo: NFR-5 требует undo; обратное повторение действия не добавляется без отдельной потребности.

## 3. Файлы и ответственность

### Создать

- `backend/app/projects/importer.py` — чистый разбор вставленного экзаменационного списка без доступа к БД.
- `backend/migrations/versions/20260806_0003_stage3_actions.py` — `project_action_log` и индекс журнала; миграция цвета уже выполнена подготовительной вертикалью.
- `backend/scripts/check_stage3.py` — один сквозной smoke-check этапа 3, переиспользующий `ApiServer` и `request` из `check_stage2.py`.
- `frontend/src/hooks/useWizardDraft.ts` — загрузка, последовательное автосохранение, конфликт ревизий, активация и удаление черновика для обеих веток.
- `docs/architecture/stage-3-live-projects.md` — реализованный поток, новые ручки, журнал undo и честные границы этапа.

### Изменить

- `PLAN.md` — исправить учебниковую границу, считать Настройки завершённой подготовительной вертикалью, уточнить «удаление» как вывод из текущей программы.
- `SCREENS.md` — описать реальные loading/error/empty/conflict-состояния четырёх поверхностей этапа и переходный итог учебникового черновика; готовый раздел Настроек не переписывать.
- `backend/app/models.py` — добавить только `ProjectActionLog`; тип цвета уже выровнен.
- `backend/app/projects/schemas.py` — импорт, порядок проектов, move/subtree/remove/undo и сводка последнего отменяемого действия.
- `backend/app/projects/service.py` — транзакционные пользовательские действия и запись обратных данных.
- `backend/app/projects/router.py` — новые узкие маршруты.
- `backend/scripts/check_stage2.py` — только если числовой цвет требует обновить существующий payload проверки.
- `frontend/src/api/projects.ts` — расширить готовый `request/getProject/updateProjectSettings` функциями мастера, списка, программы и раскладки.
- `frontend/src/screens/ProjectWizard.tsx` — пустые начальные значения, реальный черновик, вставленный список, импорт, активация и возобновление.
- `frontend/src/screens/TextbookWizard.tsx` — реальный draft-only путь без фиктивных источников и генерации.
- `frontend/src/screens/Projects.tsx` — список, порядок, архив/восстановление и состояния API.
- `frontend/src/screens/Program.tsx` — серверный вариант и дерево, реальные ручные действия и undo; mock-AI убрать.
- `frontend/src/screens/ProjectWorkspace.tsx` — серверный ProjectDetail и WorkspaceState без доменных данных в `localStorage`.
- `frontend/src/app/AppLayout.tsx` — убрать mock-покрытие, темы, задачи, библиотечные числа и названия моделей.
- `frontend/src/app/CommandPalette.tsx` — искать реальные проекты и не вести project-specific экраны на demo id.
- `frontend/src/app/screens.ts` — убрать demo-ID из реальных переходов; реестр путей оставить единственным.
- `frontend/src/styles/layout.css` — только стили новых реальных состояний через существующие токены; стили Настроек не дублировать.

### Оставить без изменений

- `Material` и `ProjectMaterial`: таблицы готовы, но без загрузки их нельзя честно заполнить.
- `frontend/src/screens/workspaceDemo.ts`: временно остаётся только для ещё не оживлённых Lessons; ProjectWorkspace больше его не импортирует.
- `frontend/src/screens/Materials.tsx`, `Plan.tsx`, `cards/`, `lessons/`: их mock-сценарии не становятся частью этапа 3 и не получают ссылки из реального базового пути.

## 4. Контракты API

Существующие десять действий этапа 2 сохраняются. Добавляются только действия, у которых есть вызывающий экран.

| Метод и путь | Назначение | Атомарность/ограничение |
|---|---|---|
| `DELETE /api/wizard-drafts/{project_id}` | Явно удалить подтверждённый черновик | Только `status=draft`, каскадом удаляются его паспорт и программа |
| `POST /api/wizard-drafts/{project_id}/exam-import` | Разобрать сырой текст и заменить программу черновика | Проверяет `expected_revision`, полностью валидирует результат, затем заменяет дерево и увеличивает revision в одной транзакции |
| `PUT /api/projects/order` | Сохранить порядок активных карточек | Принимает каждый active id ровно один раз, нормализует `0..n-1` |
| `POST /api/projects/{project_id}/archive` | Перевести active в archived | Обновляет `status_changed_at`; повторный вызов идемпотентен |
| `POST /api/projects/{project_id}/restore` | Вернуть archived/completed в active | Ставит позицию после текущих активных; повторный вызов идемпотентен |
| `POST /api/projects/{project_id}/program-nodes/{node_id}/move` | Перенести узел в parent/position | Проверяет проект, цикл и глубину; перенумеровывает обе группы соседей |
| `POST /api/projects/{project_id}/program-nodes/{node_id}/merge` | Структурно объединить похожий узел с выбранной целью | Переносит детей в target, source выводит из текущей программы, обе строки сохраняет |
| `POST /api/projects/{project_id}/program-nodes/{node_id}/target-level` | Уровень цели для узла или поддерева | `include_descendants=true` реализует FR-G25 одной транзакцией |
| `POST /api/projects/{project_id}/program-nodes/{node_id}/remove` | Убрать поддерево из текущей программы | Меняет только `is_in_current_program`; физические строки остаются |
| `POST /api/projects/{project_id}/program-nodes/{node_id}/restore` | Вернуть поддерево в текущую программу | Восстанавливает узлы и пишет новое отменяемое действие |
| `POST /api/projects/{project_id}/actions/undo` | Отменить последнее неотменённое действие программы | Применяет `inverse_data`, ставит `undone_at`, возвращает новое дерево и следующий доступный undo |

### 4.1. Импорт

Запрос:

```json
{
  "expected_revision": 3,
  "exam_format": "tickets",
  "raw_text": "Билет 1\n1. Реляционная модель\n2. Задача: нормализовать отношение"
}
```

Ответ:

```json
{
  "revision": 4,
  "counts": { "tickets": 1, "questions": 1, "tasks": 1 },
  "warnings": [],
  "program_nodes": [
    { "node_type": "section", "exam_kind": "ticket", "title": "Билет 1", "sort_order": 0 },
    { "node_type": "topic", "exam_kind": "question", "title": "Реляционная модель", "sort_order": 0 },
    { "node_type": "topic", "exam_kind": "task", "title": "Нормализовать отношение", "sort_order": 1 }
  ]
}
```

Правила `importer.py`:

- нормализовать CRLF/LF, обрезать пробелы и игнорировать пустые строки;
- распознавать маркеры `1.`, `1)`, `1.2.`, `-`, `—`, `*`, `•`;
- строку без нового маркера присоединять к предыдущему пункту как продолжение, а не создавать ложную тему;
- для `questions` создавать плоские `topic + question`;
- для `questions_tasks` заголовки `Вопросы`/`Задачи` меняют текущий тип, а явные префиксы `Задача:`/`Задание:` имеют приоритет; без признака использовать `question`;
- для `tickets` заголовок `Билет`, `Билет №`, `Билет #` создаёт `section + ticket`, вложенные пункты — `topic + question/task`;
- билет без пунктов и формат tickets без заголовка билета отклонять с 422;
- одинаковые формулировки не удалять молча: сохранить и вернуть предупреждение с номерами;
- ограничить сырой текст 1 000 000 символов и требовать хотя бы один изучаемый узел;
- корни и дети получают плотный `sort_order` с нуля, `origin_kind=import`, `origin_note="Вставленный текст"`.

### 4.2. Журнал действий

`project_action_log` хранит:

- `id: UUID`, `project_id: UUID`;
- `action_type: str` из реально реализованных значений `node_create`, `node_update`, `node_move`, `node_merge`, `target_level_subtree`, `node_remove`, `node_restore`;
- `target_title: str` для понятной подписи кнопки undo;
- `inverse_data: JSON` — только прежние значения изменённых строк и их id;
- `created_at`, `undone_at | null`.

Никаких command bus, registry или универсального event sourcing. `undo_last_project_action()` содержит один явный `match action_type`; следующий этап добавляет ветку только вместе с новым отменяемым действием.

`ProjectDetail` и `WizardDraftDetail` получают `latest_undoable_action: {id, action_type, target_title, created_at} | null`, поэтому undo остаётся доступен после перезагрузки и в ручном редакторе учебникового черновика. Все мутации программы возвращают один точный `ProgramChangeResult {changed_node, program_nodes, latest_undoable_action}`; `changed_node` равен созданному/изменённому узлу либо `null` для группового undo. Отдельные экраны не угадывают последствия локально.

Undo создания не выполняет физический `DELETE`: созданное поддерево выводится из текущей программы. Это оставляет безопасную семантику, когда на следующих этапах у узла уже могут появиться ответы, привязки или карточки.

## 5. Порядок реализации

### Task 1: Зафиксировать границу этапа в документах

**Files:**
- Modify: `PLAN.md`
- Modify: `SCREENS.md`
- Create: `docs/architecture/stage-3-live-projects.md` (каркас, окончательные факты дописать в Task 9)

**Produces:** однозначная граница между этапами 3, 4 и 5; пять обязательных пунктов для Проектов, обеих веток Мастера, Программы и Рабочей области без повторного проектирования готовых Настроек.

- [ ] В `PLAN.md` заменить обещание сохранённых источников учебниковой ветки на draft-only результат без источников и активации до этапа 5.
- [ ] В `PLAN.md` зафиксировать Настройки как завершённую подготовительную вертикаль и убрать их реализацию из состава этапа 3.
- [ ] В `PLAN.md` заменить «удаление темы» на «вывод поддерева из текущей программы с undo».
- [ ] В `SCREENS.md` для каждой поверхности дописать loading, API error, 404, 409 revision conflict, пустое состояние и переход после успешного действия.
- [ ] В `SCREENS.md` явно убрать из этапа 3 настоящие ответы, материалы, покрытие, конспекты и попытки.
- [ ] Создать заголовок архитектурного документа с перечнем утверждённых границ и ссылкой на этот план.
- [ ] Проверить prerequisite: настоящий route Настроек зарегистрирован, `PUT /settings` проходит через restart, `projects.ts` содержит общий `request<T>()`, цвет равен `int | null`, а `GoalLevelValue` совпадает с `TargetOutcome`. Если нет — сначала выполнить подготовительный промпт, не чинить это попутно.
- [ ] Проверить формулировки поиском: `rg -n "этапа 5|источник|удален|Настройки|409|localStorage" PLAN.md SCREENS.md docs/architecture/stage-3-live-projects.md`.
- [ ] Commit: `docs: define stage 3 live-data boundary`.

### Task 2: Расширить единый клиент API и добавить очередь черновика

**Files:**
- Modify: `frontend/src/api/projects.ts`
- Create: `frontend/src/hooks/useWizardDraft.ts`

**Interfaces:**
- Extends: готовые `request<T>`, `getProject` и `updateProjectSettings`, не создавая второй transport/helper.
- Produces: `listProjects`, `listWizardDrafts`, `getWizardDraft`, `createWizardDraft`, `saveWizardDraft`, `discardWizardDraft`, `importExamProgram`, `activateWizardDraft`, `saveProjectOrder`, `archiveProject`, `restoreProject`, program mutation functions and `saveWorkspaceState`.
- Produces: `useWizardDraft({templateKey, workspaceVariant})` with `detail`, `saving`, `error`, `conflict`, `queueSave(payload)`, `flush()`, `importExam(rawText, format)`, `activate()`, `discard()`.

- [ ] Проверить готовый `request<T>(path, init)` и расширить его только если новый фактический формат ошибки этого требует; второй helper и retry не добавлять.
- [ ] Описать API types по Pydantic-схемам; даты остаются ISO-строками, UUID — `string`.
- [ ] В загрузочных эффектах использовать `AbortController`; abort не переводить в ErrorState.
- [ ] В hook держать одну Promise-очередь: новый save отправляется только после предыдущего, payload получает последнюю подтверждённую revision.
- [ ] Debounce 400 мс использовать только для редактирования полей; переход шага, импорт, выход и активация вызывают `flush()`.
- [ ] При 409 остановить очередь, показать конфликт с действиями «Загрузить серверную версию» и «Остаться на странице»; автоматического force overwrite нет.
- [ ] Не писать Project/GoalPassport/ProgramNode в `localStorage`.
- [ ] Run: `npm run typecheck`.
- [ ] Commit: `feat: extend project API client with draft queue`.

### Task 3: Реализовать импорт экзамена и настоящий экзаменационный мастер

**Files:**
- Create: `backend/app/projects/importer.py`
- Modify: `backend/app/projects/schemas.py`
- Modify: `backend/app/projects/service.py`
- Modify: `backend/app/projects/router.py`
- Modify: `frontend/src/screens/ProjectWizard.tsx`
- Modify: `frontend/src/screens/TextbookWizard.tsx` only to receive the draft hook contract; full branch is Task 7

**Interfaces:**
- Produces: `parse_exam_program(raw_text: str, exam_format: ExamFormat) -> ParsedExamProgram`.
- Produces: `POST /api/wizard-drafts/{project_id}/exam-import` and `DELETE /api/wizard-drafts/{project_id}`.

- [ ] Написать чистый parser по правилам §4.1; ParsedNode хранит временный parent index, node_type, exam_kind, title и sort_order.
- [ ] В сервисе импорта проверить draft/revision, разобрать весь текст до мутации, удалить прежнее дерево черновика от листьев к корням, создать новое дерево, увеличить revision и вернуть counts/warnings/nodes в одной транзакции.
- [ ] Добавить удаление только draft-проекта; active/archived дают 409.
- [ ] Убрать `DEMO_FILES`, `REVIEW_ITEMS`, демонстрационные значения предмета/даты/преподавателя и кнопки «Добавить пример».
- [ ] На шаге ввода оставить активным только «Вставить текст». «Файлы» показать недоступным с причиной «Загрузка файлов появится на этапе 5»; ответы — «этап 4», учебные материалы — «этап 5».
- [ ] Форматы `questions`, `questions_tasks`, `tickets` сделать проходимыми; `unknown` оставить видимым, но недоступным до материалов этапа 5.
- [ ] Создавать draft при переходе к первому осмысленному вводу; сохранять в `state` только raw text, input mode, выбранный format и UI-предупреждения, не копируя паспорт или program nodes.
- [ ] На шаге проверки строить список из `detail.program_nodes`; inline-редактирование вызывает существующий PATCH на blur, а не на каждый символ.
- [ ] Предупреждение о расхождении ожидаемого и найденного количества считать по настоящему `counts` ответа импорта; расхождение не блокирует активацию и ведёт к полю expected count.
- [ ] Преобразовать wizard значения в API: `zero→beginner`, `partial→familiar`, `refresh→refreshing`; `orient→awareness`, `understand→understanding`, `answer→application`, `master→mastery`; `mixed→theory_and_practice`.
- [ ] Сохранять `purpose=exam`, имя `${subject} — экзамен` и модули пресета `plan`, `cards`, `repetitions`, `oral_answers`; сырой текст не использовать как название или описание проекта.
- [ ] Перед активацией выполнить `flush()`, при необходимости импорт, затем activate с актуальной revision; после ответа перейти на `/projects/{id}?topic={firstStudyNodeId}`.
- [ ] При входе в мастер загрузить summaries черновиков и предложить «Продолжить» или «Начать новый»; свободный трек остаётся недоступен.
- [ ] Выход с изменённым draft предлагает «Сохранить и выйти»; отдельное подтверждённое действие «Удалить черновик» вызывает DELETE.
- [ ] Run: `cd backend && python -m ruff check .`.
- [ ] Run: `npm run typecheck`.
- [ ] Commit: `feat: create exam projects from pasted lists`.

### Task 4: Оживить список Проектов и жизненный цикл

**Files:**
- Modify: `backend/app/projects/schemas.py`
- Modify: `backend/app/projects/service.py`
- Modify: `backend/app/projects/router.py`
- Modify: `frontend/src/screens/Projects.tsx`

**Interfaces:**
- Produces: `PUT /api/projects/order`, `POST /archive`, `POST /restore`.
- Modifies: `ProjectSummary` includes `status_changed_at`.

- [ ] Реализовать сохранение порядка: payload не содержит дублей и совпадает с множеством active id; иначе 422.
- [ ] Реализовать archive/restore с идемпотентностью и `status_changed_at`; завершённый проект разрешить восстановить как active.
- [ ] Загрузить реальные проекты с LoadingState/ErrorState и retry; разделить active и archived/completed по status.
- [ ] При drag-and-drop сначала переставить карточки оптимистично, вызвать один PUT, при ошибке вернуть прежний порядок и показать локальную ошибку рядом с сеткой.
- [ ] Добавить Menu активной карточки с «В архив» и ConfirmDialog; архивная строка получает рабочее «Вернуть в работу».
- [ ] Кнопку «Повторить» оставить видимой, но disabled с пояснением до этапа 9; не вести в mock Cards.
- [ ] Карточки пустого состояния ведут в `/projects/new?track=exam` и `/projects/new?track=textbook`; свободный шаблон недоступен с причиной.
- [ ] Run: `npm run typecheck`.
- [ ] Commit: `feat: connect project dashboard to API`.

### Task 5: Сделать Program настоящим редактором с единым undo

**Files:**
- Create: `backend/migrations/versions/20260806_0003_stage3_actions.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/projects/schemas.py`
- Modify: `backend/app/projects/service.py`
- Modify: `backend/app/projects/router.py`
- Modify: `backend/scripts/check_stage2.py`
- Modify: `frontend/src/screens/Program.tsx`

**Interfaces:**
- Produces: move, structural merge, subtree target level, remove, restore and undo routes from §4.
- Produces: `ProgramChangeResult {changed_node: ProgramNodeRead | null, program_nodes: ProgramNodeRead[], latest_undoable_action: ActionLogRead | null}` from create/PATCH/move/merge/target/remove/restore/undo.
- Modifies: `ProjectDetail` and `WizardDraftDetail` include `latest_undoable_action`.

- [ ] Миграцией создать только `project_action_log` и индекс `(project_id, created_at)`; нормализацию цвета не повторять. Добавить соответствующую ORM-модель.
- [ ] Добавить helpers `_subtree_ids`, `_normalize_siblings` и `_record_action`; не создавать repository/action registry.
- [ ] Для create/update/move/target/remove/restore сохранять минимальные прежние поля в `inverse_data` в той же транзакции, что и изменение.
- [ ] В move сначала вычислить итоговый parent map и вызвать существующую проверку глубины/циклов, затем плотно перенумеровать старых и новых соседей.
- [ ] В merge перенести детей source к target с сохранением порядка, вывести source из текущей программы и записать прежних родителей/порядок/флаги для undo; связанные сущности не переносятся и не удаляются.
- [ ] Remove применять ко всему поддереву через `is_in_current_program=false`; `is_archived` не использовать как удаление.
- [ ] Undo выбирать последнее `undone_at IS NULL`, явно разбирать action_type через `match`, применять обратные данные и ставить `undone_at` в одной транзакции.
- [ ] Обновить `check_stage2.py`: id созданного раздела/темы брать из `response["changed_node"]["id"]`; остальной сценарий этапа 2 не менять.
- [ ] В Program загружать ProjectDetail по route id и выбирать экзаменационное/учебниковое представление по `workspace_variant`, не по query.
- [ ] Один helper строит дерево из плоских API nodes; неизвестный parent переводит экран в ErrorState, а не молча делает корнем.
- [ ] Реализовать add, duplicate через обычный create, rename on blur, type/exam_kind, target level по поддереву, move up/down, indent/outdent, structural merge, remove/restore и undo.
- [ ] Перед add/duplicate на клиенте сравнить `title.trim().toLocaleLowerCase("ru")` с загруженными узлами проекта: точное совпадение показать как предупреждение с действиями «Объединить» и «Всё равно добавить». Семантический поиск похожих тем не имитировать до поискового этапа.
- [ ] Убранные exam-узлы не превращать в столбец/фильтр: показывать отдельный Disclosure «Убрано из списка» только когда такие узлы есть; у каждой строки одно действие «Вернуть». Для textbook использовать предусмотренный фильтр «Вне текущей программы».
- [ ] Все disabled-операции объяснить: модельная группировка и помощник скрыты до этапа 7; фиктивные counts «эталон/материалы/план» убрать.
- [ ] В project navigation оставить рабочими Рабочую область, Программу и Настройки; Материалы, План, Карточки и Уроки показать недоступными с указанием своего этапа, а не вести реальный project id в mock-экран.
- [ ] EmptyState предлагает импортировать список для exam или добавить первую тему вручную для textbook draft.
- [ ] После каждого успешного действия использовать серверный ответ как новое состояние; при ошибке не оставлять оптимистическую копию.
- [ ] Run: `cd backend && python -m ruff check .`.
- [ ] Run: `npm run typecheck`.
- [ ] Commit: `feat: persist program edits with undo`.

### Task 6: Перевести базовую Рабочую область на ProjectDetail и WorkspaceState

**Files:**
- Modify: `frontend/src/screens/ProjectWorkspace.tsx`
- Modify: `frontend/src/screens/workspaceDemo.ts` only if exports must be separated for Lessons
- Modify: `frontend/src/styles/layout.css`

**Consumes:** `getProject`, `saveWorkspaceState`, `ProjectDetail`.

- [ ] Удалить `resolveWorkspaceProject` из ProjectWorkspace; route id всегда загружает API, 404 показывает ErrorState с переходом к Проектам.
- [ ] Построить WorkspaceNode только из ProgramNode: number, structural type, title, children, `no-material`; не создавать demo-answer/source/attempt/conspect.
- [ ] Выбрать первый `topic/subpoint` в текущей программе; query `topic` имеет приоритет, если id принадлежит проекту.
- [ ] Восстановить серверные selected/expanded/tree width/groups/weights; неизвестные/вне программы id отфильтровать и сохранить исправленную раскладку.
- [ ] Debounce PUT раскладки на 400 мс и отправлять на unmount/переход через явный flush там, где возможно; одна очередь не допускает перестановки ответов.
- [ ] Убрать из `localStorage` notes, noteRepeats, conspects, removedBindingIds, selectedSourceIds и selectedLessonIds.
- [ ] Для exam оставить базовые вкладки «Ответ» и «Материал» с EmptyState и точными переходами: ответы — этап 4, материалы — этап 5. Для textbook оставить «Источник» с нейтральным отсутствием материала.
- [ ] Не показывать источники, качество, pass2 progress, попытки, «изучено», чат и Уроки из demo.
- [ ] В нижней проектной навигации оставить рабочими Программу и Настройки; переходы в mock Материалы/План/Карточки/Уроки отключить до их этапов.
- [ ] Сохранить работающие tree search, раскрытие, выбор узла, клавиатурный focus и resize до трёх групп.
- [ ] Run: `npm run typecheck`.
- [ ] Commit: `feat: persist base workspace layout`.

### Task 7: Подключить учебниковый мастер как честный возобновляемый черновик

**Files:**
- Modify: `frontend/src/screens/ProjectWizard.tsx`
- Modify: `frontend/src/screens/TextbookWizard.tsx`
- Modify: `frontend/src/screens/Program.tsx`

**Consumes:** общий draft hook, существующие ProgramNode create/PATCH/move/remove/undo.

- [ ] Удалить `INITIAL_SOURCES`, `INITIAL_PROGRAM`, mock generation, progress, стоимость, помощника и предложения-дифы.
- [ ] Шаг 1 показывает EmptyState: файлы ещё не загружаются; основное действие «Собрать программу вручную», вторичное «Вернуться к выбору».
- [ ] Сохранить в Project/GoalPassport реальные name, subject, scope, goal, starting level/knowledge, target outcome, success criterion, important, excluded, deadline, rhythm, study format и modules.
- [ ] Шаг ручной Программы использует те же серверные узлы и операции, что активный Program; отдельной копии дерева в state нет.
- [ ] Сохранить три представления учебниковой программы «Дерево / Текст / Вопросы» как чистые проекции одних ProgramNode; поиск и фильтры не создают копий и не меняют серверные данные.
- [ ] После перезагрузки восстановить current/max step и выбранный узел из серверного draft/UI state.
- [ ] Итог показывает только реально сохранённые паспорт, модули и дерево; блока «Источники сохранены» нет.
- [ ] Основная кнопка «Сохранить черновик и выйти» делает flush и ведёт в Проекты; activate не вызывается.
- [ ] На входе в мастер этот draft доступен через «Продолжить учебниковый черновик».
- [ ] Run: `npm run typecheck`.
- [ ] Commit: `feat: persist textbook planning draft`.

### Task 8: Убрать оставшиеся ложные данные с живого пути

**Files:**
- Modify: `frontend/src/app/AppLayout.tsx`
- Modify: `frontend/src/app/CommandPalette.tsx`
- Modify: `frontend/src/app/screens.ts`
- Modify: `frontend/src/screens/Projects.tsx`
- Modify: `frontend/src/screens/Program.tsx`
- Modify: `frontend/src/screens/ProjectWorkspace.tsx`

- [ ] Удалить DEMO_COVERAGE, DEMO_RECENT_TOPICS и DEMO_TASKS; покрытие и последние темы скрыть до появления данных, фон показывает «Фон свободен».
- [ ] Убрать фиктивные 14 файлов/1,8 ГБ, mock model names, bot status и backup date; оставить только факты, которые умеет подтвердить `/api/health`, либо нейтральное «не настроено».
- [ ] В CommandPalette заменить DEMO_PROJECTS настоящим `listProjects`, убрать DEMO_FILES до этапа 5 и исключить project-specific `SCREENS` без реального project id; глобальные экраны продолжают искаться.
- [ ] Обновить подпись бренда «этап 1» на нейтральную версию без номера этапа.
- [ ] Убрать использование DEMO_PROJECT_ID/DEMO_TEXTBOOK_PROJECT_ID из реальных переходов; константы можно оставить только если ещё нужны изолированным прототипам вне пути этапа 3.
- [ ] Поискать ложные данные: `rg -n "DEMO_|mock|Появится вместе с API|данные выдуманные|localStorage" frontend/src/app frontend/src/screens/ProjectWizard.tsx frontend/src/screens/TextbookWizard.tsx frontend/src/screens/Projects.tsx frontend/src/screens/Program.tsx frontend/src/screens/ProjectWorkspace.tsx`.
- [ ] Для каждого совпадения либо удалить его, либо подтвердить, что оно относится только к экрану будущего этапа и недоступно из живого пути.
- [ ] Run: `npm run typecheck`.
- [ ] Commit: `chore: remove stage 3 demo fallbacks`.

### Task 9: Сквозная проверка, браузер и архитектурный итог

**Files:**
- Create: `backend/scripts/check_stage3.py`
- Modify: `docs/architecture/stage-3-live-projects.md`
- Modify: `README.md` only to add the stage 3 smoke command if stage 3 is accepted as complete

- [ ] В `check_stage3.py` на временной БД проверить три импорта: плоские вопросы, вопросы+задачи, билеты с многострочным пунктом и предупреждением о дубле.
- [ ] Проверить 409 устаревшей ревизии, возобновление после restart, активацию экзаменационного проекта и отсутствие draft в active list.
- [ ] Создать второй active project, проверить order, archive, restart и restore.
- [ ] Проверить rename, move, target level subtree, remove, restart, наличие latest undo, undo и восстановленное дерево.
- [ ] Проверить settings и workspace layout после ещё одного restart; выполнить SQLite `foreign_key_check`, WAL и Alembic head.
- [ ] Run: `python backend/scripts/check_stage2.py`; expected: `stage 2 smoke check passed`.
- [ ] Run: `python backend/scripts/check_stage3.py`; expected: `stage 3 smoke check passed`.
- [ ] Run: `cd backend && python -m ruff check .`; expected: exit 0.
- [ ] Run: `npm run typecheck`; expected: exit 0.
- [ ] Run: `npm run build`; expected: exit 0.
- [ ] Run: `docker compose restart web`; expected: container restarts successfully.
- [ ] В браузере пройти exam questions и tickets, reload мастера, activation, reorder/archive/restore, все ручные операции Program, undo после reload, settings и workspace layout после reload.
- [ ] В браузере пройти textbook draft, reload и «Сохранить черновик и выйти»; убедиться, что active project не создан и demo-источники не появились.
- [ ] Дописать архитектурный документ фактическими маршрутами, таблицей action types, диаграммой потока и командами проверки.
- [ ] Обновить `README.md` только после всех свежих проверок.
- [ ] Commit: `docs: record stage 3 live project architecture`.

## 6. Ручные примеры для проверки импорта

### Отдельные вопросы

```text
1. Архитектура системы управления базами данных
2) Реляционная модель данных и её компоненты
- Транзакции и свойства ACID
```

Ожидание: три корневых `topic/question`, порядок `0..2`.

### Вопросы и задачи

```text
Вопросы
1. Уровни изоляции транзакций
2. Индексы и планы выполнения

Задачи
1. Нормализовать отношение до третьей нормальной формы
2. Составить SQL-запрос с группировкой
```

Ожидание: четыре корневых topic; первые два `question`, последние два `task`; искусственные разделы не создаются.

### Билеты

```text
Билет № 1
1. Реляционная модель данных
2. Задача: нормализовать отношение

Билет 2
1) Транзакции и свойства ACID,
   уровни изоляции и аномалии чтения
```

Ожидание: два `section/ticket`; у первого вопрос и задача, у второго один многострочный вопрос.

## 7. Финальный gate этапа

Этап 3 нельзя считать завершённым, если выполняется хотя бы одно условие:

- реальный route id получает подменённый demo-проект;
- Project/Program/Workspace восстанавливаются только из `localStorage`;
- мастер показывает «сохранены» для ответа или файла, которого нет в Material/ProjectMaterial;
- учебниковый draft активируется без сохранённого источника;
- удаление ProgramNode физически стирает строку;
- undo исчезает после перезапуска;
- drag-and-drop оставляет дубли `sort_order`;
- Program выбирает variant из query;
- на живом пути видны фиктивные метрики, источники, попытки, модели или фоновые задачи;
- `check_stage2.py`, `check_stage3.py`, ruff, typecheck или build не прошли свежим запуском.

## 8. Параллельная разведка главной идеи (не блокирует этап 3)

Разведку из `PLAN.md:90-105` не смешивать с production-кодом этапа 3. После основного вертикального среза выполнить отдельной короткой задачей:

1. Во временном окружении поставить PyMuPDF, не добавляя его в `backend/requirements.txt` до этапа 5.
2. Одноразовым скриптом прочитать первые 30 содержательных страниц методички, выделить блоки по заголовкам и отправить несколько размеров batch в один выбранный OpenAI-compatible endpoint через переменные окружения.
3. Записать в `docs/research/pass2-feasibility.md`: качество границ блоков, типовые промахи, приемлемый batch size, число предполагаемых вызовов и стоимость полного учебника с датой цены.
4. Удалить одноразовый скрипт; в production не переносить его парсер или клиент модели.

Эта разведка может изменить этапы 5/8, но не API проектов и программы этапа 3.
