# Stage 2 Core Data and API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Создать минимальное устойчивое ядро данных и API Tentex: черновик мастера переживает перезапуск, проект активируется с паспортом цели и деревом программы, а активный проект и раскладка Рабочей области снова открываются без потери данных.

**Architecture:** Один синхронный процесс FastAPI работает через SQLAlchemy 2 с одним SQLite-файлом в WAL; Alembic является единственным способом создания и изменения схемы и автоматически доводит локальную базу до `head` при старте API. Модуль `projects` предоставляет интерфейс в терминах пользовательских действий, а не универсальный CRUD; доменные сущности имеют собственные таблицы, а JSON используется только для ограниченных списков, раскладки и веточного ввода, который не дублируется в других полях.

**Tech Stack:** Python 3.13 · FastAPI · Pydantic 2 · SQLAlchemy 2 · Alembic · SQLite WAL · стандартные `uuid`, `datetime`, `subprocess`, `urllib`

## Global Constraints

- Tentex работает локально, офлайн, для одного пользователя на установку.
- Целевая версия Python — **3.13**; локальная 3.14 допустима для этапов 0–4.
- SQLite работает в режиме **WAL**, внешняя серверная БД не добавляется.
- Миграции — единственный источник физической схемы; `Base.metadata.create_all()` не используется.
- Программа первична: активный проект с программой и без материалов является корректным.
- Шаблон проекта — пресет, а не класс сущности; ORM-наследование `ExamProject`/`TextbookProject` запрещено.
- Русский используется в текстах для пользователя и документации, английский — в идентификаторах и JSON API.
- TDD и сплошное покрытие на этом этапе выключены; остаётся один исполняемый сквозной smoke-check без тестового фреймворка.
- Не добавлять async ORM, repository interface, generic CRUD, event bus, DI-контейнер и фонового воркера.
- Не реализовывать загрузку/разбор файлов, импорт текста, undo, привязки, Уроки, активности, повторения и подключение React-экранов: это этапы 3–9.
- Не изменять и не восстанавливать посторонние пользовательские правки в грязном worktree.

---

## 1. Итоги критики предыдущего варианта

| Проблема | Почему опасно | Исправленное решение |
|---|---|---|
| `Project.mode = exam/textbook/free` выглядел как жёсткий тип проекта | Противоречит FR-P7: шаблон должен задавать начальные настройки, а не отдельную модель и закрытый набор поведения | Хранить `template_key` как происхождение пресета и отдельно `workspace_variant` как настройку представления; все проекты остаются одной сущностью |
| Для учебника и экзамена с неизвестным списком материал попадал в общий инвариант активации | Нарушает П1 и делает ядро зависимым от конкретной ветки мастера | Ядро требует паспорт и изучаемый узел; ветка мастера сама не даёт дойти до активации без обязательного для неё источника |
| Канонические поля предлагалось одновременно нормализовать и дублировать в `WizardDraft.payload` | Два источника истины рано или поздно расходятся при автосохранении | Project, GoalPassport и ProgramNode хранятся только в своих таблицах; JSON черновика владеет только сырым вводом и UI-состоянием, которое больше нигде не хранится |
| «Вставил список → открыл Рабочую область» был назван результатом этапа 2 | Разбор текста и подключение React запланированы на этап 3 | Этап 2 демонстрирует тот же жизненный цикл через API с уже разобранными узлами; настоящий экранный путь появляется на этапе 3 |
| `ProgramNode.type` мог смешать `section/topic/subpoint` с `ticket/question/task` | Структура дерева и экзаменационная семантика — разные оси; смешение ломает учебниковую ветку | `node_type` хранит только структуру, `exam_kind` — необязательную экзаменационную семантику |
| В `WorkspaceState` могли попасть конспекты, пометки и снятые привязки | Эти данные имеют собственный жизненный цикл, источники и будущий undo; JSON раскладки стал бы скрытой второй БД | На этапе 2 сохраняются только навигация и раскладка; доменные данные получают собственные сущности на своих этапах |
| `Material` заранее получил подробные статусы OCR и качества | Реальный жизненный цикл конвейера проектируется на этапе 5 и сейчас ещё неизвестен | Сейчас фиксируется только стабильная файловая идентичность; статусы разбора и качество добавляет миграция этапа 5 |
| В этапе 3 повторно упоминались база, миграции и слой доступа | Размывалась граница готовности этапа 2 | `PLAN.md` уточнён: база и API завершаются на этапе 2, этап 3 подключает экраны и импорт |

Решения, которые выдержали повторную проверку: UUID из стандартной библиотеки, синхронный SQLAlchemy, Alembic, автоматический `upgrade head`, WAL, один модуль действий без repository interface.

## 2. Проверяемый срез и границы

Сквозная проверка этапа 2:

1. Создать черновой экзаменационный Project и связанный WizardDraft.
2. Сохранить название, настройки проекта, GoalPassport и сырой текст мастера.
3. Создать раздел и тему через API ProgramNode.
4. Сохранить минимальную раскладку WorkspaceState.
5. Перезапустить API и возобновить черновик с теми же данными.
6. Активировать проект одной транзакцией; WizardDraft исчезает, канонические данные остаются.
7. Ещё раз перезапустить API, получить проект в списке и открыть его с деревом и раскладкой.

Этап не включает парсер списка. Smoke-check отправляет уже разделённые узлы ровно так, как на этапе 3 их отправит импортёр.

## 3. Концептуальная модель

```mermaid
erDiagram
    Project ||--o| WizardDraft : "имеет, пока status=draft"
    Project ||--o| GoalPassport : "имеет"
    Project ||--o{ ProgramNode : "содержит"
    ProgramNode ||--o{ ProgramNode : "родитель"
    Project ||--o| WorkspaceState : "сохраняет раскладку"
    Project ||--o{ ProjectMaterial : "использует"
    Material ||--o{ ProjectMaterial : "переиспользуется"

    Project {
        uuid id PK
        string template_key
        string workspace_variant
        string status
        string name
        date deadline
        json enabled_modules
    }
    WizardDraft {
        uuid project_id PK_FK
        int current_step
        int max_completed_step
        int revision
        int schema_version
        json state
    }
    GoalPassport {
        uuid project_id PK_FK
        string subject
        string purpose
        string starting_level
        string target_outcome
        string study_format
    }
    ProgramNode {
        uuid id PK
        uuid project_id FK
        uuid parent_id FK
        string node_type
        string exam_kind
        int sort_order
        string title
        string origin_kind
    }
    Material {
        uuid id PK
        string sha256 UK
        string storage_path UK
        string original_name
        int size_bytes
    }
    ProjectMaterial {
        uuid project_id PK_FK
        uuid material_id PK_FK
        string source_role
        int priority
        bool affects_program
    }
    WorkspaceState {
        uuid project_id PK_FK
        int schema_version
        json layout
    }
```

### 3.1. Физические поля первого среза

**Project**

- `id: UUID` — UUIDv4, создаётся сервером.
- `template_key: exam | textbook | free` — от какого встроенного пресета начат проект; не выбирает ORM-класс.
- `workspace_variant: exam | textbook` — какая конфигурация одной Рабочей области используется; свободный шаблон позже использует развёрнутую `textbook`-конфигурацию.
- `status: draft | active | archived | completed`.
- `name: str | null` — в черновике может отсутствовать, при активации обязателен.
- `description: str | null`, `icon: str | null`, `color: str | null`.
- `sort_order: int >= 0`.
- `deadline: date | null` — единственное каноническое место срока; в GoalPassport не дублируется.
- `enabled_modules: list[str]` — JSON-массив включённых модулей, без отдельной таблицы ради нескольких переключателей.
- `status_changed_at: datetime | null`, `created_at`, `updated_at` — UTC.

**WizardDraft**

- `project_id: UUID` — одновременно PK и FK на Project с `ON DELETE CASCADE`.
- `current_step: int` и `max_completed_step: int`, диапазон 1–5.
- `revision: int >= 0` — защита автосохранения от запоздавшей записи; каждое успешное PUT увеличивает значение.
- `schema_version: int`, первая версия `1`.
- `state: JSON object` — только выбранные способы ввода, вставленный сырой текст, временные предупреждения и другие веточные поля, которых нет в нормализованных таблицах.
- `updated_at: datetime` — для списка возобновляемых черновиков.

**GoalPassport**

- `project_id: UUID` — PK/FK.
- `subject`.
- `purpose: exam | work | interview | interest`.
- `scope: whole | goal | null`.
- `starting_level: beginner | familiar | refreshing` и `current_knowledge`.
- `target_outcome: awareness | understanding | application | mastery`.
- `goal`, `success_criterion`, `important`, `excluded`.
- `study_format: theory | theory_and_practice | practice`.
- `minutes_per_day`, `days_per_week`, `session_minutes` — положительные числа; дней в неделю 1–7.
- `exam_format: questions | questions_tasks | tickets | unknown | null`.
- `expected_item_count: int | null`, `instructor_requirements: str | null`.
- `updated_at`.

**Material**

- `id: UUID`, `sha256: 64 lowercase hex` с UNIQUE.
- `original_name`, `storage_path` с UNIQUE; путь хранится относительно `settings.storage_dir`.
- `media_type`, `size_bytes`, `page_count | null`, `created_at`.
- Нет полей OCR, качества, прогресса и ошибки: их семантика появится вместе с конвейером этапа 5.

**ProjectMaterial**

