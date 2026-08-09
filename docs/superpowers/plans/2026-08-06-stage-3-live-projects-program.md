# Stage 3 Live Projects and Program Implementation Plan

> Ревизия от 08.08.2026 после двух проходов сверки с `REQUIREMENTS.md` ред. 6,
> этапами 4–10, завершённой вертикалью Настроек и текущим кодом этапа 2.

> **Статус: выполнен 09.08.2026.** Фактический контракт и результаты проверок записаны в
> `docs/architecture/stage-3-live-projects.md`. Пункты Commit оставлены невыполненными намеренно:
> пользователь не просил создавать коммиты в грязном рабочем дереве.

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести создание проекта, список Проектов, Программу и базовую Рабочую область на единое серверное состояние, сохранив один полноценный демонстрационный проект как обычные записи SQLite. Экзаменационный проект проходит путь «вставленный список → возобновляемый черновик → импортированная программа → активация → рабочая область», а учебниковая ветка честно сохраняет паспорт и ручную программу как черновик до появления загрузки на этапе 5.

**Architecture:** React расширяет уже созданный перед этапом 3 клиент над нативным `fetch`; сервер остаётся синхронным FastAPI + SQLAlchemy + SQLite WAL. Все изменения дерева проходят через один модуль Program, сверяют `Project.program_revision`, атомарно нормализуют дерево и пишут версионированные обратные данные в общий журнал. Демонстрационный проект создаётся идемпотентным seed после миграций и дальше ничем не отличается от пользовательского: те же таблицы, маршруты и экраны, без fallback на TypeScript-массивы. Канонические проект, паспорт, программа и раскладка не копируются в `localStorage` или `WizardDraft.state`.

**Tech Stack:** React 19 · TypeScript 5.9 · Vite 8 · нативный `fetch` · FastAPI · Pydantic 2 · SQLAlchemy 2 · Alembic · SQLite WAL · стандартные `re`, `uuid`, `datetime`

## Global Constraints

- Tentex работает локально, офлайн и для одного пользователя на установку.
- Целевая версия Python — **3.13**; локальная 3.14 допустима для этапов 0–4.
- Все русские тексты интерфейса остаются русскими; идентификаторы и JSON API — английскими.
- SQLite остаётся в WAL; миграции Alembic — единственный способ менять схему.
- Не добавлять зависимости фронтенда или бэкенда: HTTP — нативный `fetch`, импорт текста — стандартная библиотека Python.
- Не добавлять загрузку или чтение файлов, OCR, страницы, фрагменты, привязки, ответы, Уроки, занятия, карточки, План, фонового воркера или внешние модели.
- Не хранить на фронтенде параллельную копию Project, GoalPassport, ProgramNode или WorkspaceState. `localStorage` остаётся только для темы и сворачивания глобальной панели.
- Единственное исключение из пустого старта — демонстрационное содержимое, записанное в настоящие таблицы. Специальный `demo`-ответ API, подмена route id и отдельный data source запрещены.
- Пустое состояние не является ошибкой. Программа без материалов корректна; темы без материала показываются нейтрально.
- Покрытие не изображается полосой прогресса и не окрашивается как проблема (FR-D17).
- TDD и новый тестовый фреймворк не вводятся. Остаются сквозные исполняемые проверки `check_stage2.py` и `check_stage3.py` плюс ручной браузерный маршрут.
- После любой правки фронтенда перед браузерной проверкой выполнить `docker compose restart web`.
- Перед изменением экранов Tasks 3–8 перечитать проектные `tentex-screens` и `tentex-ui-kit`; новые примитивы не создавать, пока подходящий не проверен на `/ui-kit`.
- Не восстанавливать и не перезаписывать посторонние изменения в грязном worktree.

---

## 0. Обязательная подготовительная вертикаль

До запуска этого плана должна быть выполнена задача из `docs/superpowers/prompts/2026-08-06-pre-stage-3-project-settings.md`. Её результат — настоящий `/projects/:projectId/settings`, `PUT /api/projects/{project_id}/settings`, базовый `frontend/src/api/projects.ts`, единые типы `Project.color` и `TargetOutcome`, проектные ссылки и обновлённая документация.

Этап 3 не перепроектирует этот экран и не создаёт второй клиент. Он расширяет существующий `projects.ts`, сужает только response PUT /settings до нужных форме project+passport, сохраняет поведение и рабочие ссылки на Настройки. Если любой prerequisite отсутствует, сначала выполняется подготовительная задача; временная заглушка внутри этапа 3 не допускается.

---

## 1. Критика исходной формулировки этапа и принятые решения

| Противоречие или риск | Почему это сломает следующий этап | Решение в этом плане |
|---|---|---|
| Этап требует сохранить источники учебниковой ветки, но одновременно запрещает загрузку файлов до этапа 5 | `File` браузера не переживает перезапуск; метаданные без сохранённого файла — фиктивный Material | На этапе 3 учебниковая ветка сохраняет настоящий черновик, паспорт, модули и ручную программу, но не создаёт активный проект. Источники и финальная активация этой ветки переходят в этап 5 |
| Настройки проекта раньше находились внутри этапа 3, хотя их форма и контракт нужны всем живым проектным экранам | Этап смешивал отдельную вертикаль формы с мастером, списком, деревом и рабочей областью; общий клиент и типы появлялись слишком поздно | Выполнить Настройки отдельной подготовительной задачей; этап 3 только переиспользует готовые экран, PUT-контракт, API-клиент и типы |
| Критерий говорит «удаление темы», а FR-G9.1/FR-G11 запрещают терять накопленную работу | Физический `DELETE` позже оборвёт привязки, карточки, конспекты и историю | «Удалить из списка» меняет `is_in_current_program=false` для поддерева. Возврат и undo восстанавливают прежние значения; строка из БД не удаляется |
| Текущий Program выбирает экзамен/учебник по `?mode=textbook` | URL может открыть экзаменационный интерфейс для учебникового проекта и наоборот | Вариант Программы и Рабочей области берётся только из `project.workspace_variant`; параметр `mode` удаляется |
| Рабочая область сохраняет заметки, конспекты и снятые привязки в `localStorage` | Это скрытая вторая база без миграций, ссылочной целостности и будущего общего undo | На этапе 3 сервер хранит только выбранный узел, раскрытые ветви, ширину дерева, группы вкладок и веса. Неподдержанные доменные вкладки показывают честное пустое состояние или недоступны |
| Несовпадение `Project.color` между UI и API было найдено старым планом | Реальный ответ API создавал бы несуществующий CSS-токен | Уже закрыто подготовительной вертикалью и миграцией `6c7ad9e40c82`; этап 3 только держит это регрессионной проверкой |
| Текущий Program меняет только один `sort_order` и допускает дубликаты позиций | Перетаскивание и изменение вложенности быстро дадут нестабильный порядок | Отдельное действие move атомарно нормализует старых и новых соседей и повторно проверяет глубину/цикл |
| Автосохранение мастера может отправить несколько PUT одновременно | Более медленный старый ответ способен затереть новую локальную ревизию или породить ложный 409 | Сохранения идут через одну очередь, каждое использует последнюю серверную `revision`; импорт и активация сначала дожидаются очереди |
| Текущие ручки ProgramNode разрешают менять draft, не увеличивая `WizardDraft.revision` | Вторая вкладка не увидит структурную правку и сможет затереть её старым состоянием мастера | Любая мутация сверяет общую для draft/active `program_revision`; для draft та же транзакция дополнительно увеличивает `WizardDraft.revision` |
| Универсальный PATCH сейчас принимает `parent_id`, `sort_order`, `is_in_current_program` и `origin_kind` | Клиент может обойти нормализацию соседей, журнал undo и правило П6 о происхождении | Пользовательский PATCH оставляет только редактируемые свойства. Структура меняется через move/remove/restore, уровень поддерева — через target-level, происхождение задаёт только сервер |
| Старый план предлагал реализовать merge до появления ответов, привязок и карточек | «Перенести детей и скрыть исходный узел» не определяет судьбу связанных данных и закрепляет неверную семантику до первого реального потребителя | На этапе 3 merge не реализуется. Точное совпадение формулировок даёт предупреждение; полноценное объединение проектируется там, где впервые появляются связанные данные |
| Требование убрать mock-данные лишало проект готового примера | Пустая установка хуже демонстрируется и не даёт проверить Рабочую область без прохождения мастера | Оставить один пример «Базы данных — экзамен», но записать его в Project, GoalPassport, ProgramNode и WorkspaceState. Seed использует фиксированные UUID, ничего не перезаписывает и не создаёт отдельной ветки чтения |
| Активные ProgramNode меняются без concurrency token | Две вкладки могут применить move к уже устаревшему дереву; будущий диф прохода 1 усугубит гонку | Добавить `Project.program_revision`. Каждая прямая мутация дерева требует `expected_program_revision`; общий undo отдельно сверяет sequence последнего действия, чтобы его контракт подошёл будущим Binding/Card actions |
| Журнал выбирает «последнее» по времени и не версионирует JSON | Равные timestamps дают неоднозначный undo, а изменение формата inverse_data сделает старые записи нечитаемыми | Журнал получает `sequence INTEGER PRIMARY KEY AUTOINCREMENT`, `phase`, `payload_version` и индекс. Sequence наружу выходит только как opaque token «отмени увиденное действие», не как доменный id |
| Все 409 отличаются только русским текстом | Клиенту придётся разбирать сообщение, чтобы отличить stale revision от readonly и неверного перехода статуса | Ошибки сохраняют `detail`, но получают стабильные `code` и `context`; UI ветвится по code, текст остаётся только для человека |
| Public create принимает `sort_order`, а PATCH — структуру | Даже после появления move клиент может оставить дубли порядка и обойти undo | Create принимает `parent_id` и `position`, PATCH — только свойства, move — только структуру. `sort_order` всегда вычисляется сервером и присутствует лишь в read-model |
| WizardDraftWrite принимает Project.sort_order | Два черновика могут активироваться с одной позицией, а мастер получает власть над dashboard-порядком | Удалить sort_order из ProjectDraftWrite; activate всегда назначает конец active-списка, единственный пользовательский writer порядка — PUT /projects/order |
| WizardDraftCreate независимо принимает template_key и workspace_variant | Можно создать exam-шаблон с textbook-интерфейсом, после чего экраны будут спорить о варианте | Create принимает только template_key; сервер выводит exam→exam, textbook→textbook, а free до этапа 7 отвечает unsupported_template |
| Скрытый узел можно вернуть под скрытого родителя или создать ребёнка скрытого узла | В дереве появятся невидимые сироты, а будущие покрытие и очередь дня начнут считать разные множества | Create/move требуют текущего видимого parent; restore разрешён только для верхнего скрытого корня, весь его subtree возвращается одной командой |
| `WorkspaceState` обновляет `Project.updated_at` при resize | Будущая «последняя активность» станет временем движения границы колонки | Сохранение раскладки меняет только WorkspaceState.updated_at; учебная активность позже получит собственную дату |
| PUT /settings возвращает полный ProjectDetail с деревом и layout | Изменение цвета начнёт передавать сотни узлов и свяжет Настройки с ростом Program | Вернуть узкий ProjectSettingsResult `{project, goal_passport}`; полный detail остаётся только у GET/activate |
| `origin_note` может превратиться в JSON со ссылками на файлы | Строковое поле не обеспечит ссылочную целостность для нескольких источников прохода 1 | На этапе 3 origin server-owned и `origin_note` остаётся только подписью. Этап 7 добавит отдельную связь provenance к Material/запуску, не меняя идентичность ProgramNode |
| `AGENTS.md` запрещает undo/new entities, а `PLAN.md` и NFR-5 относят журнал к этапу 3 | Реализация по разным документам даст два несовместимых объёма этапа | Первый commit этапа синхронизирует документы: в этапе 3 разрешён только ProjectActionLog и program_revision; остальные новые сущности остаются запрещены |
| Глобальная панель и живые экраны показывают mock-покрытие, задачи, ответы и материалы | Пользователь не отличит сохранённое состояние от демонстрации | Неподдержанные доменные mock-массивы удаляются. Пример содержит только реальные сущности этапа 3; ответы добавятся в него на этапе 4, материалы — на этапе 5 |

