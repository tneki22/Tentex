# Архив: GPU-режим распознавания «Учебник»

Снят при резке функций на стабилизации экзамена (защита в декабре 2026, ограниченные
часы — контекст в `AGENTS.md`). Код на момент снятия зафиксирован тегом `gpu-ocr-last`
(коммит `55c5568`). Ниже — что это было, почему убрано и как вернуть при необходимости.

## Что делал режим

Второй (из пяти задуманных) режим распознавания материалов — «Учебник»: разбор страницы
целиком на выделенном GPU-сервисе вместо CPU-разбора обычным текстом.

- **PP-DocLayout_plus-L** размечал страницу и находил формулы отдельным классом
  разметки.
- **PP-FormulaNet Plus M** переводил найденные формулы в LaTeX.
- **PP-OCRv5** читал обычный текст тем же движком, что и режим «Быстро».
- Распознавание сетки таблиц было сознательно выключено — так единственный
  профиль укладывался в 8 ГБ видеопамяти; таблица оставалась обычным текстом.

Один профиль под одну конфигурацию железа: видеокарта NVIDIA с 8 ГБ памяти,
переменная `TENTEX_TEXTBOOK_EXECUTOR=formulas` в `docker-compose.yml`.

## Почему убран

- Контур ни разу не собирался на этой машине — ни у автора, ни в CI.
- ~1300 строк кода и 43 теста обслуживали функцию без работающего пайплайна.
- До защиты в декабре 2026 остаётся ограниченное число часов; резать нужно то,
  что не показывает демонстрируемый результат (`AGENTS.md`: «Этап заканчивается
  тем, что можно показать»).

## Из каких файлов состоял

### Целиком

- `backend/app/ocr/service_control.py` (330 строк) — запуск и остановка GPU-сервиса
  кнопкой из экрана настроек через сокет Docker вместо ручной команды в терминале.
- `backend/app/ocr/docker_engine.py` (193 строки) — тонкая обёртка над Docker Engine
  API, которую использовал `service_control`.
- `backend/app/ocr/hardware.py` (260 строк) — определение железа (GPU, видеопамять,
  Docker) для панели готовности на экране настроек.
- `backend/app/materials/parsers/textbook.py` (238 строк) — клиент парсера: отправка
  страницы на GPU-сервис, разбор ответа, кэш здоровья сервиса.
- Каталог `ocr_service/` (`Dockerfile`, `app.py` — 271 строка, `test_app.py` — 54
  строки) — сам GPU-сервис: FastAPI-обёртка над PaddleX-пайплайном, поднимаемая
  отдельным контейнером.
- `backend/scripts/check_textbook_gpu.py` (118 строк) — сквозная проверка этапа 5
  для GPU-ветки.
- `backend/tests/test_textbook_processing.py` (244 теста/строки) и
  `backend/tests/test_ocr_service_control.py` (158 строк) — юнит-тесты парсера и
  управления сервисом.

### Фрагментами

- `backend/app/ocr/router.py` — эндпоинты `POST /service/start`, `POST /service/stop`
  (см. «Эндпоинты» ниже).
- `backend/app/ocr/settings.py` — чтение/запись строки движка `textbook`, сборка
  окружения для контейнера (`textbook_environment`), проверка готовности
  (`_textbook_readiness`), вызов `service_control.start/stop`.
- `backend/app/ocr/engines.py` — запись `OcrEngineSpec("textbook", "Учебник", …,
  runtime="gpu_service")` в реестре `OCR_ENGINES` и константы
  `DEFAULT_TEXTBOOK_MODEL_ID`/`DEFAULT_TEXTBOOK_DEVICE`/`DEFAULT_TEXTBOOK_EXECUTOR`.
- `backend/app/ocr/catalog.py` — набор моделей `textbook-formulas` (профиль
  «Формулы и структура страницы», четыре репозитория Hugging Face,
  `min_vram_mb=6000`).
- `backend/app/ocr/schemas.py` — поля GPU-сервиса и готовности движка в
  `OcrEngineRead`/`OcrSettingsRead`.
- `backend/app/materials/parsers/native.py` — ветки `if mode == ParserMode.TEXTBOOK:
  yield textbook.parse_image(...)` в постраничном и потабличном разборе (строки
  ~616 и ~702 на момент снятия).
- `backend/app/models.py` — значение `ParserMode.TEXTBOOK = "textbook"` в перечислении
  режимов разбора.
- `backend/app/config.py` — настройки `textbook_ocr_url` и
  `textbook_ocr_timeout_seconds` (см. «Переменные окружения»).

### Фронтенд

