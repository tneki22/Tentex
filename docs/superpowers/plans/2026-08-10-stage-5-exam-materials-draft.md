# Этап 5: экзаменационные материалы — Implementation Plan

> **Состояние:** 5A и общий функциональный контур 5B реализованы 10.08.2026.
> Фактический контракт и границы зафиксированы в
> `docs/architecture/stage-5-material-pipeline.md`. Незакрыт только hardware-gate
> PaddleOCR-VL; следующие продуктовые функции принадлежат этапам 6–8.

**Goal:** В экзаменационном проекте загрузить реальный документ, безопасно и возобновляемо превратить его в страницы, фрагменты и блоки, проверить результат в существующем экране «Материалы» и при необходимости импортировать эталоны по точному совпадению вопросов.

**Architecture:** Файлы и производные данные общие для установки, а роль и назначение файла принадлежат связи с проектом. FastAPI только принимает команды и читает результат; единственный локальный worker арендует задачи из SQLite, коммитит одну восстанавливаемую единицу за транзакцию и приводит любой parser к общему `ParsedPage`. UI сначала включается только для `template_key=exam`, но серверный конвейер не ветвится по шаблону проекта.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, SQLite WAL, PyMuPDF, python-docx, Pillow, PaddleOCR 3.x / PP-OCRv5 для русского, PaddleOCR-VL 1.6, React 19, TypeScript.

## Global Constraints

- Сначала экзаменационный вертикальный срез; учебниковый мастер и построение программы из материала в этот план не входят.
- Не добавлять FTS5, эмбеддинги, привязки, проходы 1/2, карточки, занятия или План.
- Сохранить визуальную структуру `ui-stage-1-baseline`; неготовые вкладки остаются на месте как честно недоступные.
- Лимиты загрузки: 100 МБ и 500 страниц; проверка выполняется до постановки тяжёлой задачи.
- Один файл с тем же SHA-256 хранится и разбирается один раз, но может иметь разные роли в проектах.
- Операции дольше 10 секунд показывают прогресс; задача дольше минуты переживает остановку worker и перезапуск приложения.
- `ocr_low` — предупреждение, а не достоверный текст; низкое покрытие материала не показывается как проблема.
- Тяжёлые OCR-зависимости не включать в процесс API: worker получает отдельный requirements/Dockerfile.

---

## 1. Решение по границе этапа

### Входит в первую итерацию

1. Локальные PDF, DOCX, TXT, MD, JPG и PNG, а также вставленный текст.
2. Общая файловая библиотека, связь с экзаменационным проектом, дедупликация.
3. Возобновляемая SQLite-очередь и отдельный worker.
4. Нативный разбор, детекция скана, `Быстро` и при совместимом GPU `Учебник` — это названия режимов OCR, не шаблонов проекта.
5. Страницы, структурные элементы, фрагменты, блоки, служебная классификация, диагностика формул/таблиц/структуры.
6. Реальный экран «Материалы», оригинал/текст, прогресс, управление задачей и полноэкранный просмотрщик.
7. Экзаменационное дополнение: разобранный файл с назначением `reference_answers` можно передать существующему exact-title импорту этапа 4 без модели.

### Не блокирует экзаменационную приёмку

- URL, YouTube и локальное аудио — отдельный хвост входных адаптеров после приёмки файлового сценария; они не меняют модель страниц и блоков.
- Подключение материалов в учебниковом мастере обсуждается после первой итерации. Серверный pipeline уже пригоден, но активация учебникового проекта зависит от этапа 7.
- Вкладки «Вопросы» и «Привязки», индекс, дельта дозагрузки и последствия для покрытия остаются заблокированы до этапов 7, 8 и 6 соответственно.

---

## 2. Карта файлов и интерфейсов

**Create:**

- `backend/app/materials/{schemas,router,service,storage,worker,pipeline,segmentation}.py` — API, durable queue, файловая идентичность и чистый конвейер.
- `backend/app/materials/parsers/{base,native,paddle_fast,paddle_vl}.py` — adapters, каждый возвращает один общий `ParsedPage`.
- `backend/migrations/versions/20260810_0005_material_pipeline.py` — только сущности этапа 5.
- `backend/tests/materials/` — pytest на загрузку, очередь, сегментацию и восстановление.
- `backend/scripts/check_stage5.py` — один сквозной демонстрационный сценарий с убийством worker.
- `backend/requirements-worker.txt`, `backend/Dockerfile.worker` — тяжёлый runtime вне API.
- `frontend/src/api/materials.ts`, `frontend/src/hooks/useProjectMaterials.ts` — один клиентский контракт и polling.
- `frontend/src/screens/materials/` — каталог, документ, обработка, файл, импорт эталонов.
- `frontend/src/screens/SourceViewer.tsx` — полноэкранная страница с bbox-overlay.
- `docs/architecture/stage-5-material-pipeline.md` — фактический контракт и блок-схема А5.