После согласования первая реализационная правка синхронизирует `AGENTS.md`, `PLAN.md` и `SCREENS.md`; исторический `stage-2-core.md` получает ссылку на фактически реализованный stage-3 contract только в финальном Task 9.

## 2. Что считается готовым

### 2.1. Основной сквозной путь

1. После первого запуска `/projects` уже показывает пример «Базы данных — экзамен»; его Project, GoalPassport, ProgramNode и WorkspaceState читаются теми же GET, что пользовательские данные.
2. Пользователь открывает `/projects/new`, выбирает экзамен и вставляет текст списка.
3. После первого осмысленного ввода создаётся серверный черновик; шаг, паспорт и сырой текст сохраняются с draft revision.
4. Сервер распознаёт вопросы, задачи или билеты и одной транзакцией создаёт ProgramNode с `origin_kind=import`, увеличивая draft и program revisions.
5. Перезагрузка страницы возобновляет тот же шаг с тем же импортированным деревом.
6. «Создать проект» дожидается очереди команд, активирует черновик и открывает первый изучаемый узел в `/projects/:projectId`.
7. `/projects` показывает пример и пользовательский active-проект; порядок, архив и восстановление переживают перезапуск.
8. `/projects/:projectId/program` добавляет, переименовывает, перемещает и меняет уровень узлов; удаление из программы отменяется после перезагрузки.
9. Рабочая область показывает то же дерево и восстанавливает только серверную раскладку.

Готовые до этапа 3 Настройки продолжают открываться из Программы и Рабочей области и служат регрессионной проверкой общего `ProjectDetail`.

### 2.2. Честная граница учебниковой ветки

- `/projects/new` позволяет создать или возобновить учебниковый черновик, заполнить паспорт, выбрать модули и собрать ручную программу.
- В источниках нет demo-файлов и кнопки, притворяющейся загрузкой.
- Итоговая кнопка сохраняет черновик и возвращает к Проектам; рядом прямо сказано, что подключение источников и активация появятся вместе с загрузкой на этапе 5.
- Черновик не попадает в список активных проектов, но предлагается для возобновления при следующем входе в мастер.
- Серверный инвариант активации остаётся source-neutral: ProjectMaterial не вшивается в общий `activate`. На этапе 5 учебниковый UI сначала проверит свои источники, затем вызовет тот же endpoint — без ломки контракта экзаменационной ветки.

### 2.3. Явно не входит

- чтение TXT/DOCX/CSV/MD как файлов: на этапе 3 импортируется только вставленный текст;
- готовые ответы и сопоставление `вопрос → ответ`: этап 4;
- загрузка учебных материалов, быстрый анализ и ProjectMaterial: этап 5;
- построение по оглавлению и проход 1: этап 7;
- модельная группировка, помощник и диф программы: этап 7;
- объединение тем: этап 7 вместе с общим механизмом дифа и происхождения; до этого работает предупреждение о точном дубле, стабильные UUID и soft removal сохраняют данные для будущего merge;
- покрытие, привязки, источники темы: этап 8;
- конспекты, попытки, повторения и План: этап 9;
- redo: NFR-5 требует undo; обратное повторение действия не добавляется без отдельной потребности.

### 2.4. Точный демонстрационный набор

- Project: `Базы данных — экзамен (пример)`, description `Демонстрационный проект с настоящей программой этапа 3`, icon `database`, color `4`, deadline null, modules `plan/cards/repetitions/oral_answers`, active, sort_order `0`.
- GoalPassport: subject `Базы данных`, purpose `exam`, scope `whole`, starting_level `familiar`, target_outcome `application`, study_format `theory_and_practice`, expected_item_count `2`, ритм `45 минут · 4 дня в неделю · сессия 45 минут`.
- Билет 1: `Архитектура системы управления базами данных` (question) и `Реляционная модель данных и её компоненты` (question).
- Билет 2: `Транзакции и свойства ACID` (question) и `Нормализовать отношение до третьей нормальной формы` (task).
- Все узлы current, target/application, origin/import с подписью `Демонстрационный набор Tentex`; action log пуст, потому что seed — начальное состояние, а не пользовательская команда.
- WorkspaceState schema 1: выбран первый вопрос, оба билета раскрыты, tree_width `320`, одна группа с tabs `answer/source`, active_tab `answer`, weight `1`.

## 3. Контракт совместимости со следующими этапами

Эта таблица — не список сущностей «на будущее». Она фиксирует только инварианты этапа 3,
которые нельзя будет безболезненно исправить после появления связанных данных.

| Будущий этап и функция | Что обязан сохранить этап 3 | Как расширяется без ломки текущего интерфейса |
|---|---|---|
| 4: эталонные ответы и пары вопрос → ответ | Стабильный `ProgramNode.id`, `exam_kind`, сохранение узла при выводе из программы; public exam-import обещает replacement результата, но не физический DELETE | Ответ ссылается на node id; до ответов внутри draft импорт переходит на identity-preserving reconcile и action payload v2 без смены request/response |
| 5: материалы и удаление черновика с файлами | ProjectMaterial уже отделён от общего Material; `activate` не требует материал глобально | Учебниковый мастер проверяет наличие ProjectMaterial перед вызовом activate; discard позже добавляет отмену jobs, но сохраняет тот же DELETE |
| 7: оглавление, проход 1, каталог, диф и merge | Origin задаёт сервер, title не уникален, физического delete нет, action payload versioned | Bulk diff и merge добавляются командами Program; provenance становится отдельной relation, а не JSON в ProgramNode |
| 8: привязки и покрытие | Любой текущий/скрытый узел остаётся в БД; `project_id,id` пригодны для составного FK | Binding ссылается на `(project_id, program_node_id)`; фильтр current исключает скрытые темы без потери связей |
| 9: активности, карточки, повторы и План | target_level заполняется серверным default из GoalPassport; current/archived статусы различены | Новые таблицы ссылаются на тот же node id; журнал получает новые action_type без изменения старых payload |
| 10: экспорт/импорт проекта | Канонические факты не живут только в UI/localStorage; seed — обычный проект | Экспорт обходит те же таблицы; фиксированные UUID примера не имеют особой семантики за пределами seed |
| Позже: пользовательские шаблоны FR-P9 | Project.template_key хранит базовый встроенный preset, а variant выводится сервером | WizardDraftCreate получит альтернативный saved_template_id; сервер развернёт его в base template/settings, текущий template_key не меняется |
| Общий undo NFR-5 | Один журнал: action rows не удаляются, имеют project FK, строгий sequence, phase и payload_version; blobs в JSON не кладутся | Привязки, карточки и bulk diff добавляют свои action_type и минимальные inverse refs в ту же таблицу |

