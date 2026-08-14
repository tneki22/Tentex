# Global Library Material Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Превратить глобальную «Библиотеку» в каноническую рабочую область общего материала: с типоспецифичным просмотром, одновременным сравнением PDF и текста, PDF-оглавлением, повторной обработкой, человеческими названиями качества и историей версий — без проектных привязок.

**Architecture:** Общий `Material` и его ревизии принадлежат глобальному API `/api/materials/...`; `ProjectMaterial` остаётся отдельной связью с проектными ролями и назначениями. Бэкенд получает проектонезависимое ядро чтения и изменения материала, а существующие проектные endpoints делегируют ему после проверки связи. Фронтенд получает полноразмерный маршрут `/library/:materialId`, общие нейтральные примитивы просмотрщика и небольшие типоспецифичные представления вместо одного компонента с MIME-ветвлениями.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, SQLite WAL, PyMuPDF, React 19, TypeScript, Vite, React Router, Radix Primitives, обычный CSS на токенах Tentex, pytest и браузерная проверка Playwright.

## Global Constraints

- Источник требований: [спецификация](../specs/2026-08-14-global-library-material-workspace-design.md), `AGENTS.md`, `REQUIREMENTS.md`, `SCREENS.md`, `DESIGN.md`, `docs/architecture/stage-5-material-pipeline.md` и `docs/architecture/materials-viewer-and-answers-autolink.md`.
- В Библиотеке не появляются привязки, темы, покрытие, импорт программы или связывание эталонов.
- В пользовательском тексте запрещены `native`, `ocr`, `ocr_low`. Внутреннее значение SQLite `ocr_low` можно сохранить ради совместимости; наружная подпись всегда «Нужно проверить».
- Реально доступен только режим `Быстро`. `Учебник`, `Облако`, `Максимум`, `Эксперт` остаются честными disabled-карточками.
- Не добавлять новый OCR-провайдер, эмбеддинги, проходы 1/2, чат с документом, LibreOffice или видеоплеер YouTube.
- Облачные режимы нельзя оживлять только потому, что общий шлюз ИИ уже существует: им нужен отдельный consumer-контракт этапа 7.
- Все цвета — через токены. Сначала переиспользовать примитивы UI-кита и Radix. Экранный CSS вынести в отдельный файл, подключённый до `layout.css`.
- Не расширять `Materials.tsx` новым глобальным сценарием. Общие инструменты извлекать в `components/domain/material-viewer`, проектную композицию оставлять в проектном экране.
- По правилам Tentex TDD выключен. В каждом задании порядок такой: зафиксировать контракт, реализовать небольшой срез, добавить точечный регрессионный тест там, где поведение легко сломать, затем выполнить проверку.
- После правок фронтенда обязательно `docker compose restart web` перед браузерной проверкой.
- После каждого самостоятельного проверенного задания делать отдельный коммит, добавляя только собственные файлы и строки.
- Миграция ниже рассчитана на текущее состояние, где последняя ревизия — `20260814_0017`. Если к началу реализации уже появилась новая миграция, сначала выбрать следующий свободный номер и обновить имя/`down_revision`, не создавая развилку.

---

## Task 1: Зафиксировать новый экран и изменение baseline

**Files:**

- Modify: `SCREENS.md`
- Modify: `docs/ui/stage-1-interface-baseline.md`
- Read only: `docs/superpowers/specs/2026-08-14-global-library-material-workspace-design.md`

### Steps

- [ ] В разделе глобальной «Библиотеки» в `SCREENS.md` записать два состояния: список `/library` и рабочая область `/library/:materialId`.
- [ ] Перенести в описание неизменяемые пункты: полноразмерная оболочка, сравнение PDF, PDF-оглавление слева, типоспецифичный центр, инспектор `Обработка / Версии / Файл`, отсутствие привязок.
- [ ] Заменить в актуальном описании экрана формулировку `ocr_low` на «страницы, которые нужно проверить». В перечне модели данных разрешается один раз указать совместимое внутреннее значение в скобках.
- [ ] В `docs/ui/stage-1-interface-baseline.md` добавить строку отклонения от baseline: новая структура явно одобрена пользователем 14.08.2026, потому что глобальная обработка и PDF-оглавление требуют локальной трёхзонной рабочей области; проектные привязки в неё не переносятся.
- [ ] Проверить, что документы не обещают работающие будущие режимы OCR.

### Verification

```powershell
rg -n "Библиотек|library/:materialId|Оглавление|Нужно проверить" SCREENS.md docs/ui/stage-1-interface-baseline.md
rg -n "ocr_low" SCREENS.md docs/ui/stage-1-interface-baseline.md
```

Ожидается: новый маршрут и граница найдены; `ocr_low` остаётся максимум в одном явно техническом пояснении, а не в интерфейсном тексте.

### Commit

```powershell
git add SCREENS.md docs/ui/stage-1-interface-baseline.md
git commit -m "docs: define global library material workspace"
```

---

## Task 2: Ввести реестр версий общего материала

**Files:**

- Create: `backend/migrations/versions/20260814_0018_library_material_revisions.py`
- Modify: `backend/app/models.py`
- Create: `backend/app/materials/revisions.py`
- Modify: `backend/app/materials/schemas.py`
- Create: `backend/tests/test_material_revisions.py`

### Contract

Добавить модель:

```python
class MaterialRevision(Base):
    __tablename__ = "material_revisions"

    id: Mapped[UUID]
    material_id: Mapped[UUID]
    revision: Mapped[int]
    origin: Mapped[str]  # imported | parse | manual_edit | ai_cleanup | source_refresh | restore
    parser_mode: Mapped[str | None]
    parent_revision: Mapped[int | None]
    task_id: Mapped[UUID | None]
    source_storage_path: Mapped[str | None]
    source_hash: Mapped[str | None]
    scope: Mapped[dict[str, Any]]
    summary: Mapped[dict[str, Any]]
    created_at: Mapped[datetime]
```

В той же миграции добавить в `material_fragments` nullable-поля `time_from` и `time_to`. Они нужны не только сырому `MaterialPage.elements`, но и публичным фрагментам временной расшифровки. Ограничения: оба значения неотрицательны, `time_to IS NULL OR time_from IS NULL OR time_to >= time_from`.

Ограничения:

- `UniqueConstraint("material_id", "revision")`;
- `revision > 0`;
- `parent_revision IS NULL OR parent_revision > 0`;
- FK `material_id -> materials.id ON DELETE CASCADE`;
- индекс `(material_id, revision)`;
- `task_id` — nullable FK `processing_tasks.id` с `ON DELETE SET NULL`, если порядок таблиц в SQLite/Alembic позволяет; иначе хранить UUID без FK и объяснить это комментарием миграции.

Pydantic-схема:

```python
class MaterialRevisionRead(ApiModel):
    revision: int
    origin: Literal["imported", "parse", "manual_edit", "ai_cleanup", "source_refresh", "restore"]
    parser_mode: ParserMode | None
    parent_revision: int | None
    scope: dict[str, Any]
    summary: dict[str, Any]
    created_at: datetime
    is_current: bool
```

### Steps

- [ ] Создать Alembic-миграцию с таблицей и индексом.
- [ ] В той же миграции сделать backfill для каждой уникальной пары `(material_id, revision)` в `material_pages`: `origin="imported"`, `parent_revision=revision-1` только для ревизий выше первой, `source_storage_path=materials.storage_path`, `source_hash=materials.sha256`, пустые `scope/summary`.
- [ ] Добавить SQLAlchemy-модель и экспорт в существующий модуль моделей, не меняя `Material.active_parse_revision`.
- [ ] Расширить `MaterialFragment` полями времени и `FragmentRead` соответствующими nullable-полями; backfill не нужен, старые фрагменты получают `NULL`.
- [ ] Создать `revisions.py` с маленькими функциями: `record_revision`, `get_revision`, `list_revisions`, `revision_source_path`, `revision_summary`.
- [ ] `record_revision` должен падать с доменной ошибкой при повторе номера, а не молча заменять запись.
- [ ] Не реализовывать восстановление в этом задании; только хранение и чтение.
- [ ] Добавить тест: мигрированная старая ревизия доступна, новая запись создаётся, повтор номера запрещён, каскадное удаление материала удаляет версии.

### Verification

```powershell
cd backend
python -m pytest tests/test_material_revisions.py -q
python -m ruff check app/models.py app/materials/revisions.py app/materials/schemas.py tests/test_material_revisions.py
cd ..
python backend/scripts/check_stage5.py
```

### Commit

```powershell
git add backend/migrations/versions/20260814_0018_library_material_revisions.py backend/app/models.py backend/app/materials/revisions.py backend/app/materials/schemas.py backend/tests/test_material_revisions.py
git commit -m "feat: add material revision registry"
```

---

## Task 3: Добавить глобальное чтение материала и исходника

**Files:**

- Create: `backend/app/materials/library.py`
- Modify: `backend/app/materials/schemas.py`
- Modify: `backend/app/materials/router.py`
- Modify: `backend/app/materials/service.py`
- Modify: `backend/app/materials/storage.py`
- Create: `backend/tests/test_library_material_workspace.py`

### API types

```python
MaterialPresentationKind = Literal[
    "pdf", "image", "document", "plain_text", "web", "youtube", "audio"
]

class LibraryMaterialCapabilities(ApiModel):
    can_compare: bool
    can_view_original: bool
    can_edit_text: bool
    can_run_ocr: bool
    can_refresh_source: bool
    has_outline: bool
    has_timeline: bool

class LibraryMaterialUsageRead(ApiModel):
    project_id: UUID
    project_name: str
    project_status: str
    display_name: str
    source_role: SourceRole
    purposes: list[MaterialPurpose]

class LibraryMaterialDetailRead(LibraryMaterialRead):
    presentation_kind: MaterialPresentationKind
    capabilities: LibraryMaterialCapabilities
    outline: list[OutlineItem]
    outline_source: Literal["embedded", "recognized", "none"]
    active_parse_revision: int
    parser_mode: ParserMode | None
    diagnostics: list[str]
    task: ProcessingTaskRead | None
    usages: list[LibraryMaterialUsageRead]
    retrieved_at: datetime | None
```

`FragmentRead` расширить полями `time_from: float | None` и `time_to: float | None`.

### Presentation mapping

Реализовать одну чистую функцию `presentation_kind(material)`:

- `source_kind == youtube` → `youtube`;
- `source_kind == audio` или `media_type.startswith("audio/")` → `audio`;
- `source_kind == url` → `web`;
- `application/pdf` → `pdf`;
- `image/*` → `image`;
- DOCX MIME → `document`;
- TXT/Markdown MIME → `plain_text`;
- неизвестный поддержанный текстовый формат → `plain_text`;
- неподдержанный формат не угадывать: вернуть существующую доменную ошибку при загрузке.

Capabilities выводятся из `presentation_kind` и фактических данных, а не хранятся отдельными флагами.

### Endpoints

- `GET /api/materials/{material_id}` → глобальная детальная карточка.
- `GET /api/materials/{material_id}/pages/{page_number}?revision=N` → страница активной или исторической ревизии.
- `GET /api/materials/{material_id}/pages/{page_number}/image` → оригинальная PDF-страница/изображение.
- `GET /api/materials/{material_id}/source?revision=N` → локальный исходник или снимок соответствующей ревизии.
- `GET /api/materials/{material_id}/search?q=...&revision=N&limit=50` → совпадения внутри одного материала.
- `GET /api/materials/{material_id}/revisions` → список готовых версий.

Specific routes (`delete-preview`, `revisions`) объявить раньше общего `/{material_id}`, чтобы не получить конфликт маршрутов.

### Steps

- [ ] В `library.py` реализовать `_material_or_404`, `read_library_material`, `read_library_page`, `library_page_image_path`, `library_source_path` и `list_library_revisions`.
- [ ] Добавить `search_library_material`: для активной ревизии переиспользовать FTS5/BM25 и русскую лемматизацию без фильтра `ProjectMaterial`; для исторической ревизии выполнить ограниченный поиск по её сохранённым фрагментам. Результат содержит страницу, fragment id, bbox, фрагмент текста и rank. Пустой запрос отвечает пустым списком, limit ограничен 1–100.
- [ ] Для `outline_source`: существующее PDF-outline считается `embedded`; если его нет, собрать дерево из заголовочных `MaterialBlock` активной ревизии и назвать `recognized`; иначе `none`.
- [ ] Историческая страница читается только по существующей `MaterialRevision`; запрос несуществующей ревизии отвечает 404 `material_revision_not_found`.
- [ ] Глобальный endpoint страницы не проверяет `ProjectMaterial`.
- [ ] `source` отдаёт файл inline с исходным MIME. Для локального аудио проверить byte-range/seek. Если установленный Starlette не обрабатывает `Range`, добавить ограниченный range-response в `storage.py` и тест `206`.
- [ ] Проектные `get_page`, `page_image_path` и чтение материала оставить совместимыми, но делегировать общую часть функциям без `project_id` после проверки проекта и связи.
- [ ] В тестах создать PDF с outline, PDF без outline с заголовочными блоками, изображение, DOCX/TXT, URL, YouTube и audio; проверить `presentation_kind`, capabilities и отсутствие требования проекта.
- [ ] Проверить, что `FragmentRead` действительно возвращает временные границы.
- [ ] Тестом подтвердить, что глобальный поиск не требует проекта, не возвращает соседний материал и открывает точную страницу; исторический поиск не использует фрагменты активной ревизии.