- Составной PK `(project_id, material_id)`.
- `source_role: main | additional | reference`.
- `priority: int >= 0`, `affects_program: bool`, `instruction: str | null`, `created_at`.
- Роль источника не смешивается с экзаменационными ролями «список вопросов» и «готовые ответы»; последние остаются входом импорта.

**ProgramNode**

- `id: UUID`, `project_id: UUID`, `parent_id: UUID | null`.
- UNIQUE `(project_id, id)` и составной FK `(project_id, parent_id) -> (project_id, id)` гарантируют, что родитель находится в том же проекте.
- `node_type: section | topic | subpoint` — структурная ось.
- `exam_kind: question | task | ticket | null` — необязательная экзаменационная ось.
- `sort_order: int >= 0`, `title`, `section_purpose | null`.
- `goal_role: target | prerequisite | related | null`.
- `target_level: awareness | understanding | application | mastery | null`.
- `is_in_current_program`, `needs_material`, `is_archived`.
- `origin_kind: manual | import | outline | pass1 | catalog | model` и `origin_note | null`.
- `created_at`, `updated_at`.
- Не хранятся `depth`, иерархический номер и статус освоения: они вычисляются из дерева и будущих сущностей.
- Детальные ссылки происхождения на файлы/страницы не прячутся в JSON; отдельная relation добавляется на этапе 5/7, когда появятся Page и Fragment.

**WorkspaceState**

- `project_id: UUID` — PK/FK, потому что пользователь на установке один.
- `schema_version: int`, первая версия `1`.
- `layout: JSON object` с `selected_node_id`, `expanded_node_ids`, `tree_width`, `groups`, `group_weights`.
- Каждый `group` имеет строковый `id`, неповторяющийся список вкладок `answer | source | lesson | conspect | history | chat | summary` и `active_tab`, который равен одной из вкладок группы либо `null`.
- `updated_at`.
- Конспекты, пометки, снятые привязки и результаты занятий сюда не входят.

Физической таблицы User в срезе нет: при фиксированной кратности «один пользователь на установку» внешний ключ не различает ни одной строки и только размножается по схеме. Концептуальный пользователь из §20 остаётся владельцем установки; настройки и Telegram-профиль получат одну запись на своём этапе. Таблицы ProjectTemplate тоже пока нет: `template_key` хранит встроенный пресет, а пользовательские шаблоны FR-P9 добавляются вместе с экраном их сохранения.

### 3.2. Инварианты и переходы

- Project со статусом `draft` имеет WizardDraft; активированный Project его не имеет.
- `POST activate` идемпотентен: повтор для уже активного Project возвращает существующий Project.
- PUT черновика и первая активация принимают `expected_revision`; устаревшая вкладка получает `409`, а не затирает новые данные.
- Активация одной транзакцией проверяет непустое имя, GoalPassport с `subject`, `purpose`, `starting_level`, `target_outcome` и `study_format`, хотя бы один неархивный `topic`/`subpoint` в текущей программе и целостность дерева.
- Наличие Material не является инвариантом активации ядра.
- Родитель ProgramNode принадлежит тому же Project; цикл, ссылка на себя и глубина больше 4 отвергаются до записи.
- Физического удаления ProgramNode и Project в этапе 2 нет. Удаление появится вместе с журналом undo на этапе 3.
- `GET /projects` никогда не возвращает drafts; они доступны только через `/wizard-drafts`.
- Один факт хранится в одном месте: срок — в Project, экзаменационный формат — в GoalPassport, текущий шаг — в WizardDraft, структура — в ProgramNode.
- Все составные записи одного действия сохраняются в одной транзакции; при ошибке частичного состояния не остаётся.

## 4. Интерфейс HTTP

| Метод и путь | Действие экрана | Результат |
|---|---|---|
| `POST /api/wizard-drafts` | Первое содержательное сохранение мастера | Создаёт Project(status=draft) и WizardDraft |
| `GET /api/wizard-drafts` | Предложить продолжить незавершённый мастер | Сводки drafts по `updated_at desc` |
| `GET /api/wizard-drafts/{project_id}` | Возобновить выбранный мастер | Project + WizardDraft + GoalPassport + ProgramNode[] |
| `PUT /api/wizard-drafts/{project_id}` | Атомарно автосохранить поля мастера | Обновляет Project, WizardDraft и upsert GoalPassport без дублирования в JSON |
| `POST /api/wizard-drafts/{project_id}/activate` | «Создать проект» | Принимает `expected_revision`, проверяет инварианты, меняет status, удаляет WizardDraft |
| `GET /api/projects` | Экран «Проекты» | Все active/archived/completed без drafts, отсортированные по `sort_order`, затем имени |
| `GET /api/projects/{project_id}` | Открыть проект | Project + GoalPassport + плоский отсортированный ProgramNode[] + WorkspaceState |
| `POST /api/projects/{project_id}/program-nodes` | Добавить раздел/тему/подпункт | Создаёт один узел после проверки дерева |
| `PATCH /api/projects/{project_id}/program-nodes/{node_id}` | Переименовать, перенести или изменить свойства | Частично обновляет один узел и повторно проверяет дерево |
| `PUT /api/projects/{project_id}/workspace-state` | Автосохранить раскладку | Полностью заменяет версионированную раскладку |

