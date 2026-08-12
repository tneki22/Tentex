# API Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать бэкенду эксплуатационную зрелость — сквозное логирование, единый разбор необработанных ошибок, потоковую загрузку вложений и наблюдаемый воркер — не меняя внешних контрактов API.

**Architecture:** Логирование настраивается один раз при старте процесса (и API, и воркер) через `logging.config.dictConfig`. HTTP-слой получает middleware с request-id и таймингом и глобальный обработчик исключений, дополняющий существующий `ProjectDomainError`-handler. Загрузка вложений к эталонам переводится на тот же потоковый путь с обрубанием по размеру, что и материалы. Воркер логирует жизненный цикл задач с трейсами вместо молчаливого проглатывания.

**Tech Stack:** Python 3.13, FastAPI, Starlette middleware, стандартный `logging`, SQLAlchemy 2.x, SQLite (WAL), pytest, ruff.

## Global Constraints

- Python `target-version = py313`, ruff `line-length = 100`, правила `E, F, I, UP, B, SIM` (`backend/pyproject.toml`). Код обязан проходить `python -m ruff check .` из `backend/`.
- Настройки только через `pydantic-settings`, префикс `TENTEX_`, файл `.env` (`app/config.py`). Новые опции добавляются туда, а не читаются из `os.environ` напрямую.
- Внешние контракты API (пути, тела, коды ответов, `code`/`context` в ошибках) не меняются. Это рефакторинг наблюдаемости и надёжности, а не переработка API.
- Пользователь один, БД — один файл SQLite. Не вводить внешние брокеры, очереди, демоны логов. Логи — в stdout/stderr, как принято для локального `npm run dev`.
- Комментарии и пользовательские тексты — по-русски, в тон существующему коду. Тексты доменных ошибок из `app/projects/errors.py` и `app/materials/storage.py` не переписывать.
- Каждая задача завершается прогоном `python -m ruff check .` и относящихся к ней тестов, затем коммитом.

---

## File Structure

- `backend/app/logging_config.py` — **создать.** Единая точка настройки логирования (`configure_logging()`), вызывается из `main.create_app()` и `worker.main()`.
- `backend/app/config.py` — **изменить.** Добавить `log_level: str = "INFO"` и `log_json: bool = False`.
- `backend/app/main.py` — **изменить.** Вызвать `configure_logging()`, добавить middleware request-id/тайминга и глобальный `Exception`-handler.
- `backend/app/materials/storage.py` — **изменить.** Добавить потоковый помощник для вложений с лимитом на лету.
- `backend/app/projects/answers.py` — **изменить.** `add_attachment` принимает поток/временный путь вместо `bytes`.
- `backend/app/projects/router.py` — **изменить.** `add_answer_attachment` перестаёт делать `await file.read()`.
- `backend/app/materials/worker.py` — **изменить.** Логи жизненного цикла задач и тайминги, `exc_info` вместо молчаливого проглатывания.
- `backend/tests/test_attachment_upload.py` — **создать.** Стриминг и обрубание по размеру.
- `backend/tests/test_error_handler.py` — **создать.** Глобальный обработчик исключений и request-id.
- `README.md` — **изменить.** Убрать устаревшую фразу про отсутствие тестового фреймворка; добавить строку про `TENTEX_LOG_LEVEL`.

---

## Task 1: Центральный конфиг логирования

**Files:**
- Create: `backend/app/logging_config.py`
- Modify: `backend/app/config.py`
- Test: (проверяется в задачах 2 и 5 через реальные логи)

**Interfaces:**
- Produces: `configure_logging(level: str | None = None, *, json_logs: bool | None = None) -> None` — идемпотентна, читает значения из `settings`, если аргументы `None`. Логгеры приложения берутся как `logging.getLogger("tentex.<область>")`.
- Consumes: `app.config.settings.log_level`, `app.config.settings.log_json`.

- [ ] **Step 1: Добавить настройки в config**

В `backend/app/config.py`, внутри класса `Settings`, после `seed_demo_project`:

```python
    # Уровень корневого логгера приложения. Ниже INFO стоит опускать только при
    # отладке: DEBUG в SQLAlchemy очень многословен.
    log_level: str = "INFO"
    # JSON-строки в лог вместо человекочитаемых — на случай, если логи начнут
    # куда-то собираться. По умолчанию человекочитаемо: это локальный запуск.
    log_json: bool = False
```