### Verification

```powershell
cd backend
python -m pytest tests/test_library_material_workspace.py tests/test_material_sources.py tests/test_material_segmentation.py -q
python -m ruff check app/materials/library.py app/materials/router.py app/materials/service.py app/materials/storage.py app/materials/schemas.py tests/test_library_material_workspace.py
cd ..
python backend/scripts/check_stage5.py
```

### Commit

```powershell
git add backend/app/materials/library.py backend/app/materials/schemas.py backend/app/materials/router.py backend/app/materials/service.py backend/app/materials/storage.py backend/tests/test_library_material_workspace.py
git commit -m "feat: expose global material workspace API"
```

---

## Task 4: Разрешить создание общего материала и подключение к проекту

**Files:**

- Modify: `backend/app/materials/library.py`
- Modify: `backend/app/materials/service.py`
- Modify: `backend/app/materials/router.py`
- Modify: `backend/app/materials/schemas.py`
- Modify: `backend/tests/test_library_material_workspace.py`
- Modify: `backend/tests/test_material_sources.py`

### Endpoints

```text
POST /api/materials/upload
POST /api/materials/text
POST /api/materials/external
POST /api/materials/{material_id}/project-links
```

Тело подключения:

```python
class LibraryMaterialAttachWrite(ApiModel):
    project_id: UUID
    display_name: str | None = None
    source_role: SourceRole = SourceRole.ADDITIONAL
    purposes: list[MaterialPurpose] = Field(
        default_factory=lambda: [MaterialPurpose.STUDY_SOURCE]
    )
```

### Steps

- [ ] Выделить из `upload_material`, `create_text_material` и `create_external_material` проектонезависимое создание общего `Material`.
- [ ] Глобальная загрузка сохраняет исходник, выполняет дедупликацию и создаёт задачу так же, как текущая проектная загрузка, но не требует активного проекта и не создаёт `ProjectMaterial`.
- [ ] Для аудиофайла выставлять `source_kind=audio`; для обычного файла — `file`; для вставленного текста — `text`; для URL/YouTube — существующие `url`/`youtube`.
- [ ] Глобальный `POST /external` принимает только уже поддержанные виды источников; произвольный URL аудиопотока не добавлять.
- [ ] `project-links` проверяет доступность проекта, правило одного файла эталонных ответов и дубликат связи. При существующей связи отвечать 409 `material_already_attached`.
- [ ] Подключение не запускает повторную обработку и не копирует файл.
- [ ] Существующие проектные endpoints продолжают создавать материал и связь одним вызовом, используя то же ядро.
- [ ] Тестами закрыть: создание без проектов; последующее подключение; повторное подключение; дедупликация; подключение к двум проектам; корректный список `usages`.

### Verification

```powershell
cd backend
python -m pytest tests/test_library_material_workspace.py tests/test_material_sources.py tests/test_exam_wizard_materials.py -q
python -m ruff check app/materials/library.py app/materials/service.py app/materials/router.py app/materials/schemas.py
cd ..
python backend/scripts/check_stage2.py
python backend/scripts/check_stage5.py
```

### Commit

```powershell
git add backend/app/materials/library.py backend/app/materials/service.py backend/app/materials/router.py backend/app/materials/schemas.py backend/tests/test_library_material_workspace.py backend/tests/test_material_sources.py
git commit -m "feat: create and attach library materials globally"
```

---

## Task 5: Реализовать область повторной обработки и полные ревизии

**Files:**

- Modify: `backend/app/materials/schemas.py`
- Modify: `backend/app/materials/library.py`
- Modify: `backend/app/materials/service.py`
- Modify: `backend/app/materials/worker.py`
- Modify: `backend/app/materials/revisions.py`
- Modify: `backend/app/materials/segmentation.py`
- Modify: `backend/tests/test_material_revisions.py`
- Modify: `backend/tests/test_binding_transfer.py`
- Modify: `backend/tests/test_material_segmentation.py`

### Processing contract

```python
class ProcessingStart(ApiModel):
    parser_mode: ParserMode
    scope: Literal["all", "needs_review", "range"] = "all"
    page_from: int | None = None
    page_to: int | None = None
```

Validation:

- `all`: диапазон отсутствует;
- `needs_review`: выбрать страницы активной ревизии с внутренним качеством `ocr_low`; если список пуст — 409 `material_has_no_review_pages`;
- `range`: оба числа обязательны, `1 <= page_from <= page_to <= page_count`;
- для YouTube/audio/web/text обработка остаётся полноисточниковой, пока их парсер не имеет безопасной единицы частичного запуска; попытка диапазона отвечает 422 с человеческим сообщением.

Checkpoint задачи:

```json
{
  "revision": 4,
  "source_revision": 3,
  "selected_pages": [12, 13, 14],
  "next_index": 1,
  "scope": {"kind": "range", "page_from": 12, "page_to": 14}
}
```

### Steps

- [ ] Добавить глобальные `POST /api/materials/{id}/processing` и `/processing/{action}`; проектные endpoints делегируют тем же функциям после проверки связи.
- [ ] На старте определить неизменяемый список выбранных страниц и записать его в checkpoint. `total` равен длине списка, не числу страниц всего документа.
- [ ] Для частичной обработки создать полную новую ревизию: скопировать неизменённые `MaterialPage` вместе с `elements/diagnostics`, выбранные страницы разобрать заново.
- [ ] После появления всех страниц один раз перестроить блоки и фрагменты для всей новой ревизии, затем вызвать существующий `transfer_bindings_on_revision` и FTS-переиндексацию.
- [ ] При создании каждого `MaterialFragment` переносить `ParsedElement.time_from/time_to`; копирование, ручная правка и restore также сохраняют временные границы неизменённых сегментов.
- [ ] Только после успешных сегментации, переноса и индексации изменить `Material.active_parse_revision` и записать `MaterialRevision(origin="parse")`.
- [ ] В `summary` сохранить `page_count`, `native_page_count`, `ocr_page_count`, `review_page_count`, `changed_pages`, `diagnostics_count`.
- [ ] Удалить `_drop_unbound_fragments` из успешного пути или изменить политику так, чтобы фрагменты зарегистрированных исторических ревизий сохранялись. Старые привязанные фрагменты также не удалять.
- [ ] Незарегистрированные страницы незавершённой ревизии можно безопасно очищать при явном retry той же задачи; активную и зарегистрированные ревизии никогда не удалять.
- [ ] Пауза/продолжение должны использовать `next_index`, а не предполагать последовательные номера страниц.
- [ ] Разрешить read-only preview страницы строящейся ревизии только через `GET /api/materials/{id}/pages/{page}?task_id=...`: task должен принадлежать material, быть текущим активным заданием, а page уже существовать. Обычный `revision=N` продолжает принимать только зарегистрированные версии.
- [ ] Ошибка оставляет `active_parse_revision` прежней и добавляет понятную ошибку задаче.
- [ ] Тестами закрыть диапазон, `needs_review`, пустой `needs_review`, паузу после первой выбранной страницы, ошибку, полный состав новой ревизии, сохранение старой ревизии, перенос привязок и повторный индекс.