HTTP-ошибки:

- `404` — проект, черновик, узел или родитель не найден.
- `409` — неверный переход состояния или устаревшая `expected_revision`, например попытка сохранить активный проект через draft endpoint или активировать неполный draft.
- `422` — неверное поле запроса, цикл, глубина больше 4, отрицательный порядок или выбранный workspace node из другого проекта.
- `500` при ошибке миграции не маскируется: приложение не начинает принимать запросы.

Пример полного сохранения черновика:

```json
{
  "expected_revision": 0,
  "current_step": 4,
  "max_completed_step": 4,
  "schema_version": 1,
  "project": {
    "name": "Базы данных — экзамен",
    "description": null,
    "icon": "database",
    "color": "blue",
    "sort_order": 0,
    "deadline": "2026-12-15",
    "enabled_modules": ["plan", "cards", "repetitions"]
  },
  "goal_passport": {
    "subject": "Базы данных",
    "purpose": "exam",
    "scope": null,
    "starting_level": "familiar",
    "current_knowledge": "Помню SQL, хуже понимаю нормализацию",
    "target_outcome": "mastery",
    "goal": "Уверенно отвечать на вопросы и решать типовые задачи",
    "success_criterion": "Могу письменно раскрыть случайный вопрос без конспекта",
    "important": "Транзакции и индексы",
    "excluded": null,
    "study_format": "theory_and_practice",
    "minutes_per_day": 120,
    "days_per_week": 6,
    "session_minutes": 50,
    "exam_format": "questions_tasks",
    "expected_item_count": 64,
    "instructor_requirements": "Нужны определения и примеры"
  },
  "state": {
    "question_input_mode": "text",
    "question_text": "1. Архитектура СУБД\n2. Реляционная модель"
  }
}
```

## 5. Карта файлов

```text
backend/
  alembic.ini                         конфигурация миграций с путём от backend/
  migrations/
    env.py                            metadata SQLAlchemy и SQLite batch mode
    script.py.mako                    шаблон ревизии
    versions/
      20260806_0001_stage2_core.py    первая физическая схема
  app/
    config.py                         существующие data/storage paths
    db.py                             engine, PRAGMA, SessionLocal, migration bootstrap
    models.py                         семь ORM-моделей и доменные enum
    main.py                           lifespan и подключение projects router
    projects/
      __init__.py
      schemas.py                      Pydantic-команды и ответы
      service.py                      транзакции и доменные инварианты
      router.py                       тонкий HTTP-адаптер
  scripts/
    check_stage2.py                   один сквозной smoke-check с перезапусками
docs/
  architecture/
    stage-2-core.md                   схема и объяснение решений для записки/защиты
```

Не создавать `repositories.py`, `unit_of_work.py`, `interfaces.py`, `exceptions.py` и отдельный файл на каждую модель. Реальная seam находится у функций `projects.service`; SQLAlchemy — единственная реализация хранения.

---

### Task 1: Database runtime and migration bootstrap

**Files:**

- Modify: `backend/requirements.txt`
- Modify: `backend/pyproject.toml`
- Create: `backend/app/db.py`
- Create: `backend/alembic.ini`
- Create: `backend/migrations/env.py`
- Create: `backend/migrations/script.py.mako`

**Interfaces:**

- Consumes: `settings.database_path`, `settings.data_dir`, `settings.storage_dir` from `app.config`.
- Produces: `Base`, `engine`, `SessionLocal`, `get_session()`, `upgrade_database()`.

- [ ] **Step 1: Add only the database dependencies**

Add to `backend/requirements.txt`:

```text
sqlalchemy>=2.0,<3
alembic>=1.16,<2
```

Change Ruff `target-version` from `py312` to `py313`. Do not add `aiosqlite`, SQLModel, pytest or httpx.

- [ ] **Step 2: Install the backend environment used for verification**

Run from the repository root:

```powershell
python -m pip install -r backend/requirements-dev.txt
```

Expected: SQLAlchemy, Alembic and the existing FastAPI dependencies install successfully under local Python.

- [ ] **Step 3: Implement `app.db`**

Use SQLAlchemy 2 typed declarative base and one sync engine. Required shape:

```python
class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


engine = create_engine(
    URL.create("sqlite+pysqlite", database=str(settings.database_path)),
    connect_args={"autocommit": False, "check_same_thread": False, "timeout": 5},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
```

On every DBAPI connection, temporarily enable autocommit and execute exactly:

```sql
PRAGMA foreign_keys=ON;
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
```

Restore the prior `autocommit` value. `upgrade_database()` must build an Alembic `Config` from an absolute path and call `command.upgrade(config, "head")`; it must not catch migration failures.

- [ ] **Step 4: Configure Alembic for SQLite**

`migrations/env.py` imports `Base.metadata` and imports `app.models` so all tables register. Configure autogenerate with:

```python
context.configure(
    connection=connection,
    target_metadata=target_metadata,
    compare_type=True,
    render_as_batch=True,
)
```

The database URL comes from `settings.database_path`, not from a committed machine-specific path. CLI migration path creates `settings.data_dir` before opening SQLite, so a clean installation needs no manual directory setup.

- [ ] **Step 5: Verify imports and configuration**

Run:

```powershell
cd backend
python -c "from app.db import Base, SessionLocal; print(Base.metadata.naming_convention['pk'], SessionLocal.kw['expire_on_commit'])"
python -m ruff check app/db.py migrations/env.py
```

Expected: prints `pk_%(table_name)s False`; Ruff exits 0.

### Task 2: ORM model and initial migration

**Files:**

- Create: `backend/app/models.py`
- Create: `backend/migrations/versions/20260806_0001_stage2_core.py`

**Interfaces:**

- Consumes: `Base` from `app.db`.
- Produces: `Project`, `WizardDraft`, `GoalPassport`, `Material`, `ProjectMaterial`, `ProgramNode`, `WorkspaceState` and their `StrEnum` values.

- [ ] **Step 1: Declare stable enum vocabulary**

Use Python `StrEnum` with the exact external values listed in §3.1. Add `ModuleKey` with current values `plan`, `lessons`, `cards`, `repetitions`, `oral_answers`, `sql`. SQLAlchemy enum columns use `native_enum=False`, named CHECK constraints, and `validate_strings=True`. Keep display labels out of the backend.

- [ ] **Step 2: Declare the seven ORM models**

Use SQLAlchemy 2 `Mapped[...]` and `mapped_column()`. Implement every field, uniqueness rule, FK action and CHECK described in §3.1. Project-owned rows cascade only on a future physical Project deletion; `ProjectMaterial.material_id` and the ProgramNode parent use `ON DELETE RESTRICT`. Store timestamps as naive SQLite DateTime values that are always interpreted as UTC, produced by one `utc_now()` helper. Include indexes:

```python
Index("ix_projects_status_sort_order", Project.status, Project.sort_order)
Index("ix_wizard_drafts_updated_at", WizardDraft.updated_at)
Index("ix_program_nodes_project_parent_order", ProgramNode.project_id, ProgramNode.parent_id, ProgramNode.sort_order)
Index("ix_project_materials_project_priority", ProjectMaterial.project_id, ProjectMaterial.priority)
```

Use `Uuid(as_uuid=True)` and `default=uuid4`. JSON list/dict defaults must be callables (`default=list`, `default=dict`), never shared mutable values.

- [ ] **Step 3: Generate the initial revision**

From `backend/` with an empty temporary data directory:

```powershell
$env:TENTEX_DATA_DIR = Join-Path $env:TEMP 'tentex-stage2-plan-check'
New-Item -ItemType Directory -Force -Path $env:TENTEX_DATA_DIR | Out-Null
python -m alembic revision --autogenerate -m "create stage 2 core"
```

Rename the generated revision file to `20260806_0001_stage2_core.py` while preserving its generated revision id. Review the migration: exactly seven domain tables plus `alembic_version`; no `create_all`, Page, Fragment, Binding, User or job tables.

- [ ] **Step 4: Apply and inspect the schema**

Run:

```powershell
python -m alembic upgrade head
python -c "import os, sqlite3; from pathlib import Path; db=Path(os.environ['TENTEX_DATA_DIR'])/'tentex.sqlite'; c=sqlite3.connect(db); assert c.execute('PRAGMA journal_mode').fetchone()[0]=='wal'; assert c.execute('PRAGMA foreign_key_check').fetchall()==[]; print([r[0] for r in c.execute(\"select name from sqlite_master where type='table' order by name\")])"
```

Expected: the listed tables match the revision and both assertions pass.

- [ ] **Step 5: Verify migration reversibility on disposable data**

Run against the same temporary directory:

```powershell
python -m alembic downgrade base
python -m alembic upgrade head
```

Expected: both commands exit 0. Never run downgrade against the real `data/` directory.

### Task 3: Typed request and response contracts

**Files:**

- Create: `backend/app/projects/__init__.py`
- Create: `backend/app/projects/schemas.py`

**Interfaces:**

