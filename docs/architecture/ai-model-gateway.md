# Шлюз внешних моделей: фактический контракт

Дата фиксации: 12.08.2026. Реализованы серверное ядро, типизированный клиент,
глобальные Параметры → ИИ и два первых потребителя. HTTP-контракт серверной части
после фронтенд-среза не менялся.

## Граница среза

Работают:

- одно OpenAI-совместимое текстовое подключение и заготовленное отдельное речевое;
- глобальный и ролевые выключатели, общие модели и ролевые переопределения;
- безопасное хранение ключей, каталог моделей, возможности, избранное и цены;
- локальный снимок USD/RUB, предварительная оценка, лимиты, журнал и exact-кэш;
- структурный `complete` и потоковый `stream` через единый `ModelGateway`;
- «Прибрать текст с ИИ» и «Разложить по разделам»;
- живой раздел Параметров → ИИ и краткий снимок моделей в глобальной панели.

Не реализованы и не имитируются: Ollama, fallback между провайдерами, автоматический
курс валют, OCR через модель, эмбеддинги, проходы 1/2, веб-поиск, STT/TTS, чат,
агенты и инструменты модели.

## Граница модуля

Consumer передаёт роль, сообщения, manifest состава, снимок источников и Pydantic-схему.
Он не читает ключ, URL, каталог, цену, лимиты или кэш.

```text
cleanup / grouping
        │ AiTextRequest(role, messages, schema, source fingerprint)
        ▼
ModelGateway
  resolve model → capability → hash/cache → estimate/limits
  → OpenAI-compatible transport → Pydantic validation
  → AiRun + usage/cost + optional cache
```

| Модуль | Ответственность |
|---|---|
| `app/ai/roles.py` | статический реестр ролей и допустимых параметров |
| `app/ai/credentials.py` | installation secret и Fernet |
| `app/ai/settings.py` | безопасные настройки и разрешение модели |
| `app/ai/provider.py` | production OpenAI transport и программируемый fake |
| `app/ai/catalog.py` | проверка соединения и локальный снимок `/models` |
| `app/ai/gateway.py` | preflight, кэш, лимиты, вызов, валидация и журнал |
| `app/ai/router.py` | глобальный HTTP раздела ИИ |
| `app/materials/ai_cleanup.py` | снимок, prompt, run и apply уборки |
| `app/projects/program_ai.py` | eligibility, prompt, валидация и apply группировки |

Production transport создаёт `AsyncOpenAI(base_url, api_key, timeout, max_retries=0)`.
Платный completion автоматически не повторяется. Каталог является бесплатной проверкой
соединения. Вызов структурного consumer передаёт strict JSON Schema и затем независимо
проверяет результат Pydantic-моделью Tentex.

## Роли и наследование модели

Зарегистрированы шесть стабильных ролей:

| Роль | Модальность | Возможность | Кэш | Сейчас вызывается |
|---|---|---|---|---|
| `material_text_cleanup` | text | structured output | exact | да |
| `exam_program_grouping` | text | structured output | exact | да |
| `exam_chat_reply` | text | streaming | none | шлюз готов, consumer позже |
| `exam_answer_judge` | text | structured output | exact | позже |
| `exam_chat_memory` | text | structured output | none | позже |
| `speech_transcription` | speech | audio transcription | content hash | позже |

Порядок разрешения:

```text
разрешённый request override → override роли → default модели модальности
```

Cleanup и grouping запрещают request override. Чатовые ответ и судья его разрешают.
`Auto` будущего интерфейса означает наследование, а не провайдерный роутер.

## Данные и миграция

Миграция `20260812_0011_ai_gateway.py` добавляет:

- `ai_settings` — singleton с выключателем, лимитами и локальным курсом;
- `ai_connections` — ровно `text` и `speech`, URL, ciphertext и default model;
- `ai_role_settings` — только пользовательские отклонения от реестра;
- `ai_model_catalog` — локальный снимок возможностей/цен и избранное;
- `ai_runs` — безопасный журнал каждого фактического или cache-вызова;
- `ai_cache_entries` — только проверенный структурный payload.

Денежные значения хранятся `Numeric`, а не `float`. Удалённая из нового каталога
модель не удаляется: `is_available=false`, поэтому старые запуски остаются читаемыми.
`AiRun` и кэш каскадно удаляются вместе с проектом; глобальные настройки остаются.

Миграция проверена на пустой базе и копии рабочей SQLite; в обоих случаях
`PRAGMA foreign_key_check` вернул пустой список.

