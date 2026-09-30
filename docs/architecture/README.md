# Фактические контракты Tentex

Документы здесь описывают уже реализованное поведение. `STATUS.md` говорит, где проект
сейчас, `PLAN.md` — что делать дальше, `REQUIREMENTS.md` — что требуется в целевом
продукте, `SCREENS.md` — текущий интерфейс. Для реализованной подсистемы авторитетны код,
его потребители/тесты и релевантный документ из этого индекса; контракт этапа остаётся
историческим срезом и не означает, что вся система по-прежнему находится на этом этапе.

| Подсистема | Актуальный документ | Проверка |
| --- | --- | --- |
| Ядро данных | `stage-2-core.md` | `check_stage2.py` |
| Память, процессы и контейнерный запуск | `resource-usage.md` | профильные pytest, `scripts/profile_resources.py`, Docker/Playwright |
| Проекты и Программа | `stage-3-live-projects.md` | `check_stage3.py` |
| Эталонные ответы | `stage-4-reference-answers.md` | `check_stage4.py` |
| Конвейер материалов | `stage-5-material-pipeline.md`; практический сквозной guide — `../../LIBRARY_FILE_PROCESSING.md` | `check_stage5.py` |
| Поиск и ручные привязки | `pre-stage-6-search-and-manual-binding.md` | `check_manual_binding.py` |
| Общий retrieval, RAG и гибридный поиск | `retrieval.md` | pytest (`test_retrieval.py`), typecheck/build |
| Просмотрщик и автопривязка | `materials-viewer-and-answers-autolink.md` | pytest |
| Шлюз внешних моделей | `ai-model-gateway.md` | `check_ai_gateway.py` |
| Провайдеры и модели | `ai-provider-model-settings.md` | pytest |
| Настройки распознавания | `ocr-settings.md` | pytest, `check_stage5.py` |
| Экзаменационный чат | `exam-chat.md` | `check_exam_chat.py` |
| Экзаменационный мастер | `exam-wizard-material-onboarding.md` | `check_stage5.py` |
| Глобальная Библиотека | `global-library-material-workspace.md` | `check_library_workspace.py` |
| Typst-материалы | `typst-materials.md` | `check_typst_material.py` |
| Оглавление источника (мастер учебника) | `textbook-outline.md` | pytest (`test_material_outline.py`) |
| Ручная программа учебника и импорт оглавлений | `textbook-program.md` | pytest (`test_textbook_program.py`) |
| Свободное изучение: мастер, программа по цели, подбор материалов Библиотеки, темы без материала; метаданные материалов | `free-study-wizard.md` | pytest (`test_free_study.py`, `test_material_suggestions.py`), `frontend/free-study-wizard.spec.ts`, `frontend/free-study-lessons.spec.ts` |
| Чат «Поиск в интернете» в Материалах: SearXNG, план запросов по программе, карточки источников; общие сессии проектных чатов | `source-search-chat.md` | pytest (`test_source_search_chat.py`, `test_web_search.py`), `frontend/free-study-wizard.spec.ts` |
| Конспекты | `conspects.md` | pytest |
| Уроки: быстрый урок, чтение, ручной редактор, массовая подготовка и прохождение | `lessons.md` | pytest (`test_lessons.py`, `test_lesson_editing.py`, `test_lesson_progress.py`), typecheck/build |
| Планирование готовых уроков и активное время учебника | `lesson-planning.md` | pytest (`test_lesson_planning.py`), typecheck, сценарий браузера |
| Карточки и сохраняемый сеанс | `cards.md` | pytest, миграции, typecheck/build |
| Фоновые операции | `background-jobs.md` | pytest |
| Хранилище, резервные копии и перенос проектов | `storage-backups.md` | pytest (`test_storage_backups.py`), `check_storage_backups.py` |
| Сводка «Состояние», журнал сбоев и пульс воркера | `system-status.md` | pytest (`test_system_status.py`) |
| Потребление ресурсов и результаты комплексного аудита | `resource-usage.md`, `resource-audit.md` | pytest, живые замеры из отчётов |
| Проход 2: данные, публикация и жизненный цикл | `coverage-pass-two.md` | pytest (`test_coverage*.py`), `check_coverage.py` |
| Моя подготовка: текущие данные, расчёты, экран и интеграции | `my-preparation.md` | профильные pytest, миграции, typecheck/build |
| Моя подготовка: инвентарь текущих и совместимых функций | `my-preparation-functions.md` | — |

`my-preparation-interface.md` содержит целевой проект интерфейса и отдельное дополнение
о реализованных изменениях от 05.09.2026. Текущий фактический контракт —
`my-preparation.md`: блоки не пересекаются, назначения задаются календарём, а
автоматическое открытие закрывает назначение только после «Начать день».
Оставшиеся реализации SM-2 относятся к совместимости и не задают новый интерфейс.

`ai-provider-model-settings.md` заменяет старую модель двух жёстких подключений из
`ai-model-gateway.md`. Если историческая граница говорит «не входит в этап», проверяй
этот индекс: функция могла появиться позже.

Пользовательский путь, примеры и схемы прохода 2 — в
[`docs/pass-two-explained.md`](../pass-two-explained.md). Точный контракт остаётся в
`coverage-pass-two.md`.

Режим распознавания «Учебник» (GPU-контур) снят при стабилизации экзамена — история
и путь возврата в `docs/archive/gpu-ocr-textbook.md`, тег `gpu-ocr-last`. Из режимов
разбора остались `fast` (локальный PP-OCRv5) и `cloud` (внешняя зрительная модель
через шлюз, включён 04.09.2026); документы выше отражают только их.