- [ ] **Step 2: Написать `configure_logging`**

Создать `backend/app/logging_config.py`:

```python
import logging
from logging.config import dictConfig

from app.config import settings

_CONFIGURED = False


def configure_logging(level: str | None = None, *, json_logs: bool | None = None) -> None:
    """Настроить логирование один раз на процесс. Повторный вызов — no-op.

    Вызывается и из API (`create_app`), и из воркера (`worker.main`): у каждого
    свой процесс, поэтому конфиг нужен обоим, но внутри процесса — единожды.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    resolved_level = (level or settings.log_level).upper()
    use_json = settings.log_json if json_logs is None else json_logs
    fmt = (
        '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s",'
        '"msg":"%(message)s"}'
        if use_json
        else "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
    )
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"default": {"format": fmt}},
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                }
            },
            "root": {"handlers": ["console"], "level": resolved_level},
            "loggers": {
                # SQLAlchemy на INFO печатает каждый SQL — держим на WARNING.
                "sqlalchemy.engine": {"level": "WARNING"},
                "uvicorn.access": {"level": resolved_level},
            },
        }
    )
    _CONFIGURED = True
    logging.getLogger("tentex").debug("logging configured at %s", resolved_level)
```

- [ ] **Step 3: Проверить импорт и линт**

Run: `cd backend && python -c "from app.logging_config import configure_logging; configure_logging()" && python -m ruff check .`
Expected: без ошибок; в stderr одна строка про уровень при DEBUG (на INFO строки нет — это норма).

- [ ] **Step 4: Commit**

```bash
git add backend/app/logging_config.py backend/app/config.py
git commit -m "feat(api): центральный конфиг логирования"
```

---

## Task 2: Request-id, тайминг и глобальный обработчик ошибок

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_error_handler.py`

**Interfaces:**
- Consumes: `configure_logging` (Task 1), существующий `ProjectDomainError` и его handler.
- Produces: заголовок ответа `X-Request-ID` на каждом ответе; для необработанного исключения — ответ `500` с телом `{"detail": "...", "code": "internal_error", "request_id": "<uuid>"}` и залогированным трейсом.

- [ ] **Step 1: Написать падающие тесты**

Создать `backend/tests/test_error_handler.py`:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app


def _client_with_boom() -> TestClient:
    app: FastAPI = create_app()

    @app.get("/api/_boom")
    def _boom() -> None:
        raise RuntimeError("нарочно упали")

    return TestClient(app, raise_server_exceptions=False)


def test_request_id_header_present() -> None:
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_unhandled_exception_returns_clean_envelope() -> None:
    response = _client_with_boom().get("/api/_boom")
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert body["request_id"]
    # Текст исключения наружу не утекает.
    assert "нарочно упали" not in body["detail"]
```

- [ ] **Step 2: Прогнать — убедиться, что падает**

Run: `cd backend && python -m pytest tests/test_error_handler.py -v`
Expected: FAIL — нет заголовка `X-Request-ID` и нет чистого конверта на 500.

- [ ] **Step 3: Реализовать в `main.py`**

В `backend/app/main.py` добавить импорты вверху:

```python
import logging
import uuid

from app.logging_config import configure_logging
```

В начале `create_app()`, до создания `FastAPI(...)`:

```python
    configure_logging()
    log = logging.getLogger("tentex.http")
```

После `app.add_middleware(CORSMiddleware, ...)` добавить middleware:

```python
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000
            log.exception(
                "unhandled error %s %s rid=%s %.1fms",
                request.method,
                request.url.path,
                request_id,
                elapsed_ms,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "Внутренняя ошибка сервера",
                    "code": "internal_error",
                    "request_id": request_id,
                },
                headers={"X-Request-ID": request_id},
            )
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        log.info(
            "%s %s -> %s rid=%s %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            request_id,
            elapsed_ms,
        )
        return response
```

Добавить `import time` к импортам стандартной библиотеки вверху файла.

> Примечание: обработчик `ProjectDomainError` оставить как есть — доменные ошибки уже дают корректный статус и `code`; глобальный перехват в middleware ловит только то, что не поймано доменным handler'ом.

- [ ] **Step 4: Прогнать тесты — убедиться, что проходят**