Дополнительные инварианты Program:

- `ProgramNode.id` не меняется при rename/move/remove/restore; физическое удаление допустимо только при замене дерева неактивного draft, пока у него нет связанных сущностей.
- Любая будущая таблица, принадлежащая проекту и ссылающаяся на узел, использует составной FK `(project_id, program_node_id) → program_nodes(project_id, id)`.
- `title` намеренно не уникален: точные и смысловые дубли являются состоянием для проверки, а не ошибкой базы.
- `origin_note` не хранит UUID материалов, model run или произвольный JSON; ссылки происхождения появятся нормализованной связью.
- `sort_order` — read-only представление плотного порядка. Клиенты выражают намерение через `position`; сервер единолично пересчитывает соседей.
- `Project.sort_order` также server-owned: draft save/settings его не принимают, activate добавляет проект в конец, archive/order нормализуют active-позиции.
- `Project.program_revision` относится только к дереву. Workspace resize и будущие фоновые Binding не должны создавать ложные конфликты редактора Program.

## 4. Файлы и ответственность

### Создать

- `backend/app/projects/importer.py` — чистый разбор вставленного экзаменационного списка без доступа к БД.
- `backend/app/projects/errors.py` — общие typed domain errors с `status`, стабильным `code` и небольшим `context`; их используют lifecycle и Program без циклического импорта.
- `backend/app/projects/program.py` — единственный модуль чтения и изменения дерева: инварианты, program revision, нормализация порядка, журнал и undo.
- `backend/app/projects/demo.py` — маленький идемпотентный seed одного настоящего проекта с фиксированными UUID; не содержит ответов или материалов будущих этапов.
- `backend/migrations/versions/20260808_0003_stage3_program.py` — `Project.program_revision`, `project_action_log` и индексы; миграция цвета уже выполнена подготовительной вертикалью.
- `backend/scripts/check_stage3.py` — один сквозной smoke-check этапа 3, переиспользующий `ApiServer` и `request` из `check_stage2.py`.
- `frontend/src/hooks/useWizardDraft.ts` — загрузка, последовательное автосохранение, конфликт ревизий, активация и удаление черновика для обеих веток.
- `frontend/src/screens/project-wizard/ExamWizard.tsx` — только пять шагов экзаменационной ветки; route/выбор трека остаются в ProjectWizard.
- `frontend/src/screens/programTree.ts` — одна чистая сборка и обход дерева из плоских `ProgramNodeRead` для Программы, Мастера и Рабочей области.
- `docs/architecture/stage-3-live-projects.md` — реализованный поток, новые ручки, журнал undo и честные границы этапа.

### Изменить

- `PLAN.md` — исправить учебниковую границу, считать Настройки завершённой подготовительной вертикалью, уточнить «удаление» как вывод из текущей программы.
- `AGENTS.md` — устранить конфликт границ: разрешить на этапе 3 только `ProjectActionLog` и `program_revision`, сохранив запрет на сущности материалов, ответов и обучения.
- `SCREENS.md` — описать реальные loading/error/empty/conflict-состояния четырёх поверхностей этапа и переходный итог учебникового черновика; готовый раздел Настроек не переписывать.
- `docs/architecture/stage-2-core.md` — после реализации пометить изменённые create/PATCH/settings response как superseded этапом 3 и сослаться на новый документ; историю этапа 2 не переписывать.
- `backend/app/config.py` — добавить `seed_demo_project: bool = True`; smoke этапа 2 выключает seed через `TENTEX_SEED_DEMO_PROJECT=false`.
- `backend/app/main.py` — после успешного Alembic upgrade вызвать seed в отдельной короткой транзакции.
- `backend/app/models.py` — добавить только `Project.program_revision` и `ProjectActionLog`; тип цвета уже выровнен.
- `backend/app/projects/schemas.py` — revision-aware program commands, импорт, порядок проектов, move/subtree/remove/undo, стабильные ошибки и сводка последнего отменяемого действия.
- `backend/app/projects/service.py` — оставить lifecycle черновика/проекта, настройки и WorkspaceState; дерево делегировать в `program.py`, не дублируя его запросы и проверки.
- `backend/app/projects/router.py` — новые узкие маршруты.
- `backend/scripts/check_stage2.py` — выключить demo seed для изолированного сценария и адаптировать ответы program commands к новому read-model, не менять остальную проверку.
- `frontend/src/api/projects.ts` — расширить готовый `request/getProject/updateProjectSettings` функциями мастера, списка, программы и раскладки.
- `frontend/src/screens/ProjectSettings.tsx` — принять узкий ProjectSettingsResult без изменения формы и пользовательского поведения.
- `frontend/src/screens/ProjectWizard.tsx` — выбор трека, список возобновляемых черновиков и делегирование в две ветки; экзаменационная форма больше не живёт в этом 1200-строчном файле.
- `frontend/src/screens/TextbookWizard.tsx` — реальный draft-only путь без фиктивных источников и генерации.
- `frontend/src/screens/Projects.tsx` — список, порядок, архив/восстановление и состояния API.
- `frontend/src/screens/Program.tsx` — серверный вариант и дерево, реальные ручные действия и undo; mock-AI убрать.
- `frontend/src/screens/ProjectWorkspace.tsx` — серверный ProjectDetail и WorkspaceState без доменных данных в `localStorage`.
- `frontend/src/app/AppLayout.tsx` — убрать mock-покрытие, темы, задачи, библиотечные числа и названия моделей; пример приходит из `listProjects`.
- `frontend/src/app/CommandPalette.tsx` — искать реальные проекты и не вести project-specific экраны на demo id.
- `frontend/src/app/screens.ts` — убрать строковые demo-ID и подмену route; фиксированный UUID seed не экспортируется во frontend.
- `frontend/src/styles/layout.css` — только стили новых реальных состояний через существующие токены; стили Настроек не дублировать.

### Оставить без изменений

- `Material` и `ProjectMaterial`: таблицы готовы, но без загрузки их нельзя честно заполнить.
- `frontend/src/screens/workspaceDemo.ts`: временно остаётся только для ещё не оживлённых Lessons; ProjectWorkspace больше его не импортирует.
- `frontend/src/screens/Materials.tsx`, `Plan.tsx`, `cards/`, `lessons/`: их mock-сценарии не становятся частью этапа 3 и не получают ссылки из реального базового пути.

## 5. Контракты API

Маршруты чтения, мастер, Настройки и WorkspaceState этапа 2 сохраняются. Две пока не
подключённые к живому UI ручки create/PATCH ProgramNode намеренно уточняются сейчас — это
последнее дешёвое окно до появления ответов и привязок. После этапа 3 структура Program command
считается стабильной.

`PUT /api/projects/{project_id}/settings` сохраняет прежний request, но возвращает узкий
`ProjectSettingsResult {project, goal_passport}`, а не ProjectDetail с Program/WorkspaceState.