**Modify:**

- `backend/app/models.py`, `backend/app/main.py`, `backend/requirements.txt`.
- `backend/app/projects/answers.py` и schemas — только provenance импорта эталона из Материала.
- `docker-compose.yml`, `package.json` — отдельный worker в `docker compose up` и `npm run dev`.
- `frontend/src/screens/Materials.tsx`, `frontend/src/app/views.ts`, `frontend/src/styles/layout.css`.
- `backend/scripts/check_stage2.py` … `check_stage4.py` — только если новая миграция требует обновить ожидаемый head; прежние сценарии не переписывать.

**Core interface:**

```python
@dataclass(frozen=True)
class ParsedElement:
    kind: Literal["heading", "paragraph", "list", "table", "formula", "image"]
    text: str
    bbox: tuple[float, float, float, float]  # normalized 0..1
    level: int | None
    confidence: float | None

@dataclass(frozen=True)
class ParsedPage:
    page_number: int
    width: float
    height: float
    markdown: str
    plain_text: str
    quality: Literal["native", "ocr", "ocr_low"]
    elements: tuple[ParsedElement, ...]
    diagnostics: tuple[str, ...]
```

PyMuPDF, PP-OCRv5 и PaddleOCR-VL не просачиваются за этот интерфейс.

---

## 3. Порядок реализации и контрольные точки

### Task 0: одноразовая разведка до production-кода

**Files:** Create `docs/research/stage-5-segmentation-and-ocr.md`; production-файлы не менять.

- [ ] Прогнать `Exam-NDB/Пособие.pdf`, `Подготовка к экзамену НБД.pdf`, `БД_Основные термины.pdf`, DOCX вопросов и 3 фотографии бумажных страниц.
- [ ] Зафиксировать точные правила: порог скана, нормализацию reading order, открытие/закрытие блока по уровням заголовка, деградированное разбиение, признаки титула/оглавления/колонтитула/литературы.
- [ ] Проверить PP-OCRv6 CPU и официальный Blackwell-путь PaddleOCR-VL 1.6 на RTX 5060; записать версии, VRAM, время страницы и результат `available/unavailable`.
- [ ] Удалить spike-скрипт. В репозитории оставить только решение, минимальные обезличенные fixtures и ожидаемые границы блоков.

**Gate:** без записанных чисел и fixtures Task 3 не начинается.

### Task 1: миграция и инварианты

**Produces:** `MaterialPage`, `MaterialFragment`, `MaterialBlock`, `ProcessingTask`, `ProcessingEstimate`, enum-ы `TaskKind`, `PageQuality`, `ParserMode`, `ProcessingState`, `ProcessingStage`, `MaterialPurpose`.

- [ ] Расширить `Material` общей метаинформацией и `active_parse_revision`; расширить `ProjectMaterial` отображаемым именем и валидируемым набором назначений `exam_structure/reference_answers/study_source`.
- [ ] Добавить уникальности `(material_id, revision, page_number)`, `(page_id, sort_order)` и `(material_id, revision, sort_order)`; bbox хранить в JSON только после проверки четырёх чисел `0..1`.
- [ ] `ProcessingTask` имеет kind `inspect/parse` и хранит state, stage, done, total, checkpoint JSON, parser mode, diagnostics, error, lease owner/expiry, heartbeat и timestamps.
- [ ] `ProcessingEstimate` хранит число страниц, предполагаемые OCR-страницы, выбранный режим, диапазон времени, локальную стоимость `0` и дату расчёта; parse-задача без готовой оценки не создаётся.
- [ ] Новая попытка разбора пишет revision `N+1`; текущая успешная revision остаётся читаемой до атомарного переключения.
- [ ] Миграционный тест проверяет cascade производных данных, `RESTRICT` общего файла при активной связи и отсутствие сирот.

### Task 2: приём файла и API материалов

**Produces:**