### Verification

```powershell
cd backend
python -m pytest tests/test_material_revisions.py tests/test_binding_transfer.py tests/test_material_segmentation.py tests/test_fragment_search.py -q
python -m ruff check app/materials/schemas.py app/materials/library.py app/materials/service.py app/materials/worker.py app/materials/revisions.py app/materials/segmentation.py
cd ..
python backend/scripts/check_stage5.py
python backend/scripts/check_manual_binding.py
```

### Commit

```powershell
git add backend/app/materials/schemas.py backend/app/materials/library.py backend/app/materials/service.py backend/app/materials/worker.py backend/app/materials/revisions.py backend/app/materials/segmentation.py backend/tests/test_material_revisions.py backend/tests/test_binding_transfer.py backend/tests/test_material_segmentation.py
git commit -m "feat: support scoped material reprocessing"
```

---

## Task 6: Глобальные исправления, история, восстановление и обновление источника

**Files:**

- Modify: `backend/app/materials/library.py`
- Modify: `backend/app/materials/revisions.py`
- Modify: `backend/app/materials/router.py`
- Modify: `backend/app/materials/service.py`
- Modify: `backend/app/materials/ai_cleanup.py`
- Modify: `backend/app/materials/storage.py`
- Modify: `backend/app/materials/external.py`
- Modify: `backend/app/materials/parsers/base.py`
- Modify: `backend/app/materials/parsers/native.py`
- Modify: `backend/app/materials/parsers/audio.py`
- Modify: `backend/tests/test_material_revisions.py`
- Modify: `backend/tests/test_ai_cleanup.py`
- Modify: `backend/tests/test_material_sources.py`

### Global mutation endpoints

```text
PUT  /api/materials/{id}/pages/{page}
POST /api/materials/{id}/pages/{page}/ai-cleanup/preflight
POST /api/materials/{id}/pages/{page}/ai-cleanup
POST /api/materials/{id}/pages/{page}/ai-cleanup/apply
POST /api/materials/{id}/revisions/{revision}/restore
POST /api/materials/{id}/source/refresh
```

### Steps

- [ ] Разделить `update_page_text` на общий core без `project_id` и проектную обёртку. Общий core сохраняет существующие optimistic checks (`expected_revision`, `expected_source_hash`), перенос привязок и переиндексацию.
- [ ] После ручной правки записывать `MaterialRevision(origin="manual_edit", parent_revision=old_revision, scope={"page": N})`.
- [ ] Разрешить существующему `ai_cleanup` работать с `project_id=None`: роль шлюза, prompt version, предпросмотр отправляемого, кэш, usage/cost и поведение при выключенном шлюзе сохраняются. Проектная обёртка по-прежнему валидирует связь.
- [ ] После apply записывать `origin="ai_cleanup"` и идентификатор AI-run в `summary`.
- [ ] Реализовать `restore_revision`: клонировать страницы/элементы выбранной версии в номер `max_revision+1`, заново собрать блоки/фрагменты, перенести привязки с текущей активной версии, переиндексировать, записать `origin="restore"`, `parent_revision=selected` и только затем активировать.
- [ ] Историческую версию не разрешать редактировать: mutation с `expected_revision`, отличной от активной, отвечает 409 `stale_material_revision`.
- [ ] Для `source/refresh` разрешить только `web` и `youtube`. Сохранять новый снимок в неизменяемом revision-specific пути, не перезаписывая старый файл; записывать `source_storage_path` и `source_hash` в `MaterialRevision`.
- [ ] Если хеш обновлённого снимка уже принадлежит другому `Material`, не сливать материалы и не нарушать unique constraint: ответить 409 `material_refresh_duplicate` с id найденного материала, а текущий материал и его активную версию оставить без изменений.
- [ ] При обновлении веба/YouTube создать новую разобранную ревизию и только после успеха обновить `Material.storage_path`, `sha256`, `retrieved_at` и активную ревизию. Ошибка оставляет прежний снимок.
- [ ] Из результата YouTube извлекать структурные `time_from/time_to`; текстовые метки `[mm:ss]` можно оставить для обратной совместимости, но UI опирается на числовые поля.
- [ ] Для всех синхронных ревизий унаследовать `source_storage_path/source_hash` родителя, если исходник не менялся.
- [ ] Тестами закрыть ручную правку, глобальный AI cleanup без проекта, read-only историю, restore-as-new, сохранение старого веб-снимка, неуспешный refresh и временные поля YouTube.

### Verification

```powershell
cd backend
python -m pytest tests/test_material_revisions.py tests/test_ai_cleanup.py tests/test_material_sources.py tests/test_binding_transfer.py -q
python -m ruff check app/materials/library.py app/materials/revisions.py app/materials/router.py app/materials/service.py app/materials/ai_cleanup.py app/materials/storage.py app/materials/parsers
cd ..
python backend/scripts/check_ai_gateway.py
python backend/scripts/check_stage5.py
python backend/scripts/check_manual_binding.py
```

### Commit

```powershell
git add backend/app/materials/library.py backend/app/materials/revisions.py backend/app/materials/router.py backend/app/materials/service.py backend/app/materials/ai_cleanup.py backend/app/materials/storage.py backend/app/materials/external.py backend/app/materials/parsers/base.py backend/app/materials/parsers/native.py backend/app/materials/parsers/audio.py backend/tests/test_material_revisions.py backend/tests/test_ai_cleanup.py backend/tests/test_material_sources.py
git commit -m "feat: manage global material revisions"
```

---

## Task 7: Добавить сквозную серверную проверку Библиотеки

**Files:**

- Create: `backend/scripts/check_library_workspace.py`
- Modify: `docs/architecture/materials-viewer-and-answers-autolink.md`
- Create: `docs/architecture/global-library-material-workspace.md`

### Steps

- [ ] Скрипт поднимает изолированную тестовую базу тем же способом, что `check_stage5.py`, и не читает живой bind-mounted SQLite с хоста.
- [ ] Создать PDF с двумя страницами и outline, подключить к двум проектам, выполнить полный разбор.
- [ ] Проверить глобальный detail, outline, исходник, страницу и человечески интерпретируемые счётчики.
- [ ] Повторно обработать диапазон одной страницы, убедиться, что активна новая полная ревизия, старая читается, а привязка перенесена.
- [ ] Исправить страницу, затем восстановить первую ревизию как новую; номера должны монотонно расти.
- [ ] Создать web/YouTube/audio материалы и проверить `presentation_kind`, сохранённый snapshot и временные поля.
- [ ] Подтвердить, что физический delete-preview перечисляет два проекта.
- [ ] В архитектурном документе описать фактический контракт и явно отметить, что привязки остаются проектными.