| Метод и путь | Назначение | Атомарность/ограничение |
|---|---|---|
| `DELETE /api/wizard-drafts/{project_id}?expected_revision=N` | Явно удалить подтверждённый черновик | Только `status=draft` и актуальная draft revision; ProjectMaterial stage 5 будет удаляться каскадом, общий Material сохранится |
| `POST /api/wizard-drafts/{project_id}/exam-import` | Разобрать сырой текст и заменить программу черновика | Проверяет draft и program revisions, полностью валидирует результат, пишет обратный снимок, заменяет дерево и увеличивает обе ревизии одной транзакцией |
| `PUT /api/projects/order` | Сохранить порядок активных карточек | Принимает каждый active id ровно один раз, нормализует `0..n-1` |
| `POST /api/projects/{project_id}/archive` | Перевести active в archived | Обновляет `status_changed_at`; повторный вызов идемпотентен |
| `POST /api/projects/{project_id}/restore` | Вернуть archived в active | Archived ставится после текущих active; повтор active возвращает текущее состояние, completed даёт 409 |
| `POST /api/projects/{project_id}/program-nodes` | Добавить узел в parent/position | Проверяет program revision и parent; server назначает UUID, origin, default target_level и плотный sort_order |
| `PATCH /api/projects/{project_id}/program-nodes/{node_id}` | Изменить свойства узла | Не принимает parent/order/visibility/origin; null отличается от отсутствующего поля |
| `POST /api/projects/{project_id}/program-nodes/{node_id}/move` | Перенести узел в parent/position | Проверяет revision, current parent, цикл и глубину всего поддерева; перенумеровывает обе группы соседей |
| `POST /api/projects/{project_id}/program-nodes/{node_id}/target-level` | Уровень цели для узла или поддерева | `include_descendants=true` реализует FR-G25 одной транзакцией |
| `POST /api/projects/{project_id}/program-nodes/{node_id}/remove` | Убрать поддерево из текущей программы | Меняет только `is_in_current_program`; физические строки остаются |
| `POST /api/projects/{project_id}/program-nodes/{node_id}/restore` | Вернуть верхний скрытый root и поддерево | Отклоняет descendant скрытого root; восстанавливает поддерево и пишет отменяемое действие |
| `POST /api/projects/{project_id}/actions/undo` | Отменить последнее действие текущей phase | Проверяет `expected_action_sequence`, применяет versioned inverse и ставит undone_at; Program action увеличивает program revision, а в draft также draft revision |

`PUT /projects/order` возвращает новый `list[ProjectSummary]` активных проектов; archive/restore
возвращают один `ProjectSummary`, а не тяжёлый ProjectDetail с деревом. DELETE draft отвечает 204.

Общий read-model дерева — `ProgramState {nodes: list[ProgramNodeRead], revision: int}`. Его без
вариаций используют ProjectDetail, WizardDraftDetail, ExamImportResult, ProgramChangeResult и
program-поле ActionUndoResult.

Точные command shapes:

| Команда | Поля request |
|---|---|
| Create node | `expected_program_revision`, `parent_id: UUID | null`, `position: int | null`, `node_type`, `exam_kind: ExamKind | null`, `title`, `section_purpose`, `goal_role`, optional `target_level`, `needs_material` |
| PATCH node | `expected_program_revision` плюс только переданные `title`, `node_type`, `exam_kind`, `section_purpose`, `goal_role`, `needs_material`; nullable очищается явным null |
| Move | `expected_program_revision`, `parent_id`, `position: int | null` |
| Target level | `expected_program_revision`, `target_level: TargetOutcome`, `include_descendants: bool` |
| Remove / restore | только `expected_program_revision` |
| Undo | только `expected_action_sequence` |
| Project order | `project_ids: UUID[]` |
| Archive / restore project | пустое body |
| Create draft | только `template_key`; extra workspace_variant запрещён |

`ProjectDetail` и `WizardDraftDetail` вместо отдельного `program_nodes` получают единый
`program: {nodes, revision}`. Каждый create/PATCH/move/target/remove/restore для draft и active
передаёт `expected_program_revision`; сервер делает compare-and-increment в
той же транзакции, что дерево и action log. Для draft сервер дополнительно увеличивает
`WizardDraft.revision`, чтобы устаревший autosave или activation получили 409; клиент не передаёт
draft revision каждой структурной команде и не смешивает две области версионирования.

Undo не принимает program-specific concurrency token. Запрос `{ "expected_action_sequence": 42 }`
означает «отмени именно действие, которое я вижу последним». Если sequence уже другой, сервер
возвращает `stale_action_sequence`; это одинаково работает сейчас для Program и позже для
Binding/Card. Конкретная ветка undo сама увеличивает затронутые aggregate revisions.

Public create принимает `parent_id`, `position | null` (`null` = append), `node_type`, `exam_kind`,
`title`, `section_purpose`, `goal_role`, необязательный `target_level` и `needs_material`.
`origin_kind=manual` и `origin_note=null` задаёт сервер; отсутствующий target_level берётся из
GoalPassport.target_outcome. PATCH принимает только `title`, `node_type`, `exam_kind`,
`section_purpose`, `goal_role`, `needs_material`. Поля `parent_id`, `sort_order`, `target_level`,
`is_in_current_program`, `is_archived`, `origin_kind`, `origin_note` меняются только своими
командами или внутренним импортом.

Семантика дерева едина для всех команд:

- parent обязан принадлежать проекту, быть `is_in_current_program=true` и `is_archived=false`;
- create/move hidden node и create под hidden parent отклоняются с 422;
- `position` считается среди текущих siblings; сервер сохраняет относительный порядок скрытых
  строк, затем делает общий плотный `sort_order` без дублей;
- textbook node всегда получает `exam_kind=null`; в exam `ticket` допустим только для section,
  а question/task — для topic/subpoint; обычный группирующий section может иметь exam_kind=null;
- target-level с include_descendants меняет структурное поддерево целиком, включая временно hidden
  descendants, чтобы их уровень не устарел после restore;
- пустой title, цикл, глубина больше четырёх и ссылка между проектами дают 422 до первой мутации;
- activation заполняет всё ещё null target_level значением GoalPassport.target_outcome и один раз
  увеличивает program revision; существующее ненулевое значение не меняет и action log не создаёт;
- static route `/api/projects/order` регистрируется раньше `/{project_id}`, чтобы `order` не
  попадал в UUID converter.

### 5.1. Ошибки

Domain error сохраняет совместимое поле `detail: string` и добавляет:

```json
{
  "detail": "Программа уже изменена в другой вкладке",
  "code": "stale_program_revision",
  "context": { "current_program_revision": 8 }
}
```

Минимальный стабильный набор codes: `not_found`, `stale_draft_revision`,
`stale_program_revision`, `stale_action_sequence`, `project_read_only`, `invalid_status_transition`,
`unsupported_template`, `program_invariant`. Pydantic 422 остаётся в стандартном формате FastAPI. `ProjectApiError`
хранит `status`, `code | null`, `context` и message; UI никогда не сравнивает русский текст.
Revision contexts используют точные ключи `current_draft_revision`, `current_program_revision` и
`current_action_sequence` (null, если отменять нечего); status transition добавляет `current_status`.

### 5.2. Импорт

Запрос:

```json
{
  "expected_revision": 3,
  "expected_program_revision": 1,
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
  "program": {
    "revision": 2,
    "nodes": [
      {
        "id": "10000000-0000-4000-8000-000000000001",
        "project_id": "20000000-0000-4000-8000-000000000001",
        "parent_id": null,
        "node_type": "section",
        "exam_kind": "ticket",
        "sort_order": 0,
        "title": "Билет 1",
        "section_purpose": null,
        "goal_role": "target",
        "target_level": "application",
        "is_in_current_program": true,
        "needs_material": false,
        "is_archived": false,
        "origin_kind": "import",
        "origin_note": "Вставленный текст",
        "created_at": "2026-08-08T12:00:00",
        "updated_at": "2026-08-08T12:00:00"
      },
      {
        "id": "10000000-0000-4000-8000-000000000002",
        "project_id": "20000000-0000-4000-8000-000000000001",
        "parent_id": "10000000-0000-4000-8000-000000000001",
        "node_type": "topic",
        "exam_kind": "question",
        "sort_order": 0,
        "title": "Реляционная модель",
        "section_purpose": null,
        "goal_role": "target",
        "target_level": "application",
        "is_in_current_program": true,
        "needs_material": false,
        "is_archived": false,
        "origin_kind": "import",
        "origin_note": "Вставленный текст",
        "created_at": "2026-08-08T12:00:00",
        "updated_at": "2026-08-08T12:00:00"
      },
      {
        "id": "10000000-0000-4000-8000-000000000003",
        "project_id": "20000000-0000-4000-8000-000000000001",
        "parent_id": "10000000-0000-4000-8000-000000000001",
        "node_type": "topic",
        "exam_kind": "task",
        "sort_order": 1,
        "title": "Нормализовать отношение",
        "section_purpose": null,
        "goal_role": "target",
        "target_level": "application",
        "is_in_current_program": true,
        "needs_material": false,
        "is_archived": false,
        "origin_kind": "import",
        "origin_note": "Вставленный текст",
        "created_at": "2026-08-08T12:00:00",
        "updated_at": "2026-08-08T12:00:00"
      }
    ]
  },
  "latest_undoable_action": {
    "sequence": 1,
    "action_type": "exam_import",
    "target_title": "Импорт списка экзамена",
    "created_at": "2026-08-08T12:00:00"
  }
}
```

Правила `importer.py`:

- нормализовать CRLF/LF, обрезать пробелы и игнорировать пустые строки;
- распознавать маркеры `1.`, `1)`, `1.2.`, `-`, `—`, `*`, `•`;
- строку без нового маркера присоединять к предыдущему пункту как продолжение, а не создавать ложную тему;
- если во всём questions/questions_tasks тексте нет ни одного маркера, считать каждую непустую
  строку отдельным пунктом; tickets без заголовков по-прежнему отклонять;