- `frontend/src/screens/OcrSettingsSection.tsx` — панель железа, статус GPU-сервиса,
  кнопки «Запустить сервис» / «Остановить сервис».
- `frontend/src/api/ocr.ts` — клиентские вызовы `startService`/`stopService` и связанные
  типы.
- `frontend/src/styles/ocr.css` — стили панели железа и кнопок управления сервисом.

## Эндпоинты, которые занимал

Роутер `backend/app/ocr/router.py` подключён в `backend/app/main.py` с префиксом
`/api/settings/ocr` (`app.include_router(ocr_router)`, сам `router = APIRouter(prefix=
"/api/settings/ocr", ...)`). GPU-сервисом управляли:

- `POST /api/settings/ocr/service/start`
- `POST /api/settings/ocr/service/stop`

Остальные эндпоинты этого роутера (`GET`, `PUT`, `PUT /engines/{mode}`, установка/отмена/
удаление моделей) режима не касались напрямую и остаются рабочими для «Быстро».

## Переменные окружения

`backend/app/config.py` (`Settings`, префикс `TENTEX_`):

- `textbook_ocr_url: str = "http://127.0.0.1:8090"` → `TENTEX_TEXTBOOK_OCR_URL`
- `textbook_ocr_timeout_seconds: float = 180.0` → `TENTEX_TEXTBOOK_OCR_TIMEOUT_SECONDS`

`docker-compose.yml` переопределял адрес именем сервиса в контейнерах `api` и `worker`:
`TENTEX_TEXTBOOK_OCR_URL: http://textbook-ocr:8090`. Сам сервис `textbook-ocr` получал
`CUDA_VISIBLE_DEVICES=0`, `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` и
`TENTEX_TEXTBOOK_EXECUTOR=formulas`.

## Сервис в compose

`textbook-ocr` был единственным сервисом за профилем `profiles: ["textbook"]` — не
поднимался обычным `docker compose up`, только явным `--profile textbook`. Занимал порт
`8090`, монтировал `./data/models:/root/.paddlex` и
`./data/models/huggingface:/root/.cache/huggingface`, требовал GPU-резервацию
(`deploy.resources.reservations.devices` с `driver: nvidia`, `capabilities: [gpu]`).

Ради этого сервиса `api` монтировал `/var/run/docker.sock:/var/run/docker.sock` (чтобы
кнопки запуска/остановки могли управлять контейнером), а `worker` монтировал
`./data/models/huggingface:/root/.cache/huggingface` (кеш моделей, читаемых напрямую
через `transformers`).

**`./data/models:/root/.paddlex` в `worker` остаётся** — он нужен быстрому режиму
(PP-OCRv5 живёт там же, в `data/models/official_models/`).

## Миграции, которые его засеяли

- `backend/migrations/versions/20260825_0022_ocr_settings.py` — создаёт таблицы
  `ocr_settings`/`ocr_engine_configs` и засеивает по одной строке на движок; строка
  движка «Учебник» (`mode="textbook"`, `device="gpu"`, `executor="auto"`) — второй
  элемент `bulk_insert` в `ocr_engine_configs`, строки ~102–111.
- `backend/migrations/versions/20260827_0024_textbook_engine_model_id.py` — точечно
  поправляет `model_id`/`executor` этой же строки на актуальные константы
  `app.ocr.engines` (`PP-StructureV3 + PP-FormulaNet Plus M`, `formulas`), не трогая
  строку, если пользователь уже задал своё значение.

Снимает засеянную строку и режим `ParserMode.TEXTBOOK`
`20260901_0030_drop_textbook_ocr_mode.py`.

## Дословные команды восстановления

```bash
git show gpu-ocr-last:backend/app/ocr/service_control.py > backend/app/ocr/service_control.py
git checkout gpu-ocr-last -- ocr_service/
git diff gpu-ocr-last -- backend/app/ocr/
```

Первая команда достаёт один файл в его последнем виде на теге, не трогая рабочее
дерево вокруг. Вторая возвращает весь каталог сервиса разом. Третья показывает полный
diff по всему `backend/app/ocr/` между тегом и текущим состоянием — по нему видно, что
именно менять точечно в `router.py`, `settings.py`, `engines.py`, `catalog.py`,
`schemas.py`, а не восстанавливать эти файлы целиком (в них остались изменения после
снятия режима, которые терять нельзя).

## Принятый регресс

Формулы не распознаются ни одним режимом до появления облачного режима «Облако».
KaTeX-рендер уже готового LaTeX остаётся и работает — деградирует только
распознавание новых формул со страницы, не отображение ранее распознанных.
