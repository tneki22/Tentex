# Workspace Interface and Context Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Устранить визуальные переполнения и дубли в экзаменационной Рабочей области, согласовать понятие учебного источника между вкладкой «Источники», поиском и чатом, а также исправить сводный конспект.

**Architecture:** `answers_file` остаётся технической привязкой файла с ответами и показывается во вкладке «Ответ», но не считается учебным источником для вкладки «Источники», общего поиска и контекста чата. Визуальные правки остаются локальными для Рабочей области и существующих примитивов; серверный контракт меняется только там, где сейчас возвращается неверная семантика (`already_bound`, состав контекста, номер конспекта).

**Tech Stack:** React 19, TypeScript, Vite, обычный CSS на токенах Tentex, Radix UI, Milkdown/Crepe + KaTeX, FastAPI, SQLAlchemy, SQLite/FTS5, pytest.

## Global Constraints

- База работы — `main`; реализация ведётся в worktree `.worktrees/workspace-interface-fixes`, ветка `codex/workspace-interface-fixes`.
- В интерфейсе экзамена пользовательский термин — «Ответ»; технические имена `ReferenceAnswer`, `reference_answers`, `answers_file` и существующие поля API не переименовываются.
- Привязка `mechanism="answers_file"` не является учебным источником и не должна дублировать Ответ в контексте чата.
- Поиск остаётся локальным FTS5/BM25 и не вызывает внешнюю модель.
- Цвета, размеры и отступы задаются только существующими токенами; новый UI-примитив не вводится.
- Отдельный мобильный режим не проектируется, но содержимое рабочей зоны не выходит за её границы при минимальной поддерживаемой ширине.
- После фронтенд-правок перезапустить `web`; после серверных правок — `api` и `web`.

---

## Диагноз, на котором строится план

1. `ExaminerControl` вложен в Popover шириной `296px`, но его корень имеет `min-width: 320px`, а `ProviderModelPicker` требует колонки минимум `150px + 220px`. Поэтому карточки, переключатель и селекты физически шире окна.
2. Вкладка «Источники» фильтрует `answers_file`, а `search_project_materials.already_bound` и `exam.context.bound_fragments` считают все активные привязки. Отсюда одновременно пустая вкладка, «Уже привязано» в выдаче и ненулевой `Материал · N` в чате.
3. Кнопка «Новые сообщения» центрируется через `transform: translateX(-50%)`; общий hover `.secondary-button` заменяет весь `transform` на `translateY(-1px)`, поэтому кнопка скачет по горизонтали.
4. `list_conspect_summary` присваивает `position=len(entries)+1`, то есть нумерует только вопросы с непустым конспектом.
5. Формулы в конспекте уже поддержаны: `Crepe.Feature.Latex`, `katexOptions.throwOnError=false`, пункт «Формула» в тулбаре и CSS для `.katex-display` присутствуют и используются также в readonly-сводке.

## Карта файлов

**Серверная семантика и тесты**

- `backend/app/bindings/service.py` — область общего поиска и расчёт `already_bound`.
- `backend/app/exam/context.py` — фрагменты, фактически передаваемые в чат и судье.
- `backend/app/conspects/service.py` — реальная позиция вопроса в сводке.
- `backend/tests/test_bindings.py` — различие учебной привязки и `answers_file` в поиске.
- `backend/tests/test_exam_chat_foundation.py` — состав preview/контекста.
- `backend/tests/test_conspects.py` — нумерация с пропусками непустых конспектов.

**Рабочая область**

- `frontend/src/screens/ProjectWorkspace.tsx` — Ответ, Источники и действие поиска.
- `frontend/src/screens/workspace/chat/ChatHeader.tsx` — компактная шапка, история и дата.
- `frontend/src/screens/workspace/chat/ExamChatPanel.tsx` — убрать бесполезную кнопку «Задать вопрос».
- `frontend/src/screens/workspace/chat/ExaminerControl.tsx` — класс Popover и терминология.
- `frontend/src/screens/workspace/chat/ContextChips.tsx` — «Ответ» и честный счётчик материалов.
- `frontend/src/components/domain/ConspectSummary.tsx` — раскрываемый индекс вопросов.
- `frontend/src/api/conspects.ts` — тип позиции остаётся `number`, контракт не расширяется.
- `frontend/src/styles/chat.css`, `frontend/src/styles/layout.css`, `frontend/src/styles/conspects.css` — локальная адаптивность.

**Терминология и контракты**