- для `questions` создавать плоские `topic + question`;
- для `questions_tasks` заголовки `Вопросы`/`Задачи` меняют текущий тип, а явные префиксы `Задача:`/`Задание:` имеют приоритет; без признака использовать `question`;
- для `tickets` заголовок `Билет`, `Билет №`, `Билет #` создаёт `section + ticket`, вложенные пункты — `topic + question/task`;
- билет без пунктов и формат tickets без заголовка билета отклонять с 422;
- одинаковые формулировки не удалять молча: сохранить и вернуть предупреждение с номерами;
- ограничить сырой текст 1 000 000 символов и требовать хотя бы один изучаемый узел;
- корни и дети получают плотный `sort_order` с нуля, `goal_role=target`, target_level из паспорта,
  `is_in_current_program=true`, `needs_material=false`, `is_archived=false`,
  `origin_kind=import`, `origin_note="Вставленный текст"`;
- stage-3 implementation может удалить старое дерево физически только здесь и только у draft,
  потому что зависимых Answer/Binding ещё нет; inverse snapshot хранит все UUID, parent_id и поля;
- public contract обещает replacement результата, не способ удаления. Этап 4 до разрешения
  Answer внутри draft заменяет implementation на identity-preserving reconcile и payload v2;
  endpoint никогда не расширяется на active — будущая пересборка использует soft diff.

### 5.3. Журнал действий

`project_action_log` хранит:

- `sequence: INTEGER PRIMARY KEY AUTOINCREMENT`, `project_id: UUID ON DELETE CASCADE`;
- `action_type: str` из реально реализованных значений `exam_import`, `node_create`, `node_update`, `node_move`, `target_level_subtree`, `node_remove`, `node_restore`;
- `phase: str` из `draft | active`, зафиксированный в момент действия;
- `payload_version: int = 1`;
- `target_title: str` для понятной подписи кнопки undo;
- `inverse_data: JSON` — только прежние значения изменённых строк и их id;
- `created_at`, `undone_at | null`.

Индекс `(project_id, phase, undone_at, sequence)` обслуживает выбор последнего действия без
сортировки по timestamp. Никаких command bus, registry или универсального event sourcing.
`undo_last_project_action()` содержит один явный `match (action_type, payload_version)`;
следующий этап добавляет ветку только вместе с новым отменяемым действием. Большие тексты, файлы,
страницы и фрагменты в inverse_data не копируются — журнал хранит прежние scalars, UUID и малые
снимки дерева импорта.

`ProjectDetail` и `WizardDraftDetail` получают `latest_undoable_action:
{sequence, action_type, target_title, created_at} | null`, поэтому undo остаётся доступен после
перезагрузки и в ручном редакторе учебникового черновика. Обычные мутации программы возвращают
`ProgramChangeResult {changed_node, program: {nodes, revision}, latest_undoable_action,
draft_revision}`; changed_node равен созданному/изменённому узлу либо null для группового действия.

Общий undo возвращает отдельный расширяемый `ActionUndoResult {undone_action_type,
program: {nodes, revision} | null, draft_revision, latest_undoable_action}`. На этапе 3 program
всегда заполнен. Следующие этапы добавят рядом необязательные `bindings`/`cards`, не меняя
существующие поля и не заставляя Program знать их схемы.

После активации действия мастера остаются аудиторской историей, но не предлагаются для undo в
active-проекте: detail выбирает `phase=draft` только для draft и `phase=active` для active. Так
отмена импорта после активации не превращает валидный проект в пустой и не удаляет уже связанные
данные будущих этапов. `program_revision` при активации не сбрасывается.

Undo создания не выполняет физический `DELETE`: созданное поддерево выводится из текущей программы. Это оставляет безопасную семантику, когда на следующих этапах у узла уже могут появиться ответы, привязки или карточки.

## 6. Порядок реализации

### Task 1: Зафиксировать границу этапа и compatibility contract

**Files:**
- Modify: `PLAN.md`
- Modify: `AGENTS.md`
- Modify: `SCREENS.md`
- Create: `docs/architecture/stage-3-live-projects.md` (каркас, окончательные факты дописать в Task 9)

**Produces:** однозначная граница этапа 3, утверждённый seed-пример и инварианты Program, которые используют этапы 4–10.

- [ ] В `PLAN.md` заменить обещание сохранённых источников учебниковой ветки на draft-only результат без источников и активации до этапа 5.
- [ ] В `PLAN.md` зафиксировать Настройки как завершённую подготовительную вертикаль и убрать их реализацию из состава этапа 3.
- [ ] В `PLAN.md` заменить «удаление темы» на «вывод поддерева из текущей программы с undo».
- [ ] В `AGENTS.md` заменить противоречивый запрет на undo/new entities точной границей: разрешены только Project.program_revision и ProjectActionLog; Material pipeline, ответы, Binding и учебные сущности не входят.
- [ ] В `SCREENS.md` для каждой поверхности дописать loading, API error, 404, 409 revision conflict, пустое состояние и переход после успешного действия.
- [ ] В `SCREENS.md` явно убрать из этапа 3 настоящие ответы, материалы, покрытие, конспекты и попытки.
- [ ] В `SCREENS.md` описать пример «Базы данных — экзамен» как обычную редактируемую карточку с реальными данными этапа 3, без fake badges/метрик будущих этапов.
- [ ] Создать каркас архитектурного документа: diagram Project → ProgramNode, draft/program revisions, seed flow и таблица compatibility из §3.
- [ ] Проверить prerequisite: настоящий route Настроек зарегистрирован, `PUT /settings` проходит через restart, `projects.ts` содержит общий `request<T>()`, цвет равен `int | null`, а `GoalLevelValue` совпадает с `TargetOutcome`. Если нет — сначала выполнить подготовительный промпт, не чинить это попутно.
- [ ] Проверить формулировки поиском: `rg -n "этапа 5|ProjectActionLog|program_revision|пример|источник|удален|Настройки|409|localStorage" AGENTS.md PLAN.md SCREENS.md docs/architecture/stage-3-live-projects.md`.
- [ ] Commit: `docs: define stage 3 live-data boundary`.

### Task 2: Заложить единый модуль Program, revisions и журнал

**Files:**
- Create: `backend/app/projects/errors.py`
- Create: `backend/app/projects/program.py`
- Create: `backend/migrations/versions/20260808_0003_stage3_program.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/projects/schemas.py`
- Modify: `backend/app/projects/service.py`
- Modify: `backend/app/projects/router.py`
- Modify: `backend/app/main.py`
- Modify: `backend/scripts/check_stage2.py`
- Modify: `frontend/src/api/projects.ts`
- Modify: `frontend/src/screens/ProjectSettings.tsx`

**Interfaces:**
- Produces: domain errors `{status, code, detail, context}` and совместимый JSON exception handler.
- Produces: `ProgramChangeResult`, `ActionUndoResult` and Program commands from §5.
- Consumed by lifecycle: `read_program(session, project_id) -> ProgramState` and `prepare_for_activation(session, project_id, default_target_level) -> ProgramState`; service.py не знает внутренние tree helpers.

- [ ] Перенести ProjectNotFoundError/Conflict/Invariant в `errors.py`; добавить code/context без создания общей framework hierarchy. Main handler возвращает detail+code+context, существующие status остаются 404/409/422.
- [ ] Миграцией добавить `projects.program_revision INTEGER NOT NULL DEFAULT 0 CHECK >= 0`, создать action log из §5.3 с FK cascade, CHECK phase/payload_version и индексом; существующим null ProgramNode.target_level подставить ненулевой GoalPassport.target_outcome. Downgrade удаляет только новые table/column и не откатывает безопасный backfill.
- [ ] В `schemas.py` разделить read-model и команды: sort_order/origin/visibility отсутствуют в create/update input; position отсутствует в ProgramNodeRead; все extra fields forbidden. ProjectDraftWrite использует ProjectIcon и нормализует enabled_modules без дублей тем же helper, что Settings.
- [ ] Удалить `sort_order` из ProjectDraftWrite; в activate плотно нормализовать active projects и поставить новый проект последним. Настройки и draft save не меняют порядок.
- [ ] WizardDraftCreate принимает только template_key; create_wizard_draft исчерпывающим match задаёт workspace_variant. Free возвращает 409 unsupported_template до этапа 7, клиент не может передать variant вручную.
- [ ] Create/import берут отсутствующий target_level из GoalPassport; activation заполняет оставшиеся null для draft, увеличивает program revision при фактическом изменении и никогда не перезаписывает явно заданный уровень.
- [ ] Вынести `_nodes`, полную проверку дерева и все мутации ProgramNode из service.py в program.py. Service detail/activation вызывает только read_program/prepare_for_activation и не меняет узлы напрямую.
- [ ] Один внутренний `_begin_program_change` делает SQL compare-and-swap `UPDATE projects ... WHERE program_revision=:expected`; rowcount 0 даёт stale context. При успехе он увеличивает revision и для draft той же транзакцией увеличивает WizardDraft.revision.
- [ ] Реализовать create/update/move/target/remove/restore через этот helper; перед записью валидировать весь итоговый parent map, subtree depth, current parent и variant/exam_kind.
- [ ] Create/move переводят position в плотные sort_order на сервере. Проверить root и nested siblings, move в той же группе, между группами, indent/outdent, append и недопустимый position.
- [ ] Реализовать ProjectActionLog и `_record_action` с payload_version=1; inverse_data содержит только перечисленные в §5.3 значения. Seed и системная миграция actions не создают.
- [ ] Undo выбирает максимальный sequence для текущей phase и undone_at IS NULL, сравнивает его с `expected_action_sequence`, применяет `match (action_type, payload_version)`, помечает строку и увеличивает затронутые revisions одной транзакцией.
- [ ] Hidden subtree: remove сохраняет прежние visibility flags; restore принимает только верхний hidden root; create/move под hidden parent отклоняются.
- [ ] Обновить ProjectDetail/WizardDraftDetail на единый ProgramState `{nodes, revision}`; ProjectRead/Summary revision дерева не дублируют. Create/PATCH/move/target/remove/restore возвращают ProgramChangeResult, undo — ActionUndoResult. `/projects/order` пока не добавлять, но зарезервировать его регистрацию перед `/{project_id}` в Task 4.
- [ ] Сузить response PUT /settings до ProjectSettingsResult и обновить готовый frontend settings flow; request и все поддерживаемые поля остаются прежними.
- [ ] В save_workspace_state убрать изменение Project.updated_at; сам WorkspaceState.updated_at продолжает обновляться.
- [ ] В `check_stage2.py` выключить будущий seed env и брать узлы/revision из `program.nodes` и `changed_node`; все прежние проверки lifecycle/settings/WAL/FK оставить.
- [ ] Run: `python backend/scripts/check_stage2.py`; expected: `stage 2 smoke check passed`.
- [ ] Run: `cd backend && python -m ruff check .`.
- [ ] Run: `npm run typecheck`.
- [ ] Commit: `feat: add revisioned program command module`.