### Verification

```powershell
python backend/scripts/check_library_workspace.py
cd backend
python -m ruff check scripts/check_library_workspace.py
cd ..
```

### Commit

```powershell
git add backend/scripts/check_library_workspace.py docs/architecture/materials-viewer-and-answers-autolink.md docs/architecture/global-library-material-workspace.md
git commit -m "test: cover global library workspace flow"
```

---

## Task 8: Ввести общий frontend-контракт и человеческие бейджи качества

**Files:**

- Modify: `frontend/src/api/materials.ts`
- Modify: `frontend/src/components/domain/QualityBadge.tsx`
- Modify: `frontend/src/components/domain/index.ts`
- Modify: `frontend/src/screens/UiKit.tsx`
- Create: `frontend/src/components/domain/material-viewer/types.ts`
- Create: `frontend/src/components/domain/material-viewer/sourcePresentation.ts`
- Create: `frontend/src/components/domain/material-viewer/index.ts`

### Frontend types

Типы повторяют snake_case API, без второго слоя ручного преобразования:

```ts
export type MaterialPresentationKind =
  | "pdf" | "image" | "document" | "plain_text"
  | "web" | "youtube" | "audio";

export type MaterialViewMode = "compare" | "source" | "text";

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
```

Mapping:

| kind | sourceLabel | textLabel | processingTitle | default |
| --- | --- | --- | --- | --- |
| pdf | Оригинал | Подготовленный текст | Распознавание | compare |
| image | Изображение | Распознанный текст | Распознавание | compare |
| document | Документ | Подготовленный текст | Разбор документа | compare |
| plain_text | Исходный текст | Подготовленный текст | Подготовка текста | text |
| web | Сохранённая страница | Подготовленный текст | Снимок и извлечение | text |
| youtube | Источник | Расшифровка | Субтитры | text |
| audio | Запись | Расшифровка | Расшифровка | text |

### Steps

- [ ] Добавить в API-клиент функции для всех глобальных endpoints спецификации, `AbortSignal` и единый существующий разбор ошибок.
- [ ] Не удалять проектные API-функции; типы общих page/task/revision переиспользовать.
- [ ] В `QualityBadge` заменить пользовательские подписи и title:

```ts
native: { label: "Текст из файла", title: "Текст взят из текстового слоя документа." }
ocr: { label: "Распознано", title: "Текст распознан по изображению." }
ocr_low: { label: "Нужно проверить", title: "Распознавание могло ошибиться — сравните текст с оригиналом." }
```

- [ ] Обновить примеры UI-кита и все aria-label/title, которые формируются из raw quality.
- [ ] Создать чистую `getMaterialPresentation(detail)`; неизвестное значение должно исчерпывающе проверяться TypeScript `never`, а не падать в молчаливый PDF-default.
- [ ] Поискать literal-выводы качества во фронтенде и заменить их через общий mapping. Не переименовывать wire value в этом задании.

### Verification

```powershell
rg -n 'label: "(native|ocr|ocr_low)"|>\s*(native|ocr|ocr_low)\s*<' frontend/src
npm run typecheck
npm run build
```

Первая команда не должна находить пользовательские подписи. Совпадения в type union/API допустимы и просматриваются вручную.

### Commit

```powershell
git add frontend/src/api/materials.ts frontend/src/components/domain/QualityBadge.tsx frontend/src/components/domain/index.ts frontend/src/screens/UiKit.tsx frontend/src/components/domain/material-viewer
git commit -m "feat: add material presentation contract"
```

---

## Task 9: Перестроить список Библиотеки и маршрут открытия

**Files:**

- Modify: `frontend/src/screens/Library.tsx`
- Create: `frontend/src/screens/library/LibraryFilters.tsx`
- Create: `frontend/src/screens/library/AddLibraryMaterialDialog.tsx`
- Create: `frontend/src/screens/library/AddToProjectDialog.tsx`
- Modify: `frontend/src/app/screens.ts`
- Modify: `frontend/src/app/views.ts`
- Modify: `frontend/src/app/AppLayout.tsx`
- Modify: `frontend/src/styles/layout.css`

### URL state

Список использует query params:

```text
q=строка
kind=all|pdf|image|document|plain_text|web|youtube|audio
status=all|ready|processing|paused|failed
quality=all|needs_review
usage=all|attached|unattached
sort=updated_desc|name_asc|created_desc
```

### Steps

- [ ] Добавить реестровый экран `library-material` с path `/library/:materialId`, но не добавлять его второй строкой в глобальную навигацию.
- [ ] В `AppLayout` дать точному маршруту `/library/[^/]+` ту же полноразмерную оболочку `Outlet`, что проектным маршрутам. `/library` остаётся в обычной глобальной оболочке.
- [ ] Сделать всю смысловую область строки кликабельной и доступной с клавиатуры; вложенные кнопки останавливают навигацию.
- [ ] Перед переходом записать `location.state.libraryReturnTo` с полным `pathname + search` и сохранить `scrollY` в `sessionStorage` под ключом query string.
- [ ] При возврате восстановить прокрутку после загрузки списка.
- [ ] Добавить компактную строку поиска/фильтров без отдельной пустой hero-зоны. На 1600 px фильтры занимают одну строку, на узком окне переносятся осмысленными группами.
- [ ] Диалог добавления содержит вкладки/варианты «Файл», «Текст», «Ссылка». Аудио загружается через «Файл»; ссылка распознаёт обычную веб-страницу и YouTube.
- [ ] Создание не требует активного проекта. После успеха открыть новый `/library/:id`; подключение к проекту остаётся отдельным необязательным действием.
- [ ] `AddToProjectDialog` загружает активные проекты, роль и назначение; после успеха обновляет `usages`, не перезапускает обработку.
- [ ] Список отображает человеческую сводку качества: «Нужно проверить: 3 страницы», а не wire enum.

### Verification

```powershell
npm run typecheck
npm run build
docker compose restart web
```

Браузерная проверка на этом этапе:

- открыть `/library`, ввести поиск и фильтр;
- открыть материал кликом и клавишей Enter;
- вернуться и убедиться, что query params и scroll сохранены;
- проверить, что delete/menu не открывают просмотрщик;
- загрузить материал без проекта и затем подключить к проекту.

### Commit