- `frontend/src/screens/CoverageMap.tsx`, `frontend/src/screens/Materials.tsx` и связанные диалоги/виджеты экзамена — видимые строки «эталон» → «ответ».
- `SCREENS.md`, `docs/architecture/exam-chat.md`, `docs/architecture/pre-stage-6-search-and-manual-binding.md`, `docs/architecture/conspects.md` — фактическое поведение после правок.

---

### Task 1: Согласовать учебные источники, поиск и контекст чата

**Files:**

- Modify: `backend/app/bindings/service.py`
- Modify: `backend/app/exam/context.py`
- Modify: `backend/tests/test_bindings.py`
- Modify: `backend/tests/test_exam_chat_foundation.py`

**Interfaces:**

- Consumes: `MaterialPurpose.REFERENCE_ANSWERS`, `BindingMechanism.ANSWERS_FILE`, `ACTIVE_STATUSES`.
- Produces: общий поиск без файлов структуры/ответов; `already_bound` только для учебных привязок; chat manifest без фрагментов `answers_file`.

- [ ] **Step 1: Зафиксировать падающими тестами три наблюдаемых правила**

```python
# 1. Общий поиск проекта не возвращает material с purpose reference_answers.
assert service.search_project_materials(session, project.id, "реляционная модель") == []

# 2. answers_file не делает учебный результат already_bound.
assert result.already_bound is False

# 3. answers_file не появляется вторым экземпляром Ответа в контексте чата.
assert context.fragments == []
assert not any(item["kind"] == "fragment" for item in context.manifest)
```

  Явный поиск с `material_id` оставить рабочим: он нужен внутри открытого материала и не подчиняется общему фильтру проекта.

- [ ] **Step 2: Запустить точечные тесты и подтвердить нынешнее расхождение**

```powershell
cd backend
python -m pytest tests/test_bindings.py tests/test_exam_chat_foundation.py -q
```

Expected: новые проверки падают — `reference_answers` попадает в общий поиск, а `answers_file` попадает в `already_bound`/chat fragments.

- [ ] **Step 3: Ввести один серверный критерий учебного источника**

В `_project_material_ids` исключить при поиске без `material_id` материалы, у которых есть назначение `exam_structure` или `reference_answers`. В запросе `bound_fragment_ids` добавить условие:

```python
Binding.mechanism != BindingMechanism.ANSWERS_FILE
```

В `exam.context.bound_fragments` отфильтровать результаты `list_bindings` тем же правилом до применения `MAX_FRAGMENTS`, чтобы скрытые привязки не съедали лимит настоящих учебных фрагментов.

- [ ] **Step 4: Прогнать профильную серверную регрессию**

```powershell
cd backend
python -m pytest tests/test_bindings.py tests/test_exam_chat_foundation.py tests/test_chat_tools.py -q
python scripts/check_manual_binding.py
python scripts/check_exam_chat.py
python -m ruff check .
```

- [ ] **Step 5: Зафиксировать серверную часть отдельным коммитом**

```powershell
git add backend/app/bindings/service.py backend/app/exam/context.py backend/tests/test_bindings.py backend/tests/test_exam_chat_foundation.py
git commit -m "fix: согласовать источники вопроса и контекст чата"
```

---

### Task 2: Починить поиск и адаптивность вкладки «Источники»

**Files:**

- Modify: `frontend/src/screens/ProjectWorkspace.tsx`
- Modify: `frontend/src/styles/layout.css`

**Interfaces:**

- Consumes: `runSourceSearch()`, `sourceQuery`, `sourceSearchInput`, `SearchResultRead.already_bound` после Task 1.
- Produces: одинаковое действие обеих кнопок поиска и карточки результатов, не выходящие за рабочую зону.

- [ ] **Step 1: Объединить входы в поиск**

Добавить локальный обработчик с одним правилом:

```ts
function runSourceSearchOrFocus() {
  if (sourceQuery.trim()) void runSourceSearch();
  else sourceSearchInput.current?.focus();
}
```

Пустая кнопка «Найти в материалах» вызывает его; submit формы по-прежнему вызывает `runSourceSearch`. Таким образом предзаполненная формулировка вопроса запускает поиск сразу, а действительно пустая строка получает фокус.

- [ ] **Step 2: Убрать неустойчивую сетку карточки результата**

Сгруппировать фрагмент и подпись источника в `.workspace-source-tab-result-copy`, а статус и действие оставить отдельными элементами. На широкой зоне использовать `minmax(0, 1fr) auto auto`; на узкой — переносить статус и кнопку целиком на следующую строку. Текст получает `min-width: 0`, перенос строк и `overflow-wrap: anywhere`; кнопки не сжимаются и не выходят за рамку.