Run: `cd backend && python -m pytest tests/test_error_handler.py -v && python -m ruff check .`
Expected: PASS, линт чист.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_error_handler.py
git commit -m "feat(api): request-id, тайминг запросов и глобальный обработчик ошибок"
```

---

## Task 3: Потоковая загрузка вложений к эталонам

**Files:**
- Modify: `backend/app/materials/storage.py`
- Modify: `backend/app/projects/answers.py:451` (`add_attachment`)
- Modify: `backend/app/projects/router.py` (`add_answer_attachment`)
- Test: `backend/tests/test_attachment_upload.py`

**Interfaces:**
- Produces: `store_answer_upload(project_id: str, upload: UploadFile, *, allowed_suffixes: set[str], max_bytes: int) -> tuple[str, str, int, str]` — возвращает `(relative_path, media_type, size, original_name)`; читает чанками по 1 МБ, при превышении `max_bytes` удаляет временный файл и бросает `ProjectDomainError(status=413, code="attachment_too_large")`; при неверном расширении — `status=422, code="attachment_unsupported"`; при нулевом размере — `status=422, code="attachment_empty"`.
- Consumes (в `answers.add_attachment`): новую сигнатуру, принимающую `UploadFile` вместо `bytes`.
- Существующие константы: `ATTACHMENT_SUFFIXES` и `MAX_ATTACHMENT_BYTES` в `answers.py` остаются источником правды для лимитов.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_attachment_upload.py`:

```python
import io

import pytest
from fastapi import UploadFile

from app.materials.storage import store_answer_upload
from app.projects.errors import ProjectDomainError

ALLOWED = {".txt", ".md", ".png"}


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(data))


@pytest.mark.asyncio
async def test_streams_small_file() -> None:
    rel, media, size, original = await store_answer_upload(
        "proj-1", _upload("note.txt", b"hello"), allowed_suffixes=ALLOWED, max_bytes=1024
    )
    assert size == 5
    assert original == "note.txt"
    assert rel.startswith("answers/proj-1/")


@pytest.mark.asyncio
async def test_rejects_oversize_before_full_buffer() -> None:
    big = b"x" * 5000
    with pytest.raises(ProjectDomainError) as err:
        await store_answer_upload(
            "proj-1", _upload("big.txt", big), allowed_suffixes=ALLOWED, max_bytes=1024
        )
    assert err.value.status == 413


@pytest.mark.asyncio
async def test_rejects_unknown_suffix() -> None:
    with pytest.raises(ProjectDomainError) as err:
        await store_answer_upload(
            "proj-1", _upload("evil.exe", b"x"), allowed_suffixes=ALLOWED, max_bytes=1024
        )
    assert err.value.status == 422
```

> Если `pytest-asyncio` не подключён, проверить `backend/tests/conftest.py`/`requirements-dev.txt`; при отсутствии — добавить `pytest-asyncio` в `requirements-dev.txt` и `asyncio_mode = "auto"` в конфиг pytest в рамках этой задачи.

- [ ] **Step 2: Прогнать — убедиться, что падает**

Run: `cd backend && python -m pytest tests/test_attachment_upload.py -v`
Expected: FAIL — `store_answer_upload` не существует.

- [ ] **Step 3: Реализовать `store_answer_upload` в `storage.py`**

В `backend/app/materials/storage.py` добавить (рядом со `store_answer_attachment`, переиспользуя стиль `store_upload`):

```python
async def store_answer_upload(
    project_id: str,
    upload: UploadFile,
    *,
    allowed_suffixes: set[str],
    max_bytes: int,
) -> tuple[str, str, int, str]:
    """Вложение к эталону: пишем потоком во временный файл и обрубаем на лету.

    В отличие от прежнего `await file.read()`, гигантский файл не попадает в
    память целиком — превышение ловится посреди потока и временный файл удаляется.
    """
    original_name = Path(upload.filename or "файл").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in allowed_suffixes:
        raise ProjectDomainError(
            "К ответу прикрепляются изображения, PDF, DOCX, TXT и MD",
            status=422,
            code="attachment_unsupported",
        )
    temporary_dir = settings.storage_dir / "tmp"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = temporary_dir / f"{uuid4().hex}{suffix}"
    size = 0
    try:
        with temporary_path.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise ProjectDomainError(
                        "Файл больше 20 МБ", status=413, code="attachment_too_large"
                    )
                target.write(chunk)
        if size == 0:
            raise ProjectDomainError("Файл пуст", status=422, code="attachment_empty")
        relative_path = Path("answers") / project_id / f"{uuid4().hex}{suffix}"
        final_path = settings.storage_dir / relative_path
        final_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path.replace(final_path)
        media_type = (
            upload.content_type
            or mimetypes.guess_type(original_name)[0]
            or "application/octet-stream"
        )
        return relative_path.as_posix(), media_type, size, original_name
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
```