### Task 3: Реализовать импорт экзамена и настоящий экзаменационный мастер

**Files:**
- Create: `backend/app/projects/importer.py`
- Modify: `backend/app/projects/schemas.py`
- Modify: `backend/app/projects/service.py`
- Modify: `backend/app/projects/program.py`
- Modify: `backend/app/projects/router.py`
- Modify: `frontend/src/api/projects.ts`
- Create: `frontend/src/hooks/useWizardDraft.ts`
- Modify: `frontend/src/screens/ProjectWizard.tsx`
- Create: `frontend/src/screens/project-wizard/ExamWizard.tsx`
- Modify: `frontend/src/screens/TextbookWizard.tsx` only to receive the draft hook contract; full branch is Task 7

**Interfaces:**
- Produces: `parse_exam_program(raw_text: str, exam_format: ExamFormat) -> ParsedExamProgram`.
- Produces: `POST /api/wizard-drafts/{project_id}/exam-import -> ExamImportResult` and revision-guarded `DELETE /api/wizard-drafts/{project_id}`.
- Extends: готовый `request<T>`; ProjectApiError получает code/context, второй transport/helper не создаётся.
- Produces: `useWizardDraft({templateKey})` with `detail`, `status`, `conflict`, `queueSave`, `flush`, `enqueueProgramCommand`, `importExam`, `activate`, `discard`, `reload`.

- [ ] Написать чистый parser по правилам §5.2; ParsedNode хранит временный parent index, node_type, exam_kind, title и position.
- [ ] В Program import проверить draft/program revisions, разобрать весь текст до мутации, записать прежнее дерево с UUID в versioned inverse, удалить прежний draft-tree от листьев к корням, создать новый, увеличить обе revisions и вернуть counts/warnings/ProgramState одной транзакцией.
- [ ] Добавить удаление только draft-проекта с актуальной draft revision; из-за self-FK RESTRICT сначала удалить ProgramNode от листьев к корням, затем Project. ProjectMaterial/action log/passport/draft каскадируются, общий Material сохраняется; active/archived/completed дают invalid_status_transition.
- [ ] В projects.ts описать типы строго по Pydantic: даты ISO string, UUID string, `ProgramNodeRead.sort_order` только read-only, ProgramChangeResult и ActionUndoResult не смешиваются.
- [ ] Расширить request разбором code/context, сохранив текущую обработку стандартного validation detail; русский message не использовать для ветвления.
- [ ] В hook держать одну Promise-очередь для autosave, import и program commands. `enqueueProgramCommand` сначала flush текущего form payload, ждёт предыдущую команду, передаёт последнюю program revision и принимает обе revisions из ответа.
- [ ] Debounce 400 мс использовать только для полей. Переход шага, import, program command, «Сохранить и выйти» и activation проходят через общую очередь; discard намеренно отбрасывает локальные несохранённые поля и использует последнюю подтверждённую revision.
- [ ] При `stale_draft_revision`, `stale_program_revision` или `stale_action_sequence` остановить очередь и предложить «Загрузить серверную версию»/«Остаться на странице»; другие 409 показывать как действие запрещено. Force overwrite и auto retry отсутствуют.
- [ ] AbortController использовать только для read effects; abort не переводить экран в ErrorState. POST/PUT не отменять после отправки, чтобы неизвестный исход не повторялся автоматически.
- [ ] Перенести экзаменационные шаги без визуального редизайна в `project-wizard/ExamWizard.tsx`; ProjectWizard оставляет track selection/resume и не становится вторым хранилищем draft state.
- [ ] Убрать `DEMO_FILES`, `REVIEW_ITEMS`, демонстрационные значения предмета/даты/преподавателя и кнопки «Добавить пример».
- [ ] Удалить локальный `getPreparationForecast` с выдуманными минутами/коэффициентами: до этапа 9 показывать только вычислимые из введённой даты календарные дни и выбранный пользователем ритм, не обещать готовность.
- [ ] На шаге ввода оставить активным только «Вставить текст». «Файлы» показать недоступным с причиной «Загрузка файлов появится на этапе 5»; ответы — «этап 4», учебные материалы — «этап 5».
- [ ] Форматы `questions`, `questions_tasks`, `tickets` сделать проходимыми; `unknown` оставить видимым, но недоступным до материалов этапа 5.
- [ ] Создавать draft при переходе к первому осмысленному вводу; сохранять в `state` только raw text, input mode, выбранный format и UI-предупреждения, не копируя паспорт или program nodes.
- [ ] На шаге проверки строить список из `detail.program.nodes`; inline-редактирование на blur проходит через `enqueueProgramCommand`, не вызывает API на каждый символ и не держит отдельное каноническое дерево.
- [ ] Предупреждение о расхождении ожидаемого и найденного количества считать по настоящему `counts` ответа импорта; расхождение не блокирует активацию и ведёт к полю expected count.
- [ ] Преобразовать wizard значения в API: `zero→beginner`, `partial→familiar`, `refresh→refreshing`; `orient→awareness`, `understand→understanding`, `answer→application`, `master→mastery`; `mixed→theory_and_practice`.
- [ ] Сохранять `purpose=exam`, имя `${subject} — экзамен` и модули пресета `plan`, `cards`, `repetitions`, `oral_answers`; сырой текст не использовать как название или описание проекта.
- [ ] Финальное подтверждение перечисляет только реально сохранённые паспорт и вопросы/задачи/билеты. Строки «ответы сохранены», «материалы сохранены» и фоновая обработка отсутствуют до соответствующих этапов.
- [ ] Перед активацией завершить общую очередь, при необходимости импорт, затем activate с актуальной draft revision; после ответа перейти на `/projects/{id}?topic={firstStudyNodeId}`.
- [ ] При входе в мастер загрузить summaries черновиков и предложить «Продолжить» или «Начать новый»; свободный трек остаётся недоступен.
- [ ] Выход с изменённым draft предлагает «Сохранить и выйти»; подтверждённое «Удалить черновик» flush не делает, но передаёт последнюю подтверждённую draft revision в DELETE.
- [ ] Не писать Project/GoalPassport/ProgramNode в localStorage.
- [ ] Run: `cd backend && python -m ruff check .`.
- [ ] Run: `npm run typecheck`.
- [ ] Commit: `feat: create exam projects from pasted lists`.

### Task 4: Посеять настоящий пример и оживить lifecycle Проектов

**Files:**
- Create: `backend/app/projects/demo.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/projects/schemas.py`
- Modify: `backend/app/projects/service.py`
- Modify: `backend/app/projects/router.py`
- Modify: `frontend/src/api/projects.ts`
- Modify: `frontend/src/screens/Projects.tsx`

**Interfaces:**
- Produces: `PUT /api/projects/order`, `POST /archive`, `POST /restore`.
- Produces: `seed_demo_project(session) -> UUID`, default config `seed_demo_project=true`.
- Modifies: `ProjectSummary` includes `status_changed_at`; никаких demo-only fields.

