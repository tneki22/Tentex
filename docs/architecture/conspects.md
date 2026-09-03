# Конспекты. «Мой конспект» и «Сводный конспект»

Личный WYSIWYG Markdown-конспект по теме — формулы, локальные изображения, безопасное автосохранение — и его сводное чтение в порядке Программы. Первая итерация: без цитат из Материалов и без экспорта (остаются в backlog, см. `REQUIREMENTS.md`, FR-U3).

## Граница

«Мой конспект» доступен в проектах `exam` и `textbook`. «Сводный конспект» и виртуальная категория «Конспекты» в Материалах — только в `exam`. Конспект привязывается лишь к изучаемым узлам `topic`/`subpoint`; разделы редактора не получают.

## Данные и целостность

`Conspect` хранится в таблице `conspects`, одна строка на пару `(project_id, program_node_id)` — составной первичный ключ, без отдельного `id`.

- составной внешний ключ ведёт на `(ProgramNode.project_id, ProgramNode.id)` с `ondelete=CASCADE`: удаление узла или всего проекта (`delete_program_tree`) каскадно уносит конспект и его изображения на уровне БД;
- `revision >= 1` после первого `PUT`; строки без сохранения не существует — отсутствующий конспект не материализуется как пустая запись;
- `content_markdown` сохраняется без `trim()`; пустота для сводки определяется на фронтенде как `content_markdown.trim().length === 0`, а на бэкенде — при построении summary теми же средствами (`.strip()`);
- максимальный размер — `1_048_576` байт UTF-8, проверяется Pydantic-валидатором `ConspectWrite`.

`ConspectImage` хранится в `conspect_images`, тот же составной внешний ключ и `ondelete=CASCADE`, плюс `size_bytes >= 0`. Изображение принадлежит паре `(project_id, program_node_id)`, а не самому конспекту: так PUT может безопасно удалить лишние изображения узла независимо от текста.

## Хранилище файлов