- [ ] **Step 4: Перевести `answers.add_attachment` на `UploadFile`**

В `backend/app/projects/answers.py` заменить сигнатуру и тело `add_attachment` (строки ~451–480) так, чтобы принимать `UploadFile` и звать `store_answer_upload`. Импортировать `from fastapi import UploadFile` и заменить `store_answer_attachment` на `store_answer_upload` в импорте из `app.materials.storage`:

```python
async def add_attachment(
    session: Session, project_id: UUID, node_id: UUID, upload: UploadFile
) -> ReferenceAnswerAttachmentRead:
    _require_exam_project(session, project_id, writable=False)  # ранний отказ до чтения тела
    storage_path, media_type, size, original_name = await store_answer_upload(
        str(project_id),
        upload,
        allowed_suffixes=ATTACHMENT_SUFFIXES,
        max_bytes=MAX_ATTACHMENT_BYTES,
    )
    with session.begin():
        _require_exam_project(session, project_id, writable=True)
        _require_study_node(session, project_id, node_id)
        row = ReferenceAnswerAttachment(
            project_id=project_id,
            program_node_id=node_id,
            file_name=original_name,
            storage_path=storage_path,
            media_type=media_type,
            size_bytes=size,
            created_at=utc_now(),
        )
        session.add(row)
        session.flush()
        return ReferenceAnswerAttachmentRead.model_validate(row)
```

> `store_answer_attachment` (синхронная, для внутренних вызовов с уже готовыми `bytes`) оставить в `storage.py`, если на неё ссылается что-то ещё — проверить `grep -rn store_answer_attachment backend/app`. Если ссылок не осталось — удалить её.

- [ ] **Step 5: Обновить роутер**

В `backend/app/projects/router.py`, `add_answer_attachment`: убрать `data = await file.read()` и передавать сам `file`:

```python
async def add_answer_attachment(
    project_id: UUID,
    node_id: UUID,
    session: SessionDependency,
    file: Annotated[UploadFile, File()],
) -> ReferenceAnswerAttachmentRead:
    return await answers.add_attachment(session, project_id, node_id, file)
```

- [ ] **Step 6: Прогнать тесты и линт**

Run: `cd backend && python -m pytest tests/test_attachment_upload.py -v && python -m ruff check .`
Expected: PASS, линт чист.

- [ ] **Step 7: Commit**

```bash
git add backend/app/materials/storage.py backend/app/projects/answers.py backend/app/projects/router.py backend/tests/test_attachment_upload.py backend/requirements-dev.txt
git commit -m "feat(api): потоковая загрузка вложений к эталонам с обрубанием по размеру"
```

---

## Task 4: Наблюдаемость воркера

**Files:**
- Modify: `backend/app/materials/worker.py`
- Test: (проверяется прогоном `python backend/scripts/check_stage5.py` и ручным чтением логов)

**Interfaces:**
- Consumes: `configure_logging` (Task 1).
- Produces: логи `tentex.worker` на события `claim`/`finish`/`fail` с длительностью и `material_id`; трейс падения через `log.exception`.

- [ ] **Step 1: Подключить логгер и настройку**

В `backend/app/materials/worker.py` добавить вверху:

```python
import logging

from app.logging_config import configure_logging

log = logging.getLogger("tentex.worker")
```

В `main()`, сразу после `upgrade_database()` (в обеих ветках — до `run_once`), вызвать `configure_logging()`.

- [ ] **Step 2: Логировать захват задачи**

В `claim_task`, перед `return task` (после установки `RUNNING`):

```python
        log.info("claimed task=%s material=%s total=%s", task.id, task.material_id, task.total)
```

- [ ] **Step 3: Логировать успех и тайминг в `run_once`**

Переписать `run_once` так, чтобы мерить время `process_task`:

```python
def run_once() -> bool:
    with SessionLocal() as session:
        worker_id = _worker_id()
        task = claim_task(session, worker_id)
        if task is None:
            return False
        started = time.perf_counter()
        process_task(session, task)
        log.info(
            "processed task=%s material=%s %.1fms",
            task.id,
            task.material_id,
            (time.perf_counter() - started) * 1000,
        )
        return True
```