- [ ] В demo.py зафиксировать UUID через `uuid5(NAMESPACE_URL, "tentex:demo:database-exam:v1")` и производные стабильные UUID узлов. Если Project с этим id существует — вернуть id без UPDATE; пользовательские правки примера не перезаписывать.
- [ ] При отсутствии id одной транзакцией создать точный набор §2.4. `program_revision=0`, action log пуст, ответы/Material/coverage не создавать; Workspace layout провалидировать через WorkspaceStateWrite до ORM insert.
- [ ] После Alembic upgrade lifespan при включённом `TENTEX_SEED_DEMO_PROJECT` открывает SessionLocal и вызывает seed. Seed не находится в миграции, поэтому downgrade не удаляет пользовательски изменённый пример.
- [ ] Проверить повторный startup: row counts и updated_at примера не меняются. Архивирование примера допустимо и не приводит к созданию второго.
- [ ] Реализовать сохранение порядка: payload не содержит дублей и совпадает с множеством active id; иначе 422.
- [ ] Зарегистрировать static `PUT /projects/order` до `GET /projects/{project_id}` и проверить, что строка `order` не разбирается как UUID.
- [ ] Реализовать archive/restore с `status_changed_at`: archive плотно перенумеровывает оставшиеся active, restore добавляет в конец; повторный archive archived и restore active идемпотентно возвращают текущий ProjectSummary, completed и draft дают `invalid_status_transition`.
- [ ] Добавить list/order/archive/restore в единый projects.ts.
- [ ] Загрузить реальные проекты с LoadingState/ErrorState и retry; разделить active и archived/completed по status.
- [ ] При drag-and-drop сначала переставить карточки оптимистично, вызвать один PUT, при ошибке вернуть прежний порядок и показать локальную ошибку рядом с сеткой.
- [ ] Добавить Menu активной карточки с «В архив» и ConfirmDialog; архивная строка получает рабочее «Вернуть в работу».
- [ ] Кнопку «Повторить» оставить видимой, но disabled с пояснением до этапа 9; не вести в mock Cards.
- [ ] Карточки пустого состояния ведут в `/projects/new?track=exam` и `/projects/new?track=textbook`; свободный шаблон недоступен с причиной.
- [ ] Карточка примера показывает только его знак, название, дедлайн при наличии и действия. Никаких захардкоженных процентов, последней сессии или долга; это будут реальные поля следующих этапов.
- [ ] Run: `cd backend && python -m ruff check .`.
- [ ] Run: `npm run typecheck`.
- [ ] Commit: `feat: seed example and connect project lifecycle`.

### Task 5: Подключить экран Program к единому command-модулю

**Files:**
- Modify: `frontend/src/api/projects.ts`
- Modify: `frontend/src/screens/Program.tsx`
- Create: `frontend/src/screens/programTree.ts`

**Interfaces:**
- Consumes: Program routes, ProgramChangeResult и ActionUndoResult from §5; active экран всегда передаёт текущий `program_revision` обычным командам.
- Produces: `buildProgramTree(nodes)`, `flattenProgramTree(tree)` and `visibleHiddenRoots(tree)` as pure helpers shared by Program, Wizard and Workspace.

- [ ] Добавить в projects.ts create/update/move/target/remove/restore/undo с точными command types; функции не принимают raw `Record<string, unknown>`.
- [ ] В Program загружать ProjectDetail по route id и выбирать экзаменационное/учебниковое представление по `workspace_variant`, не по query.
- [ ] В `programTree.ts` один helper строит дерево из плоских API nodes, проверяет отсутствующего parent и повторяющийся id, выдаёт нумерованный depth-first порядок; неизвестный parent переводит экран в ErrorState, а не молча делает корнем.
- [ ] `visibleHiddenRoots` возвращает только верхние hidden roots; потомки не дублируются в Disclosure и не могут быть восстановлены отдельно.
- [ ] Реализовать add, rename on blur, type/exam_kind, target level по поддереву, move up/down, indent/outdent, remove/restore и undo. Во время одной команды блокировать только действия дерева, чтение и навигацию не блокировать.
- [ ] Сохранить действие «Продублировать» без нового endpoint: public create копирует только выбранный узел (не subtree), ставит `${title} — копия`, того же parent/свойства, position сразу после исходного и server-owned origin=manual.
- [ ] Обычная команда отправляет текущий program_revision, undo — sequence показанного latest action. Успешный ProgramChangeResult или его `program` из ActionUndoResult целиком заменяет nodes/revision/latest action; при stale revision/sequence показать reload conflict, при другой ошибке оставить прежнее server state.
- [ ] Перед add на клиенте сравнить `title.trim().toLocaleLowerCase("ru")` с загруженными узлами проекта: точное совпадение показать как предупреждение с действием «Всё равно добавить». Объединение и семантический поиск похожих тем не имитировать до появления связанных данных.
- [ ] Убранные exam-узлы не превращать в столбец/фильтр: показывать отдельный Disclosure «Убрано из списка» только когда такие узлы есть; у каждой строки одно действие «Вернуть». Для textbook использовать предусмотренный фильтр «Вне текущей программы».
- [ ] Все disabled-операции объяснить: модельная группировка и помощник скрыты до этапа 7; фиктивные counts «эталон/материалы/план» убрать.
- [ ] В project navigation оставить рабочими Рабочую область, Программу и Настройки; Материалы, План, Карточки и Уроки показать недоступными с указанием своего этапа, а не вести реальный project id в mock-экран.
- [ ] EmptyState предлагает импортировать список для exam или добавить первую тему вручную для textbook draft.
- [ ] После каждого успешного действия использовать серверный ответ как новое состояние; при ошибке не оставлять оптимистическую копию.
- [ ] Run: `npm run typecheck`.
- [ ] Commit: `feat: persist program edits with undo`.

### Task 6: Перевести базовую Рабочую область на ProjectDetail и WorkspaceState

**Files:**
- Modify: `frontend/src/screens/ProjectWorkspace.tsx`
- Modify: `frontend/src/screens/programTree.ts`
- Modify: `frontend/src/screens/workspaceDemo.ts` only if exports must be separated for Lessons
- Modify: `frontend/src/styles/layout.css`

**Consumes:** `getProject`, `saveWorkspaceState`, `ProjectDetail.program`.

- [ ] Удалить `resolveWorkspaceProject` из ProjectWorkspace; route id всегда загружает API, 404 показывает ErrorState с переходом к Проектам.
- [ ] Построить WorkspaceNode через общий `programTree.ts` только из ProgramNode: number, structural type, title, children, `no-material`; не создавать второй алгоритм дерева и demo-answer/source/attempt/conspect.
- [ ] Выбрать первый current/non-archived `topic/subpoint`; query `topic` имеет приоритет только если id принадлежит проекту и удовлетворяет тем же условиям, section/hidden/чужой id игнорируется.
- [ ] Если изучаемых узлов нет, selected_node_id остаётся null и Рабочая область показывает EmptyState со ссылкой в Program; section автоматически как тема не выбирается.
- [ ] Восстановить серверные selected/expanded/tree width/groups/weights; неизвестные/вне программы id отфильтровать и сохранить исправленную раскладку.
- [ ] Изменения выбора, раскрытия и вкладок сохранять через одну последовательную очередь; debounce 400 мс оставить только для resize, где теряется не доменный факт, а несколько пикселей раскладки.
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

**Consumes:** общий draft hook; все Program commands идут через `enqueueProgramCommand` и текущий program revision.

- [ ] Удалить `INITIAL_SOURCES`, `INITIAL_PROGRAM`, mock generation, progress, стоимость, помощника и предложения-дифы.
- [ ] Шаг 1 показывает EmptyState: файлы ещё не загружаются; основное действие «Собрать программу вручную», вторичное «Вернуться к выбору».
- [ ] Сохранить в Project/GoalPassport реальные name, subject, scope, goal, starting level/knowledge, target outcome, success criterion, important, excluded, deadline, rhythm, study format и modules.
- [ ] Шаг ручной Программы использует те же серверные узлы и операции, что active Program; каждая операция передаёт program revision, принимает program+draft revisions из ответа и не держит отдельную каноническую копию дерева.
- [ ] Сохранить три представления одних ProgramNode: «Дерево» — иерархия, «Текст» — нумерованный depth-first список, «Вопросы» — topic/subpoint как `Объясните тему: {title}` (готовый title с `?` не меняется). Проекция не сохраняется и позже уступит реальным активностям без миграции ProgramNode.
- [ ] После перезагрузки восстановить current/max step и выбранный узел из серверного draft/UI state.
- [ ] Итог показывает только реально сохранённые паспорт, модули и дерево; блока «Источники сохранены» нет.
- [ ] Основная кнопка «Сохранить черновик и выйти» делает flush и ведёт в Проекты; activate не вызывается.
- [ ] На входе в мастер этот draft доступен через «Продолжить учебниковый черновик».
- [ ] Не добавлять material-check в общий activate endpoint: на этапе 5 учебниковая ветка проверит ProjectMaterial в своём orchestration до вызова существующей активации.
- [ ] Run: `npm run typecheck`.
- [ ] Commit: `feat: persist textbook planning draft`.