```powershell
git add frontend/src/screens/Library.tsx frontend/src/screens/library/LibraryFilters.tsx frontend/src/screens/library/AddLibraryMaterialDialog.tsx frontend/src/screens/library/AddToProjectDialog.tsx frontend/src/app/screens.ts frontend/src/app/views.ts frontend/src/app/AppLayout.tsx frontend/src/styles/layout.css
git commit -m "feat: open materials from global library"
```

---

## Task 10: Собрать нейтральные инструменты просмотрщика

**Files:**

- Create: `frontend/src/components/domain/material-viewer/ViewerToolbar.tsx`
- Create: `frontend/src/components/domain/material-viewer/DocumentStage.tsx`
- Create: `frontend/src/components/domain/material-viewer/StructuredPage.tsx`
- Create: `frontend/src/components/domain/material-viewer/PdfOutline.tsx`
- Create: `frontend/src/components/domain/material-viewer/TimedTranscript.tsx`
- Modify: `frontend/src/components/domain/material-viewer/index.ts`
- Create: `frontend/src/hooks/useMaterialViewport.ts`
- Create: `frontend/src/hooks/useDocumentSearch.ts`

### Component boundaries

`ViewerToolbar` получает только состояние просмотра и callbacks:

```ts
interface ViewerToolbarProps {
  presentation: MaterialPresentation;
  mode: MaterialViewMode;
  page: number;
  pageCount: number;
  query: string;
  zoom: number | "fit-page" | "fit-width";
  showRegions: boolean;
  fullscreen: boolean;
  onModeChange(mode: MaterialViewMode): void;
  onPageChange(page: number): void;
  onQueryChange(query: string): void;
  onZoomChange(zoom: number | "fit-page" | "fit-width"): void;
  onToggleRegions(): void;
  onToggleFullscreen(): void;
}
```

Компонент не знает о `projectId`, bindings, OCR-mode или API.

### Steps

- [ ] Извлечь из текущего `Materials.tsx` вычисление fit zoom, resize observer, page keyboard shortcuts, fullscreen, edge navigation и поиск в два hooks. Сохранить действующее поведение.
- [ ] `DocumentStage` реализует `compare/source/text`, перетаскиваемый разделитель, связанную прокрутку и раскрытие одной половины. Состояние ширины хранить по material id в localStorage.
- [ ] `StructuredPage` отображает существующий Markdown/элементы/изображения без проектных привязок; selection/focus передаются необязательными props для проектного потребителя.
- [ ] `PdfOutline` реализует древовидную клавиатурную навигацию, active page, auto-expand и вкладки «Оглавление»/«Страницы». Миниатюры ленивые; если это ухудшает срок или производительность, допустимы аккуратные номера страниц — это разрешённая визуальная свобода.
- [ ] `TimedTranscript` отображает временные сегменты, форматирует `hh:mm:ss`, вызывает `onSeek(time_from)` и подсвечивает активный сегмент.
- [ ] `useDocumentSearch` принимает async provider и не знает о project/library. Для Библиотеки provider вызывает глобальный `/search`, для project viewer — существующий проектный поиск. Hook хранит query, matches, current index, loading/error и отменяет устаревший запрос.
- [ ] Не добавлять CSS в компоненты inline, кроме вычисляемых размеров/transform. Все цвета и постоянная геометрия пойдут в `library-viewer.css` следующего задания.
- [ ] Подключить новые hooks обратно в проектный viewer только после того, как их API стабилен; на этом шаге достаточно добиться typecheck без изменения визуальной композиции проекта.

### Verification

```powershell
npm run typecheck
npm run build
```

### Commit

```powershell
git add frontend/src/components/domain/material-viewer frontend/src/hooks/useMaterialViewport.ts frontend/src/hooks/useDocumentSearch.ts
git commit -m "refactor: extract neutral material viewer tools"
```

---

## Task 11: Реализовать типоспецифичную рабочую область

**Files:**

