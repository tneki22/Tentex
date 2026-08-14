# Editable Material File Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать вкладку «Файл» редактируемым паспортом материала с атомарной заменой файла эталонных ответов.

**Architecture:** Существующий `PATCH /projects/{project_id}/materials/{material_id}` остаётся единственной точкой сохранения. Сервис получает явный флаг подтверждённой замены и внутри одной транзакции освобождает прежний файл ответов; `MaterialRead` дополнительно отдаёт дату связи с проектом. Экранная форма выносится из большого `Materials.tsx` в отдельный компонент с локальным черновиком и явным сохранением.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, SQLite, React, TypeScript, обычный CSS на токенах, Radix-компоненты Tentex.

## Global Constraints

- Физический файл и результаты OCR не редактируются.
- Хотя бы одно назначение материала обязательно.
- В проекте остаётся не более одного материала с назначением `reference_answers`.
- Подтверждённая замена выполняется атомарно и не удаляет существующие эталоны или привязки.
- `affects_program` остаётся производным от `source_role`.
- Несохранённый черновик не сбрасывается фоновым обновлением текущего материала.
- TDD в проекте выключен; профильные тесты добавляются вместе с серверным поведением и прогоняются до коммита.

---

### Task 1: Расширить контракт и атомарное обновление материала

**Files:**
- Modify: `backend/app/materials/schemas.py`
- Modify: `backend/app/materials/service.py`
- Test: `backend/tests/test_material_sources.py`
- Modify: `docs/architecture/stage-5-material-pipeline.md`

**Interfaces:**
- Consumes: существующий `update_material(session, project_id, material_id, command)` и защита `_guard_single_answers_file`.
- Produces: `MaterialUpdate.replace_reference_answers: bool = False`; `MaterialRead.attached_at: datetime`; атомарная замена назначения в `update_material`.

- [ ] **Step 1: Добавить контракт команды и ответа**

В `MaterialUpdate` добавить `replace_reference_answers: bool = False` и model-validator: значение `true` разрешено только когда `purposes` содержит `reference_answers`. В `MaterialRead` добавить `attached_at: datetime`.

- [ ] **Step 2: Реализовать атомарную замену**

В `update_material` до обычной защиты найти другой `ProjectMaterial` с `reference_answers`. Без флага оставить существующий конфликт. С флагом удалить у старой связи `reference_answers`, добавить `study_source`, если список опустел, затем применить текущую команду. `affects_program` пересчитать после смены роли. `_read` заполняет `attached_at=link.created_at`.

- [ ] **Step 3: Покрыть серверное поведение**

Добавить проверки: ответ содержит `attached_at`; все редактируемые поля сохраняются; второй файл ответов без флага даёт `answers_file_already_exists`; подтверждённая замена оставляет старый материал учебным источником и назначает новый; флаг без `reference_answers` даёт 422.

- [ ] **Step 4: Выполнить профильные проверки**

Run: `docker compose exec api python -m pytest -q tests/test_material_sources.py`

Run: `docker compose exec api python -m ruff check app/materials tests/test_material_sources.py`

Expected: все проверки проходят.

- [ ] **Step 5: Обновить серверный контракт и закоммитить**

В `stage-5-material-pipeline.md` описать редактируемые поля, `attached_at` и атомарную замену. Закоммитить только четыре файла задачи сообщением `feat: support editable material project settings`.

---

### Task 2: Построить редактируемую вкладку «Файл»

**Files:**
- Create: `frontend/src/screens/materials/MaterialFileTab.tsx`
- Modify: `frontend/src/screens/Materials.tsx`
- Modify: `frontend/src/api/materials.ts`
- Modify: `frontend/src/styles/layout.css`
- Modify: `SCREENS.md`

**Interfaces:**
- Consumes: `MaterialRead.attached_at`, `useProjectMaterials.update(materialId, command)`, `MaterialUpdate.replace_reference_answers`.
- Produces: `MaterialFileTab` с props `material`, `answersMaterial`, `busy`, `notice`, `onSave`, `onRemove`, `onDismissNotice`.