- `POST /api/projects/{project_id}/materials` — multipart upload, связь с проектом и `inspect` task, `202`.
- `POST /api/projects/{project_id}/materials/text` — вставленный текст через тот же storage/pipeline.
- `GET /api/projects/{project_id}/materials` и `GET .../{material_id}`.
- `PATCH .../{material_id}` — display name, source role, priority, instruction, purposes.
- `DELETE .../{material_id}` — убрать связь с проектом, но не физический файл.
- `POST .../{material_id}/processing` — подтвердить оценку, mode и поставить parse task.
- `POST .../{material_id}/processing/{pause|resume|retry|reparse}`.
- `GET .../{material_id}/pages/{page_number}` и `/image`.

- [ ] Стримить upload во временный файл внутри `data/storage/tmp`, одновременно считать SHA-256 и жёстко остановиться после 100 МБ.
- [ ] Проверять signature/читаемость, пароль PDF и 500 страниц; расширение не считать источником истины.
- [ ] После успешной проверки атомарно перемещать в content-addressed path; дубликат только связывать с проектом.
- [ ] Upload запускает только дешёвый `inspect`; тяжёлый parse начинается после показа оценки и явного выбора режима.
- [ ] Мутации запрещать для архивного/завершённого проекта; GET оставлять доступным.
- [ ] Ошибки вернуть стабильными кодами `material_too_large`, `material_too_many_pages`, `material_encrypted`, `material_corrupt`, `material_unsupported`, `material_already_attached`.

### Task 3: durable worker и нативный pipeline

**Consumes:** `ParsedPage`; **Produces:** прогрессивные строки страниц/фрагментов/блоков.

- [ ] Worker атомарно арендует одну queued-задачу, обновляет heartbeat и позволяет забрать просроченную lease после падения.
- [ ] Чекпоинт имеет форму `{"stage": "extract", "next_page": 17}`; одна страница либо полностью записана, либо повторяется без дублей.
- [ ] Pipeline: validate → outline → extract/render → scan detection → normalize → fragments → blocks → service classification → finalize revision.
- [ ] PyMuPDF извлекает TOC, текстовые блоки/слова и координаты; DOCX/TXT/MD нормализуются в те же страницы; JPG/PNG создают одну страницу, ожидающую OCR.
- [ ] Pause завершается после текущей страницы; retry продолжает checkpoint, reparse создаёт новую revision.
- [ ] Compose и `npm run dev` запускают worker отдельно; API никогда не выполняет parse inline.

### Task 4: сегментация и служебные блоки

**Produces:** чистые функции `build_fragments(page)`, `build_blocks(fragments)`, `classify_service_blocks(blocks, document_stats)`.

- [ ] Заголовок открывает блок, заголовок того же или более высокого уровня закрывает его; вводный текст до первого заголовка становится отдельным блоком.
- [ ] При утрате структуры включается только зафиксированный в Task 0 paragraph fallback и ставится `degraded_structure=true`.
- [ ] Повторяющиеся колонтитулы, титул, оглавление, предисловие, выходные данные и литература получают объяснимый `service_reason`; исходный текст не удаляется.
- [ ] Параметризованные pytest-fixtures из `Exam-NDB` проверяют точные границы, порядок, межстраничный блок, fallback и отсутствие потери текста.

### Task 5: два локальных OCR-режима

**Produces:** `PaddleFastParser.parse_page(...) -> ParsedPage` и `PaddleVlParser.parse_page(...) -> ParsedPage`.

- [ ] `Быстро`: PP-OCRv5 CPU для русского, bbox и confidence; плохое качество становится `ocr_low` по порогу Task 0. PP-OCRv6 не используется, пока у него нет русской модели.
- [ ] `Учебник`: полный PaddleOCR-VL 1.6 pipeline на совместимой GPU, а не один VLM-компонент; результат нормализуется тем же adapter.
- [ ] Ошибка одной страницы не удаляет готовые; task падает с checkpoint и конкретной страницей.
- [ ] Диагностика сохраняет low confidence, broken structure, tables и formulas; рекомендация режима вычисляется правилами и ничего не запускает автоматически.
- [ ] Если RTX 5060 не проходит hardware gate, capability endpoint честно возвращает `textbook.available=false`; режим остаётся видимым и недоступным.

### Task 6: экзаменационный UI на реальных данных