- Consumes: enum classes from `app.models`.
- Produces: `WizardDraftCreate`, `WizardDraftWrite`, `ActivateWizardDraft`, `WizardDraftSummary`, `WizardDraftDetail`, `ProgramNodeCreate`, `ProgramNodeUpdate`, `WorkspaceStateWrite`, `ProjectSummary`, `ProjectDetail`.

- [ ] **Step 1: Create one strict schema base**

```python
class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
```

All write schemas inherit it. Use `Field` for nonblank strings, nonnegative `sort_order`, steps 1–5, positive minute counts and days 1–7.

- [ ] **Step 2: Model draft commands without duplicate ownership**

`WizardDraftCreate` contains only `template_key` and `workspace_variant`. `WizardDraftWrite` contains `expected_revision`, `current_step`, `max_completed_step`, `schema_version`, `project`, optional `goal_passport`, and `state: dict[str, JsonValue]`. `ActivateWizardDraft` contains only `expected_revision`. The `project` object does not repeat template/workspace keys; they remain stable Project settings created with the draft.

- [ ] **Step 3: Model program and workspace commands**

`ProgramNodeUpdate` makes every editable field optional and the service uses `model_fields_set` so omitted values differ from explicit `null`. `WorkspaceStateWrite` contains:

```python
class WorkspaceLayout(ApiModel):
    selected_node_id: UUID | None = None
    expanded_node_ids: list[UUID] = Field(default_factory=list)
    tree_width: int = Field(default=320, ge=260, le=460)
    groups: list[WorkspaceGroup]
    group_weights: list[float]


class WorkspaceStateWrite(ApiModel):
    schema_version: Literal[1]
    layout: WorkspaceLayout
```

Validate 1–3 groups, positive weights and equal `groups`/`group_weights` lengths. No notes or conspects.

- [ ] **Step 4: Model aggregate responses**

`WizardDraftDetail` returns `project`, `draft`, nullable `goal_passport`, and sorted `program_nodes`. `ProjectDetail` returns the same canonical Project/GoalPassport/ProgramNode shapes plus nullable WorkspaceState. Never return raw SQLAlchemy objects after their Session closes.

- [ ] **Step 5: Verify schema examples**

Run:

```powershell
cd backend
python -c "from app.projects.schemas import WizardDraftWrite; assert WizardDraftWrite.model_json_schema()['additionalProperties'] is False; print('schemas ok')"
python -m ruff check app/projects/schemas.py
```

Expected: `schemas ok`; Ruff exits 0.

### Task 4: Project and draft lifecycle module

**Files:**

- Create: `backend/app/projects/service.py`

**Interfaces:**

- Consumes: `Session`, ORM models, schemas.
- Produces:

```python
def create_wizard_draft(session: Session, command: WizardDraftCreate) -> WizardDraftDetail: ...
def list_wizard_drafts(session: Session) -> list[WizardDraftSummary]: ...
def get_wizard_draft(session: Session, project_id: UUID) -> WizardDraftDetail: ...
def save_wizard_draft(session: Session, project_id: UUID, command: WizardDraftWrite) -> WizardDraftDetail: ...
def activate_wizard_draft(session: Session, project_id: UUID, expected_revision: int) -> ProjectDetail: ...
def list_projects(session: Session) -> list[ProjectSummary]: ...
def get_project(session: Session, project_id: UUID) -> ProjectDetail: ...
```

- [ ] **Step 1: Add three local error types in `service.py`**

Create `ProjectNotFoundError`, `ProjectConflictError`, and `ProjectInvariantError` with a human-readable Russian message. Do not create a separate exception hierarchy file.

- [ ] **Step 2: Implement aggregate readers**

Use explicit SQLAlchemy `select()` statements ordered by `(parent_id is not null, parent_id, sort_order, id)`. Build response schemas while the Session is open. `list_projects` filters out `draft`; `list_wizard_drafts` includes only projects that are still `draft` and orders by newest WizardDraft first.

- [ ] **Step 3: Implement create and full draft save**

Each public write function owns one `with session.begin():` transaction. Create inserts Project and WizardDraft together with `revision=0`. Save first performs an atomic `UPDATE wizard_drafts SET revision = revision + 1 WHERE project_id = :id AND revision = :expected`; zero affected rows becomes `ProjectConflictError`. It then updates only Project-owned fields, updates WizardDraft-owned fields, and upserts GoalPassport only when the command contains it. This acquires SQLite's single writer before canonical rows change and prevents two overlapping autosaves from both accepting one revision. It never copies canonical fields into `WizardDraft.state`.

- [ ] **Step 4: Implement activation**

Inside one transaction:

1. Load Project.
2. If Project is already `active`, return current ProjectDetail without looking for the already removed WizardDraft.
3. Atomically bump WizardDraft revision with the same expected-revision condition as save; reject zero affected rows, `archived`/`completed` and incomplete drafts with `ProjectConflictError`. The later delete makes the increment unobservable; a validation failure rolls the whole transaction back.
4. Require a nonblank Project.name, GoalPassport with common structured fields, and at least one current nonarchived `topic` or `subpoint`.
5. Run the complete tree validation from Task 5.
6. Set status to `active`, set `status_changed_at`, delete WizardDraft, update timestamp, commit.

