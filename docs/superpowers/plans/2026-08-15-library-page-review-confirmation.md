# Library Page Review Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Показывать страницы OCR по качеству и сохранять подтверждение слабого OCR после сверки с оригиналом.

**Architecture:** Качество OCR остаётся неизменным, а подтверждение хранится на `MaterialPage` отдельным временем. Детальная карточка материала отдаёт компактные состояния всех страниц, а рабочая область использует их для навигации и вызывает отдельную идемпотентную команду подтверждения.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, SQLite, React, TypeScript, CSS tokens.

## Global Constraints

- `ocr_low` не превращается в `ocr` после пользовательской проверки.
- Подтверждённая страница выглядит как обычная; непроверенная — жёлтая; `ocr` — синяя.
- Подтверждать можно только страницу активной ревизии.
- Новый OCR сбрасывает подтверждение, копирование неизменённой страницы сохраняет его.
- Чужие изменения рабочего дерева не включаются в коммит.

---

### Task 1: Хранение и серверный контракт

**Files:**
- Create: `backend/migrations/versions/20260815_0019_page_review_confirmation.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/materials/schemas.py`
- Modify: `backend/app/materials/library.py`
- Modify: `backend/app/materials/router.py`
- Test: `backend/tests/test_library_material_workspace.py`

**Interfaces:**
- Produces: `MaterialPage.reviewed_at`, `PageStateRead`, `confirm_library_page_review()` и `POST .../confirm-review`.

- [ ] Добавить падающие тесты подтверждения, счётчика и выборки `needs_review`.
- [ ] Добавить nullable-колонку миграцией и моделью.
- [ ] Добавить состояние страниц в схемы чтения.
- [ ] Реализовать идемпотентное подтверждение активной `ocr_low` и пересчёт счётчика.
- [ ] Сохранять подтверждение только при копировании неизменённой страницы.
- [ ] Запустить профильные backend-тесты и Ruff.

### Task 2: Навигация и действие в инспекторе

**Files:**
- Modify: `frontend/src/api/materials.ts`
- Modify: `frontend/src/components/domain/material-viewer/PdfOutline.tsx`
- Modify: `frontend/src/screens/library/LibraryProcessingPanel.tsx`
- Modify: `frontend/src/screens/library/LibraryMaterialInspector.tsx`
- Modify: `frontend/src/screens/library/LibraryMaterialWorkspace.tsx`
- Modify: `frontend/src/styles/library-viewer.css`

**Interfaces:**
- Consumes: `LibraryMaterialDetailRead.page_states`, `MaterialPageRead.reviewed_at`, `confirmLibraryPageReview()`.

- [ ] Добавить типы и клиент команды подтверждения.
- [ ] Передать состояние страницы и обработчик через композицию инспектора.
- [ ] Показать предупреждение и кнопку только на непроверенной `ocr_low` активной ревизии.
- [ ] Добавить классы синего OCR и жёлтого непроверенного OCR в сетку и оглавление.
- [ ] Добавить текстовые подписи статуса для клавиатуры и скринридера.
- [ ] Запустить typecheck и build.

### Task 3: Контракт и сквозная проверка

**Files:**
- Modify: `SCREENS.md`
- Modify: `docs/architecture/global-library-material-workspace.md`

- [ ] Описать отображение и жизненный цикл подтверждения.
- [ ] Перезапустить `web` и проверить рабочую область материала в браузере.
- [ ] Просмотреть собственный diff и закоммитить только собственные файлы.