(`time` уже импортирован в файле.)

- [ ] **Step 4: Заменить молчаливое проглатывание в `process_task`**

В блоке `except Exception as error:` внутри `process_task`, первой строкой после `session.rollback()`:

```python
        log.exception("task failed material=%s: %s", task.material_id, error)
```

- [ ] **Step 5: Прогнать сквозную проверку и линт**

Run: `cd backend && python -m ruff check . && python scripts/check_stage5.py`
Expected: `stage 5 smoke check passed`; в логах видны строки `claimed`/`processed`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/materials/worker.py
git commit -m "feat(worker): логирование жизненного цикла задач и трейсы падений"
```

---

## Task 5: Общие рекомендации — аудит N+1, пагинация, README

Эта задача закрывает «общие рекомендации» из анализа. Часть — исследование с последующей точечной правкой; каждый под-пункт коммитится отдельно.

**Files:**
- Modify: `backend/app/bindings/search.py`, `backend/app/bindings/answers_link.py`, `backend/app/materials/service.py` (только там, где найден N+1)
- Modify: `README.md`

**Interfaces:**
- Не меняет сигнатуры эндпоинтов. Пагинация, если вводится, добавляется как необязательные query-параметры `limit`/`offset` с дефолтами, сохраняющими текущее поведение.

- [ ] **Step 1: Найти N+1**

Run: `cd backend && grep -rn "\.all()\|for .* in session" app/bindings app/materials/service.py`
Просмотреть каждый цикл: если внутри тела цикла идёт ещё один запрос к БД по `id` из строки — это N+1.

- [ ] **Step 2: Починить найденное через eager loading**

Для связей, по которым итерируемся, добавить `selectinload`:

```python
from sqlalchemy.orm import selectinload
# было: session.scalars(select(Material))
# стало:
session.scalars(select(Material).options(selectinload(Material.project_links)))
```

Точные связи подставить по `backend/app/models.py`. Если N+1 не найден — зафиксировать это в сообщении коммита и перейти к шагу 4 (правка не требуется).

- [ ] **Step 3: Замерить (если правка была)**

Run: `cd backend && python scripts/check_manual_binding.py`
Expected: проверка проходит, строка тайминга поиска не деградировала.

- [ ] **Step 4: Обновить README**

В `README.md`, раздел «Проверка»: убрать фразу «Тестового фреймворка пока нет…» — тесты в `backend/tests/` уже есть. Добавить в раздел запуска строку:

```markdown
Уровень логов — переменная `TENTEX_LOG_LEVEL` (по умолчанию `INFO`).
```

- [ ] **Step 5: Прогнать линт и закоммитить**

Run: `cd backend && python -m ruff check .`

```bash
git add backend/app README.md
git commit -m "perf+docs: аудит N+1, актуализация README и заметка про TENTEX_LOG_LEVEL"
```

---

## Self-Review

**1. Покрытие анализа:**
- Пункт 1 (логирование) → Task 1 + Task 2 (HTTP) + Task 4 (воркер). ✅
- Пункт 2 (глобальный обработчик ошибок) → Task 2. ✅
- Пункт 3 (потоковая загрузка вложений) → Task 3. ✅
- Пункт 4 (наблюдаемость/надёжность воркера) → Task 4. ✅
- Общие рекомендации (N+1, пагинация, README) → Task 5. ✅

**2. Плейсхолдеры:** код приведён целиком для каждого шага; исследовательские шаги (Task 5) явно допускают исход «правка не нужна» и требуют зафиксировать это.

**3. Согласованность типов:** `configure_logging` определена в Task 1 и потребляется в Task 2/4 с той же сигнатурой. `store_answer_upload` определена в Task 3 Step 3 и потребляется в Step 4 с тем же кортежем `(relative_path, media_type, size, original_name)`. `add_attachment` стала `async` — роутер в Step 5 её `await`-ит.

**Риски для исполнителя:**
- Проверить наличие `pytest-asyncio` до Task 3; при отсутствии — добавить в рамках Task 3 Step 1.
- Перед удалением `store_answer_attachment` — `grep` по репозиторию на оставшиеся ссылки.
- `UploadFile.read()` — корутина: все затронутые функции и вызовы должны быть `async`/`await`.

## Execution Handoff

Плана достаточно для передачи. Рекомендуемый порядок — строго по задачам 1→5: логирование первично, на него опираются HTTP-обработчик и воркер.