Do not check Material count.

- [ ] **Step 5: Exercise lifecycle through the module**

Using a disposable `TENTEX_DATA_DIR`, run a short `python -c` that creates a draft, saves its Project and GoalPassport, confirms a repeated save with revision 0 is rejected, confirms `list_projects()` is empty, and confirms activation fails before a topic exists. Expected: both failures are `ProjectConflictError`, and the draft remains readable after rollback.

### Task 5: Program tree and WorkspaceState invariants

**Files:**

- Modify: `backend/app/projects/service.py`

**Interfaces:**

- Produces:

```python
def create_program_node(session: Session, project_id: UUID, command: ProgramNodeCreate) -> ProgramNodeRead: ...
def update_program_node(session: Session, project_id: UUID, node_id: UUID, command: ProgramNodeUpdate) -> ProgramNodeRead: ...
def save_workspace_state(session: Session, project_id: UUID, command: WorkspaceStateWrite) -> WorkspaceStateRead: ...
```

- [ ] **Step 1: Implement one ancestor-walk validator**

The private validator accepts `project_id`, `node_id | None`, and proposed `parent_id`. It loads ancestors iteratively, keeps a `set[UUID]`, rejects a missing/cross-project parent, self-parent and revisiting an id, and rejects the proposed node when computed depth exceeds 4. This single function is used by create, move and full-tree activation validation.

- [ ] **Step 2: Implement create and patch**

Both writes work for draft and active projects. Patch applies only fields in `command.model_fields_set`; if `parent_id` changes, validate before flush. No DELETE route, implicit subtree cascade, bulk reorder or import is added.

- [ ] **Step 3: Implement full-tree activation validation**

Load all nodes of the Project once, build `id -> parent_id` in memory, and walk each chain with memoized depths. Reject orphaned parents, cycles and depth >4. Complexity is O(n) for the small local tree.

- [ ] **Step 4: Implement WorkspaceState save**

If `selected_node_id` is present, verify that it belongs to the Project. Verify every `expanded_node_id` the same way, remove duplicates while preserving order, then upsert the one WorkspaceState row. Layout JSON is produced from the validated Pydantic model, not accepted as an untyped dict.

- [ ] **Step 5: Exercise the fragile branches**

Run a disposable module-level check that creates four levels, rejects a fifth, rejects moving a node below its descendant, and rejects a WorkspaceState pointing at another Project. Expected: all three invalid writes raise `ProjectInvariantError` and `PRAGMA foreign_key_check` remains empty.

### Task 6: Thin FastAPI adapter and startup migrations

**Files:**

- Create: `backend/app/projects/router.py`
- Modify: `backend/app/main.py`

**Interfaces:**

- Consumes: `get_session()` and every public `projects.service` function.
- Produces: the ten routes in §4 and automatic migration at FastAPI startup.

- [ ] **Step 1: Declare the router and exact status codes**

Use `APIRouter(prefix="/projects", tags=["projects"])` for project routes and `APIRouter(prefix="/wizard-drafts", tags=["wizard-drafts"])` for draft routes, then include both in one exported `router` with prefix `/api`. POST create endpoints return `201`; PUT/PATCH/GET/activate return `200`.

- [ ] **Step 2: Keep HTTP mapping thin**

Each route validates a schema, calls one service function and returns its result. Map `ProjectNotFoundError -> 404`, `ProjectConflictError -> 409`, and `ProjectInvariantError -> 422` with a shared local helper or three FastAPI exception handlers. Do not embed SQL queries or commits in router functions.

- [ ] **Step 3: Add a FastAPI lifespan**

Replace directory creation during `create_app()` with:

```python
@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    upgrade_database()
    yield
```

Pass `lifespan=lifespan` to FastAPI, keep `/api/health`, then include the projects router. A migration exception must abort startup.

- [ ] **Step 4: Inspect the generated OpenAPI contract**

Run API with a disposable data directory and open `/openapi.json`. Assert by `python -c`/`urllib.request` that all ten paths exist, drafts have no DELETE route, and Project schemas expose string UUIDs and enum values.

- [ ] **Step 5: Lint the complete backend**

Run:

```powershell
cd backend
python -m ruff check .
```

Expected: exit 0.

### Task 7: One restart-safe smoke check

**Files:**

- Create: `backend/scripts/check_stage2.py`

**Interfaces:**

- Consumes: the public HTTP interface only.
- Produces: one command that fails on broken migrations, WAL, FK integrity, draft persistence, activation or project opening.

- [ ] **Step 1: Implement a standard-library API harness**