- Create: `frontend/src/screens/library/LibraryMaterialWorkspace.tsx`
- Create: `frontend/src/screens/library/MaterialSourceView.tsx`
- Create: `frontend/src/screens/library/WebSnapshotView.tsx`
- Create: `frontend/src/screens/library/AudioTranscriptView.tsx`
- Create: `frontend/src/hooks/useLibraryMaterial.ts`
- Create: `frontend/src/styles/library-viewer.css`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/app/views.ts`

### State owner

`useLibraryMaterial(materialId)` владеет:

- detail, active/historical revision, page and polling task;
- `refreshDetail`, `loadPage`, `startProcessing`, `controlProcessing`;
- optimistic conflict refresh;
- AbortController на смене material/revision/page;
- не хранит визуальные ширины и fullscreen.

### Source selection

`MaterialSourceView` делает исчерпывающий switch по `presentation_kind`:

- `pdf`: page image + `StructuredPage`, outline visible by default when available;
- `image`: source image + recognized text, no empty outline for one image;
- `document`: formatted `StructuredPage` as «Документ» + normalized text;
- `plain_text`: source text/Markdown rendering + prepared text;
- `web`: `WebSnapshotView` with URL, retrieved_at, saved Markdown and external link;
- `youtube`: source card + `TimedTranscript`, timestamp opens `source_url?t=SECONDS` in external browser;
- `audio`: sticky `<audio controls>` using global source endpoint + `TimedTranscript`, segment seeks `currentTime`.

### Steps

- [ ] Собрать полноразмерный header, локальную навигацию, центральную сцену и пустой контейнер инспектора. Инспектор будет заполнен в Task 12, но место не должно выглядеть пустым: временно показывать рабочую карточку текущего статуса и метаданные.
- [ ] Реализовать возврат через `libraryReturnTo`; fallback — `/library`.
- [ ] Загружать текущую страницу только для ready-версии; до обработки показывать осмысленный empty state и действие, связанное с будущим инспектором.
- [ ] Для historical revision показывать полосу read-only и отключать mutation controls.
- [ ] PDF-outline показывать слева сразу при `outline_source != none`; при `none` панель отсутствует, кнопка disabled с пояснением.
- [ ] Синхронизировать page selection между outline, toolbar, source и text.
- [ ] Подключить toolbar search к глобальному endpoint; `Enter`/`Shift+Enter` листают совпадения, выбор результата открывает страницу и фокусирует fragment/bbox.
- [ ] При первой обработке, когда активной версии ещё нет, показывать готовые страницы через task preview contract. При повторной обработке оставлять на экране активную версию до полного переключения.
- [ ] Для типов без исходного второго представления не показывать сегмент «Сравнение».
- [ ] Реализовать loading skeleton в реальной геометрии, error state с повтором и not-found возвратом в Библиотеку.
- [ ] Подключить `library-viewer.css` в `main.tsx` после доменных стилей и до `layout.css`.
- [ ] Использовать `minmax(0, 1fr)`, `min-height: 0`, локальный overflow для колонок и полную высоту viewport; не допускать двойной вертикальной прокрутки окна и сцены.
- [ ] Добавить адаптацию: при ширине <900 px outline и inspector становятся слоями, сравнение — вкладками.

### Required browser checks before commit

После `docker compose restart web` открыть по одному материалу каждого `presentation_kind` и проверить:

- PDF с outline и PDF без outline;
- одиночное изображение;
- DOCX с заголовками и списком;
- TXT и Markdown;
- сохранённую веб-страницу offline;
- YouTube transcript с переходом по времени;
- локальное аудио с seek по сегменту.

Размеры: 1600×1000, 1280×800, 899×900. Темы: светлая и тёмная. Для каждого размера сохранить screenshot в `output/playwright/library-workspace/` только на время ревью; добавлять screenshots в git не нужно.

### Verification

```powershell
npm run typecheck
npm run build
docker compose restart web
```

### Commit

```powershell
git add frontend/src/screens/library/LibraryMaterialWorkspace.tsx frontend/src/screens/library/MaterialSourceView.tsx frontend/src/screens/library/WebSnapshotView.tsx frontend/src/screens/library/AudioTranscriptView.tsx frontend/src/hooks/useLibraryMaterial.ts frontend/src/styles/library-viewer.css frontend/src/main.tsx frontend/src/app/views.ts
git commit -m "feat: build source-aware library workspace"
```

---

## Task 12: Реализовать инспектор обработки, версий и файла

**Files:**

- Create: `frontend/src/screens/library/LibraryMaterialInspector.tsx`
- Create: `frontend/src/screens/library/LibraryProcessingPanel.tsx`
- Create: `frontend/src/screens/library/MaterialRevisionPanel.tsx`
- Create: `frontend/src/screens/library/LibraryMaterialFilePanel.tsx`
- Modify: `frontend/src/screens/library/LibraryMaterialWorkspace.tsx`
- Modify: `frontend/src/screens/library/AddToProjectDialog.tsx`
- Modify: `frontend/src/styles/library-viewer.css`
- Reuse: `frontend/src/screens/AiCleanupPanel.tsx`
- Reuse: `frontend/src/components/domain/TaskRow.tsx`

### OCR cards

Зафиксировать порядок и тексты:

```ts
const OCR_MODES = [
  { id: "fast", title: "Быстро", meta: "Локально · CPU", enabled: true,
    description: "Обычный текст, фотографии лекций и сканы без отправки данных." },
  { id: "textbook", title: "Учебник", meta: "Локально · GPU", enabled: false,
    description: "Сложная вёрстка, таблицы и печатные учебники.",
    reason: "Нужен совместимый локальный GPU runtime." },
  { id: "cloud", title: "Облако", enabled: false,
    description: "Недорогой облачный разбор PDF и документов.",
    reason: "Появится после подключения облачного распознавания." },
  { id: "maximum", title: "Максимум", enabled: false,
    description: "Структурированный текст, таблицы, иерархия и координаты.",
    reason: "Появится после подключения расширенного document parser." },
  { id: "expert", title: "Эксперт", enabled: false,
    description: "Дополнительная проверка сложных элементов и сомнительных формул.",
    reason: "Появится вместе с экспертной проверкой распознавания." },
];
```

### Steps

- [ ] Создать Radix Tabs `Обработка / Версии / Файл`, default `Обработка`, запомнить вкладку для материала в URL `?panel=` или локально; не смешивать с list filters при прямом маршруте.
- [ ] Для PDF/image `LibraryProcessingPanel` показывает пять карточек, человеческую сводку страниц и scope radio group `Весь документ / Только страницы, которые нужно проверить / Диапазон`.
- [ ] Для document/plain_text/web/youtube/audio заменить OCR-card stack компактным релевантным блоком, используя `processingTitle` из presentation mapping.
- [ ] Перед глобальным запуском показать `affected project count` и раскрываемые названия. Для будущего cloud дополнительно зарезервировать место под provider/data/cost, но не рисовать фальшивые числа.
- [ ] Интегрировать `TaskRow` и polling: progress, pause, resume, retry. Формулировать этап конкретно.
- [ ] Добавить ручную правку активной страницы и переиспользовать существующий `AiCleanupPanel`; historical mode отключает обе команды.
- [ ] `MaterialRevisionPanel` показывает происхождение человеческими фразами, scope, summary, current marker; click меняет `revision` query param и переводит сцену read-only.
- [ ] «Восстановить как новую» открывает подтверждение с affected projects, вызывает restore, затем возвращает на новую active revision.
- [ ] `LibraryMaterialFilePanel` показывает метаданные, source URL/retrieved_at, usages, «Добавить в проект», переходы к проектам, раскрываемые технические сведения и существующий delete-preview.
- [ ] Добавить «Скачать исходник»: локальный файл скачивается с исходным именем, web/YouTube — как сохранённый снимок; внешняя ссылка остаётся отдельным действием и не подменяет скачивание.
- [ ] Для web/YouTube показывать «Обновить снимок»/«Обновить субтитры», подтверждение и результат новой ревизии. Для локальных файлов этой команды нет.
- [ ] Удаление после успеха возвращает на сохранённый список Библиотеки; отмена не меняет маршрут.
- [ ] Все disabled-карточки доступны с клавиатуры для чтения причины; не использовать disabled button как единственный контейнер tooltip, потому что он может не получать фокус.

### Verification

```powershell
npm run typecheck
npm run build
docker compose restart web
```

Browser matrix:

- новый PDF → «Подготовить материал»;
- ready PDF → «Запустить заново», все три scope;
- processing → progress/pause/resume;
- failed → прежняя версия видна, retry работает;
- historical → read-only banner, edit/cleanup disabled;
- restore → новый номер ревизии;
- web refresh offline failure → старая версия сохранена;
- material in 2 projects → оба имени видны перед run/delete;
- ни на одной вкладке нет привязок.

### Commit

```powershell
git add frontend/src/screens/library/LibraryMaterialInspector.tsx frontend/src/screens/library/LibraryProcessingPanel.tsx frontend/src/screens/library/MaterialRevisionPanel.tsx frontend/src/screens/library/LibraryMaterialFilePanel.tsx frontend/src/screens/library/LibraryMaterialWorkspace.tsx frontend/src/screens/library/AddToProjectDialog.tsx frontend/src/styles/library-viewer.css
git commit -m "feat: add library processing and revision inspector"
```

---

## Task 13: Перевести проектный просмотрщик на общие инструменты и усилить границу

**Files:**

- Modify: `frontend/src/screens/Materials.tsx`
- Modify: `frontend/src/hooks/useProjectMaterials.ts`
- Modify: `frontend/src/styles/layout.css`
- Modify: `frontend/src/styles/library-viewer.css`
- Modify: `frontend/src/screens/ProjectWorkspace.tsx`

### Steps

- [ ] Заменить дублированные toolbar/fit/fullscreen/page-edge/search/structured page в `Materials.tsx` общими компонентами Task 10, сохранив проектные bindings как композиционные overlays/callbacks.
- [ ] Не переносить `BindingsTab`, topic picker, fragment bind/unbind и project answer actions в общие компоненты.
- [ ] В проектной вкладке «Обработка» заменить мутационные действия общим материалом на заметную ссылку **«Открыть обработку в Библиотеке»**; оставить текущий TaskRow/status для наблюдения, если он нужен в проекте.
- [ ] Ссылка включает `returnTo` на текущую страницу/фрагмент проекта, чтобы возврат не терял контекст.
- [ ] Если ручная правка из project viewer сохраняется ради короткого сценария, перед открытием диалога показать: **«Изменение будет использоваться во всех проектах с этим материалом.»** Не дублировать history UI.
- [ ] Проверить переходы из `ProjectWorkspace` к точной странице и фрагменту: они продолжают открывать проектный viewer с привязками, а не глобальную Библиотеку.
- [ ] Удалить только реально ставшие неиспользуемыми CSS-блоки; не проводить большой эстетический рефакторинг проектного экрана в этом задании.

### Verification

```powershell
npm run typecheck
npm run build
docker compose restart web
python backend/scripts/check_manual_binding.py
```

Browser checks:

- открыть проектный материал с существующими привязками;
- выделить фрагмент, привязать/снять/undo;
- найти текст, перейти по странице, включить полный экран;
- открыть обработку в Библиотеке и вернуться;
- убедиться, что глобальный экран не получил ни одной binding-команды.

### Commit

```powershell
git add frontend/src/screens/Materials.tsx frontend/src/hooks/useProjectMaterials.ts frontend/src/styles/layout.css frontend/src/styles/library-viewer.css frontend/src/screens/ProjectWorkspace.tsx
git commit -m "refactor: share viewer tools across material contexts"
```

---

## Task 14: Финальная проверка поведения, языка и визуальной плотности

**Files:**

- Modify if needed: `SCREENS.md`
- Modify if needed: `docs/architecture/global-library-material-workspace.md`
- Do not commit: `output/playwright/library-workspace/*`

### Automated verification

- [ ] Выполнить полный frontend-check:

```powershell
npm run typecheck
npm run build
```

- [ ] Выполнить backend checks:

```powershell
cd backend
python -m pytest tests/test_library_material_workspace.py tests/test_material_revisions.py tests/test_material_sources.py tests/test_material_segmentation.py tests/test_binding_transfer.py tests/test_ai_cleanup.py tests/test_fragment_search.py -q
python -m ruff check .
cd ..
python backend/scripts/check_stage2.py
python backend/scripts/check_stage3.py
python backend/scripts/check_stage4.py
python backend/scripts/check_stage5.py
python backend/scripts/check_manual_binding.py
python backend/scripts/check_ai_gateway.py
python backend/scripts/check_library_workspace.py
```

- [ ] Проверить пользовательские технические строки:

```powershell
rg -n 'label: "(native|ocr|ocr_low)"|title: "(native|ocr|ocr_low)"|>\s*(native|ocr|ocr_low)\s*<' frontend/src
rg -n "Привязк|Сопоставить автоматически|Покрытие" frontend/src/screens/library frontend/src/components/domain/material-viewer
```

Первая команда должна быть пустой. Вторая допускает только явные тестовые/комментарийные отрицания; в rendered library UI совпадений быть не должно.

### Browser acceptance checklist

После `docker compose restart web`:

- [ ] 1600×1000, light: PDF outline + compare + inspector помещаются без неоправданных пустот.
- [ ] 1600×1000, dark: контраст текста, disabled modes, предупреждения и разделители читаемы.
- [ ] 1280×800: заголовок не вытесняет page navigation, правая панель практична, сцена не схлопывается.
- [ ] 899×900: outline/inspector открываются слоями, source/text переключаются, горизонтальной прокрутки страницы нет.
- [ ] Очень длинное русское имя файла сокращается, полное имя доступно.
- [ ] PDF outline работает мышью и клавиатурой; текущий пункт следует за страницей.
- [ ] PDF без outline не оставляет пустую колонку.
- [ ] Search, page edges, arrows, zoom, fit-page, fit-width, regions, `F`, `Esc` работают.
- [ ] Global search не требует активного проекта, переходит к точной странице и корректно работает в исторической версии.
- [ ] Web snapshot и YouTube transcript читаются offline.
- [ ] Audio seek по сегменту работает и current segment подсвечивается.
- [ ] Все пять OCR-mode cards видны у PDF/image; только `Быстро` реально запускается.
- [ ] Человеческие качества используются в списке, viewer, inspector, UI kit и project viewer.
- [ ] Screen reader landmarks, focus order, focus ring, tabs, tree and dialogs проверены хотя бы клавиатурой и accessibility snapshot.
- [ ] Фильтры/scroll списка сохраняются после возврата.
- [ ] Глобальные изменения показывают affected projects; physical delete показывает preview.
- [ ] Привязки существуют только в project viewer.

### Documentation closeout

- [ ] Сверить фактические имена endpoints, полей и компонентов с архитектурным документом; исправить документ, а не оставлять расхождение.
- [ ] В `SCREENS.md` поставить фактический статус реализации и дату только после всех проверок.
- [ ] Удалить временные screenshots, созданные этой работой, или оставить их untracked; не удалять чужие артефакты.
- [ ] Проверить `git status --short` и `git diff --check`; отделить чужие изменения.

### Final verification and commit

```powershell
git diff --check
git status --short
```

Если документация потребовала финальных собственных правок:

```powershell
git add SCREENS.md docs/architecture/global-library-material-workspace.md
git commit -m "docs: record completed library workspace"
```

Если правок нет, отдельный пустой коммит не делать.

---

## Handoff notes for the implementing agent

1. Сначала прочитать спецификацию целиком и пройти Task 1; не начинать с JSX-макета.
2. Не пытаться добавить global mode в существующий `MaterialSurface`: его проектное состояние уже содержит bindings и будет источником смешения границ.
3. Самые рискованные места — полная ревизия при частичном OCR, сохранение исторических фрагментов, перенос привязок и byte-range аудио. Их тестировать до визуальной полировки.
4. Визуальную свободу использовать для выравнивания и плотности, но не для перестановки продуктовых зон. Сначала проверить 1600×1000 с настоящим PDF и длинным оглавлением, затем уменьшать ширину.
5. Любой новый внешний AI-вызов запрещён этой задачей. Глобальный AI cleanup только переиспользует уже зарегистрированную роль и существующий preflight/usage contract.
6. Не считать работу законченной по typecheck: обязательны сквозной API-скрипт и browser matrix из Task 14.
