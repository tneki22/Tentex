# Хранилище, резервные копии и перенос проектов

Фактический контракт раздела `/setup?section=storage` от 22.09.2026.

## Два формата

`.tentex-backup` заменяет всю установку. ZIP64 содержит согласованный снимок SQLite,
созданный Online Backup API, и `storage/` без `tmp/`. В manifest версии 1 находятся
версия Tentex и Alembic, размеры и SHA-256 каждого файла, число проектов, материалов и
retrieval-индексов. API-ключи, `installation.secret`, локальные OCR/embedding-модели,
Typst-пакеты, временные файлы и браузерные предпочтения не входят в копию. Путь папки
копий также не переносится между компьютерами.

`.tentex-project` добавляет один проект рядом с существующими. Пакет содержит manifest,
JSONL предметных таблиц и дедуплицированные файловые blobs. Профиль `personal` переносит
личный прогресс, профиль `share` исключает ответы, оценки, чаты, сеансы и подготовку.
UUID назначаются заново, материалы с совпавшим SHA-256 переиспользуются. Глобальный
dense-индекс не экспортируется; до его пересборки остаётся BM25.

## Копирование и расписание

Политика хранится в единственной строке `storage_settings`: автоматизация по умолчанию
выключена, время `03:00`, срок 7 дней. Worker раз в минуту проверяет пропущенный дневной
запуск. Ручные копии бессрочны; только `automatic` и `pre_restore` удаляются по сроку.

Создание копии — `BackgroundJob(kind=backup_create)`. После claim ставится файловый
maintenance-lock: новые задачи не берутся, HTTP-записи получают `503 maintenance_busy`,
а уже running-задачи заканчиваются. Затем создаются SQLite-снимок и ZIP. Проектные
экспорт/импорт также идут через общую очередь (`project_export`, `project_import`).

Ожидание покоя (`_wait_for_other_jobs`) идёт **до** `maintenance.lock`, не внутри
него: сама выдержка ничего не пишет и не трогает файлы, а другая `ai`-задача (сборка
индекса) может идти минутами из-за троттлинга внешнего провайдера. До 22.09.2026 лок
брался раньше выдержки и на всё это время глобальный HTTP-middleware (`main.py`)
отклонял **любую** запись во всей установке `503 maintenance_busy` — блокировка,
которая не была нужна, пока снимок ещё не начался. Лок теперь держится только на сам
снимок и упаковку.

Каждый переход состояния (`queued → creating → ready/failed`) обёрнут в `retry_on_locked`:
полоса `ai` держит до 8 параллельных писателей короткими транзакциями, и без ретраев
однократная запись иногда попадала в чужой busy-момент и валила всю копию с
`sqlite3.OperationalError: database is locked` (было воспроизведено и исправлено
22.09.2026, `backend/app/storage/service.py`).

Проверка и очистка (`storage_verify`, `storage_cleanup`) идут тем же путём:
`POST /api/storage/verify|cleanup` только ставит `BackgroundJob` и отвечает `202`
с `job_id`, а не выполняет проверку синхронно. `PRAGMA quick_check` по базе в
сотни мегабайт на Windows bind-mount под Docker Desktop занимает больше минуты —
синхронный вызов вешал HTTP-запрос без обратной связи (воспроизведено: 105с).
Готовый результат (`MaintenanceResult`) лежит в `checkpoint["result"]` задачи и
читается через `GET /api/background-jobs/{id}/result`, как и у остальных ролей.

## Восстановление

Загрузка сначала проверяет расширение, размер, ZIP path traversal/symlink, распакованный
лимит, manifest и SHA-256. Подтверждение запускает отдельную файловую операцию, потому что
её собственная строка не может надёжно жить в заменяемой базе.

Порядок: дождаться running-задач → создать `pre_restore` копию → извлечь в staging →
проверить SQLite → закрыть engine → атомарно переключить SQLite и `storage/` → выполнить
миграции и quick_check. `restore-journal.json` находится вне SQLite. Если процесс падает
после переключения, следующий запуск возвращает rollback-поколение; при обычной ошибке
тот же откат выполняется сразу. Страховочная копия регистрируется уже в восстановленной
базе.

## API

- `GET /api/settings/storage`, `PUT /api/settings/storage/backup-policy`;
- `GET|POST /api/backups`, `GET|DELETE /api/backups/{id}`, `GET /file`;
- `POST /api/storage/transfers`, `POST .../{id}/restore`, `GET /storage/restores/{id}`;
- `POST /api/projects/{id}/exports`, `POST .../{id}/import-project`, `GET .../{id}/file`;
- `POST /api/storage/verify`, `POST /api/storage/cleanup` — оба `202` + `job_id`.

Стабильные ошибки: `backup_incompatible`, `backup_corrupt`, `backup_too_large`,
`project_package_incompatible`, `project_package_corrupt`, `insufficient_space`,
`maintenance_busy`, `project_package_already_imported`, `restore_rolled_back`.