### Task 8: Убрать ложные данные, сохранив реальный seed-пример

**Files:**
- Modify: `frontend/src/app/AppLayout.tsx`
- Modify: `frontend/src/app/CommandPalette.tsx`
- Modify: `frontend/src/app/screens.ts`
- Modify: `frontend/src/screens/Projects.tsx`
- Modify: `frontend/src/screens/Program.tsx`
- Modify: `frontend/src/screens/ProjectWorkspace.tsx`

- [ ] Удалить DEMO_COVERAGE, DEMO_RECENT_TOPICS и DEMO_TASKS; покрытие и последние темы скрыть до появления данных, фон показывает «Фон свободен». Сам пример остаётся через `listProjects`.
- [ ] Убрать фиктивные 14 файлов/1,8 ГБ, mock model names, bot status и backup date; оставить только факты, которые умеет подтвердить `/api/health`, либо нейтральное «не настроено».
- [ ] В CommandPalette заменить DEMO_PROJECTS настоящим `listProjects`, убрать DEMO_FILES до этапа 5 и исключить project-specific `SCREENS` без реального project id; seed-пример находится обычным поиском по server response. Ошибка project fetch не ломает поиск по глобальным экранам.
- [ ] Обновить подпись бренда «этап 1» на нейтральную версию без номера этапа.
- [ ] Убрать использование DEMO_PROJECT_ID/DEMO_TEXTBOOK_PROJECT_ID из реальных переходов; фиксированный UUID существует только в backend demo.py и не импортируется экраном.
- [ ] Поискать ложные данные: `rg -n "DEMO_|mock|Появится вместе с API|данные выдуманные|localStorage" frontend/src/app frontend/src/screens/ProjectWizard.tsx frontend/src/screens/project-wizard frontend/src/screens/TextbookWizard.tsx frontend/src/screens/Projects.tsx frontend/src/screens/Program.tsx frontend/src/screens/ProjectWorkspace.tsx`.
- [ ] Для каждого совпадения либо удалить его, либо подтвердить, что оно относится только к изолированному экрану будущего этапа и недоступно из живого пути. Настоящие seeded rows словом mock не помечаются.
- [ ] Run: `npm run typecheck`.
- [ ] Commit: `chore: remove stage 3 demo fallbacks`.

### Task 9: Сквозная проверка, браузер и архитектурный итог

**Files:**
- Create: `backend/scripts/check_stage3.py`
- Modify: `docs/architecture/stage-2-core.md`
- Modify: `docs/architecture/stage-3-live-projects.md`
- Modify: `README.md` only to add the stage 3 smoke command if stage 3 is accepted as complete

- [ ] На чистой временной БД с default config проверить ровно один seeded Project с ожидаемыми GoalPassport/ProgramNode/WorkspaceState, отсутствие action rows и открытие через обычный GET. После restart UUID, row counts и updated_at не меняются.
- [ ] Отдельно запустить существующий stage2 сценарий с `TENTEX_SEED_DEMO_PROJECT=false`, чтобы empty-install и prerequisite продолжали проверяться независимо от fixture.
- [ ] Проверить импорты: нумерованные и ненумерованные вопросы, вопросы+задачи, билеты с многострочным пунктом и предупреждением о дубле; пустой/слишком большой input и tickets без заголовка дают 422; import undo после restart возвращает прежние UUID и parent links.
- [ ] Проверить `stale_draft_revision`, `stale_program_revision` и `stale_action_sequence` как code+context, возобновление после restart, активацию exam и отсутствие draft в active list. Program revision при активации не сбрасывается.
- [ ] Активировать два черновика и assert, что Project.sort_order назначен сервером как плотные разные позиции; присланный extra sort_order в draft payload отклоняется 422.
- [ ] Проверить server-derived workspace_variant, 422 для переданного extra variant/неизвестной icon, 409 unsupported_template для free и нормализацию повторяющихся enabled_modules.
- [ ] Создать ещё один active project, проверить static `/projects/order`, archive, повторный archive, restart, restore, повторный restore и 409 completed.
- [ ] Проверить create default target_level, rename, move внутри/между siblings, indent/outdent, полный subtree depth, target level subtree, remove, запрет restore descendant, restore root, restart, latest undo и восстановленное дерево.
- [ ] После каждой Program command assert: revision вырос ровно на 1, `(project_id,parent_id,sort_order)` не дублируется, sort_order плотный, журнал имеет возрастающий sequence/phase/payload_version=1.
- [ ] Для textbook draft проверить structural conflict, обе новые revisions в ответе, variant validation `exam_kind=null`, undo ручной правки после restart и отсутствие Material rows.
- [ ] Проверить settings и workspace layout после ещё одного restart; layout save не меняет Project.updated_at. Выполнить SQLite `foreign_key_check`, WAL, unique `(project_id,id)` и Alembic head.
- [ ] Run: `python backend/scripts/check_stage2.py`; expected: `stage 2 smoke check passed`.
- [ ] Run: `python backend/scripts/check_stage3.py`; expected: `stage 3 smoke check passed`.
- [ ] Run: `cd backend && python -m ruff check .`; expected: exit 0.
- [ ] Run: `npm run typecheck`; expected: exit 0.
- [ ] Run: `npm run build`; expected: exit 0.
- [ ] Run: `docker compose restart web`; expected: container restarts successfully.
- [ ] В браузере сначала открыть seeded пример из Projects/CommandPalette, изменить Program, undo после reload и архивировать/восстановить — никаких специальных demo-переходов.
- [ ] В браузере пройти exam questions и tickets, reload мастера, activation, reorder/archive/restore, все ручные операции Program, конфликт второй вкладки, settings и workspace layout после reload.
- [ ] В браузере пройти textbook draft, reload и «Сохранить черновик и выйти»; убедиться, что active project не создан и demo-источники не появились.
- [ ] Дописать архитектурный документ фактическими маршрутами, таблицей action types, диаграммой потока и командами проверки.
- [ ] В stage-2-core.md не менять объяснение выполненного этапа 2; у устаревшей API-таблицы добавить короткую пометку «актуальный contract после оживления — stage-3-live-projects.md».
- [ ] Обновить `README.md` только после всех свежих проверок.
- [ ] Commit: `docs: record stage 3 live project architecture`.

## 7. Ручные примеры для проверки импорта

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

## 8. Финальный gate этапа

Этап 3 нельзя считать завершённым, если выполняется хотя бы одно условие:

- произвольный route id получает подменённый пример вместо 404 или frontend читает пример не через обычный API;
- повторный startup перезаписывает изменённый пользователем seed-пример или создаёт второй;
- Project/Program/Workspace восстанавливаются только из `localStorage`;
- мастер показывает «сохранены» для ответа или файла, которого нет в Material/ProjectMaterial;
- stage-3 UI учебниковой ветки вызывает activate или заявляет о сохранённых источниках; общий source-neutral endpoint при этом не получает ложный material-инвариант;
- удаление ProgramNode физически стирает строку;
- undo исчезает после перезапуска;
- drag-and-drop оставляет дубли `sort_order`;
- create/PATCH принимает server-owned `sort_order`, visibility или origin;
- draft save или settings принимает Project.sort_order, либо activation оставляет дубли порядка карточек;
- клиент может передать workspace_variant отдельно от template_key или сохранить неизвестную icon/дубли enabled_modules;
- PUT /settings возвращает Program nodes или WorkspaceState;
- мутация программы проходит без compare-and-increment `Project.program_revision`;
- мутация программы черновика не увеличивает также `WizardDraft.revision`;
- клиент разбирает русский текст 409 вместо стабильного error code;
- общий undo требует только program-specific revision вместо sequence видимого действия;
- action log выбирает последнее действие по timestamp, не имеет phase/payload_version или хранит большие blobs;
- импорт списка нельзя отменить после перезапуска;
- Program выбирает variant из query;
- на живом пути видны фиктивные метрики, источники, попытки, модели или фоновые задачи; реальные seeded Project/GoalPassport/ProgramNode к фиктивным не относятся;
- `check_stage2.py`, `check_stage3.py`, ruff, typecheck или build не прошли свежим запуском.

## 9. Параллельная разведка главной идеи (не блокирует этап 3)

Разведку из `PLAN.md:90-105` не смешивать с production-кодом этапа 3. После основного вертикального среза выполнить отдельной короткой задачей:

1. Во временном окружении поставить PyMuPDF, не добавляя его в `backend/requirements.txt` до этапа 5.
2. Одноразовым скриптом прочитать первые 30 содержательных страниц методички, выделить блоки по заголовкам и отправить несколько размеров batch в один выбранный OpenAI-compatible endpoint через переменные окружения.
3. Записать в `docs/research/pass2-feasibility.md`: качество границ блоков, типовые промахи, приемлемый batch size, число предполагаемых вызовов и стоимость полного учебника с датой цены.
4. Удалить одноразовый скрипт; в production не переносить его парсер или клиент модели.

Эта разведка может изменить этапы 5/8, но не API проектов и программы этапа 3.