- [ ] **Step 3: Выровнять строку поиска и пустое состояние**

Сделать поле и «Найти» одной высоты через общий `min-height`/stretch, а не пиксельную подгонку. Для узкой зоны:

```css
.workspace-source-tab-empty-actions { flex-wrap: wrap; }
.workspace-source-tab-search { grid-template-columns: minmax(0, 1fr) auto; }
@media (max-width: 600px) {
  .workspace-source-tab { padding-inline: var(--space-4); }
  .workspace-source-tab-search { grid-template-columns: minmax(0, 1fr); }
  .workspace-source-tab-search > button { width: 100%; }
}
```

- [ ] **Step 4: Проверить сценарий на реальных данных**

После `docker compose restart api web` проверить: пустой список → кнопка запускает поиск; результат из файла ответов не появляется; учебный результат показывает «Привязать»; после привязки появляется в верхнем списке и становится «Уже привязано»; при ширине зоны 360–600 px видны текст, качество и обе кнопки.

- [ ] **Step 5: Зафиксировать вкладку отдельным коммитом**

```powershell
git add frontend/src/screens/ProjectWorkspace.tsx frontend/src/styles/layout.css
git commit -m "fix: сделать поиск источников согласованным и адаптивным"
```

---

### Task 3: Упростить шапку чата и стабилизировать элементы управления

**Files:**

- Modify: `frontend/src/screens/workspace/chat/ChatHeader.tsx`
- Modify: `frontend/src/screens/workspace/chat/ExamChatPanel.tsx`
- Modify: `frontend/src/screens/workspace/chat/ExaminerControl.tsx`
- Modify: `frontend/src/styles/chat.css`

**Interfaces:**

- Consumes: существующие `ChatSessionSummary.updated_at`, `message_count`, настройки сессии.
- Produces: компактная панель действий без повторного вопроса/названия чата; стабильная кнопка прокрутки; адаптивный Popover экзаменатора.

- [ ] **Step 1: Убрать дубли из ChatHeader**

Удалить проп `question`, `.chat-panel-heading`, `.chat-panel-question`, `.chat-panel-title` и `chat-history-title`. В истории каждая строка показывает только дату/время и количество сообщений; `item.title` остаётся в API для совместимости, но интерфейс его не использует.

- [ ] **Step 2: Форматировать сегодняшние чаты относительно локального дня**

```ts
function sessionTime(iso: string, now = new Date()): string {
  const value = new Date(iso);
  const time = new Intl.DateTimeFormat("ru-RU", { timeStyle: "short" }).format(value);
  if (value.toDateString() === now.toDateString()) return `Сегодня, ${time}`;
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(value);
}
```

Сравнение делается по календарной дате, а не по разнице менее 24 часов.

- [ ] **Step 3: Убрать кнопку «Задать вопрос»**

В пустом приглашении оставить «Сдать ответ» и «Найти в материалах». Обычный композер остаётся доступным внизу и сохраняет возможность отправить сообщение; текст приглашения заменить на нейтральный «Выберите действие или напишите сообщение».

- [ ] **Step 4: Сделать ExaminerControl контейнерно-адаптивным**

Передать Popover локальный класс `chat-examiner-popover`. Убрать `min-width: 320px` у внутреннего блока, задать ширину через `min(24rem, calc(100vw - ...))`, всегда складывать `ProviderModelPicker` внутри этого Popover в одну колонку и разрешить перенос длинных подписей RadioCards. Не менять общий `ProviderModelPicker` на страницах настроек.

- [ ] **Step 5: Исправить скачок «Новые сообщения»**

Отделить постоянное горизонтальное смещение от hover-transform:

```css
.chat-jump-button {
  left: 50%;
  translate: -50% 0;
  transform: none;
}
```

Общий hover сможет менять только `transform: translateY(-1px)`, не сбрасывая `translate`.

- [ ] **Step 6: Проверить чат при нескольких ширинах**

Проверить одну широкую зону, две зоны рядом и ширину 390 px: шапка не оставляет пустой блок слева, действия переносятся целиком, Popover не выходит за viewport, кнопка «Новые сообщения» остаётся под курсором при hover/focus/active.

- [ ] **Step 7: Зафиксировать чат отдельным коммитом**

```powershell
git add frontend/src/screens/workspace/chat frontend/src/styles/chat.css
git commit -m "fix: упростить и стабилизировать интерфейс чата"
```

---

### Task 4: Перестроить вкладку «Ответ» и заменить пользовательский «эталон»

**Files:**