## Секреты

Ключ провайдера шифруется Fernet до записи. Источник ключа шифрования:

1. `TENTEX_SECRET_KEY`, если задан;
2. иначе один раз созданный `<data_dir>/installation.secret`.

Файл создаётся через exclusive create и с правами владельца там, где ОС поддерживает
POSIX mode. API возвращает только `has_api_key`. Пустой `api_key` в обычном PUT ничего
не стирает; удаление возможно только отдельным DELETE. Несовпадение installation secret
даёт стабильный код `ai_secret_mismatch`.

Это защищает ключ при копировании одной SQLite, но не от процесса, который одновременно
получил базу и installation secret.

## Preflight, деньги и лимиты

До внешнего запроса проверяются:

1. глобальный выключатель и выключатель роли;
2. ключ, модель и обязательные возможности;
3. exact-кэш;
4. консервативная оценка токенов по UTF-8 и ролевой максимум ответа;
5. лимит операции и фактический расход текущего дня;
6. подтверждение неизвестной цены или большого контекста.

Цена каталога хранится в USD за токен. После ответа источником фактической стоимости
является `usage.cost` провайдера. Курс и его дата копируются в `AiRun`, поэтому изменение
локального курса не переписывает старые рублёвые суммы.

```text
estimated_rub = estimated_usd × current local rate
actual_rub    = usage.cost    × run rate snapshot
```

Cache-hit создаёт отдельный `AiRun(status=cached)`, увеличивает `hit_count`, имеет нулевую
новую стоимость и не прибавляется к дневному расходу. Неизвестная цена требует явного
`confirmed=true`, но не запрещает вызов.

## Ключ кэша и журнал

SHA-256 считается от канонического JSON:

- роль, модальность, разрешённая модель и параметры;
- версия prompt и JSON Schema;
- сообщения;
- project id и manifest;
- consumer-specific source fingerprint.

Для cleanup fingerprint содержит page id, revision, source hash и instruction hash.
Для grouping — `program_revision` и hash списка `node_id/type/title`.

`ai_runs.context_manifest` хранит id, ревизии, хеши, размеры и включённые поля. Полный
текст страницы, формулировки вопросов, пользовательская инструкция, provider response
и ключ в журнал не копируются. Проверенный JSON результата хранится только в локальном
кэше, потому что без него невозможно повторное применение.

## HTTP Параметров → ИИ

Префикс: `/api/settings/ai`.

| Метод | Путь | Результат |
|---|---|---|
| GET | `/` | полный безопасный снимок настроек, каталога, ролей и расхода сегодня |
| PUT | `/` | выключатель, лимиты, курс и дата |
| PUT | `/connections/{text|speech}` | label, URL, необязательный новый ключ, default model |
| DELETE | `/connections/{modality}/credential` | явное удаление ключа |
| POST | `/connections/{modality}/test` | бесплатный `/models`, нормализованный статус |
| POST | `/connections/{modality}/models/refresh` | заменить локальный снимок каталога |
| PUT | `/roles/{role}` | enabled, model override и разрешённые параметры |
| PUT | `/favorites` | заменить избранные текстовые модели |
| GET | `/runs` | до 1000 записей журнала с фильтрами project/role/from/to |
| GET | `/usage` | полный агрегат фактического расхода за период по ролям |

URL принимает только `http`/`https`, разрешает localhost и запрещает credentials внутри
URL. Сохранение настройки не тестирует соединение и не делает платный запрос.

## Фронтенд

`frontend/src/api/ai.ts` зеркалит безопасный OpenAPI-снимок: настройки, подключения,
каталог, роли, избранное, preflight, расход и нормализованные коды ошибок. Consumer-ручки
описаны рядом с прежними API Материалов и Проектов. Все запросы, которые могут ждать
модель, принимают `AbortSignal`; ciphertext ключа, полный prompt и ответ модели в клиент
не попадают.

`/setup?section=ai` использует серверный GET/PUT и разделяет:

- глобальный выключатель и расход сегодня;
- независимые подключения текста и речи, замену/удаление ключа, test и refresh каталога;
- модели модальностей по умолчанию, совместимые ролевые override и все шесть ролей;
- избранные текстовые модели, лимиты и локальный снимок USD/RUB.

Остальные внутренние разделы Параметров показывают честные пустые состояния. Глобальная
панель «Модели» читает тот же снимок и ведёт в `/setup?section=ai`. Ключ после сохранения
обозначается только `has_api_key`; его значение сервер не возвращает.

