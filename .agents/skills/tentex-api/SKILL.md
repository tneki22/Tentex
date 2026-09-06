---
name: tentex-api
description: Правила бэкенда Tentex — слои, доменные ошибки, SQLite, воркер. Брать при правке эндпоинта, схемы, сервиса или миграции.
---

# API Tentex

Бэкенд живёт в `backend/app`, это FastAPI. Один пользователь, одна установка, всё офлайн. Контракт — по-русски, ошибки — с кодами.

Полные контракты этапов — в `docs/architecture/*.md`. Модель данных — `backend/app/models.py` и словарь терминов в `REQUIREMENTS.md`.

Подробности, которые нужны не каждый раз, лежат отдельно: **`references/data-and-worker.md`** — SQLite и сессии, хранилище файлов, воркер разбора, исходящие запросы. Открывай, когда правка их задевает.

## Слои — не смешивать

| Слой | Где | Отвечает за |
| --- | --- | --- |
| Роутер | `<домен>/router.py` | Только HTTP: пути, коды статусов, разбор тела. Тонкий. |
| Схемы | `<домен>/schemas.py` | Pydantic-модели запроса/ответа (`response_model`). |
| Сервис | `<домен>/service.py`, `answers.py`, `program.py`, … | Вся бизнес-логика и работа с БД. |

Домены: `projects`, `materials`, `bindings`, `ai` (шлюз моделей), `exam` (чат, попытки, оценки). Роутер не лазит в БД напрямую и не собирает логику — зовёт функцию сервиса. Сервис не знает про `Request`/`Response`.

Сессия приходит через зависимость: `session: Annotated[Session, Depends(get_session)]`. Не создавай `SessionLocal()` в обработчике запроса — это для воркера и скриптов. Единственное исключение — генератор `StreamingResponse`: зависимость закрывается до отправки тела, поэтому поток открывает свою сессию (пример и обоснование — `exam/router.py`).

## Ошибки — только доменные

Не бросай `HTTPException`. Бросай подкласс `ProjectDomainError` из `app/projects/errors.py`:

- `ProjectNotFoundError` → 404 `not_found`
- `ProjectConflictError` → 409 (по умолчанию `invalid_status_transition`)
- `ProjectInvariantError` → 422 `program_invariant`
- или свой `ProjectDomainError(detail, status=..., code=..., context=...)` с человекочитаемым русским `detail` и стабильным машинным `code`.

Единый handler в `main.py` превращает их в JSON `{detail, code, context}`. `code` — контракт с фронтендом, не переименовывай существующие. Необработанные исключения ловит глобальный обработчик и отдаёт `code: "internal_error"` — наружу текст исключения не утекает.

## Логирование

Настройка одна на процесс: `app/logging_config.py:configure_logging()`, зовётся из `create_app()` и `worker.main()`. Логгер бери по имени области: `logging.getLogger("tentex.http" | "tentex.worker" | ...)`. Уровень — `TENTEX_LOG_LEVEL` (дефолт `INFO`).

`print()` в `app/` нет (только в `scripts/`). Проглотил исключение — `log.exception(...)`, а не молча в поле БД. Тела файлов, содержимое материалов и личные тексты в лог не идут — только идентификаторы и метрики.

## Своё к общему циклу проверки

Общий порядок — в `CLAUDE.md`. Бэкенду сверх него:

- `cd backend && python -m ruff check .` — чисто (правила `E,F,I,UP,B,SIM`, line-length 100, py313).
- Затронул домен — прогони профильную проверку из `backend/scripts/`: `check_stage2` … `check_stage5`, `check_manual_binding`, `check_ai_gateway`, `check_exam_chat`, `check_library_workspace`.
- Меняешь контракт (путь, тело, код ответа, `code` ошибки) — обнови соответствующий `docs/architecture/*.md`.
- Новая настройка — только через `Settings` в `config.py` (префикс `TENTEX_`), не `os.environ` напрямую.