- [ ] **Step 1: Синхронизировать TypeScript-контракт**

Добавить `attached_at: string` в `MaterialRead`, а в команду `updateMaterial` — `replace_reference_answers?: boolean`.

- [ ] **Step 2: Создать локальную форму**

Компонент хранит `displayName`, `purposes`, `sourceRole`, `priority`, `instruction`; сбрасывает их только при смене `material.id` или после успешного сохранения. Назначения — доступная группа checkbox, минимум одно. Роль — существующий `Select`; приоритет — `input type="number"`; пояснение — `textarea`.

- [ ] **Step 3: Реализовать сохранение и подтверждение**

Обычное сохранение вызывает `onSave(command)`. Если добавляется `reference_answers`, а `answersMaterial.id !== material.id`, сначала открыть `ConfirmDialog`; подтверждение повторяет команду с `replace_reference_answers: true`. Кнопка недоступна без изменений, при невалидной форме и во время запроса.

- [ ] **Step 4: Добавить паспорт файла**

Показывать исходное имя, источник, формат, размер, страницы, сканы, OCR, состояние, режим, даты `attached_at`, `created_at`, `updated_at`, `retrieved_at`; ссылку и оглавление оставить. В раскрываемых технических сведениях показать ID, MIME и активную ревизию. Даты форматировать через `Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" })`.

- [ ] **Step 5: Подключить компонент к экрану**

Удалить локальный read-only `FileTab` из `Materials.tsx`. Передать текущий `answersMaterial` и обработчик, который вызывает `store.update`; после успеха показать «Настройки файла сохранены». Ошибка остаётся в форме через существующий notice/store error.

- [ ] **Step 6: Добавить стили и документацию экрана**

Использовать только токены, сохранить ширину инспектора и вертикальную прокрутку. Разделить форму, паспорт и опасное действие визуально. Обновить вкладку «Файл» в `SCREENS.md`.

- [ ] **Step 7: Проверить фронтенд и закоммитить**

Run: `npm run typecheck`

Run: `npm run lint`

Run: `npm run build`

Expected: команды проходят. Закоммитить только файлы задачи сообщением `feat: make material file tab editable`.

---

### Task 3: Интеграционная и браузерная проверка

**Files:**
- Modify only if verification exposes a defect in files from Tasks 1–2.

**Interfaces:**
- Consumes: готовый API и `MaterialFileTab`.
- Produces: проверенный сценарий смены назначения и сохранения паспорта.

- [ ] **Step 1: Прогнать полный серверный набор**

Run: `docker compose exec api python -m pytest -q`

Expected: все тесты проходят; допустимо только уже известное предупреждение Starlette.

- [ ] **Step 2: Перезапустить web**

Run: `docker compose restart web`

Expected: `http://localhost:5173` отвечает 200.

- [ ] **Step 3: Проверить обычное редактирование**

В реальном браузере открыть материал → «Файл», изменить и сохранить отображаемое название, роль, приоритет и пояснение; обновить страницу и убедиться, что значения сохранились. Исходный файл и результаты OCR не должны измениться.

- [ ] **Step 4: Проверить замену ответов**

На материале-учебном источнике включить «Эталонные ответы». При существующем файле увидеть подтверждение; отмена не меняет данные, подтверждение назначает текущий файл и оставляет старый учебным источником.

- [ ] **Step 5: Проверить визуальные состояния**

Проверить светлую и тёмную темы, длинное имя, заполненное пояснение, технические сведения и ширину 390 px. Не открывать содержимое прикреплённого пользователем документа; проверяется только инспектор.

- [ ] **Step 6: Финальная целостность**

Run: `git diff --check`

Run: `docker compose exec api alembic current`

Expected: diff без whitespace-ошибок, одна миграционная голова `20260814_0017`; новая миграция не требуется.