Изображения пишутся потоково через общий helper `materials/storage.py::store_namespaced_upload(namespace, owner_id, upload, *, allowed_suffixes, max_bytes, unsupported_message, error_code_prefix)` — выделен из прежнего `store_answer_upload`, который остался совместимой обёрткой над ним. Конспекты используют namespace `conspects`, путь `conspects/<project_id>/<uuid><suffix>`. Media type определяется по расширению файла (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`), присланный `content_type` не используется — в отличие от вложений к эталонам, где `content_type` доверенный.

Лимит — 20 МиБ на файл. При удалении проекта пути `ConspectImage` собираются до каскадного удаления строк, физические файлы и опустевший каталог `conspects/<project_id>` убираются после commit (`materials/storage.py::remove_storage_dir_if_empty`).

## API

| Метод | Маршрут | Назначение |
| --- | --- | --- |
| `GET` | `/api/projects/{project_id}/conspects/{node_id}` | личный конспект узла + список изображений |
| `PUT` | тот же маршрут | сохранить с оптимистической ревизией |
| `GET` | `/api/projects/{project_id}/conspects` | сводка по проекту (DFS-порядок, только непустые) |
| `POST` | `/api/projects/{project_id}/conspects/{node_id}/images` | загрузить изображение |
| `GET` | `/api/projects/{project_id}/conspect-images/{image_id}/file` | скачать изображение |
| `DELETE` | `/api/projects/{project_id}/conspect-images/{image_id}` | удалить изображение, если оно не упоминается в сохранённом тексте |

Отсутствующий конспект — не 404: `GET /conspects/{node_id}` возвращает `200`, пустой `content_markdown`, `revision=0`, `updated_at=null` и (возможные) изображения узла. Первый `PUT` принимает только `expected_revision=0` и создаёт строку с `revision=1`; дальнейшие требуют точного совпадения.

Ошибки: `project_read_only` (409, архивный/завершённый проект), `conspect_requires_study_node` (422, не `topic`/`subpoint`), `stale_conspect_revision` (409, конфликт ревизии; `context.current_revision` — актуальное значение), `conspect_summary_requires_exam_project` (409, сводка в `textbook`), `conspect_image_not_found` (422, чужой `retained_image_ids`), `conspect_image_in_use` (409, удаление изображения, упомянутого в сохранённом тексте), `conspect_image_unsupported`/`conspect_image_too_large`/`conspect_image_empty` (загрузка).

## Сводка

`list_conspect_summary` обходит дерево программы в DFS-порядке (сортировка соседей по `(sort_order, str(id))`, как в `program.py`), сначала нумерует все актуальные `topic`/`subpoint` из `is_in_current_program=true`, `is_archived=false`, а затем отбрасывает узлы без сохранённого текста. Поэтому `position` совпадает с реальным номером вопроса в Программе и сохраняет пропуски пустых конспектов.

## Фронтенд

`useConspect(projectId, nodeId)` — контроллер личного конспекта: `status` из `loading | ready | saving | saved | error | conflict`. Автосохранение отправляется через 800 мс после последней правки; каждая задача очереди (`queueRef`) несёт свой снимок `projectId/nodeId/markdown/retainedImageIds/expectedRevision`, поэтому ответ уже покинутого узла не может откатить состояние нового. На cleanup (смена узла или размонтирование) debounce отменяется, но неотправленный снимок ставится в очередь немедленно тем же механизмом. При `stale_conspect_revision` очередь останавливается, `flush()` начинает пробрасывать ошибку вызывающему — этим пользуется `ProjectWorkspace.selectNode`, чтобы не переключать тему при неудачном сохранении.

`ConspectEditor` монтирует Milkdown Crepe через `@milkdown/react` (`MilkdownProvider` + `Milkdown` + `useEditor`), ключ `${projectId}:${nodeId}:${hydrationVersion}` пересоздаёт редактор целиком при смене темы/проекта или после «Загрузить сохранённую версию». `ConspectSummary` использует отдельный readonly Crepe (`setReadonly(true)`), пересоздаваемый через `deps=[markdown]` у `useEditor` — без внешнего `key`, так как документ каждый раз один и тот же (сама сводка), просто с новым содержимым. Список вопросов над документом находится в закрытом по умолчанию `Disclosure` «Вопросы с конспектом · N».

Обе поверхности получают общий набор Crepe `featureConfigs` из `components/domain/conspectEditorText.ts`, включая `Crepe.Feature.Latex` и `katexOptions.throwOnError=false`: inline-формулы `$E=mc^2$` и блочные формулы с `$$` на отдельных строках отображаются через KaTeX и в редакторе, и в readonly-сводке. Самый надёжный ввод — пункт «Формула» в тулбаре или слэш-меню; однострочная запись `$$E=mc^2$$`, введённая как обычный абзац, остаётся текстом по правилам Markdown-парсера. Пакет не поставляет русских подписей (placeholder, тулбар, ссылка, слэш-меню, код-блок), поэтому строки заданы явно вместо английских по умолчанию. Цвет — только через `--crepe-*`, сопоставленные с токенами Tentex в `styles/conspects.css`; готовая тема пакета (`classic`/`nord`/`frame`, тёмные варианты) не подключается.

`components/domain/index.ts` **не** реэкспортирует `ConspectEditor`/`ConspectSummary` как значения (только типы) — сборка (Rolldown/Vite) явно предупреждает `INEFFECTIVE_DYNAMIC_IMPORT`, если оставить реэкспорт: барель импортируется эагерно почти всеми экранами и утаскивает Milkdown в стартовый бандл. Компоненты подключаются исключительно прямым `React.lazy(() => import("./ConspectEditor"))`, как в `ProjectWorkspace.tsx` и `Materials.tsx`; итоговый Milkdown-чанк — общий для обоих экранов, отдельный от `index-*.js`.

`ProjectWorkspace` хранит единственный `ConspectEditorHandle` (только один редактор конспекта может быть открыт: `openTab` находит существующую вкладку `conspect` в любой зоне вместо второй) и `conspectRefreshKey`, инкрементируемый в `onSaved` — так открытый рядом `ConspectSummary` узнаёт о новом сохранении. `?tab=conspect`/`?tab=summary` в URL открывает вкладку в первой/активной зоне (`sanitizeLayout`).

## Материалы: виртуальная категория

После первого непустого конспекта в экзаменационном проекте `MaterialCatalog` показывает секцию «Конспекты» → «Сводный конспект» (`/projects/{id}/materials?view=conspect-summary`). Это `discriminated state` по query-параметру `view`, не фиктивный `materialId`: существующие эффекты страницы/фрагментов уже гардированы через `if (!material) return` и не запускаются, `MaterialInspector` не рендерится тем же условием. Пункт не увеличивает счётчик «Все материалы» и скрывается из каталога, если поисковый запрос не входит в «Сводный конспект». Если последний конспект очищен, секция пропадает и активный `view=conspect-summary` заменяется `EmptyState` со ссылкой в Рабочую область.

## Проверка

```bash
cd backend
python -m pytest tests/test_conspects.py -q
python -m ruff check .
cd ..
npm run typecheck
npm run build
```

`test_conspects.py` покрывает: constraints составного FK и `CheckConstraint`, roundtrip GET/PUT в exam и textbook, инкремент ревизии и `stale_conspect_revision` без потери текста, запрет записи в архивный проект при разрешённом чтении, отказ для раздела и узла другого проекта, DFS-порядок и фильтры сводки, `conspect_summary_requires_exam_project`, upload/download/delete изображений с граничными случаями (неверный suffix, пустой файл, превышение 20 МиБ), сохранение retained IDs и физическое удаление лишних изображений, недоступность чужого изображения и очистку каталога изображений при удалении проекта.