The script resolves `backend/` from `__file__`, uses `TemporaryDirectory`, picks a free localhost port, starts `python -m uvicorn app.main:app` with `cwd=backend` and `TENTEX_DATA_DIR` pointing to the temporary directory, polls `/api/health`, and sends JSON with `urllib.request`. Always terminate the child process in `finally`; print its captured stderr on failure.

- [ ] **Step 2: Encode the exact scenario**

The script must:

1. POST a draft.
2. PUT the filled example from §4 and remember returned revision 1.
3. Repeat the PUT with stale revision 0 and assert HTTP 409.
4. POST one section and one child topic.
5. PUT WorkspaceState selecting the topic.
6. Stop/start API and GET the same draft with revision 1.
7. POST activate with revision 1 and assert the draft list is empty.
8. Stop/start API again, GET projects and ProjectDetail, and assert name, passport, topic and selected node are unchanged.
9. Open SQLite with `sqlite3`, assert `journal_mode == "wal"`, `foreign_key_check == []`, and exactly one Alembic revision is installed.

- [ ] **Step 3: Run the check twice**

From `backend/`:

```powershell
python scripts/check_stage2.py
python scripts/check_stage2.py
```

Expected both times: `stage 2 smoke check passed`. Each run uses a fresh temporary database and does not touch repository `data/`.

- [ ] **Step 4: Verify in Python 3.13 container**

From the repository root:

```powershell
docker compose build api
docker compose run --rm -e TENTEX_DATA_DIR=/tmp/tentex-stage2-check api python scripts/check_stage2.py
```

Expected: image builds and the same success line appears under Python 3.13.

### Task 8: Architecture note and final review

**Files:**

- Create: `docs/architecture/stage-2-core.md`
- Modify only if implementation diverged: `PLAN.md`

**Interfaces:**

- Consumes: the implemented schema, migration and OpenAPI document.
- Produces: a stable explanation for the course paper and oral defense.

- [ ] **Step 1: Record the implemented model, not the planned model**

Create `stage-2-core.md` after code works. Include the final ER diagram, the seven entities, ownership of every JSON field, activation transaction, WAL/foreign-key setup, why sync SQLAlchemy/Alembic were selected, and a table mapping routes to screens. Generate field names from the actual migration/OpenAPI; do not copy a field that was not implemented.

- [ ] **Step 2: Add a short defense narrative**

Use this order:

1. «Программа первична, поэтому Material не входит в инвариант активации».
2. «Шаблон — пресет, поэтому одна таблица Project обслуживает все входы».
3. «Нормализованные таблицы хранят доменные факты, JSON — только изменчивую раскладку и незавершённый ввод».
4. «Составной FK защищает изоляцию дерева проектов; сервис защищает глубину и отсутствие циклов».
5. «WAL оставляет чтение доступным при записи, Alembic делает схему воспроизводимой одной командой».

- [ ] **Step 3: Run the final evidence bundle**

Run from the repository root:

```powershell
python -m ruff check --config backend/pyproject.toml backend
python backend/scripts/check_stage2.py
docker compose build api
git diff --check
```

Expected: Ruff 0, smoke success, Docker build success, no whitespace errors. If a command fails, report the failure and do not claim the stage complete.

- [ ] **Step 4: Review scope before handoff**

Confirm `git diff --name-only` contains no frontend files, no Page/Block/Fragment/Binding models, no async dependency, no test framework and no generated database under `data/`. Leave all changes unstaged and uncommitted unless the user explicitly asks otherwise.

---

## 6. Требования, покрытые планом

| Источник | Покрытие |
|---|---|
| П1, FR-E3 | Project активируется без Material |
| FR-P1–P2 | Изолированные проекты, свойства и четыре статуса |
| FR-P5 | Общий Material и проектная связь с ролью/приоритетом/инструкцией |
| FR-P7–P8 | Шаблон как preset, без классов проектов и переключения подхода внутри проекта |
| FR-P11, FR-P17 | Переживающий перезапуск WizardDraft и транзакционная активация |
| FR-G1–G4 | Структурированный GoalPassport как вход будущих механизмов |
| FR-G5, FR-G23 | Дерево до четырёх уровней, свойства и происхождение ProgramNode |
| NFR-10–NFR-11 | Первый запуск и миграции без ручной настройки, офлайн |
| §20 | Первые семь сущностей и минимальный WorkspaceState |
| PLAN stage 2 | Ровно видимые действия мастера, Проектов, Программы и Рабочей области |

Осознанно не покрыты сейчас: пользовательский шаблон FR-P9, быстрый анализ FR-P13, фоновые задачи FR-P15/NFR-1, undo NFR-5, статусы разбора Material, подробное происхождение страниц и подключение UI. Для каждого уже назначен этап в `PLAN.md`; пустые интерфейсы под них не создаются.
