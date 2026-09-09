# Как Tentex обрабатывает файлы Библиотеки

> Черновик корневого руководства. Описан **фактический код коммита `9acd0f78167a6e3d0b2f79479cfc99139b1ee298`**, а не желаемая архитектура. Аудит выполнен чтением исходников; приложение, компилятор, OCR и тесты в рамках этой проверки **не запускались**. Примеры строк БД ниже вымышлены и показывают схему, а не данные пользователя.

## Как пользоваться руководством

Сначала прочитайте разделы 1–3: они объясняют общий путь и момент запуска. Раздел 4 разбирает обычные форматы, раздел 5 — Typst; разделы 6–9 — индексацию, готовность, ошибки и использование в проекте. Раздел 10 показывает файлы на диске, таблицы SQLite и примеры для каждого семейства, раздел 11 — зависимости. В разделе 13 — статьи и YouTube с таблицей соответствия форматам.

**Мини-словарь:** страница — физический лист PDF или логическая единица текста/аудио; элемент — результат извлечения на странице; блок — группа по заголовку; фрагмент — адресуемая часть для поиска и привязки; ревизия — опубликованная версия разбора; исходный Typst-chunk — отдельный отрезок кода, не тот же объект, что фрагмент PDF.

## 1. Самое важное

**Загрузить ≠ разобрать ≠ проверить ≠ подключить к проекту.**

- Библиотека общая для установки. Один источник — строка `materials`; два проекта используют её через две строки `project_materials`. Разбор и исправления общие, названия и назначения внутри проекта — проектные.
- Обычный файл после загрузки находится в `ready_to_process`. HTTP `202` у `/materials/upload` **не означает**, что задача уже создана. Нужно отдельно нажать «Подготовить материал».
- **Typst — исключение:** загрузка автоматически ставит сборку; при неоднозначном входе сразу просит выбрать `.typ`.
- Для поиска и привязок нужен опубликованный разбор (`active_parse_revision > 0`). Сохранённые страницы ещё строящейся версии можно читать через `task_id`, но это не публикация всей версии.
- `ready` означает завершение конвейера, **не отсутствие ошибок OCR**. Материал может быть `ready`, а отдельная страница — пустой `ocr_low`.
- Файл вопросов не превращается в Программу сам. Файл ответов не равен эталонным ответам: после разбора ещё требуется сопоставление с вопросами конкретного проекта.

