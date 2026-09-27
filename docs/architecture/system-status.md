# Сводка «Состояние» и журнал сбоев

Панель «Состояние» в приборном блоке оболочки показывает здоровье установки. Код:
`backend/app/system/` (сервис, схемы, журнал), `frontend/src/app/SystemStatusWidget.tsx`,
`frontend/src/hooks/useSystemStatus.ts`. Интерфейс описан в `SCREENS.md`, раздел «Проекты».

## HTTP

| Метод и путь | Что делает |
| --- | --- |
| `GET /api/system/status` | Лёгкие независимые проверки, ничего не пишет в базу. Сам ответ значит, что API жив. |
| `POST /api/system/write-probe` | «Проверить»: `BEGIN IMMEDIATE` + `ROLLBACK` отдельным соединением с таймаутом 2 с, запись и удаление файла в `data/`. Возвращает `{ok, status}`. |

Пример ответа (сокращён):

```json
{
  "checked_at": "2026-09-27T09:04:11+00:00",
  "overall": "warning",
  "attention_count": 1,
  "items": [
    {"code": "backup_missing", "level": "warning", "section": "attention",
     "title": "Резервных копий ещё нет", "action": "создайте первую",
     "target": {"kind": "command", "label": "Создать копию", "href": null, "command": "create_backup"},
     "last_failure_at": null, "occurrences": null},
    {"code": "ai_disabled", "level": "info", "section": "capabilities",
     "title": "Внешние модели выключены", "action": "включите их, если нужны облачные функции",
     "target": {"kind": "link", "label": "ИИ", "href": "/setup?section=ai&subsection=overview", "command": null},
     "last_failure_at": null, "occurrences": null}
  ],
  "storage": {"used_bytes": 1837203456, "free_bytes": 214748364800, "total_bytes": 511101108224,
              "last_backup_at": null, "backup_in_progress": false,
              "automatic_enabled": false, "daily_time": "03:00", "retention_days": 7}
}
```

## Уровни, разделы и итог

- `danger` — серьёзный сбой, `warning` — замечание, `unknown` — проверить не удалось,
  `info` — нейтральная настройка, `ok` — проверено и работает.
- Строки `danger`/`warning`/`unknown` любого домена поднимаются в раздел `attention` и
  сортируются по серьёзности; остальные остаются в `storage` или `capabilities`.
- `overall`: `attention` («Нужна помощь»), если есть `danger`; `warning` («Есть замечания»),
  если есть любая строка `attention`; иначе `ok`. Неизвестное зелёным не считается.
- У строк одной причины (`external_off`, `ai_setup`, `database`, `integrity`, `worker`)
  остаётся самая серьёзная: облачное распознавание при выключенных моделях не звучит
  второй строкой рядом с «Внешние модели выключены».

## Коды строк

| Код | Уровень | Когда |
| --- | --- | --- |
| `database_missing` / `database_unavailable` | danger | Файла базы нет / короткое чтение не прошло. Зависящие от базы проверки сводятся в `dependent_unchecked`. |
| `database_locked`, `database_io`, `disk_full` | danger | Неснятый сбой узла `database` из журнала. Снимается успешной пробой записи. |
| `database_corrupt`, `storage_integrity` | danger | Узел `integrity`: журнал или итог проверки хранилища. Снимается только успешным `quick_check` фоновой проверки. |
| `worker_offline` | danger / warning | Пульс воркера старше 90 с; danger, если задачи ждут в очереди. |
| `jobs_failed`, `jobs_stuck` | warning | Непросмотренные упавшие задачи (кроме копий и проверки хранилища — у них свои строки); задача с лизом, истёкшим больше 2 мин назад. |
| `disk_low` | danger / warning | Свободно < 1 ГБ / < 5 ГБ или меньше размера следующей копии (база + исходники). |
| `backup_missing` | warning | Есть материалы или проекты, кроме примера, а готовой копии нет. Если копия уже ставится — `backup_in_progress` (info). |
| `backup_failed`, `backup_overdue` | warning | Последняя копия упала; автокопии включены, а готовой нет больше 48 ч. |
| `storage_verify_failed`, `storage_files_missing` | warning | Последняя проверка хранилища упала или не нашла файлы. |
| `backups_inside_data`, `storage_maintenance` | info | Копии достоверно лежат внутри `data/` (сравнение путей, а не `Path.drive`); идёт обслуживание. |
| `ai_disabled`, `ai_no_provider`, `ai_no_key`, `ai_no_text_model`, `ai_key_rejected`, `ai_limit_reached`, `ai_limit_near`, `ai_ready` | info / warning / ok | Внешние модели: первый недостающий шаг, отклонённый ключ, дневной лимит. |
| `ocr_not_ready`, `ocr_ready`, `ocr_fast_no_models`, `ocr_cloud_off` | warning / ok / info | Выбранный по умолчанию способ распознавания и облачный режим. |
| `search_semantic_off`, `search_semantic_ready` | info / ok | Есть ли активный смысловой индекс; поиск по словам сломанным не объявляется. |
| `<проверка>_unchecked` | unknown | Эта проверка упала; остальные продолжают. |

## Журнал сбоев

`data/diagnostics/events.jsonl` — независимый от SQLite, до ~400 последних строк. Строка
содержит только время, вид, код и источник:

```json
{"at": "2026-09-27T09:01:52+00:00", "kind": "failure", "code": "database_locked", "source": "worker"}
{"at": "2026-09-27T09:06:30+00:00", "kind": "recovered", "node": "database", "source": "api"}
```

- `failure` пишет обработчик логов `DiagnosticsHandler` (корневой логгер, уровень ERROR) по
  классификации цепочки исключения: `database is locked` → `database_locked`, `disk I/O error`
  → `database_io`, `database disk image is malformed` → `database_corrupt`, `ENOSPC` или
  `database or disk is full` → `disk_full`. Текст исключения, SQL и пути не сохраняются.
- `exhausted` пишет `retry_on_locked`, когда повторы кончились, и воркер при отложенной
  проверке расписания или продлении лиза. Одиночная серия не показывается; две и больше —
  устойчивая блокировка.
- `recovered` пишут проба записи (узел `database`) и успешный `quick_check` (узел
  `integrity`). Всё, что было по узлу раньше, в сводку не попадает.
- `data/diagnostics/worker.json` — пульс воркера раз в 15 с.

Тесты: `backend/tests/test_system_status.py`. Журнал тестов уходит во временную папку
(фикстура `isolated_diagnostics` в `conftest.py`).
