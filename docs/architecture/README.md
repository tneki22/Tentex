# Фактические контракты Tentex

Документы здесь описывают уже реализованное поведение. `STATUS.md` говорит, где проект
сейчас, `PLAN.md` — что делать дальше. Контракт этапа остаётся историческим срезом и не
означает, что вся система по-прежнему находится на этом этапе.

| Подсистема | Актуальный документ | Проверка |
| --- | --- | --- |
| Ядро данных | `stage-2-core.md` | `check_stage2.py` |
| Проекты и Программа | `stage-3-live-projects.md` | `check_stage3.py` |
| Эталонные ответы | `stage-4-reference-answers.md` | `check_stage4.py` |
| Конвейер материалов | `stage-5-material-pipeline.md` | `check_stage5.py` |
| Поиск и ручные привязки | `pre-stage-6-search-and-manual-binding.md` | `check_manual_binding.py` |
| Просмотрщик и автопривязка | `materials-viewer-and-answers-autolink.md` | pytest |
| Шлюз внешних моделей | `ai-model-gateway.md` | `check_ai_gateway.py` |
| Провайдеры и модели | `ai-provider-model-settings.md` | pytest |
| Настройки распознавания | `ocr-settings.md` | pytest, `check_stage5.py` |
| Экзаменационный чат | `exam-chat.md` | `check_exam_chat.py` |
| Экзаменационный мастер | `exam-wizard-material-onboarding.md` | `check_stage5.py` |
| Глобальная Библиотека | `global-library-material-workspace.md` | `check_library_workspace.py` |

`ai-provider-model-settings.md` заменяет старую модель двух жёстких подключений из
`ai-model-gateway.md`. Если историческая граница говорит «не входит в этап», проверяй
этот индекс: функция могла появиться позже.