- Modify: `frontend/src/screens/ProjectWorkspace.tsx`
- Modify: `frontend/src/styles/layout.css`
- Modify: `frontend/src/screens/workspace/chat/ContextChips.tsx`
- Modify: `frontend/src/screens/workspace/chat/ExaminerControl.tsx`
- Modify: `frontend/src/screens/CoverageMap.tsx`
- Modify: `frontend/src/screens/Materials.tsx`
- Modify: `frontend/src/screens/materials/MaterialFileTab.tsx`
- Modify: `frontend/src/screens/answers/AnswerSourceDialog.tsx`
- Modify: `frontend/src/components/domain/AnswerMatchStatus.tsx`
- Modify: `frontend/src/components/domain/LibraryMaterialPickerDialog.tsx`

**Interfaces:**

- Consumes: `ReferenceAnswerBadge`, `answerViewMode`, `answerScanGroups`, существующие ссылки на карту Ответов.
- Produces: порядок «Текст/Страницы → ответ → нижняя метаинформация» без повторного вопроса и единая пользовательская терминология экзамена.

- [ ] **Step 1: Перестроить разметку активного ответа**

Удалить верхний `<header>` и `<h2>{selected.title}</h2>`. Сохранить первым элементом `SegmentedTabs`, затем текст/страницы, затем единый `.workspace-reference-footer`:

```tsx
<footer className="workspace-reference-footer">
  <Link to={answerPath}>Открыть и изменить ответ</Link>
  <div className="workspace-reference-meta">
    <ReferenceAnswerBadge status={answerSlot.status} />
    <span>{source} · {match}</span>
  </div>
</footer>
```

На узкой зоне footer переносится по строкам без горизонтального overflow; сам текст начинается сразу под переключателем, без компенсационных пустых отступов.

- [ ] **Step 2: Заменить видимое слово «эталон» на «ответ» в экзаменационных поверхностях**

Обязательные формулировки: `Эталон` → `Ответ`, `эталонный ответ` → `ответ`, `эталонные ответы` → `ответы` или `файл с ответами`, `Открыть эталоны` → `Открыть ответы`, `Загружаем эталон` → `Загружаем ответ`. В чипе контекста использовать `Ответ`; в пояснении экзаменатора — «факты и ответ не меняются».

Комментарии и идентификаторы не переписывать ради косметики. После прохода выполнить:

```powershell
rg -n -S 'Эталон|эталон' frontend/src --glob '*.tsx' --glob '*.ts'
```

Каждое оставшееся совпадение классифицировать: технический комментарий допустим, видимая пользователю строка экзамена — нет.

- [ ] **Step 3: Проверить все состояния вкладки Ответ**

Проверить: ответ с текстом; ответ со страницами; `source_only`; связанные учебные материалы без ответа; полностью пустой вопрос; ошибка загрузки. Во всех состояниях вопрос остаётся только в верхней панели Рабочей области.

- [ ] **Step 4: Зафиксировать структуру и copy отдельным коммитом**

```powershell
git add frontend/src
git commit -m "fix: упростить вкладку ответа и терминологию экзамена"
```

---

### Task 5: Исправить сводный конспект и свернуть список вопросов

**Files:**

- Modify: `backend/app/conspects/service.py`
- Modify: `backend/tests/test_conspects.py`
- Modify: `frontend/src/components/domain/ConspectSummary.tsx`
- Modify: `frontend/src/styles/conspects.css`

**Interfaces:**

- Consumes: DFS-список всех актуальных `study_nodes`.
- Produces: `ConspectSummaryEntry.position` — номер вопроса среди всех актуальных изучаемых узлов, даже если предыдущие вопросы не имеют конспекта; закрытый по умолчанию список ссылок.

- [ ] **Step 1: Сделать тест с пропуском явным**

Изменить `test_conspect_summary_dfs_order_and_filters`: оставить пустой вопрос между заполненными и ожидать, например:

```python
assert [entry.node_id for entry in summary.entries] == [topic_a1.id, topic_a2.id, topic_b1.id]
assert [entry.position for entry in summary.entries] == [1, 2, 4]
```

- [ ] **Step 2: Нумеровать до фильтрации пустых конспектов**

```python
for position, node in enumerate(study_nodes, start=1):
    conspect = conspects_by_node.get(node.id)
    if conspect is None or conspect.content_markdown.strip() == "":
        continue
    entries.append(ConspectSummaryEntry(position=position, ...))
```

Порядок и набор записей не меняются, меняется только отображаемый номер.

- [ ] **Step 3: Обернуть индекс в существующий Disclosure**