- [ ] Разделить 1100+ строк текущего `Materials.tsx` по зонам, сохранив DOM-композицию и `materials-*` CSS baseline.
- [ ] Подключить каталог, upload/dialog, выбор файла, фильтры, original/text, outline, страницы, zoom, документный поиск по уже загруженным страницам, прогресс и pause/resume/retry.
- [ ] В «Обработке» показывать inspect/оценку до запуска, реальные этапы, качество, diagnostics и capability пяти режимов; облачные три и «Индексирование» всегда disabled с указанием этапа 7 или 6.
- [ ] В «Файле» подключить metadata, роли и удаление связи; «Вопросы» и «Привязки» оставить честными заглушками будущих этапов.
- [ ] Polling делать через один hook с `AbortController`; не добавлять WebSocket/SSE.
- [ ] Пусто, частично готово, ошибка страницы и `ocr_low` локализуются внутри выбранного файла, а не заменяют весь экран.

### Task 7: полезный экзаменационный результат — эталоны из файла

**Produces:** `POST /api/projects/{project_id}/materials/{material_id}/reference-answer-import`.

- [ ] Разрешить действие только готовому материалу с purpose `reference_answers` в экзаменационном проекте.
- [ ] Передать постраничный текст существующему exact-title parser этапа 4; не добавлять fuzzy matching и модель.
- [ ] Создавать только пустые слоты, возвращать created/skipped/unmatched/ambiguous/empty и страницы происхождения.
- [ ] Добавить к `ReferenceAnswer` nullable provenance `source_material_id`, `source_page_from/to`; потеря связи с проектом не удаляет ответ и явно отображается как источник вне проекта.
- [ ] После импорта вопрос открывается в текущей Рабочей области с тем же `ProgramNode.id`.

### Task 8: просмотрщик и исправление текста

- [ ] Добавить `source-viewer` в `views.ts`; route открывает конкретную страницу и fragment id.
- [ ] Оригинал рендерить постраничным изображением, поверх — bbox выбранных фрагментов; текстовый режим строить из структурных элементов без небезопасного HTML.
- [ ] Ручная правка страницы создаёт новую parse revision и повторяет normalize → fragments → blocks; исходный файл не изменяется.
- [ ] До этапа 8 перенос подтверждённых привязок не нужен, потому что самих привязок ещё нет; API revision сразу проектируется так, чтобы этап 8 мог добавить перенос без смены page/fragment контракта.

### Task 9: проверка и приёмка экзаменационной итерации

- [ ] `pytest backend/tests/materials -q` и `python backend/scripts/check_stage5.py`.
- [ ] В check-stage5: upload → dedupe → partial pages → kill worker → restart → complete → exact-title answer import → detach material → no orphan rows.
- [ ] Ошибочные fixtures: битый, защищённый, пустой, >100 МБ через synthetic stream, >500 страниц, PDF без текста, упавшая OCR-страница.
- [ ] Регрессия: `check_stage2.py`, `check_stage3.py`, `check_stage4.py`, Ruff, typecheck, build.
- [ ] После `docker compose restart web` вручную пройти экзаменационный путь и сравнить основные области со screenshot baseline.
- [ ] Готовность итерации 5A: реальный PDF виден страницами/фрагментами/блоками, качество не маскируется, а worker продолжает с checkpoint после принудительного завершения.

---

## 4. Хвост после экзаменационной приёмки

1. Отдельные adapters для URL snapshot, YouTube transcript и локального аудио используют тот же `ParsedPage`; каждый принимается отдельным сквозным fixture. Это 5B, не условие приёмки 5A.
2. В 5B оживить глобальную Библиотеку: preview последствий и физическое удаление общего файла через `DELETE /api/materials/{material_id}`. Страницы/фрагменты/блоки удаляются, а производные эталоны сохраняют текст и `source_label`, обнуляют `source_material_id` и показывают недоступный источник.
3. Только после наблюдений первой итерации проектируется подключение к учебниковому мастеру: загрузка в draft, предварительный анализ и переход к этапу 7 «Программа по оглавлению / проход 1».
4. Если различий кроме входа мастера не окажется, экран Материалов повторно не проектируется: переиспользуется тот же API и layout с учебниковыми названиями ролей.
5. Этап 5 целиком закрывается после 5B; дозагрузка с дельтой и обработкой только новых блоков остаётся частью этапа 8 вместе с проходом 2.

## 5. Точки согласования

1. После Task 0 — пороги сегментации, рабочая установка OCR и окончательные dependency pins.
2. После Tasks 1–5 — kill/restart demo без UI.
3. После Tasks 6–8 — экзаменационный сценарий в браузере.
4. После приёмки 5A — отдельное решение: выполнять ли 5B сразу или сначала согласовать учебниковую ветку; ни один вариант не меняет общий pipeline.