`AiCleanupPanel` и `AiGroupingDialog` открываются из прежних мест baseline и не меняют
источник до apply. Оба показывают точный manifest, preflight, подтверждение, ожидание с
отменой, расход/кэш, редактируемое предложение, stale-состояние и offline-путь. Cleanup
после apply предлагает восстановить исходный снимок обычной новой ревизией; grouping
переходит в общий undo Программы. На 390 px диалоги остаются внутри viewport, а сравнение
cleanup переключается вкладками. Экзаменационный чат в этот срез не входит и остаётся
заглушкой.

## Cleanup

Ручки:

```text
POST .../pages/{page}/ai-cleanup/preflight
POST .../pages/{page}/ai-cleanup
POST .../pages/{page}/ai-cleanup/apply
```

Пустая инструкция включает безопасный prompt: OCR/пунктуация/абзацы/заголовки/списки,
без добавления фактов, удаления пунктов, сокращения или пересказа. Явная инструкция
включается в запрос и hash, но в журнале остаются только её hash и размер.

Результат имеет поля `markdown`, `changes`, `warnings`. Run ничего не сохраняет в материал.
Apply повторно проверяет project, роль/run, page id, revision и source hash, затем вызывает
существующий `update_page_text`. Тот внутри транзакции создаёт новую полную ревизию,
перестраивает фрагменты и переносит картинки/привязки. Исходный файл не меняется.
Обычный `PUT` страницы позволяет интерфейсу сохранить исходный снимок новой ревизией как
«Отменить применение».

## Grouping

Ручки:

```text
POST /api/projects/{project}/program/ai-grouping/preflight
POST /api/projects/{project}/program/ai-grouping
POST /api/projects/{project}/program/ai-grouping/apply
```

Eligibility: активный exam-проект, плоский список, минимум шесть активных вопросов/задач,
без разделов и билетов. В модель уходят только название экзамена и `node_id/type/title`.

Сервер проверяет:

- 2–8 групп;
- уникальные названия по 2–8 слов;
- exact cover текущих node id без пропуска, дубля или чужого id;
- rationale для одиночной группы.

Apply принимает отредактированные пользователем названия и распределение, повторяет те же
проверки и одной транзакцией создаёт `origin_kind=model` разделы, переносит существующие
узлы, увеличивает `program_revision` один раз и пишет одно действие
`ai_program_grouping`. Стабильные id вопросов и все зависимые данные сохраняются.
Обычный общий undo возвращает прежних родителей/порядок и удаляет созданные разделы;
если состав или названия уже редактировались, возвращается `ai_grouping_undo_conflict`.

Сущности Плана подготовки в текущем ядре ещё нет, поэтому отдельный stale-флаг пока не
пишется. Когда План появится, он должен реагировать на уже существующий increment
`program_revision`, а не добавлять второй commit в grouping.

## Нормализованные ошибки

| Код | HTTP | Смысл |
|---|---:|---|
| `ai_disabled` | 422 | внешние модели выключены |
| `ai_role_disabled` | 422 | выключена функция |
| `ai_credentials_missing` | 422 | нет ключа модальности |
| `ai_model_not_configured` | 422 | модель не разрешилась |
| `ai_capability_unsupported` | 422 | модель отсутствует/несовместима |
| `ai_confirmation_required` | 422 | нужна явная подтверждённость |
| `ai_operation_limit` / `ai_daily_limit` | 422 | лимит остановил вызов до provider |
| `ai_invalid_credentials` | 401 | provider отверг ключ |
| `ai_rate_limited` | 429 | временное ограничение provider |
| `ai_provider_unavailable` | 503 | сеть или 5xx |
| `ai_timeout` | 504 | локальный timeout |
| `ai_invalid_structured_output` | 422 | ответ не прошёл Pydantic |
| `ai_cancelled` | 499 | поток отменён пользователем |

Provider body и текст исключения наружу не передаются.

## Проверки

```bash
cd backend
python -m ruff check .
python -m pytest -q
python scripts/check_ai_gateway.py
```

`check_ai_gateway.py` использует временную SQLite и fake provider: настройки → каталог →
локальный курс → cleanup preflight/run/cache/apply → grouping preflight/run/apply/undo →
лимит операции → global off → `foreign_key_check`.

Автоматические проверки не требуют сети и не тратят деньги. Ручной OpenRouter smoke
разрешён только при уже настроенном локальном ключе; ключ и полный ответ не печатаются.
