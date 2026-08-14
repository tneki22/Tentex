# Центрированное состояние загрузки Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать все начальные загрузки экранов заметным, спокойным центром рабочей области, а загрузки вложенных зон — центром их контейнера.

**Architecture:** `LoadingState` остаётся одним UI-примитивом. Его новый вариант `placement` управляет только раскладкой, поэтому подписи и API 17 потребителей не меняются. Ранние возвраты целых экранов получают `placement="page"`; вложенные запросы остаются на безопасном значении `section`.

**Tech Stack:** React, TypeScript, CSS с токенами Tentex, Vite.

## Global Constraints

- Русский текст интерфейса, английские идентификаторы.
- Значения CSS берутся только из токенов; `transition: all` не применяется.
- Индикатор не показывает процент и не заменяет прогресс измеримой работы.
- При `prefers-reduced-motion` движение кольца отключено.
- Тестового раннера фронтенда пока нет; проверка состоит из typecheck, production build и живого просмотра после `docker compose restart web`.

---

### Task 1: Варианты единого примитива загрузки

**Files:**
- Modify: `frontend/src/components/ui/LoadingState.tsx:1-8`
- Modify: `frontend/src/styles/ui-kit.css:222-257`

**Interfaces:**
- Consumes: существующий `label?: string`.
- Produces: `LoadingState({ label, placement }: { label?: string; placement?: "page" | "section" })`.

- [ ] **Step 1: Добавить контракт размещения к компоненту**

```tsx
type LoadingPlacement = "page" | "section";

export function LoadingState({ label = "Загружаем", placement = "section" }: {
  label?: string;
  placement?: LoadingPlacement;
}) {
  return <div className={`loading-state loading-state--${placement}`} role="status">…</div>;
}
```

- [ ] **Step 2: Заменить полоску неопределённого ожидания на кольцо**

В `ui-kit.css` собрать `.loading-state` как центрированную группу с кольцевым индикатором и подписью. `page` занимает доступную высоту рабочей области, `section` сохраняет небольшую минимальную высоту. В `@media (prefers-reduced-motion: reduce)` отключить вращение кольца.

- [ ] **Step 3: Проверить типы и стили**

Run: `npm run typecheck && npm run build`

Expected: обе команды завершаются с кодом 0; в CSS нет чисел вне существующих исключений или `transition: all`.

### Task 2: Пометить начальные загрузки экранов

**Files:**
- Modify: `frontend/src/screens/Projects.tsx`
- Modify: `frontend/src/screens/ProjectWorkspace.tsx`
- Modify: `frontend/src/screens/Program.tsx`
- Modify: `frontend/src/screens/ProjectSettings.tsx`
- Modify: `frontend/src/screens/Library.tsx`
- Modify: `frontend/src/screens/CoverageMap.tsx`
- Modify: `frontend/src/screens/ProjectWizard.tsx`
- Modify: `frontend/src/screens/AiSettingsSection.tsx`

**Interfaces:**
- Consumes: `LoadingState` с `placement="page"` из Task 1.
- Produces: все загрузки, которые заменяют поверхность экрана до прихода данных, используют `page`; загрузки внутри диалогов, вкладок, инспекторов и строк остаются `section`.

- [ ] **Step 1: Обновить только ранние возвраты целых экранов**

Заменить `return <LoadingState label="…" />` на `return <LoadingState label="…" placement="page" />` там, где состояние загрузки замещает весь экран. Не менять вызовы рядом с уже отрисованными данными, например `slotLoading` на Карте покрытия и загрузку каталога в диалоге параметров ИИ.

- [ ] **Step 2: Проверить границу вариантов**

Run: `rg -n '<LoadingState' frontend/src`

Expected: каждый начальный экранный return имеет `placement="page"`; вызов внутри существующей поверхности не имеет `placement` и получает `section` по умолчанию.

- [ ] **Step 3: Проверить типы**

Run: `npm run typecheck`

Expected: команда завершается с кодом 0.

### Task 3: Показать оба состояния в витрине и проверить живой интерфейс

**Files:**
- Modify: `frontend/src/screens/UiKit.tsx:620-628`

**Interfaces:**
- Consumes: `LoadingState` из Task 1.
- Produces: на `/ui-kit` одновременно видны вариант всей рабочей области и вариант локальной зоны.

- [ ] **Step 1: Добавить на витрину оба варианта**

```tsx
<LoadingState placement="page" label="Загружаем рабочую область" />
<LoadingState label="Загружаем каталог моделей" />
```

- [ ] **Step 2: Собрать production-вариант**

Run: `npm run typecheck && npm run build`

Expected: обе команды завершаются с кодом 0.

- [ ] **Step 3: Перезапустить фронтенд и посмотреть в браузере**

Run: `docker compose restart web`

Expected: контейнер `web` запущен; на `/ui-kit` полная загрузка находится по центру доступной рабочей области, локальная — по центру своей зоны; в тёмной теме контраст сохраняется.

- [ ] **Step 4: Закоммитить изменение**

```bash
git add frontend/src/components/ui/LoadingState.tsx frontend/src/styles/ui-kit.css frontend/src/screens/Projects.tsx frontend/src/screens/ProjectWorkspace.tsx frontend/src/screens/Program.tsx frontend/src/screens/ProjectSettings.tsx frontend/src/screens/Library.tsx frontend/src/screens/CoverageMap.tsx frontend/src/screens/ProjectWizard.tsx frontend/src/screens/AiSettingsSection.tsx frontend/src/screens/UiKit.tsx
git commit -m "feat: center loading states"
```