Код: [регистрация обычного файла](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L848-L894), [создание Typst](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L897-L965), [публикация](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/worker.py#L258-L313), [модель связей](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/models.py#L490-L615).

## 2. Что действительно можно добавить

| Вход Библиотеки | Где выбрать | Что получится | Первая обработка |
|---|---|---|---|
| `.pdf` | «Файл» | Исходный PDF; настоящие страницы | Отдельный запуск, по страницам |
| `.docx` | «Файл» | Исходный Word; одна логическая страница | Чтение XML без OCR |
| `.txt`, `.md` | «Файл» | UTF-8-текст; одна логическая страница | Построчный разбор без OCR |
| `.jpg`, `.jpeg`, `.png` | «Файл» | Изображение; одна страница | Локальный OCR или внешняя зрительная модель |
| `.mp3`, `.wav`, `.m4a`, `.ogg`, `.flac` | «Файл» | Исходная запись; одна логическая страница транскрипта | Локальный faster-whisper |
| Вставленный текст | «Текст» | Физический `.md`, если имя заканчивается на `.md`; иначе `.txt` | Отдельный запуск текстового разбора |
| Публичный URL | «Ссылка» | Локальный Markdown-снимок HTML/текста, URL и дата | Снимок получают при добавлении; разбор запускают отдельно |
| YouTube URL | «Ссылка», вид определяется по адресу | Markdown-снимок субтитров ru/en, не видео | Получение субтитров при добавлении; затем текстовый разбор |
| Один `.typ` | «Typst → файл» | Нормализованный ZIP, даже если исходник один | Автоматическая компиляция |
| Typst ZIP | «Typst → ZIP» | Нормализованный ZIP дерева проекта | Автоматическая компиляция либо запрос точки входа |
| Typst папка браузера | «Typst → папка» (`webkitdirectory`) | ZIP файлов с относительными путями | Автоматическая компиляция либо запрос точки входа |

Обычный input имеет точный `accept=".pdf,.docx,.txt,.md,.jpg,.jpeg,.png,.mp3,.wav,.m4a,.ogg,.flac"`; `.typ` и `.zip` идут через **отдельный** маршрут. Папка Typst передаёт **все выбранные файлы**, поэтому изображения, шрифты, `.bib`, `.json`, `.csv` и другие зависимости могут быть частью bundle, но это **не отдельные поддерживаемые библиотечные форматы**. Обычные ZIP, PPTX, XLSX, EPUB, RTF, DOC, HTML-файл, GIF, TIFF, WEBP и видеофайл не входят в whitelist загрузки Библиотеки. URL на PDF также не подменяет загрузку PDF: web-адаптер принимает только `text/html` и `text/plain`.

`accept` — подсказка браузеру, а не защита. Итоговое решение делает сервер по расширению и специализированной проверке содержимого.

Код: [диалог и все input](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/frontend/src/screens/library/AddLibraryMaterialDialog.tsx#L12-L164), [frontend multipart](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/frontend/src/api/materials.ts#L647-L694), [серверный whitelist](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/storage.py#L12-L74), [URL MIME](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/external.py#L90-L137).

### Не перепутайте три сценария

1. **Общая Библиотека:** `/api/materials/...`; проект не требуется.
2. **Материалы проекта / импорт вопросов:** `/api/projects/{project_id}/materials/...` создаёт или подключает общий материал и проектную связь. В «Вопросах экзамена» отдельный выбор файла предлагает PDF/DOCX/TXT/MD/JPG/JPEG/PNG; некоторые мастера используют более широкий `image/*`, но сервер всё равно разрешает только JPG/JPEG/PNG. У проекта также есть прямой **текстовый** импорт программы, не создающий библиотечный файл. Импорт из готового материала читает `material_pages.text` активной версии, разбирает нумерацию/билеты/подпункты, показывает preview и только после подтверждения меняет `program_nodes` с проверкой revision. Для него нужны `exam_structure` и `materials.status == ready`. При применении backend читает материал заново: revision guard защищает Программу, а не неизменность снимка материала между preview и apply.
3. **Ответы проекта:** вставленный текст ответа и ручные вложения принадлежат `reference_answers` / `reference_answer_attachments`. Вложение до **20 МБ** не становится автоматически материалом, не получает OCR-страницы и FTS. «Файл эталонных ответов» — другой путь: общий материал с проектным назначением `reference_answers`, затем сопоставление.

Проектные input: [Материалы](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/frontend/src/screens/Materials.tsx#L376-L392), [Программа](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/frontend/src/screens/Program.tsx#L802-L823), [мастер](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/frontend/src/screens/project-wizard/ExamMaterialUploadPanel.tsx#L130-L150), [вложения ответов](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/frontend/src/screens/answers/AnswerFileList.tsx#L117-L133). Сервер: [импорт из материала](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/service.py#L401-L515), [прямой импорт черновика](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/projects/router.py#L87-L91), [схема эталонов и вложений](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/models.py#L914-L985).

## 3. Общий путь обычного файла

### 3.1. Приём и хранение

1. `POST /api/materials/upload` получает multipart `file`.
2. `store_upload` берёт basename, приводит расширение к нижнему регистру, проверяет whitelist.
3. Читает блоками по 1 МиБ во временный `storage/tmp/<uuid><suffix>`, одновременно считает SHA-256 и размер. Пустой файл — `422 material_empty`; больше 100 МиБ — `413 material_too_large`.
4. Перемещает в `storage/materials/<первые 2 символа sha>/<sha><suffix>`; если файл уже существует, удаляет временный дубликат. MIME берётся из `content_type` браузера либо `mimetypes`, а не из универсального анализатора байтов.
5. До записи SQL выполняет `inspect`: PDF открывается PyMuPDF, проверяются пароль и предел **500 страниц**, считаются страницы без непустого текстового слоя; JPG/PNG проходят `Pillow.verify`; DOCX открывается `Document`; TXT/MD читаются как UTF-8 с допустимым BOM. Для аудио на этом шаге **нет декодирования**: ставится одна страница и `audio_transcription_required`.
6. По `sha256` ищется существующая строка `materials`. Совпадение возвращает тот же материал, не новую независимую копию; переименование файла не создаёт нового содержания.
7. Новый материал: `status=ready_to_process`, `active_parse_revision=0`. Выдаётся карточка. Задачи ещё нет.

`material_encrypted`, `material_too_many_pages`, `material_corrupt` отображают ошибки проверки. Проверка происходит после сохранения физического файла: это не одна атомарная операция filesystem + SQLite, и отказ inspection может оставить объект на диске без строки материала.

Код: [маршрут](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/router.py#L63-L71), [storage](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/storage.py#L33-L74), [inspection](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/native.py#L67-L92), [отображение ошибок и дедупликация](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L779-L894).

### 3.2. Запуск

`POST /api/materials/{id}/processing` получает `parser_mode` (`fast`/`cloud`) и `scope` (`all`/`range`/`needs_review`). Первый запуск — только `all`. Частичный запуск доступен после первой публикации: диапазон для постраничных представлений; `needs_review` выбирает `ocr_low` с `reviewed_at IS NULL`.

Проверяется готовность выбранного движка; параллельная активная задача запрещена. Создаётся `background_jobs(kind=parse,state=queued)` с checkpoint:

```json
{"revision": 2, "source_revision": 1, "selected_pages": [3,4], "next_index": 0,
 "scope": {"kind":"range","page_from":3,"page_to":4}}
```

Настройки OCR снимаются worker один раз на запуск. Для TXT/DOCX/аудио режим не меняет сам парсер, **но общая проверка доступности режима перед постановкой в очередь всё равно выполняется**. UI не предлагает OCR как способность этих представлений; «подготовить текст» и «распознать страницу» — разные по смыслу операции.

Код: [scope и постановка задачи](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L1202-L1329), [способности](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L128-L144), [runtime params](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/ocr/settings.py#L69-L87).

### 3.3. Worker, checkpoints и публикация

Worker — отдельный Python-процесс, а не HTTP-запрос и не браузерный таймер. Берёт старейшую queued-задачу, выдаёт lease на 60 секунд, выставляет running и `materials.status=processing`. Истёкшая lease возвращается в queued. **Несколько worker сейчас небезопасны:** claim реализован read-then-write, без атомарного conditional claim.

При частичном разборе worker копирует нетронутые страницы старой версии в новую. Каждая извлечённая страница сохраняется в отдельной короткой транзакции вместе с checkpoint; сразу создаются временный блок и фрагменты, чтобы её можно было читать. `next_index` — индекс в списке выбранных страниц, не номер листа.

Только после всех страниц `_finish` в одной SQL-транзакции:

1. пересобирает блоки и фрагменты всей новой версии;
2. меняет `active_parse_revision`, ставит `ready`, пересчитывает quality counters;
3. переносит привязки, строит FTS5 по активным фрагментам;
4. регистрирует `material_revisions` с источником, происхождением, scope и summary;
5. пытается сопоставить ответы во всех подходящих подключённых проектах;
6. делает задачу `completed`, `stage=complete`, `done=total`.

Перенос привязок не означает «все останутся точными»: сопоставление выполняется в пределах **того же номера страницы**; ненайденная связь получает `status=orphaned`. Исторические страницы/фрагменты не удаляются при обычной новой публикации.

Код: [claim и checkpoint](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/worker.py#L69-L224), [finish](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/worker.py#L258-L313), [перенос](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/bindings/service.py#L614-L658).

## 4. По форматам: что происходит внутри парсера

### PDF: текстовый, скан и смешанный

**Решение принимается для каждой страницы**, а не для PDF целиком. Критерий — `page.get_text("text").strip()` непусто или пусто. Порог «меньше 40 символов» из старой разведки больше не действует. Наличие плохого/частичного/ошибочно закодированного текстового слоя не гарантирует корректный результат: такой лист всё равно пойдёт по native-ветке в `fast`/`cloud auto`.

**`fast`, текстовый слой есть:**

1. PyMuPDF legacy-reader извлекает строки, шрифты и встроенные растры; классифицирует заголовки, списки, абзацы, сохраняет крупные растры. На встроенных растровых областях может вызвать PaddleOCR.
2. `PyMuPDF4LLM.to_json` выполняет layout-анализ с `use_ocr=False`: порядок областей, заголовки, списки, таблицы, формулы, рисунки. Это локальная layout-модель, **не встроенный OCR**.
3. JSON превращается в `ParsedElement`. Таблица — один элемент с Markdown и bbox, не SQL-ячейки. Формула без textlines получает линейные глифы из её bbox и оригинальный crop, а **не гарантированный LaTeX**. Нетекстовые picture/figure/chart/diagram и некоторые пустые текстовые боксы сохраняются crop-элементом `[Изображение]`.
4. Legacy-растры объединяются с layout-элементами; legacy-картинки исключаются, если пересечение покрывает не менее 60% их bbox относительно layout-picture (это не IoU). Поэтому не следует обещать, что OCR любого legacy-растра непременно сохранится: перекрытый layout-picture может его заместить.
5. При ValueError/KeyError/RuntimeError layout-анализа используется legacy-результат с `layout_fallback`. Это рабочая деградация, не доказательство корректного порядка колонок.

**`fast`, текстового слоя нет:** PDF-страница рендерится в PNG → PaddleOCR PP-OCRv5 (русский) → детектированные строки и confidence → XY-Cut-порядок чтения с поправкой на наклон как ключом сортировки → склейка переносов/разделение номерных строк → список элементов. Непрочитанные области по остаткам «чернил» сохраняются как изображения. Автоматического распознавания формул в LaTeX, dewarp и поворота страницы здесь нет. Целевой raster quality = 150 dpi × параметр 1.5/2/3, с поправкой на исходное разрешение и пределами 150–450 dpi. Это не preview-растр, который отдельно кешируется с матрицей 1.5.

**`cloud auto`:** текстовые страницы проходят тот же layout-путь, но полученные элементы `image`/`formula` отправляются в VLM **вырезами**; нативный текст сохраняется. На страницу без текста уходит весь её растр. Существующий `kind=table` сам по себе не выбран списком целей; таблица-картинка может быть `image`. Поэтому «наружу никогда не уходит целая страница» неверно для сканов.

**`cloud page`:** каждый лист, включая born-digital, рендерится и отправляется целиком. Модель возвращает текст/структуру/bbox/confidence. Для PDF надёжные bbox формул, таблиц и картинок используются для сохранения оригинальных вырезов; элементы без надёжных координат не вырезаются. Это не слепая пересылка PDF-файла: наружу идут изображения внутри запросов шлюза.

Общие исходники: [ветки PDF](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/native.py#L645-L898), [layout-адаптер](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/pdf_layout.py#L223-L341), [локальный OCR](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/paddle_fast.py#L263-L321), [настройка Paddle](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/paddle_fast.py#L64-L78), [адаптивный растр](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/raster.py#L85-L157).

### JPG / JPEG / PNG

После Pillow-проверки это одна страница. `fast` вызывает `paddle_fast.parse_image` непосредственно; `cloud` отправляет исходные байты изображения в `recognize_page`. У фото нет предварительного PDF layout-анализа. Существенное отличие: отдельная cloud-фотография **не вызывает PDF-функцию `_attach_region_assets`**; наличие формулы/картинки в ответе модели не гарантирует сохранённый asset-crop. Оригинал фото всё равно доступен целиком. На изображении с рукописью, поворотом, перспективой, бликами или математикой проверка человеком обязательна; приём расширения не равен обещанию распознавания всех символов.

Код: [ветка фото](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/native.py#L845-L863).

### DOCX

Одна логическая страница размером 1×1, **не количество листов в Word**. `python-docx` читает `document.paragraphs`: стиль Heading, нумерация из `numbering.xml`, абзацы и встроенные в абзацы изображения по `r:embed`. Bbox — синтетические полосы по порядку абзацев, а не координаты печатного листа. Ни PaddleOCR, ни cloud не вызываются. Изображения сохраняются с `[Изображение]`.

Этот reader не проходит `document.tables` и не содержит конвертера OMML-формул; таблицы, формулы, текстовые блоки и иные конструкции Word вне прочитанных абзацев нельзя считать полностью поддержанными. Для точной визуальной сверки сохраняйте исходный DOCX; для распознавания картинок/формул экспортируйте в PDF и используйте соответствующий PDF-путь. LibreOffice-конвертации на сервере здесь нет.

Код: [DOCX parser](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/native.py#L476-L630).

### TXT / MD / вставленный текст

TXT/MD читаются UTF-8-SIG; вставка записывается UTF-8. Не декодируются автоматически CP1251/KOI8-R. Parser идёт по **непустым строкам**: Markdown `#` → heading; bullet → list; короткая нумерованная строка до 120 символов → heading; другие номерные строки → list; остальное → paragraph. Это не полноценный CommonMark AST: fenced code, таблицы и формулы не получают автоматически специализированных элементов. Сохраняемый Markdown страницы пересобирается из элементов, исходный файл остаётся отдельно. Bbox — условные полосы 0..1. Один строковый элемент не режется по токенам, overlap и embedding chunks не строятся.

Код: [текстовый parser](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/native.py#L421-L465), [запись вставки](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/storage.py#L77-L105).

### Публичная веб-страница

При добавлении: проверка http/https и DNS → запрет неглобальных адресов → HTTP fetch с timeout 15 с и повторной проверкой редиректа → только `text/html`/`text/plain`, максимум 10 МиБ → декодирование charset → простой HTMLParser пропускает script/style/noscript/svg → извлекает title и читаемый текст → формирует Markdown с URL → сохраняет хешированный `.md` и `source_url`/`retrieved_at`.

Это **не браузер**: JavaScript не исполняется, авторизация не выполняется, картинки/CSS/полная DOM-структура не архивируются, математический SVG игнорируется. Не обещайте точный снимок внешнего вида. Затем нужен отдельный запуск обычного текстового разбора.

«Обновить источник» повторно получает снимок. Не изменился хеш — меняется дата. Изменился — синхронно создаёт новую native-страницу, новую ревизию и FTS, сохраняя файл в `snapshots/<material_id>/<revision>.md`; старый снимок не перезаписывается. Это отдельный путь, **не OCR-задача**.

Код: [fetch](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/external.py#L16-L137), [refresh](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L1867-L1955).

### YouTube

При добавлении извлекается video id; поддержаны `youtu.be`, `youtube.com`/`m.youtube.com` watch и shorts. `youtube-transcript-api` запрашивает субтитры в приоритете `ru`, затем `en`. В `.md` попадают строки `[MM:SS] текст`. Видео, дорожка звука и кадры **не скачиваются**, Whisper для YouTube не запускается.

Сетевые блокировки YouTube — `503 material_youtube_network_blocked`; отсутствие/недоступность субтитров — отдельные `422`-ошибки. Длительности субтитров при записи не сохраняются: parser затем читает timestamp как обычный текст, `time_from`/`time_to` этим путём не заполняются. Нельзя описывать это как ту же структурированную временную шкалу, что у аудио. Обновление снимка — как у URL.

Код: [YouTube adapter](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/external.py#L140-L193), [текстовый parser](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/native.py#L421-L465).

### Локальное аудио

После загрузки оригинал уже на диске, но речь ещё не распознана. Worker импортирует `faster_whisper.WhisperModel`, берёт модель из `TENTEX_WHISPER_MODEL` (по умолчанию `small`), CPU, `compute_type=int8`; `transcribe(language="ru", beam_size=5)`. Удаляет пустые сегменты; если речи нет — исключение и failed-задача. Результат — одна страница: `width=1`, `height=duration`; каждому paragraph сохраняются настоящие `time_from` и `time_to`, bbox по относительной позиции во времени, Markdown с `[MM:SS]`.

Важная оговорка происхождения: код возвращает `quality=native`, а recognition_source остаётся default `native`, **хотя это машинная транскрипция**, не готовый авторский текст. Это свойство текущей схемы, не гарантия точности. Cloud-режим не превращает эту ветку в облачное ASR. Первая инициализация модели может требовать загрузки весов; детальная проверка аудиокодека происходит уже при работе Whisper. В прямых зависимостях нет требования executable `ffmpeg`; faster-whisper работает через свои транзитивные библиотеки, а данный аудит не проверял их конкретную установленную сборку.

Код: [audio.py целиком](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/audio.py#L1-L42).

## 5. Typst: исходник, сборка, недостающие файлы и код для модели

### 5.1. Три вида загрузки — один нормализованный bundle

- **Single `.typ`:** подходит автономному исходнику. Если есть `#include`, `#import`, `image`, `bibliography`, `read`, `csv`, JSON и другие файловые зависимости, их нельзя получить из вашего компьютера по имени: передайте папку/ZIP либо дошлите недостающее.
- **ZIP:** читается содержимое архива, проверяются пути, шифрование, symlink, число файлов и распакованный размер; затем архив создаётся заново.
- **Browser folder:** клиент берёт `webkitRelativePath` и передаёт параллельные массивы `files` и `paths`. **Внешняя папка не срезается**: `notes/main.typ` остаётся таким путём. Для ZIP с обёрточной папкой то же правило.

Нормализация сортирует имена, фиксирует ZIP timestamp и права, исключая различия исходного ZIP-metadata. Дедупликация совпадёт **только если совпадают пути и байты всех файлов**. `main.typ` и `notes/main.typ` — разные bundle. Поэтому безусловное «single/folder/ZIP всегда дают один материал» неверно.

Пределы: 100 МиБ входного архива/суммы uploads; 250 МиБ распакованных данных; 2 000 файлов; путь до 240 символов, до 20 компонентов. Отвергаются абсолютные POSIX-пути, компоненты `..`, дубли без учёта регистра; обратные слеши заменяются `/`. Bundle хранится в `storage/typst/<sha[:2]>/<sha>.zip`; `materials.media_type=application/zip`, `source_kind=typst`. Имя карточки — имя ZIP/папки либо исходного entrypoint, это не физическое имя ZIP в storage.

Код: [frontend paths](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/frontend/src/screens/library/AddLibraryMaterialDialog.tsx#L87-L95), [router](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/router.py#L74-L143), [валидация и нормализация](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/typst.py#L25-L229), [хранение](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/typst.py#L260-L292).

### 5.2. Как выбирается точка входа

1. Явно переданный при первоначальной загрузке `entrypoint` должен присутствовать в перечне `.typ`.
2. Если в **корне** есть `typst.toml`, выбирается корневой `main.typ`; если его нет, возвращается `None` — содержимое TOML не разбирается, перехода к правилу «единственный `.typ`» в этой ветке нет.
3. Иначе корневой `main.typ`.
4. Иначе единственный `.typ` во всём дереве.
5. Иначе `needs_input`: нужно выбрать полный путь из `entrypoint_candidates`.

Для папки `notes/` с `notes/main.typ` и `notes/lib.typ` корневого `main.typ` нет: потребуется выбор `notes/main.typ`. Архив вообще без `.typ` не даёт осмысленного кандидата; это не готовый Typst-документ.

Код: [правила entrypoint](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/typst.py#L73-L91), [кандидаты](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/typst.py#L245-L257), [очередь](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L897-L1008).

### 5.3. Пакеты и разрешение загрузки

Сканирование текстов `.typ` регуляркой находит литералы `@preview/name:version`; список живёт в `typst_materials.packages`. Проверка отсутствия пакета — наличие **директории** `data/typst-packages/preview/name/version`, не проверка её полноты или checksum.

Если известный пакет отсутствует и `download_packages=false`, worker не запускает компилятор: `materials.status=needs_input`, `material.error=NULL`, `typst_materials.issues` содержит `kind=package`; сама задача становится **completed**. Кнопка «Скачать пакет и продолжить» создаёт новую сборку с `download_packages=true`. Внутренняя функция называет этот аргумент `allow_download` и повторяет precheck после распаковки.

**Это не сетевой sandbox и не настоящий offline-флаг Typst CLI.** Предварительная проверка охватывает только найденные регуляркой `@preview`-ссылки. Она не строит полное дерево транзитивных зависимостей пакетов и не покрывает все способы вычисления import-path. Каталог существующего пакета также может быть неполным. Следовательно, обещать гарантированное отсутствие сетевых обращений без системного ограничения сети нельзя. `typst` получает окружение процесса, а не отдельную сетевую namespace.

Код: [packages и compile guard](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/typst.py#L94-L98), [cache и CLI](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/typst.py#L285-L376), [worker precheck](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/worker.py#L488-L531).

### 5.4. Что компилируется

Worker создаёт одноразовый build-root под `storage/tmp`, распаковывает bundle и запускает executable `typst compile`:

```text
--root <project>
--ignore-system-fonts --font-path <project>
--package-cache-path <data/typst-packages>
--deps <temporary deps.json> --diagnostic-format short
--creation-timestamp 0 --jobs 2
<project/entrypoint> <temporary rendered.pdf>
```

Timeout — 120 секунд. Docker-образ фиксирует Typst **0.15.1** с SHA-256 скачиваемого executable. Системные шрифты игнорируются; нужные собственные шрифты передавайте в bundle. Версия в `CompileResult` — константа кода, не результат опроса фактически подменённого `TENTEX_TYPST_BINARY`; при локальной замене бинарника это важно для воспроизводимости. `--deps` запрашивается, но его JSON не сохраняется как модель зависимостей: `dependency_json` не включён в путь обработки, временный каталог удаляется.

stderr отбирается только по `error:`/`warning:`. `file not found` даёт `kind=missing_file` и, если удалось разобрать `searched at`, точный `missing_path`; `unknown font family` — `missing_font`. Прогресс скачивания пакетов не считается проблемой.

Если compile отказал и есть `missing_file`/`package` → needs_input. Другие отказы → failed с ошибкой компилятора. **Отсутствующий шрифт не входит в список resolvable issues:** warning при успешном PDF может остаться в ready, а неуспешная сборка без missing_file/package будет failed. Заглушки вместо файлов не вставляются, исходный код не переписывается автоматически.

Код: [CLI и диагностика](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/typst.py#L303-L424), [классификация отказов](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/worker.py#L427-L531), [образ](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/Dockerfile.worker#L1-L29).

### 5.5. Досылка зависимости

`POST /api/materials/{id}/typst/files`: `files` + `target_paths`. UI предлагает путь из диагностики, а не случайное место. Сервер читает существующий bundle, объединяет со свежими файлами, снова нормализует ZIP, меняет `materials.sha256/storage_path/size_bytes`, обновляет entrypoint/packages, затем ставит сборку с `download_packages=false`. Старый PDF остаётся доступен до успеха новой сборки.

Важно: реализация `files |= uploads` умеет **заменять существующий путь**, а endpoint не ограничивает targets только списком missing_path. Это не отдельный редактор исходников и не полноценная функция «заменить проект целиком», но backend-семантика шире подписи «дослать недостающую картинку». При merge отдельно не проверяется casefold-коллизия между старым и новым словарём; защита новых uploads не равна полной повторной проверке объединения.

Код: [merge](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/typst.py#L195-L229), [endpoint](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/router.py#L122-L143), [смена bundle](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L1011-L1032).

### 5.6. Что происходит после успешной компиляции

1. PDF читается `text_layer_pages` → `_native_pdf_page(ocr_images=False)`. **Ни OCR, ни `parse_layout_page`/PyMuPDF4LLM здесь не вызываются.** Это общий legacy-reader с font/geometry эвристиками, а не полный обычный PDF-путь.
2. Все `ParsedPage` сначала собираются в память; затем сохраняются `_save_page`. На этапе самой компиляции постраничного прогресса нет.
3. PDF перемещается в `storage/typst-rendered/<material_id>/<revision>.pdf`; кеш `storage/pages/<material_id>` удаляется.
4. Из bundle извлекаются source chunks и пишутся в `typst_source_chunks`.
5. Общая `_finish` публикует страницы/фрагменты, FTS, связи и реестр версии.
6. **Отдельная транзакция** `_register_typst_build` дописывает `render_storage_path` в запись ревизии, `current_pdf_path`, `compiler_version`, `build_hash`, issues и page_count.

Отсюда два ограничения. Во-первых, PDF-preview может быть визуально правильным, но извлечённый текст/векторные иллюстрации не иметь полной структуры: legacy-reader возвращает пустую страницу, если вообще нет текстовых строк. Во-вторых, публикация всех Typst-артефактов не атомарна: между шагами 5 и 6 есть окно, и сбой после `_finish` способен оставить активную новую текстовую версию со старым `current_pdf_path`. Не следует обещать «PDF и все SQL-части меняются одной транзакцией».

Код: [text_layer_pages и legacy-reader](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/native.py#L246-L327), [Typst последовательность](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/worker.py#L533-L569), [регистрация PDF](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/worker.py#L460-L485).

### 5.7. Source chunks — не PDF-фрагменты

| Слой | Для чего | Как режется | Где лежит |
|---|---|---|---|
| Rendered PDF | Человек смотрит результат компиляции | Настоящие листы PDF | `typst-rendered/...pdf` |
| Rendered fragments | FTS/BM25, поиск, bbox, привязки, автосопоставление ответов | Элементы legacy-reader → блоки по heading | `material_pages`, `material_blocks`, `material_fragments` |
| Source chunks | Дословный Typst-код для контекста модели | Достижимые `.typ`, разрез по строкам заголовков `=` | `typst_source_chunks` |

`source_chunks` начинает с entrypoint, далее breadth-first следует только буквальным `#import "..."` и `#include "..."` по регулярке. Читает UTF-8, обходит посещённые пути один раз, режет по заголовкам `={1,6} ` **в начале строки**; преамбула тоже отдельный chunk. Сохраняет `path`, `line_from`, `line_to`, неизменённый отрезок `source_text`, его `source_hash`. Максимума токенов, overlap или смыслового RAG-chunking нет.

Это **не AST и не граф компилятора**: динамические imports, чтение файлов через функции, пакеты и вложения не становятся автоматически исходными chunks. Регулярка может увидеть текст в комментарии. `../` в локальном import отвергается `_safe_path`, даже если переход в реальном Typst-проекте оставался бы внутри root; такой проект может успешно скомпилироваться, но упасть на сборе source chunks.

Для каждого chunk ставится `page_from=1`, `page_to=<всего страниц>`, `diagnostic=page_mapping_coarse`. **FK на конкретный `material_fragment` нет.** Поэтому совпадение вопроса со страницей PDF ещё не значит, что найден соответствующий кусок исходника.

`material_context` выбирает chunks активной ревизии, чья область включает page_number, но берёт **только первые три** по sort_order. При coarse-mapping для любой страницы это обычно одни и те же первые три chunks. Если chunks нет — возвращает fallback PDF-текст. В этом коммите вызов адаптера подтверждён в `exam/context.py` при формировании контекста привязок, причём **привязки `mechanism=answers_file` из этого списка исключены**: автозаполненный эталон остаётся отдельным контекстом, а не автоматически raw Typst. Универсальную замену PDF-текста во всех возможных AI-потребителях утверждать нельзя. Экзаменационный контекст затем ещё ограничивает длину и общий бюджет.

Код: [source_chunks](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/typst.py#L427-L472), [запись](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/worker.py#L410-L424), [выбор модели](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/context.py#L15-L43), [потребитель](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/exam/context.py#L107-L143), [схема](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/models.py#L775-L797).

### 5.8. Осторожно с версиями Typst в этой реализации

- `_finish` вызывает общий `inherit_source`: если есть parent revision с `source_storage_path`, он наследует **старый** путь/хеш. После досылки нового bundle это может зарегистрировать новую сборку с прежним source ZIP, хотя исходные chunks и PDF получены из нового. Это выявлено по коду, runtime-воспроизведения здесь не было.
- «Восстановить как новую» копирует страницы/блоки/фрагменты и источник, но не копирует `typst_source_chunks`, не переносит `render_storage_path` и не меняет `typst_materials.current_pdf_path`. API восстановления не содержит отдельного Typst-запрета. Не обещайте полное восстановление Typst-тройки source/render/context.
- Endpoint page image не принимает `revision`: для Typst он рисует текущий PDF. Исторический `/rendered?revision=N` существует отдельно; исторический текст рядом с обычным page-image URL может оказаться на растре другой сборки.
- Общая уборка незавершённой ревизии удаляет страницы/блоки/фрагменты, но не `typst_source_chunks` и не rendered PDF. Для последних нужны дополнительные гарантии cleanup.

Код: [inherit_source](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/revisions.py#L173-L181), [restore](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L1810-L1864), [current image и revision PDF](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L584-L659), [discard](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L1571-L1603).

## 6. Качество, формулы, сегментация и поиск

### Качество не равно состоянию

- `material_pages.quality`: native / ocr / ocr_low.
- `material_fragments.recognition_source`: native / ocr / vl / manual — происхождение элемента.
- `confidence`: оценка модели/агрегат, nullable; не вероятность абсолютной правильности.
- `diagnostics`: предупреждения и технические счётчики; не универсальный признак failed.
- `reviewed_at`: пользователь сверил слабый OCR. Подтверждение **не меняет** `quality=ocr_low`; оно снимает потребность повторной проверки в агрегате.
- `material_pages.parser_mode=NULL` у native; у OCR — режим задачи. При копировании нетронутых страниц сохраняется их собственный режим.

В cloud page JSON проверяется схемой; bbox может быть нормализован из пикселей, clamp-нут или заменён порядковой полосой с `bbox_missing:N`. Формулы проходят дешёвую проверку `$`, `$$`, скобок и окружений, bare LaTeX обрамляется; `⟨?⟩`/синтаксическая проблема снижает confidence до 0.4. Это **не математическая проверка** и не обнаружение всех пропусков. Полностраничный результат с диагностикой получает ocr_low. Ветка region-recognition имеет иной, менее полный путь валидации: не переносите автоматически правила `CloudRecognizer._page` на каждый crop.

Сохраняются оригинальные crops (`asset_path`) там, где они реально получены; интерфейс может показывать их рядом с LaTeX/Markdown или вместо неотрисовавшегося результата. У TXT/MD строка с `$...$` может оставаться paragraph, а у native PDF математические глифы — не LaTeX.

Код: [типы результата](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/base.py#L13-L50), [cloud validation/failure](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/cloud_vlm.py#L347-L537), [review](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L538-L572).

### Что здесь называется chunk

Для обычного материала нет отдельной универсальной таблицы `chunks`. `ParsedElement` хранится сначала в JSON `material_pages.elements`, затем становится строкой `material_fragments`. **Каждый** heading открывает новый `material_blocks`; уровень heading не определяет закрытие предыдущего блока. Непрерывный блок может пересекать страницы. До первого heading образуется безымянный блок; без headings весь поток может остаться одним блоком, а `degraded_structure=true` выставляется фрагментам страниц без заголовков. Это не обязательный «один fallback-блок на страницу» — такой блок временно используется только для checkpoint-viewer.

Служебный класс определяется по точному нормализованному заголовку из малого словаря: оглавление/содержание, предисловие, литература/список литературы, выходные данные. Полного распознавания титулов и повторяющихся колонтитулов сегментатор не делает.

Код: [сегментатор целиком](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/segmentation.py#L5-L37), [финальные фрагменты](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L1484-L1568), [checkpoint-структура](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L1606-L1656).

### FTS5 / BM25 (не «FT5»)

Индекс строится из **`material_fragments.text` активной ревизии**, не из исходного ZIP, PDF-байтов, `material_pages.markdown` или raw Typst-code. `fragment_search` — SQLite virtual table FTS5 с колонками `norm`, `lemmas`, `fragment_id UNINDEXED`, `material_id UNINDEXED`; companion `fragment_search_map` хранит `fragment_id`, `material_id`, `rowid` для быстрого удаления индекса материала. Нормализация: регистр/ё→е; `pymorphy3` даёт русские леммы; prefix-поиск незаконченного слова идёт по norm, ранжирование — BM25. Векторной базы и embeddings этот шаг не создаёт.

Публикация удаляет старый индекс конкретного материала и строит новый в той же SQL-транзакции. Историческая версия ищется отдельным scan-путём; глобальный FTS не хранит все revisions одновременно. Проектный поиск учитывает подключённые материалы; файл `exam_structure` исключается из общего поиска, но не из явного поиска внутри этого файла.

Код: [DDL и reindex](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/bindings/search.py#L1-L127), [поиск версии](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L679-L773).

## 7. Когда результат уже можно использовать

| Момент | Можно | Ещё нельзя / оговорка |
|---|---|---|
| Обычный файл сохранён, revision=0 | Скачать оригинал; смотреть PDF/фото; подключить к проекту | Нет разобранного текста/FTS/импорта вопросов |
| Задача queued | Смотреть источник и прежнюю активную версию | Worker ещё не начал |
| Одна страница checkpoint сохранена | Читать её с `task_id` текущей активной задачи | Она не стала активной версией и ещё может быть отменена |
| Все страницы извлечены, finish не закоммичен | Наблюдать задачу | Нет общей публикации |
| finish завершён | Читать активные страницы, искать, привязывать, импортировать | OCR_low и пропуски требуют проверки |
| Новая обработка failed/paused | Старая active revision остаётся читаемой | Некоторые сервисы требуют status=ready и откажут импорту даже при старой версии |
| Typst needs_input до первой сборки | Читать issues, дослать файл/выбрать entrypoint/разрешить package | Собранного PDF ещё нет; `/rendered` отвечает `typst_preview_unavailable` |
| Typst failed после прежнего успеха | Предыдущий current PDF обычно доступен | Учитывайте окно publish/register и ограничения истории выше |

`task_id` читается только для latest-задачи в active states; после failed/completed/отмены этот путь перестаёт быть допустимым. Для неготовой страницы сервер возвращает `material_page_not_found`, а UI должен отличать ожидание страницы от отсутствия опубликованного материала.

Код: [resolution страницы](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L441-L535), [preview PDF](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L633-L659), [требование готовности импорта](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/service.py#L401-L440).

## 8. Ошибка, пауза, отмена, повтор и правка

- **Пауза running parse:** `pause_requested=true`; worker дописывает текущую страницу и checkpoint, затем ставит paused. Это не прерывание текущего OCR/HTTP-вызова.
- **Resume paused:** та же задача в queued, флаг паузы очищен, продолжение по next_index.
- **Retry failed:** та же задача/тот же checkpoint снова queued. Для обычного parse уже сохранённые страницы не распознаются заново.
- **Запустить новую обработку после failed:** старую failed-задачу и недопубликованную структуру убирают; создаётся новая попытка.
- **Cancel parse/Typst:** задача и строящиеся страницы/блоки/фрагменты удаляются; материал возвращается в ready при наличии активной версии, иначе ready_to_process. Общий `/background-jobs/.../cancel` возвращает cancelled-снимок, хотя SQL-строка material-job уже удалена. Это не тот же механизм, что cancelled-сохранение AI-job.
- **Сбой worker:** running с истёкшей lease забирается снова. Нет гарантии безопасного второго worker; heartbeat продлевается на границах страниц, а один долгий вызов/Typst compile может длиться дольше lease.
- **Cloud:** отдельные survivable ошибки дают пустую ocr_low-страницу либо пропуск пачки вырезов; некоторые ошибки/серия подряд валят задачу. Не всякая сетевая ошибка немедленно останавливает весь материал. Переключения на другого провайдера/другой OCR без согласия нет.
- **Typst retry:** процесс заново компилирует bundle и назначает revision, это не постраничный resume обычного parse. Отмена не убивает subprocess немедленно; код проверяет существование задачи на дальнейших контрольных точках. Не обещайте транзакционную отмену посреди `_finish`/регистрации PDF.
- **Правка обычной страницы:** новая полная revision; нетронутые страницы копируются, текст правки проходит текстовый parser с `recognition_source=manual`, старые asset-элементы сохраняются. Выполняются transfer/reindex. Исходный файл не меняется. `expected_revision`/`expected_source_hash` защищают от устаревшего preview, если переданы. UI Typst редактирование выключает; общий backend `update_page_text_core` сам отдельной проверки source_kind=typst не содержит — UI-ограничение не нужно выдавать за сквозной запрет API.
- **AI cleanup:** отдельное предложение через шлюз/фоновую задачу; применение создаёт новую версию, а не переписывает оригинал автоматически. Это не обязательный этап обычного OCR.

Код: [управление](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L1256-L1375), [parse failure](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/worker.py#L316-L383), [общая отмена](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/background/registry.py#L163-L207), [ручная правка](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L1682-L1772), [AI cleanup](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/ai_cleanup.py#L256-L337).

## 9. Проектные связи и эталонные ответы

Назначение и роль живут не в materials, а в `project_materials`: `source_role`, `priority`, `affects_program`, `instruction`, `display_name`, `purposes`, `exam_slot`. Один PDF может быть списком вопросов в одном проекте и учебным источником в другом.

Список вопросов: `exam_structure` → native/OCR pages → `parse_exam_program` → preview → подтверждённая замена программы; `program_nodes.origin_material_id` фиксирует источник. Шаблоны номеров и билетов — детерминированный importer, не OCR-модель, не общая сегментация и не получение embeddings.

Файл ответов: `reference_answers` → завершённый разбор → локальный `answer_sections.detect_sections` по всем упорядоченным фрагментам → сопоставление с вопросами → `bindings(mechanism=answers_file)` → заполнение `reference_answers` без строк заголовка. Границы ищутся не только по `element_kind=heading`, поэтому хорошие fragments полезны и без идеальной сегментации. Слот проекта может ограничить тип вопросов/задач. Повторная обработка материала вызывает этот путь из `_finish` для подходящих активных экзаменационных проектов; вручную сопоставление можно поставить отдельной `link_answers`-задачей.

Подтверждённые и отредактированные пользователем ответы не следует заменять автоматически; правила жизни ответа вынесены в `answer_lifecycle`. Доступный ответ, найденное соответствие и число привязанных фрагментов — разные показатели. Ответ, состоящий из изображений, может быть доступным источником, но непригодным для текстовой проверки. Автосопоставление не гарантирует полное покрытие: смотрите matched/missing/ambiguous/available в отчёте. Не путайте это с опциональным AI-планом `ai_answer_sections`, который требует отдельного применения.

Код: [схема связей/ответов](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/models.py#L914-L1029), [сопоставление](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/bindings/answers_link.py#L633-L840), [защита жизненного цикла](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/projects/answer_lifecycle.py#L1-L137), [автозапуск](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/worker.py#L227-L255).

Отсоединение из проекта удаляет проектную связь/его привязки, но не общий исходник. Физическое удаление Библиотеки требует preview последствий; каскадно удаляются материал-зависимые SQL-строки и индекс, source_material_id ответа становится NULL, происхождение вопросов очищается. Не удаляйте хешированные файлы вручную: ими может пользоваться история.

## 10. Где лежат байты, а где — SQL

По умолчанию `TENTEX_DATA_DIR` указывает на каталог `data`; в Docker общий bind-mount `/data`. SQLite — **`data/tentex.sqlite`** (плюс рабочие WAL/SHM-файлы), не каталог отдельных JSON-документов. В SQLite лежат текст, структуры, состояния, связи и пути; бинарные исходники/растры — рядом на диске.

| Физический путь относительно data | Что это |
|---|---|
| `storage/materials/<sha[:2]>/<sha>.<ext>` | Обычный исходник/первая текстовая запись/первый web-снимок |
| `storage/typst/<sha[:2]>/<sha>.zip` | Нормализованный Typst source bundle |
| `storage/typst-rendered/<material_id>/<revision>.pdf` | PDF конкретной сборки |
| `storage/pages/<material_id>/<page_number>.png` | Ленивый кеш preview PDF, не OCR-страницы SQL; не версионирован |
| `storage/assets/<owner>/<stem>-<16-символов-хеша>.<ext>` | Вырезы/встроенные изображения; owner обычно SHA исходника |
| `storage/snapshots/<material_id>/<revision>.md` или `.txt` | Обновлённый снимок внешнего источника |
| `storage/answers/<project_id>/<uuid>.<ext>` | Вложения эталонных ответов, отдельно от материалов |
| `storage/tmp/...` | Upload/build/transient files, не долговременная версия |
| `typst-packages/preview/<name>/<version>/` | Постоянный кеш Typst-пакетов |
| `models/official_models/...` | Локальные веса Paddle/PaddleX; в worker смонтированы на `/root/.paddlex` |

SQL валидация требует `foreign_keys=ON`; приложение включает WAL, busy_timeout=30000, synchronous=NORMAL, mmap_size=0. Миграции Alembic нужно довести до head: одной начальной «stage5» миграции недостаточно. Для Typst важны **0042** (таблицы/enum/render path), **0043** (удаление старого CHECK, запрещавшего needs_input) и **0044** (выравнивание порядка значений CHECK для `materials.status` и `background_jobs.kind` с порядком enum в ORM). 0044 не добавляет новые допустимые значения: она устраняет текстовое расхождение ограничений при проверке Alembic.

Код: [config](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/config.py#L9-L55), [SQLite](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/db.py#L28-L61), [миграция 0042](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/migrations/versions/20260909_0042_typst_materials.py#L36-L102), [почему нужна 0043](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/migrations/versions/20260909_0043_drop_stale_material_state_check.py#L1-L61), [миграция 0044](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/migrations/versions/20260909_0044_reorder_enum_check_constraints.py#L1-L85), [compose](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/docker-compose.yml#L5-L37).

В таблице выше пути физические, относительно data. SQL-поля `storage_path`, `source_storage_path`, `render_storage_path`, `current_pdf_path`, `asset_path` не содержат префикс `storage/`: они относительны к `settings.storage_dir`. Например, `materials/ab/<H>.pdf` означает `<data>/storage/materials/ab/<H>.pdf`.

### 10.1. Словарь SQL-колонок

Ниже имена **реальных SQL-таблиц и колонок**, а не имена TypeScript DTO. UUID в JSON API обычно с дефисами; SQLAlchemy SQLite Uuid хранит 32 hex-символа. `material_fragments` не имеет собственной колонки revision: она берётся через `page_id → material_pages.revision`.

- **`materials`**: `id`, `sha256`, `original_name`, `storage_path`, `media_type`, `source_kind`, `source_url`, `retrieved_at`, `size_bytes`, `page_count`, `status`, `active_parse_revision`, `parser_mode`, `scan_page_count`, `ocr_low_page_count`, `estimated_seconds`, `outline`, `diagnostics`, `error`, `created_at`, `updated_at`. `sha256` и `storage_path` unique. [Схема](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/models.py#L490-L527).
- **`project_materials`**: `project_id`, `material_id` (составной PK), `source_role`, `priority`, `affects_program`, `instruction`, `display_name`, `purposes`, `exam_slot`, `created_at`. FK project cascade, material restrict. [Схема](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/models.py#L530-L550).
- **`material_pages`**: `id`, `material_id`, `revision`, `page_number`, `width`, `height`, `text`, `markdown`, `quality`, `confidence`, `parser_mode`, `elements`, `diagnostics`, `image_path`, `reviewed_at`, `created_at`. Unique `(material_id,revision,page_number)`. [Схема](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/models.py#L553-L615).
- **`material_blocks`**: `id`, `material_id`, `revision`, `sort_order`, `title`, `block_class`, `service_reason`, `page_from`, `page_to`. Unique `(material_id,revision,sort_order)`. [Схема](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/models.py#L618-L654).
- **`material_fragments`**: `id`, `material_id`, `page_id`, `block_id`, `sort_order`, `text`, `bbox`, `element_kind`, `structure_level`, `degraded_structure`, `quality`, `recognition_source`, `confidence`, `asset_path`, `time_from`, `time_to`. Unique `(page_id,sort_order)`, FK cascade на material/page/block. [Схема](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/models.py#L657-L710).
- **`material_revisions`**: `id`, `material_id`, `revision`, `origin`, `parser_mode`, `parent_revision`, `task_id`, `source_storage_path`, `source_hash`, `render_storage_path`, `scope`, `summary`, `created_at`. Unique `(material_id,revision)`. `task_id` — nullable UUID, не FK. [Схема](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/models.py#L713-L750).
- **`typst_materials`**: `material_id` (PK/FK), `input_kind`, `entrypoint`, `compiler_version`, `build_hash`, `packages`, `issues`, `current_pdf_path`, `updated_at`. [Схема](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/models.py#L753-L772).
- **`typst_source_chunks`**: `id`, `material_id`, `revision`, `sort_order`, `path`, `line_from`, `line_to`, `source_text`, `source_hash`, `page_from`, `page_to`, `diagnostic`. Только FK на material; нет FK на revision/fragment и нет уникальности `(material_id,revision,sort_order)`. [Схема](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/models.py#L775-L797).
- **`background_jobs`**: `id`, `material_id`, `project_id`, `kind`, `state`, `stage`, `parser_mode`, `done`, `total`, `checkpoint`, `diagnostics`, `error`, `pause_requested`, `lease_owner`, `lease_expires_at`, `heartbeat_at`, `created_at`, `updated_at`, `completed_at`, `reviewed_at`. [Схема](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/models.py#L800-L862).
- **`fragment_search`**: `norm`, `lemmas`, `fragment_id`, `material_id`, внутренний FTS `rowid`; **`fragment_search_map`**: `fragment_id`, `material_id`, `rowid`. Это создаётся SQL DDL, а не ORM-классом. [DDL](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/bindings/search.py#L47-L127).
- **`bindings`**: `id`, `project_id`, `program_node_id`, `fragment_id`, `material_id`, `block_id`, `status`, `mechanism`, `created_at`, `updated_at`. Unique `(project_id,program_node_id,fragment_id)`. Привязка адресует rendered fragment, **не TypstSourceChunk**. [Схема](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/models.py#L988-L1029).
- **`reference_answers`**: `project_id`, `program_node_id` (PK), `text`, `origin_kind`, `match_method`, `matched_title`, `is_confirmed`, `is_active`, `revision`, `source_label`, `source_material_id`, `source_page_from`, `source_page_to`, `created_at`, `updated_at`. Источник FK SET NULL; revision ответа не равна parse revision материала. [Схема](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/models.py#L914-L951).
- **`reference_answer_attachments`**: `id`, `project_id`, `program_node_id`, `file_name`, `storage_path`, `media_type`, `size_bytes`, `created_at`; нет material_id и нет OCR-state. [Схема](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/models.py#L954-L985).

Зависимые настройки: `ocr_settings` (`id`, `default_mode`, `quality_threshold`, `raster_scale`, timestamps), `ocr_engine_configs` (`mode`, `enabled`, `model_id`, `device`, `language`, `executor`, `extra`, `updated_at`). Cloud использует `ai_settings.default_vision_provider_id/default_vision_model_id`, provider connections, каталог/role settings, журнал `ai_runs` и `ai_cache_entries`. Они нужны облачному вызову, но их строки не являются страницами или фрагментами материала. Веса моделей и ключ шифрования не надо искать в material tables.

### 10.2. Один обычный PDF: учебный пример строк

Сокращённые объекты ниже показывают **часть колонок**, остальные заполняются сервисом; это не INSERT-команды. M/P/B/F/J обозначают UUID-примеры, H — 64 lowercase hex, начинающийся с ab. P — третья сканированная страница mixed PDF, распознанная Paddle в fast; блок B начался заголовком на странице 2. W/Hpx — размеры OCR-растра в пикселях, D — рассчитанный DPI. Текст и confidence условные; порог качества предполагается выше 0.62, дополнительных skew/unread-regions нет.

```text
materials:
 {id:M, sha256:H, original_name:"Лекции.pdf",
  storage_path:"materials/ab/<H>.pdf", media_type:"application/pdf",
  source_kind:"file", page_count:12, status:"ready", active_parse_revision:1,
  parser_mode:"fast", scan_page_count:2, ocr_low_page_count:1}

material_pages:
 {id:P, material_id:M, revision:1, page_number:3, width:W, height:Hpx,
  text:"Теорема ...\nДля любого x ...", markdown:"Теорема ...\n\nДля любого x ...", quality:"ocr_low",
  confidence:0.62, parser_mode:"fast", elements:[...], diagnostics:["low_confidence","render_dpi:<D>"],
  reviewed_at:null}

material_blocks:
 {id:B, material_id:M, revision:1, sort_order:2, title:"Теорема",
  block_class:"content", service_reason:null, page_from:2, page_to:4}

material_fragments:
 {id:F, material_id:M, page_id:P, block_id:B, sort_order:1,
  text:"Для любого x ...", bbox:[0.10,0.20,0.86,0.27], element_kind:"paragraph",
  structure_level:null, degraded_structure:true, quality:"ocr_low",
  recognition_source:"ocr", confidence:0.62, asset_path:null,
  time_from:null, time_to:null}

background_jobs:
 {id:J, material_id:M, project_id:null, kind:"parse", state:"completed",
  stage:"complete", parser_mode:"fast", done:12, total:12,
  checkpoint:{revision:1,source_revision:0,selected_pages:[1,2,3,...,12],next_index:12,
              scope:{kind:"all"}}}

material_revisions:
 {material_id:M, revision:1, origin:"imported", parser_mode:"fast", parent_revision:null,
  task_id:J, source_storage_path:"materials/ab/<H>.pdf", source_hash:H,
  render_storage_path:null, scope:{kind:"all"}, summary:{...}}

fragment_search:
 {rowid:101, norm:"для любого x", lemmas:"для любой x", fragment_id:F, material_id:M}
fragment_search_map:
 {fragment_id:F, material_id:M, rowid:101}
```

У фрагмента-формулы меняются `element_kind="formula"`, `text` и `asset_path`; бинарный crop не вставляется в эту SQL-строку. FTS-тексты приведены иллюстративно, не как реально выполненный результат pymorphy3.

### 10.3. Typst: две системы адресации

```text
materials:
 {id:M, source_kind:"typst", media_type:"application/zip", original_name:"notes.zip",
  sha256:H, storage_path:"typst/ab/<H>.zip", status:"ready", active_parse_revision:1}

typst_materials:
 {material_id:M, input_kind:"zip", entrypoint:"main.typ", compiler_version:"0.15.1",
  packages:[], issues:[], build_hash:"<64 hex PDF hash>",
  current_pdf_path:"typst-rendered/<M>/1.pdf"}

typst_source_chunks:
 {id:C, material_id:M, revision:1, sort_order:0, path:"main.typ", line_from:1, line_to:2,
  source_text:"= Интеграл\n$integral_0^1 x dif x$\n", source_hash:"<64 hex chunk hash>",
  page_from:1, page_to:8, diagnostic:"page_mapping_coarse"}

material_revisions:
 {material_id:M, revision:1, origin:"imported", parser_mode:null,
  source_storage_path:"typst/ab/<H>.zip", source_hash:H,
  render_storage_path:"typst-rendered/<M>/1.pdf"}

bindings:
 {project_id:Q, program_node_id:N, material_id:M, fragment_id:F, block_id:B,
  status:"manual", mechanism:"answers_file"}
```

C не равен F и не связан с ним FK. F — текст из PDF; C — исходный Typst. `build_hash` — хеш **PDF**, `materials.sha256` — **ZIP**, `typst_source_chunks.source_hash` — **отрезка кода**. Подмена этих хешей разрушает понимание версий.

### 10.4. Короткие примеры результата по семействам

**Это условные примеры, прочитанные из контракта кода, а не выгрузка БД и не результаты выполненного OCR/Whisper/HTTP-fetch.** Сокращённые объекты показывают часть колонок, не готовые INSERT. Имена, текст, координаты и модельные оценки выбраны для объяснения; M/P/B/F/J — метапеременные UUID. H — SHA-256 содержимого, `H[:2]` — его первые два символа.

#### Общие шаги и таблицы — одни, не отдельная база для каждого формата

Для первоначальной обработки всех строк следующей таблицы порядок общий (§3):

1. **Получить и сохранить источник.** Файлы проходят upload/inspection; вставка сохраняется текстом; web/YouTube сначала получают снимок. Новая строка `materials` имеет `status=ready_to_process`, `active_parse_revision=0`. При совпадении SHA возвращается уже существующий материал, который может находиться на другой стадии.
2. **Отдельно запустить обработку.** Проверяется доступность выбранного `fast`/`cloud`; создаётся `background_jobs(kind=parse,state=queued)`. Наличие пакета DOCX/Whisper и реально работоспособного worker этой проверкой не доказывается. Нативный текст тоже проходит общий mode-readiness gate.
3. **Извлечь страницу.** Worker вызывает соответствующий parser, получает `ParsedPage` с текстом и элементами, записывает `material_pages` и checkpoint. Сохранённую строящуюся страницу можно читать через `task_id`, но она ещё не опубликована.
4. **Опубликовать.** Общий `_finish` пересобирает `material_blocks` и `material_fragments`, переключает active revision, индексирует `fragment_search`/`fragment_search_map`, регистрирует `material_revisions`, пытается сопоставить проектные файлы ответов и завершает job. Только теперь результат — активная версия для общего поиска и дальнейших действий.

Связи `project_materials`, `bindings`, программа и эталонные ответы не появляются просто из-за расширения файла: нужны соответствующие проектные действия (§9). Все колонки общих таблиц перечислены в §10.1. Обычные форматы не создают `typst_materials`/`typst_source_chunks`.

**Пути в SQL ниже относительны к `settings.storage_dir`.** `materials/<H[:2]>/<H>.docx` означает физический `<data>/storage/materials/<H[:2]>/<H>.docx`. Asset хранит `assets/...`, а не `storage/assets/...`. У первой обработки web/YouTube источник тоже в `materials/...md`; `snapshots/...` используется при изменившемся refresh.

| Формат / вход | Порядок внутри шага 3 и зависимости | Пример сохраняемого результата | Исходник в SQL / что проверить |
|---|---|---|---|
| DOCX | python-docx → основные абзацы, Heading/нумерация, вложенные в абзац `r:embed` images → одна логическая страница | Heading «Раздел» + paragraph «Определение» → 1 page, 1 block, 2 fragments. Native, confidence NULL; page parser_mode NULL | `source_kind=file`; `materials/<H[:2]>/<H>.docx`. Нет обязательного PDF, OCR, Word/LibreOffice; таблицы/OMML вне этого обхода могут быть потеряны |
| TXT | UTF-8-SIG → непустые строки → heading/list/paragraph → одна страница 1×1; stdlib text reader | `1. Предел` становится heading уровня 1; следующая обычная строка — paragraph | `source_kind=file`; `materials/<H[:2]>/<H>.txt`. CP1251 автоматически не определяется; исходный файл не заменяется пересобранным Markdown |
| MD | Тот же текстовый reader, не полноценный Markdown AST | `# Предел` → heading без `#` в fragment.text; `$x$` → обычный paragraph, не обязательный formula | `source_kind=file`; `materials/<H[:2]>/<H>.md`. Fenced code/Markdown-таблица не гарантируют специализированный element_kind |
| Вставленный текст | Запись UTF-8 `.txt`/`.md` → тот же reader | Те же страницы и fragments, что у текстового файла с теми же строками | `source_kind=text`; расширение `.md` только если имя заканчивается на `.md`, иначе `.txt` |
| JPG / JPEG | Pillow verify → fast: PaddleOCR PP-OCRv5; cloud: исходные bytes в VLM → одна страница, размеры изображения в px | Прочитанная строка → paragraph/list; fast: recognition_source=ocr, cloud: vl; page quality=ocr/ocr_low | `source_kind=file`; `materials/<H[:2]>/<H>.jpg` или `.jpeg`. Нет PDF-layout. Cloud-фото не проходит PDF crop-attachment; оригинал доступен целиком |
| PNG | Та же ветка, что JPG; PNG не получает отдельного text-layer reader | Например paragraph «Определение» и непрочитанный image-элемент с локальным crop при fast | `source_kind=file`; `materials/<H[:2]>/<H>.png`. Проверьте прозрачность/качество изображения и результат распознавания, не только ready |
| MP3 | faster-whisper → CPU int8, ru, beam_size=5 → непустые сегменты → одна страница транскрипта | Один segment даёт paragraph, time_from/time_to; page quality=native, confidence NULL | `source_kind=audio`; `materials/<H[:2]>/<H>.mp3`. Проверка при upload не декодирует звук |
| WAV | Тот же Whisper-путь, отдельного WAV parser нет | Та же структура segments; height=max(duration,last_end,1), width=1 | `source_kind=audio`; `materials/<H[:2]>/<H>.wav`. Совместимость кодека проверяется фактическим декодированием во время обработки |
| M4A | Тот же Whisper-путь | Те же paragraph/time fields, не видеокадры | `source_kind=audio`; `materials/<H[:2]>/<H>.m4a`. Принимаемое расширение не гарантирует поддержку любого содержимого контейнера |
| OGG | Тот же Whisper-путь | Одна страница, столько paragraph, сколько непустых ASR-сегментов | `source_kind=audio`; `materials/<H[:2]>/<H>.ogg`. Нет отдельного diarization-шага или speaker_id |
| FLAC | Тот же Whisper-путь | Те же page/fragments и временные координаты; без confidence от ASR | `source_kind=audio`; `materials/<H[:2]>/<H>.flac`. Нужны faster-whisper и веса; cloud mode не меняет его на облачную транскрипцию |
| Веб-страница | При добавлении urllib/HTMLParser получают текст; после запуска обычный MD reader | Заголовок снимка, `Источник: URL` и body → native page и обычные fragments | `source_kind=url`; `materials/<H[:2]>/<H>.md`, source_url/retrieved_at. Без JS, скриншота, скачивания изображений и OCR |
| YouTube | При добавлении youtube-transcript-api запрашивает ru/en captions; после запуска обычный MD reader | `[00:12] Определение` остаётся строкой paragraph; time_from/time_to NULL | `source_kind=youtube`; `materials/<H[:2]>/<H>.md`. Видео/аудио не скачиваются; Whisper не участвует |

Для всех локальных аудиоформатов модель берётся из `TENTEX_WHISPER_MODEL` (default `small`); первый запуск может потребовать скачивания весов. Наличие установленного пакета и расширения не подтверждает работоспособность конкретного кодека/модели. У всех семей успешный `_finish` даёт `ready`, но это не гарантирует правильное распознавание, полноту извлечения или готовую Программу.

#### А. Нативный текст: один heading и один paragraph

Для MD `# Предел\nОпределение`, TXT `1. Предел\nОпределение` и DOCX с двумя обычными абзацами (Heading 1 «Предел» и «Определение») получится сходная структура. Ниже — **вариант MD**, без дополнительных строк/картинок; для TXT текст heading будет `1. Предел`.

```text
materials:
 {id:M, source_kind:"file", original_name:"Предел.md",
  storage_path:"materials/<H[:2]>/<H>.md", status:"ready",
  active_parse_revision:1, page_count:1, parser_mode:"fast", error:null}
material_pages:
 {id:P, material_id:M, revision:1, page_number:1, width:1, height:1,
  text:"Предел\nОпределение", markdown:"# Предел\n\nОпределение",
  quality:"native", confidence:null, parser_mode:null, diagnostics:[]}
material_blocks:
 {id:B, material_id:M, revision:1, sort_order:0, title:"Предел",
  block_class:"content", service_reason:null, page_from:1, page_to:1}
material_fragments:
 {id:F1, material_id:M, page_id:P, block_id:B, sort_order:0,
  text:"Предел", bbox:[0,0,1,0.5], element_kind:"heading", structure_level:1,
  degraded_structure:false, quality:"native", recognition_source:"native",
  confidence:null, asset_path:null, time_from:null, time_to:null}
 {id:F2, material_id:M, page_id:P, block_id:B, sort_order:1,
  text:"Определение", bbox:[0,0.5,1,1], element_kind:"paragraph", structure_level:null,
  degraded_structure:false, quality:"native", recognition_source:"native",
  confidence:null, asset_path:null, time_from:null, time_to:null}
background_jobs:
 {id:J, material_id:M, kind:"parse", state:"completed", stage:"complete",
  parser_mode:"fast", done:1, total:1, diagnostics:[], error:null}
material_revisions:
 {material_id:M, revision:1, origin:"imported", parser_mode:"fast",
  parent_revision:null, task_id:J, source_storage_path:"materials/<H[:2]>/<H>.md",
  source_hash:H, render_storage_path:null, scope:{kind:"all"}}
```

`fast` у job/material/revision здесь означает выбранный режим запуска; **NULL у native page — правильно**, как и NULL у confidence. FTS индексирует `fragment.text` обеих строк; это не embeddings. Если в DOCX есть встроенная картинка прочитанного абзаца, появляется дополнительный fragment `element_kind=image`, `text="[Изображение]"`, `asset_path="assets/<H>/docx<index>-<order>-<16hex>.<ext>"`; координаты — полоса абзаца, а не место на печатном листе. Страница DOCX исключает image-placeholder из plain text, но сам image-fragment хранится отдельно.

#### Б. JPG/PNG: условный OCR-result

Предположим изображение 1200×800, одна прочитанная Paddle строка «Определение» с оценкой 0.92, без skew/unread regions и порогом ≤0.92. Это **не проведённое измерение OCR**:

```text
material_pages:
 {id:P, material_id:M, revision:1, page_number:1, width:1200, height:800,
  text:"Определение", markdown:"Определение", quality:"ocr",
  confidence:0.92, parser_mode:"fast", diagnostics:[]}
material_fragments:
 {id:F, material_id:M, page_id:P, block_id:B, sort_order:0,
  text:"Определение", bbox:[0.1,0.2,0.9,0.3], element_kind:"paragraph",
  structure_level:null, degraded_structure:true, quality:"ocr",
  recognition_source:"ocr", confidence:0.92, asset_path:null,
  time_from:null, time_to:null}
```

У fast-image нет автоматического heading в этом reader, поэтому блок безымянный (`title=null`, page_from=page_to=1), а `degraded_structure=true`. При слабой оценке будут `quality=ocr_low` и `diagnostics=["low_confidence"]`; при отсутствии результатов возможна пустая страница с `empty_ocr`, confidence 0.0 и без fragments. Job всё равно может завершиться successfully; нельзя автоматически записывать ошибку material/job за каждую слабую страницу. Для cloud-page элементы имеют `recognition_source=vl`, page parser_mode=cloud, confidence считается другим правилом. Ни OCR-текст, ни bbox/score примера не гарантированы для реальной картинки.

#### В. MP3/WAV/M4A/OGG/FLAC: временная адресация, не печатный лист

Предположим Whisper вернул единственный непустой segment «Определение» от 2 до 5 секунд, а duration=10. Код преобразует **такой гипотетический** результат следующим образом:

```text
materials:
 {id:M, source_kind:"audio", original_name:"Лекция.mp3",
  storage_path:"materials/<H[:2]>/<H>.mp3", status:"ready",
  active_parse_revision:1, page_count:1, parser_mode:"fast", error:null}
material_pages:
 {id:P, material_id:M, revision:1, page_number:1, width:1, height:10,
  text:"Определение", markdown:"[00:02] Определение",
  quality:"native", confidence:null, parser_mode:null, diagnostics:[]}
material_fragments:
 {id:F, material_id:M, page_id:P, block_id:B, sort_order:0,
  text:"Определение", bbox:[0,0.2,1,0.5], element_kind:"paragraph",
  structure_level:null, degraded_structure:true, quality:"native",
  recognition_source:"native", confidence:null, asset_path:null,
  time_from:2, time_to:5}
```

У других четырёх расширений меняется исходный путь, но не этот контракт. Заголовков ASR reader не создаёт; block безымянный. Timestamp появляется в page.markdown, тогда как fragment.text и FTS содержат текст без timestamp. Значение `native` здесь **не означает авторский текст без машинных ошибок**. Если непустых speech segments нет, worker помечает job и материал failed и пишет строку `В аудио не удалось распознать речь` в их `error`; первая активная версия не появляется, прежняя при повторе сохраняется.

#### Г. Website и YouTube: снимок, а не мультимедийный архив

**Website:** допустим, адаптер получил title «Предел» и body «Определение» с `https://example.org/lesson`. Ни этот URL, ни видео ниже не запрашивались для примера. Снимок устроен так:

```text
# Предел

Источник: https://example.org/lesson

Определение
```

При первоначальной подготовке через fast worker: `materials.source_kind=url`, `source_url` — конечный URL, `retrieved_at` — время fetch; page 1×1, native, confidence=NULL, parser_mode=NULL. Получатся heading «Предел» и два paragraph («Источник: …», «Определение»), т.е. один content block и три fragments с условными вертикальными полосами. Job и первая revision имеют parser_mode=fast; у первой `material_revisions` origin=imported (у job поля origin нет). URL/дата — metadata, а не отдельный image asset.

**YouTube:** если получены субтитры со строкой в 12 секунд, snapshot имеет форму:

```text
# Транскрипт YouTube

Источник: https://www.youtube.com/watch?v=<video_id>

[00:12] Определение
```

Здесь `source_kind=youtube`; `original_name="YouTube <video_id>.md"`; тот же MD reader создаст native heading и paragraph. У fragment `[00:12] Определение` `recognition_source=native`, confidence=NULL, **time_from=NULL, time_to=NULL**. Это не аудио-example В: timestamp здесь входит в fragment.text и FTS как текст, длительность subtitle не сохранена. Никаких mp4/mp3 и ASR-таблиц этот путь не создаёт.

**Обновление обоих видов:** changed snapshot сохраняется как SQL-путь `snapshots/<M>/<R>.md` и синхронно публикуется, без нового parse job, с `origin=source_refresh`, page diagnostics `["source_refreshed"]`. В текущем коде refresh-page сохраняет **width=595,height=842**, хотя элементы текстового parser всё ещё имеют нормализованные полосы; это отличие от первоначальной 1×1 worker-page, а не настоящий PDF-layout. `material_revisions.parser_mode` берётся из материала и потому может оставаться fast/cloud; новая native page имеет parser_mode NULL. При неизменном хеше меняется дата, новая revision не создаётся.

#### Ошибки: где смотреть

| Сбой | Где результат |
|---|---|
| Пустой/слишком большой/неподдерживаемый upload, неверный UTF-8 или повреждённый DOCX/image | HTTP domain error до регистрации нового материала; не выдумывать parse-job error, когда job ещё нет |
| Не готов выбранный режим | `parser_mode_unavailable`; job не поставлен |
| DOCX/Whisper/Paddle/worker упал при обработке | `background_jobs.state=failed`, `materials.status=failed`, поле `error` со строкой исключения; опубликованная старая revision не стирается |
| Слабый OCR или survivable cloud failure | Page quality/diagnostics/confidence; job может завершиться completed, материал ready |
| Website не прочитан / YouTube captions недоступны | HTTP `material_url_*` / `material_youtube_*` при получении снимка; никакого fallback на скачивание аудио и Whisper |

Точное поле **`error`**, не `errors`, существует у материала и job; `diagnostics` у страницы — список строк. Для Typst отдельно существует `issues` — список объектов (см. §5).

Код всех примеров закреплён на проверяемом коммите: [dispatch/фото](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/native.py#L845-L898), [текст](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/native.py#L421-L465), [DOCX](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/native.py#L552-L630), [audio](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/audio.py#L7-L42), [Paddle quality](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/paddle_fast.py#L263-L322), [снимки](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/external.py#L90-L193), [source kind регистрации](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L866-L884), [сохранение страницы](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/worker.py#L168-L205), [структура и fragment fields](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L1522-L1568), [refresh](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/library.py#L1867-L1955).


## 11. Зависимости: что установить и что не обещать

| Слой | Прямые зависимости в этом коммите | Примечание |
|---|---|---|
| API/SQL/upload | Python (Docker 3.13), FastAPI, Uvicorn, Pydantic/settings, SQLAlchemy, Alembic, python-multipart | SQLite с FTS5; API и worker должны видеть одни data |
| Native PDF/layout | PyMuPDF `>=1.26,<2`, **PyMuPDF4LLM `==1.28.2`**, Pillow `>=11,<13` | Layout локальный; Tesseract не используется этим путём |
| DOCX | python-docx `>=1.2,<2` | Не LibreOffice и не Word automation |
| Локальный OCR | **paddlepaddle `3.2.2` + paddleocr `3.4.1`**, веса PP-OCRv5 | Только requirements-worker; тяжёлые веса отдельно |
| Аудио | **faster-whisper `1.2.1`**, локальные/скачиваемые веса Whisper | CPU int8, ru, модель по env |
| URL/YouTube | Python urllib/HTMLParser; youtube-transcript-api `>=1.0,<2` | Нужна сеть; не браузерный crawling |
| Поиск | pymorphy3 `>=2.0,<3`, pymorphy3-dicts-ru `>=2.4,<3`, SQLite FTS5 | Без vector DB |
| Cloud OCR | openai `>=2,<3`, cryptography `>=46,<47`, настройки провайдера/vision-модели | Нужны разрешение внешних моделей, ключ, сеть, допустимые лимиты |
| Установка OCR-весов | huggingface-hub `>=0.34,<2` | Это загрузка модели, не отправка документа в cloud OCR |
| Typst | Отдельный executable **0.15.1** | Не Python-пакет; при необходимости пакеты и шрифты |
| Системные библиотеки worker | `libgl1`, `libglib2.0-0`, `libgomp1`; build-download: `curl`, `xz-utils` | Включены Dockerfile.worker |

В текущем production-конвейере не требуются JRE/opendataloader-pdf, GPU/PaddleOCR-VL/PP-StructureV3, отдельный textbook-ocr, Tesseract, Poppler, LibreOffice. Это не запрещает исследовательские скрипты, но их нельзя перечислять как обязательную архитектуру Библиотеки. `fast` **ready даже без весов**: Paddle может скачать их при первом скане; пока явная загрузка идёт, readiness=downloading. Это означает «можно запустить», не «все зависимости доступны офлайн» и не health-check исполняющего worker. Runtime fast-language принудительно ru; UI-колонка language не гарантирует переключение языка.

Cloud readiness проверяет включённость внешних моделей, выбор vision-модели и наличие ключа. Фактический запрос ещё может упасть из-за API/модели/бюджета/структурного ответа. Роль `material_page_recognition` использует structured output и content-hash cache; confirmed=True относится к согласию на весь запуск, не отменяет лимиты. Не используйте прайсы/имена моделей из старой research-заметки как нынешнюю гарантию доступности.

Источники: [requirements](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/requirements.txt#L4-L22), [worker requirements](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/requirements-worker.txt#L1-L7), [образ worker](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/Dockerfile.worker#L1-L29), [readiness](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/ocr/settings.py#L227-L280), [реестр runtime](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/ocr/engines.py#L50-L85), [cloud request](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/app/materials/parsers/cloud_vlm.py#L406-L444).

## 12. Практическая проверка результата

1. Проверьте, что выбрали правильную поверхность: Библиотека / импорт вопросов / ответ-вложение.
2. После обычной загрузки запустите подготовку. При queued без прогресса проверьте, запущен ли worker и общий data mount.
3. Откройте несколько страниц: обычный текст, две колонки, формулу, таблицу, рисунок, страницу с плохим сканом. Сравните оригинал и текст, а не только зелёный ready.
4. Проверьте `ocr_low`, пустые страницы, `layout_fallback`, `bbox_missing`, `cloud_page_unreadable`; повторите нужный диапазон или исправьте текст новой версией.
5. Для Typst сначала добейтесь PDF, затем проверьте извлечённый текст, source chunks и страницу контекста. Обязательно проверьте документ с более чем тремя chunks и зависимостью в подпапке: успешный простой single-file сценарий их не доказывает.
6. В проекте отдельно проверьте импорт вопросов, отчёт сопоставления ответов, orphaned-привязки и доступность эталонов.

В репозитории есть тесты и smoke scripts, выражающие контракт, например `test_typst_context.py` и `check_typst_material.py` (single/ZIP, missing package/image, compile failure, очередь, cancel, autolink). Это **свидетельство предусмотренных сценариев**, не результат сегодняшнего запуска. Скрипт Typst запускает реальные API/worker/БД и компилятор; его нельзя запускать под видом read-only проверки рабочей установки. Аудит их только прочитал.

Код: [контракт context test](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/tests/test_typst_context.py#L1-L52), [описание smoke](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/scripts/check_typst_material.py#L1-L14), [основные проверки](https://github.com/tneki22/Tentex/blob/9acd0f78167a6e3d0b2f79479cfc99139b1ee298/backend/scripts/check_typst_material.py#L111-L170).

## 13. Внешние статьи, документация и видео

### Назначение и уровень проверки

Каталог для технического владельца: что прочитать и какие видео открыть, чтобы понимать технологии обработки входных материалов. Это **внешний учебный фон, а не описание реализации Tentex**. Подборка внешних источников дополнена проверкой репозитория в разделах 1–12; наличие функции у библиотеки не доказывает её использование приложением.

Проверка выполнена 2026-09-09 через ExaSearch и ExaContents. Для включённых страниц получено содержимое; для всех 11 видео подтверждены прямой YouTube URL, название и канал по извлечённым метаданным/описанию. Exa преимущественно вернула кешированные страницы: это проверка индексируемого содержания, **не гарантия доступности проигрывания сейчас, в конкретном регионе или без входа**. Видео не просматривались; оценки ниже опираются на описание, главы и извлечённые текстовые фрагменты, а не на просмотр или независимый тест качества урока. Видео-ID не выдумывались. Неподтверждённые и нерелевантные результаты исключены.

Язык: **EN — английский**. Подходящего русскоязычного материала с сопоставимой точностью в проведённом поиске не подтверждено; выбранные английские материалы явно помечены. Названия приведены на языке оригинала, пояснения — по-русски. `D-*` — документация/исходный код, `V-*` — видео. Все видео общие, **ни одно не является демонстрацией Tentex**.

#### Быстрая карта покрытия

| Вход / подсистема | Читать | Смотреть | Что обязательно сверить в Tentex отдельно |
|---|---|---|---|
| PDF с текстовым слоем | D-PDF-01, D-PDF-03 | V-PDF-01 | Порядок чтения, постраничность, сохранение таблиц/метаданных, версия PyMuPDF4LLM |
| Сканированный / смешанный PDF, OCR | D-PDF-02, D-OCR-01 | V-OCR-01 | Условие запуска OCR, рендеринг страниц, движок, язык, ошибки |
| DOCX | D-DOCX-01…05 | V-DOCX-01 | Порядок абзацев/таблиц, вложенные таблицы, OMML-формулы, пропущенные части документа |
| TXT | D-TEXT-02 | V-TEXT-01 как фон о plain text | Декодирование UTF-8/BOM, политика ошибок; видео не урок по UTF-8 |
| Markdown | D-TEXT-01, D-TEXT-02 | V-TEXT-01 | CommonMark против расширений, обработка HTML/ссылок/кода |
| JPEG / PNG | D-IMG-01, D-OCR-01 | V-IMG-01, V-OCR-01 | Нормализация цвета/ориентации, размер, вызов OCR |
| Аудио MP3 / WAV / M4A / OGG / FLAC | D-AUD-01…03 | V-AUD-01 | Реальные декодеры, модель, CPU/GPU, таймкоды, язык, допустимые расширения |
| URL сайта / HTML | D-WEB-02, D-WEB-03; D-WEB-01 как сравнение | V-WEB-01 | Что считается snapshot, исходный HTML или только текст, JS-страницы, время загрузки |
| YouTube URL / субтитры | D-YT-01 | V-YT-01 | Captions-only, язык, ручные/автосубтитры, блокировки, отсутствие трека |
| Typst одиночный `.typ` | D-TYP-01, 04, 06, 07, 08 | V-TYP-01, V-TYP-02 | В Tentex: CLI compile, PDF-reader и отдельные source chunks; query — только справочный материал |
| Typst ZIP / папка проекта | D-TYP-02, 03, 04, 05, 06, 09 | V-TYP-02 | Entry point, дерево ресурсов, безопасная распаковка, fonts/packages/bibliography |
| SQLite / SQLAlchemy / FTS5 / BM25 | D-DB-01, D-DB-02 | V-DB-01 | Схема/транзакции, наличие FTS5, синхронизация индекса, ранжирование |

### PDF: цифровой текст, сканы и структурированный вывод

#### D-PDF-01 — Text (PyMuPDF recipes)
- URL: https://pymupdf.readthedocs.io/en/latest/recipes-text.html
- Источник: официальная документация PyMuPDF; язык: EN.
- Объясняет: извлечение текста, блоков и слов с координатами; естественный порядок чтения; извлечение таблиц; переход к Markdown.
- Для владельца: PDF хранит текст и геометрию, но не обязательно готовую линейную последовательность абзацев. Обычный `get_text()` может возвращать неожиданные переносы и порядок.
- Граница с Tentex: не подтверждает конкретную сортировку блоков, разбиение на chunks или точность восстановления таблиц в приложении.

#### D-PDF-02 — OCR — Optical Character Recognition (PyMuPDF recipes)
- URL: https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html
- Источник: официальная документация PyMuPDF; язык: EN.
- Объясняет: OCR изображения и страницы, `Pixmap`, текстовый слой, `TextPage`, повторное использование результата; признаки страницы, которой нужен OCR.
- Важное различие: описанный интегрированный OCR PyMuPDF основан на **Tesseract**. Это не документация PaddleOCR. Не переносить это устройство автоматически на отдельную OCR-ветку Tentex.
- Граница с Tentex: пороги «мало текста», выбор страниц, DPI, языки и fallback должны быть подтверждены кодом и тестами приложения.

#### D-PDF-03 — PyMuPDF4LLM
- URL: https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/
- Источник: официальная документация PyMuPDF; язык: EN.
- Объясняет: преобразование PDF в Markdown и другие структурированные представления; страницы/chunks, многоколоночная верстка, метаданные и интеграции.
- Граница с Tentex: документация `latest` уже описывает расширенные layout/OCR-возможности. Нельзя заявлять, что они есть в установленной версии Tentex. Особо сверить имена параметров и формат результата; поддержка Office через Pro не доказывает, что Tentex обрабатывает DOCX этим путём.

#### D-OCR-01 — PaddlePaddle/PaddleOCR
- URL: https://github.com/PaddlePaddle/PaddleOCR
- Источник: официальный репозиторий PaddleOCR; язык основной README: EN.
- Объясняет: назначение OCR для изображений/PDF, отличие распознавания текста от восстановления структуры, семейства моделей и ссылки на руководства по их запуску.
- Применение: **оба входа — скан PDF после получения изображения и JPEG/PNG**.
- Граница с Tentex: API и модельные семейства существенно менялись; наличие PaddleOCR в зависимостях не доказывает использование современных PP-Structure/VL-моделей. Язык `ru`, устройство, формат полей и оценку уверенности сверять с зафиксированной версией. Рекламные заявления README об accuracy не являются оценкой качества Tentex.

#### V-PDF-01 — PyMuPDF4LLM Tutorial: Building a Multimodal LLM Application with PDF Data
- Прямое видео: https://www.youtube.com/watch?v=EIBtI2lNO7c
- Канал: **PyMuPDF**; язык: EN; длительность по метаданным: 06:00; публикация: 2025-01-27.
- По описанию/главам: установка и PDF → Markdown, chunks с метаданными, извлечение изображений, добавление изображений в Markdown, слова и координаты.
- Карта использования: основной урок для **цифрового PDF**, дополнительный — для понимания промежуточного Markdown. Не урок по приёму `.md` и не доказательство OCR сканов.
- Полезные главы: 00:14 — Markdown; 00:58 — chunks/метаданные; 02:00 — изображения; 04:30 — слова.
- Не про Tentex: не показывает схему его chunks, БД, поиск или гарантии мультимодального анализа; параметры из видео проверять по версии библиотеки.

#### V-OCR-01 — Multilingual OCR - PaddleOCR
- Прямое видео: https://www.youtube.com/watch?v=eNmyykrCXbc
- Канал: **Hands-on AI**; язык: EN; длительность: 05:55; публикация: 2024-07-20.
- По извлечённому тексту: установка, выбор языка, загрузка весов при первом запуске, OCR изображения, координаты областей, текст и confidence, отрисовка результата.
- Карта использования: **JPEG/PNG** и **сканированный PDF после рендеринга страницы в изображение**; общий фон для диагностики OCR.
- Не про Tentex: не показывает автоматический PDF-routing приложения. Урок старше ветки PaddleOCR 3.x; показанная структура списков и `draw_ocr` может отличаться от текущего API. Примеры автора не подтверждают качество русскоязычного OCR или распознавания формул.

### DOCX: абзацы, таблицы и математические объекты

#### D-DOCX-01 — Quickstart
- URL: https://python-docx.readthedocs.io/en/latest/user/quickstart.html
- Источник: официальная документация python-docx; язык: EN.
- Объясняет: `Document`, paragraphs/runs, заголовки, таблицы и изображения. Удобный вводный материал о структуре Word, хотя примеры во многом создают документы, а не извлекают их.
- Граница с Tentex: добавление элемента и чтение всех элементов из произвольного DOCX — разные задачи; наличие API не означает сохранение всего содержимого при импорте.

#### D-DOCX-02 — Document objects
- URL: https://python-docx.readthedocs.io/en/latest/api/document.html
- Источник: официальный API reference python-docx; язык: EN.
- Объясняет: объект документа, коллекции paragraphs/tables, свойства документа, открытие и сохранение; справочник для проверки используемых API.
- Граница с Tentex: отдельно проверить обход блоков в исходном порядке, обработку ревизий, колонтитулов и вложенных структур; нельзя обещать полное извлечение Word только по доступу к `paragraphs`.

#### D-DOCX-03 — Working with Tables
- URL: https://python-docx.readthedocs.io/en/stable/user/tables.html
- Источник: официальная документация python-docx; язык: EN.
- Объясняет: layout grid, объединённые и пропущенные ячейки, отличие таблицы Word от прямоугольной матрицы, вложенные таблицы и порядок содержимого ячейки.
- Граница с Tentex: «таблица извлечена» не равно сохранению всех merges и вложенности; способ уплощения надо описывать на основе его реализации.

#### D-DOCX-04 — Structure of a WordprocessingML document
- URL: https://learn.microsoft.com/en-us/office/open-xml/word/structure-of-a-wordprocessingml-document
- Источник: Microsoft Learn / Open XML SDK; язык: EN.
- Объясняет: DOCX как ZIP-пакет с XML-частями; `document/body/p/r/t`; отдельные stories — основной текст, комментарии, сноски, колонтитулы и др.
- Граница с Tentex: это спецификационная основа, **не предложение заменить Python на .NET**. Чтение только `word/document.xml` не тождественно чтению всех частей документа.

#### D-DOCX-05 — OfficeMath Class
- URL: https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.math.officemath?view=openxml-3.0.1
- Источник: Microsoft Learn / Open XML SDK; язык: EN.
- Объясняет: `m:oMath`, inline math и math paragraph (`oMathPara`); математическая структура в Open XML не сводится к обычным текстовым runs.
- Граница с Tentex: наличие формулы в XML не доказывает конвертацию в LaTeX/MathML или сохранение математического смысла; отдельный XML fallback приложения требует проверки.

#### V-DOCX-01 — Advanced Python Programming: Reading and Writing to Documents with docx
- Прямое видео: https://www.youtube.com/watch?v=26vNgM_wSAE
- Канал: **TheCodex**; язык: EN; публикация по индексу: 2018-01-01 UTC.
- По извлечённому тексту: чтение DOCX, получение текста абзацев, понятие runs, создание документа, добавление текста и изображения.
- Карта использования: **DOCX — базовая модель paragraphs/runs**. Для таблиц и формул дополнить D-DOCX-03 и D-DOCX-05: видео не подтверждает покрытие этих тем.
- Не про Tentex: вводный и старый API-урок; не инструкция по безошибочному извлечению полного содержания Word. Правильные имена пакета/API брать из первичной документации, а не ошибок автоматической расшифровки видео.

### TXT / Markdown: Unicode и структура plain text

#### D-TEXT-01 — CommonMark Spec (0.31.2)
- URL: https://spec.commonmark.org/0.31.2/
- Источник: спецификация CommonMark, John MacFarlane; язык: EN.
- Объясняет: blocks/inlines, заголовки, абзацы, списки, fenced code, ссылки, HTML-блоки и примеры синтаксического разбора.
- Граница с Tentex: расширения GitHub, таблицы, task lists и математическая разметка не следует автоматически считать частью базового CommonMark. Приём `.md` не доказывает полноценный CommonMark parser.

#### D-TEXT-02 — Unicode HOWTO
- URL: https://docs.python.org/3/howto/unicode.html
- Источник: официальная документация Python; язык: EN.
- Объясняет: Unicode code points, `str` против `bytes`, UTF-8, `encode`/`decode`, файловое чтение с `encoding`, обработчики ошибок, BOM и нормализация.
- Применение: **TXT и Markdown**, а также все текстовые результаты извлечения.
- Граница с Tentex: выбрать и подтвердить фактическое поведение на не-UTF-8, повреждённых последовательностях и UTF-8 BOM. `errors='ignore'` может терять данные; сам ресурс не доказывает, что Tentex его использует.

#### V-TEXT-01 — Markdown Crash Course
- Прямое видео: https://www.youtube.com/watch?v=HUBNt18RFbo
- Канал: **Traversy Media**; язык: EN; длительность: 19:31; публикация: 2018-03-23.
- По описанию/тексту: Markdown как человекочитаемый plain text, заголовки, списки, ссылки, код, preview в VS Code и оформление README на GitHub.
- Карта использования: **Markdown**, а для **TXT** — только объяснение различия между обычным текстом и текстом с разметкой. UTF-8 и декодирование покрывает D-TEXT-02, не это видео.
- Не про Tentex: GitHub-расширения из урока не являются обещанием поддержки приложением; preview редактора и сохранённый/индексируемый текст — разные представления.

### JPEG / PNG: загрузка изображения и OCR

#### D-IMG-01 — Tutorial (Pillow)
- URL: https://pillow.readthedocs.io/en/stable/handbook/tutorial.html
- Источник: официальная документация Pillow; язык: EN.
- Объясняет: `Image.open`, определение формата по содержимому, `size`, `mode`, преобразование цветовых режимов, resize/crop/rotate и сохранение.
- Граница с Tentex: **Pillow не является OCR-движком**. Чтение пикселей и распознавание текста — разные этапы; OCR см. D-OCR-01. EXIF-ориентацию, прозрачность PNG, CMYK JPEG, лимиты размеров и обработку повреждённых изображений проверять отдельно.

#### V-IMG-01 — Python Tutorial: Image Manipulation with Pillow
- Прямое видео: https://www.youtube.com/watch?v=6Qs3wObeWwc
- Канал: **Corey Schafer**; язык: EN; длительность: 15:48; публикация: 2015-11-17.
- По описанию: чтение/изменение изображений, изменение формата, resize, crop, цвета, blur и пакетная обработка.
- Карта использования: **JPEG/PNG — подготовка изображения**; вместе с **V-OCR-01** образует учебную последовательность «пиксели → распознавание текста».
- Не про Tentex: видео не выполняет OCR и не показывает его preprocessing. Старые инструкции установки не следует переносить буквально. Фильтры не всегда улучшают OCR; результат надо измерять на реальных сканах.

### Аудио: MP3 / WAV / M4A / OGG / FLAC

#### D-AUD-01 — SYSTRAN/faster-whisper — Faster Whisper transcription with CTranslate2
- URL: https://github.com/SYSTRAN/faster-whisper
- Источник: официальный репозиторий faster-whisper; язык: EN.
- Объясняет: Whisper через CTranslate2, установка, CPU/GPU и compute types, получение segments/info, word timestamps, VAD, batch inference.
- Важные понятия: `segments` — ленивый генератор; нужно его итерировать. Benchmark автора не гарантия скорости любого CPU/GPU или файла.
- Граница с Tentex: модель, язык, VAD и настройки inference определяются приложением. Поддержка функции библиотекой не означает наличие её в UI/выводе Tentex.

#### D-AUD-02 — openai/whisper — Robust Speech Recognition via Large-Scale Weak Supervision
- URL: https://github.com/openai/whisper
- Источник: официальный репозиторий OpenAI Whisper; язык: EN.
- Объясняет: multilingual speech recognition, определение языка, размеры моделей, transcription против translation, CLI и Python usage.
- Граница с Tentex: Whisper и faster-whisper используют родственную модель, но **не взаимозаменяемый Python API**. Не переносить механически требования установки и структуру результата. Транскрипция не равна переводу или diarization.

#### D-AUD-03 — faster_whisper/audio.py
- URL: https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/audio.py
- Источник: исходный код официального faster-whisper; язык комментариев/API: EN.
- Объясняет: декодирование через PyAV, resampling, mono/stereo, преобразование данных для inference. Полезнее списка расширений для понимания реального пути декодирования.
- Применение: **MP3, WAV, M4A, OGG, FLAC рассматриваются как отдельные разрешённые приложением контейнеры/форматы, далее проходящие общий декодер**. Этот файл не является исчерпывающей гарантией всех кодеков внутри каждого контейнера.
- Граница с Tentex: тестировать каждый формат на установленной сборке PyAV/FFmpeg и фактическом allowlist. M4A — контейнер; успешная проверка расширения не доказывает декодируемость содержимого.

#### V-AUD-01 — How to create captions with Fast Whisper and Python #python #coding #captions #whisper #programming
- Прямое видео: https://www.youtube.com/watch?v=BDIsyJfNRXg
- Канал: **Developer Service**; язык: EN; публикация: 2025-04-16.
- По описанию: Faster-Whisper на CPU с INT8, транскрипция аудиофайла, word timestamps, форматирование времени и запись SRT.
- Карта использования: общий ASR-этап после декодирования **всех пяти аудиоформатов**. Видео не верифицирует каждый контейнер по отдельности.
- Не про Tentex: создание SRT и word timestamps в уроке не означает, что приложение хранит или отдаёт их пользователю. Это локальная транскрипция аудио, а не получение готовых YouTube captions.

### Веб-сайт / HTML: извлечение основного текста и snapshot

#### D-WEB-02 — html.parser — Simple HTML and XHTML parser
- URL: https://docs.python.org/3/library/html.parser.html
- Источник: официальная документация Python; EN. Подтверждён содержимым страницы 09.09.2026.
- Объясняет фактически используемый класс HTMLParser: обработчики тегов и текстовых узлов. Это парсер полученного HTML, не браузер с JavaScript.

#### D-WEB-03 — urllib.request — Extensible library for opening URLs
- URL: https://docs.python.org/3/library/urllib.request.html
- Источник: официальная документация Python; EN. Подтверждён содержимым страницы 09.09.2026.
- Объясняет фактически используемый HTTP-клиент, Request/urlopen, заголовки и ответы. Ограничения URL и MIME задаёт код Tentex.

#### D-WEB-01 — Quickstart (Trafilatura), только для сравнения
- URL: https://trafilatura.readthedocs.io/en/latest/quickstart.html
- Источник: официальная документация Trafilatura; язык: EN.
- Объясняет: загрузка URL и извлечение из HTML, `extract()` для основного содержания, `html2txt()` для более широкого текста страницы, извлечение метаданных, Python и CLI.
- Для владельца: HTML-ответ, DOM после выполнения JavaScript, очищенный текст и визуальная копия страницы — разные вещи.
- **Trafilatura не используется в текущем Tentex:** там urllib + собственный HTMLParser. Документация и видео ниже приведены как дополнительное объяснение задачи извлечения, не как инструкция по установленной зависимости. **snapshot — термин/контракт приложения**, не обещание Trafilatura архивировать сайт. Уточнить, что сохранено: URL, время получения, сырой HTML, очищенный текст, метаданные, изображения. Без отдельного браузера JS-only-страница может не содержать нужного текста в исходном HTML. Наличие `fetch_url` не решает автоматически SSRF, редиректы и ограничения доступа.

#### V-WEB-01 — Web scraping and text content extraction - Beginner tutorial for Python and the command-line
- Прямое видео: https://www.youtube.com/watch?v=8GkiOM17t0Q
- Канал: **Trafilatura Web Scraping**; язык: EN (по англоязычному описанию); длительность: 08:22; публикация: 2021-02-25.
- По описанию: установка Windows/macOS, CLI, Python, основной текст, метаданные и discovery RSS/Atom.
- Главы: 01:36 — CLI; 02:50 — Python; 06:55 — metadata; 07:49 — baseline extraction.
- Карта использования: **website/HTML extraction**. Видео дополнительно обнаружено через ссылку в официальном репозитории https://github.com/adbar/trafilatura .
- Не про Tentex: используемая в ролике Trafilatura отсутствует в текущем конвейере. RSS/crawling и полный snapshot не следует приписывать приложению только потому, что они обсуждаются вокруг библиотеки. API старого ролика проверять по актуальной для приложения версии.

### YouTube: получение captions, НЕ загрузка аудио/видео

#### D-YT-01 — jdepoix/youtube-transcript-api
- URL: https://github.com/jdepoix/youtube-transcript-api
- Источник: официальный репозиторий библиотеки; язык: EN. **Это не официальный API Google/YouTube.**
- Объясняет: получение существующих ручных и автоматически созданных субтитров по video ID, приоритет языков, список доступных tracks, `is_generated`, `text/start/duration`, форматирование и ошибки блокировок.
- Важное различие версий: текущий README показывает `YouTubeTranscriptApi().fetch(video_id)` и `.list(video_id)`. В старых уроках используются `get_transcript`/`list_transcripts`; сверять установленную версию.
- Граница с Tentex: captions-only означает **получение текстового трека**, а не загрузку аудио через yt-dlp и не запуск Whisper. Если субтитры отсутствуют/выключены/заблокированы, это отдельный исход. Не изобретать ASR fallback без доказательства кода. Извлечённые captions могут содержать ошибки и не гарантируют описание визуальной части видео.

#### V-YT-01 — How to Download YouTube Subtitles Using Python's YouTube Transcript API
- Прямое видео: https://www.youtube.com/watch?v=Ok7Q2LGvQPI
- Канал: **Programming with Kumaresan**; язык: EN; публикация: 2024-07-08.
- По описанию и извлечённому тексту: video ID, установка библиотеки, получение subtitle tracks, языки, ручные/автоматические субтитры, перевод и сохранение текста.
- Карта использования: **YouTube captions ingestion**. Слово Download в названии относится к субтитрам, не к media download.
- Не про Tentex: показан старый API; язык, перевод и сохранение subtitle file — возможности примера, не обещание возможностей приложения. Не использовать главные тезисы урока как доказательство надёжности запросов с облачных IP.

### Typst: исходник, ZIP/папка, компиляция, ресурсы и query

#### D-TYP-01 — Syntax - Typst Documentation
- URL: https://typst.app/docs/reference/syntax/
- Источник: официальная документация Typst; язык: EN.
- Объясняет: markup/math/code, заголовки, комментарии, математическая разметка и переключение в код.
- Граница с Tentex: `.typ` — исполняемый в рамках языка документ с функциями, а не просто Markdown с другим расширением. Чтение исходного текста не равно получению результата компиляции.

#### D-TYP-02 — Scripting - Typst Documentation
- URL: https://typst.app/docs/reference/scripting/
- Источник: официальная документация Typst; язык: EN.
- Объясняет: content/code blocks, переменные, функции, модули, импорт/включение других файлов, package import.
- Граница с Tentex: сам `.typ` может быть недостаточен; нужные соседние файлы/ресурсы должны быть доступны относительно проекта. Порядок выбора главного файла и корень проекта — политика Tentex, не свойство произвольного ZIP.

#### D-TYP-03 — typst/packages
- URL: https://github.com/typst/packages
- Источник: официальный репозиторий пакетов Typst; язык: EN.
- Объясняет: `typst.toml`, пакет как файлы плюс ресурсы, namespace/name/version, `@preview`, локальные пакеты, загрузка по запросу и кеш.
- Граница с Tentex: компиляция с package import может зависеть от сети и кеша; наличие пакета у автора не означает его наличие на сервере. Версии и разрешённые источники надо зафиксировать; не заявлять полностью offline-путь без проверки.

#### D-TYP-04 — typst/typst
- URL: https://github.com/typst/typst
- Источник: официальный репозиторий компилятора и CLI; язык: EN.
- Объясняет: локальная установка, исходник `.typ`, компиляция в PDF, наблюдение за изменениями и общая модель typesetting.
- Граница с Tentex: приложение может вызывать CLI как subprocess; это требует собственного описания timeouts, рабочих директорий, limits и stderr. Учебный `typst compile` не доказывает обработку ZIP компилятором — проект предварительно организуется/распаковывается отдельно.

#### D-TYP-05 — Bibliography - Typst Documentation
- URL: https://typst.app/docs/reference/model/bibliography/
- Источник: официальная документация Typst; язык: EN.
- Объясняет: `.bib` (BibLaTeX), `.yaml/.yml` (Hayagriva), citation keys, список литературы и CSL-стили.
- Граница с Tentex: ZIP/папка должны сохранить нужные bibliography/CSL-файлы. Исходные записи и видимая библиография — не одно и то же: по умолчанию вывод зависит от цитирования. Не обещать индексацию всех записей `.bib`, если индексируется только PDF.

#### D-TYP-06 — Text - Typst Documentation
- URL: https://typst.app/docs/reference/text/text/
- Источник: официальная документация Typst; язык: EN.
- Объясняет: выбор family/fallback, покрытие символов, системные и embedded fonts, локальные каталоги; `--font-path`, `TYPST_FONT_PATHS`, `typst fonts`, `--ignore-system-fonts`.
- Граница с Tentex: шрифт на машине автора может отсутствовать в окружении обработки; веб-редактор Typst и CLI обнаруживают шрифты по-разному. Файлы `.ttf/.otf` проекта и окружение влияют на воспроизводимость; проверить кириллицу и математические символы.

#### D-TYP-07 — Query - Typst Documentation
- URL: https://typst.app/docs/reference/introspection/query/
- Источник: официальная документация Typst; язык: EN.
- Объясняет: поиск элементов по типу/метке, контекст, выбор headings и locations, сериализация результатов, ограничение сходимости introspection.
- **Версионная оговорка:** извлечённая `latest`-страница уже показывает CLI `typst eval 'query(...)' --in ...`; документация опубликованной Rust-библиотеки ниже ещё описывает `typst query`. Это сигнал проверить `typst --version` и CLI help в окружении Tentex, а не молча переписать его команды.
- Дополнительный первичный reference: https://docs.rs/typst-library/latest/typst_library/introspection/fn.query.html — **query in typst_library::introspection - Rust**, EN; подтверждает `typst query`, `--field`, `--one` и выбор элементов. Публикация API-документации самой библиотеки через docs.rs.
- **В текущем Tentex команда query не вызывается:** оглавление берётся из PDF через PyMuPDF. query заголовков — возможное структурное дополнение к извлечению скомпилированного PDF; не универсальное извлечение всего текста исходного проекта. Выполнять command syntax той версии, которую приложение реально использует.

#### D-TYP-08 — Heading - Typst Documentation
- URL: https://typst.app/docs/reference/model/heading/
- Источник: официальная документация Typst; язык: EN.
- Объясняет: уровни/depth, numbering, outlined/bookmarked и заголовки как структурные элементы.
- Граница с Tentex: визуально крупный текст может не быть `heading`; извлечение через query зависит от семантической структуры документа и show rules. Сохранение всего TOC не следует автоматически из наличия query.

#### D-TYP-09 — zipfile — Work with ZIP archives
- URL: https://docs.python.org/3/library/zipfile.html
- Источник: официальная документация Python; язык: EN.
- Объясняет: чтение состава ZIP, извлечение, compression methods, ZIP64 и ограничения.
- Карта использования: упаковка **Typst-проекта в ZIP**, дополнительно — понимание упаковки DOCX.
- Граница с Tentex: это общая библиотека архивов, не безопасный готовый загрузчик Typst. Отдельно проверить path traversal/абсолютные пути, symlinks, количество файлов, распакованный размер, вложенные архивы и разрешённые расширения. Для папки аналогично важны разрешённый корень и относительные пути. Материал не определяет, какой `.typ` выбрать из нескольких.

#### V-TYP-01 — Typst's Intuitive Syntax: A Comprehensive Tutorial for Beginners
- Прямое видео: https://www.youtube.com/watch?v=BB1zhr-QWjQ
- Канал: **Federico Tartarini**; язык: EN; длительность: 17:49; публикация: 2025-04-11 по часовому поясу канала (2025-04-12 UTC).
- По описанию/главам: текст, headings, списки, ссылки/сноски, таблицы, изображения и figures, code blocks, styling.
- Главы: 04:45 — headings/структура; 12:03 — таблицы; 13:48 — изображения; 15:15 — styling.
- Карта использования: **одиночный `.typ`**, семантическая структура документа и ссылки на внешние изображения.
- Не про Tentex: не демонстрирует query API, безопасную распаковку ZIP или его извлечение. Bibliography глубже изучать по D-TYP-05, не считать полное покрытие этой темы доказанным данным уроком.

#### V-TYP-02 — Getting Started with Typst - Installing and First Usage (S01E01)
- Прямое видео: https://www.youtube.com/watch?v=84O9OMHnJU0
- Канал: **BamDone**; язык: EN; публикация: 2024-03-24.
- По описанию/извлечённому тексту: локальная установка на Mac через Homebrew, VS Code, папка проекта, `.typ`, preview/PDF, шаблоны Typst Universe и терминал/`typst init`.
- Карта использования: **локальная папка Typst**, исходник плюс assets/templates; фон для понимания того, что нужно сохранить при переносе проекта через ZIP.
- Не про Tentex: UI редактора не UI приложения; не заявлять, что ролик учит загрузке ZIP в Tentex или sandbox-компиляции. Windows/Linux и pinned CLI version требуют своей инструкции.

### SQLite / SQLAlchemy / FTS5 / BM25 — общая инфраструктура

#### D-DB-01 — SQLite FTS5 Extension
- URL: https://www.sqlite.org/fts5.html
- Источник: официальная документация SQLite; язык: EN.
- Объясняет: virtual tables, `MATCH`, tokenizers, prefix/phrase/NEAR, external content, auxiliary functions, `bm25()`, snippets и rank.
- Для владельца: полнотекстовый индекс не то же самое, что хранение исходных файлов или vector search. External-content индекс надо поддерживать согласованным с основной таблицей.
- Граница с Tentex: проверить наличие FTS5 в сборке, SQL создания индекса/триггеров и actual query. **У FTS5 BM25 меньший числовой score соответствует лучшему совпадению**; не применять направление сортировки из другой реализации BM25 без проверки. Параметры weighting/нормализации не считать произвольно настраиваемыми без изучения конкретного API.

#### D-DB-02 — SQLite — SQLAlchemy 2.0 Documentation
- URL: https://docs.sqlalchemy.org/en/20/dialects/sqlite.html
- Источник: официальная документация SQLAlchemy; язык: EN.
- Объясняет: SQLite dialect, DBAPI, transactions/sqlite3, типы, foreign keys, upsert, sync/async драйверы и ограничения.
- Граница с Tentex: ORM — слой доступа, не отдельный формат исходных документов и не автоматический полнотекстовый движок. Таблицы, миграции, commit/rollback и согласование FTS с документами изучать по коду приложения.

#### V-DB-01 — Mike Bayer: Introduction to SQLAlchemy - PyCon 2014
- Прямое видео: https://www.youtube.com/watch?v=P141KRbxVKc
- Канал: **PyCon 2014**; докладчик: **Mike Bayer**; язык: EN; длительность: 03:35:32; публикация: 2014-04-23 по часовому поясу канала (2014-04-24 UTC).
- По описанию: Core и ORM, фундаментальная модель взаимодействия библиотеки с SQL и базой данных. Конференционный учебный материал от автора SQLAlchemy.
- Карта использования: общий слой хранения/доступа для результатов **всех входных семейств**; отдельное чтение D-DB-01 нужно для FTS5/BM25.
- Не про Tentex: старый синтаксис не инструкция для SQLAlchemy 2.x. Не утверждать, что доклад обучает FTS5 или описывает схему базы приложения.



## 14. Как читать ссылки

Все ссылки на код ниже/выше закреплены на одном указанном коммите и диапазоне строк. Если в README или старом архитектурном документе написано иначе, для поведения этой версии приоритет у исполняемого кода. Отдельная сверка документации подготовлена в `pipeline-doc-audit.md`; она не означает, что файлы репозитория уже исправлены.
