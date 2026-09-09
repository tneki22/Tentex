# Фактические контракты Tentex

Документы здесь описывают уже реализованное поведение. `STATUS.md` говорит, где проект
сейчас, `PLAN.md` — что делать дальше, `REQUIREMENTS.md` — что требуется в целевом
продукте, `SCREENS.md` — текущий интерфейс. Для реализованной подсистемы авторитетны код,
его потребители/тесты и релевантный документ из этого индекса; контракт этапа остаётся
историческим срезом и не означает, что вся система по-прежнему находится на этом этапе.

| Подсистема | Актуальный документ | Проверка |
| --- | --- | --- |
| Ядро данных | `stage-2-core.md` | `check_stage2.py` |
| Проекты и Программа | `stage-3-live-projects.md` | `check_stage3.py` |
| Эталонные ответы | `stage-4-reference-answers.md` | `check_stage4.py` |
| Конвейер материалов | `stage-5-material-pipeline.md`; практический сквозной guide — `../../LIBRARY_FILE_PROCESSING.md` | `check_stage5.py` |
| Поиск и ручные привязки | `pre-stage-6-search-and-manual-binding.md` | `check_manual_binding.py` |
| Просмотрщик и автопривязка | `materials-viewer-and-answers-autolink.md` | pytest |
| Шлюз внешних моделей | `ai-model-gateway.md` | `check_ai_gateway.py` |
| Провайдеры и модели | `ai-provider-model-settings.md` | pytest |
| Настройки распознавания | `ocr-settings.md` | pytest, `check_stage5.py` |
| Экзаменационный чат | `exam-chat.md` | `check_exam_chat.py` |
| Экзаменационный мастер | `exam-wizard-material-onboarding.md` | `check_stage5.py` |
| Глобальная Библиотека | `global-library-material-workspace.md` | `check_library_workspace.py` |
| Typst-материалы | `typst-materials.md` | `check_typst_material.py` |
| Конспекты | `conspects.md` | pytest |
| Карточки и сохраняемый сеанс | `cards.md` | pytest, миграции, typecheck/build |
| Фоновые операции | `background-jobs.md` | pytest |
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

Режим распознавания «Учебник» (GPU-контур) снят при стабилизации экзамена — история
и путь возврата в `docs/archive/gpu-ocr-textbook.md`, тег `gpu-ocr-last`. Из режимов
разбора остались `fast` (локальный PP-OCRv5) и `cloud` (внешняя зрительная модель
через шлюз, включён 04.09.2026); документы выше отражают только их.