При `showTopicIndex` показывать закрытый по умолчанию `Disclosure` с подписью `Вопросы с конспектом · N`; внутри оставить существующие ссылки на личные конспекты. В Материалах, где `showTopicIndex=false`, лишний раскрывающийся блок не появляется.

- [ ] **Step 4: Проверить формулы как существующую возможность**

В «Мой конспект» вставить inline-формулу `$a^2+b^2=c^2$` и блочную:

```latex
$$
P(A\mid B)=\frac{P(B\mid A)P(A)}{P(B)}
$$
```

Проверить рендер в редакторе и в «Сводном конспекте» после сохранения. Если обе поверхности отображают KaTeX корректно, код формул не менять; исправлять только обнаруженную регрессию.

- [ ] **Step 5: Прогнать тесты и зафиксировать задачу**

```powershell
cd backend
python -m pytest tests/test_conspects.py -q
cd ..
npm run typecheck
npm run build
git add backend/app/conspects/service.py backend/tests/test_conspects.py frontend/src/components/domain/ConspectSummary.tsx frontend/src/styles/conspects.css
git commit -m "fix: сохранить номера вопросов в сводном конспекте"
```

---

### Task 6: Обновить фактические контракты и провести приёмку

**Files:**

- Modify: `SCREENS.md`
- Modify: `docs/architecture/exam-chat.md`
- Modify: `docs/architecture/pre-stage-6-search-and-manual-binding.md`
- Modify: `docs/architecture/conspects.md`

- [ ] **Step 1: Обновить документацию конкретным поведением**

Зафиксировать: `answers_file` не входит в учебные материалы и chat fragments; общий поиск не ищет по файлам структуры/ответов; «Найти в материалах» запускает заполненный запрос; ChatHeader не повторяет вопрос/название; сегодня показывается как `Сегодня, HH:mm`; список сводки свёрнут; `position` считается до фильтра пустых конспектов; пользовательское название — «Ответ».

- [ ] **Step 2: Выполнить полную автоматическую проверку**

```powershell
cd backend
python -m pytest
python -m ruff check .
cd ..
npm run typecheck
npm run build
```

- [ ] **Step 3: Перезапустить приложение и выполнить визуальную матрицу**

```powershell
docker compose restart api web
```

Матрица: светлая/тёмная тема; одна/две рабочие зоны; viewport 1920, 1280, 960 и 390 px; Popover экзаменатора у правого края; пустой/непустой чат; история с сегодняшней и старой датой; Ответ текстом/страницами; Источники пустые/с выдачей/после привязки; сводный конспект с вопросами 1 и 4 и формулой.

- [ ] **Step 4: Финальный smoke-check пользовательских требований**

```text
[ ] Ни одно поле ExaminerControl не выходит за Popover.
[ ] В чате нет ложного Материал · N от файла ответов.
[ ] В видимом экзаменационном UI нет слова «эталон».
[ ] Кнопки «Задать вопрос» нет; композер работает.
[ ] В ChatHeader и истории нет повторной формулировки вопроса.
[ ] Сегодняшняя сессия подписана «Сегодня, HH:mm».
[ ] «Новые сообщения» не двигается по горизонтали.
[ ] Источники, поиск и «Уже привязано» согласованы.
[ ] Кнопка пустого состояния запускает заполненный поиск.
[ ] Кнопка «Найти» равна полю по высоте.
[ ] Ответ расположен: переключатель → содержимое → footer.
[ ] Индекс сводного конспекта закрыт по умолчанию.
[ ] Номера сводки совпадают с номерами вопросов Программы.
[ ] Inline- и block-формулы отображаются в обоих конспектах.
```

- [ ] **Step 5: Зафиксировать документы и итог**

```powershell
git add SCREENS.md docs/architecture
git commit -m "docs: обновить контракт рабочей области экзамена"
git status --short
```

Expected: рабочее дерево чистое; все проверки прошли; визуальная матрица подтверждена скриншотами.

---

## Краткая семантика «Найти в материалах» после правки

- Во вкладке «Источники» запрос по умолчанию равен формулировке выбранного вопроса. Кнопка запускает локальный FTS5/BM25-поиск по учебным материалам проекта; результат можно привязать к вопросу.
- В чате одноимённый Tool выполняет тот же локальный поиск и добавляет в ленту ссылки на найденные фрагменты, но сам не создаёт Привязки и не вызывает модель.
- Файл структуры экзамена и файл с ответами в общий поиск не входят: их содержимое уже имеет отдельные поверхности и не должно притворяться учебным источником.
