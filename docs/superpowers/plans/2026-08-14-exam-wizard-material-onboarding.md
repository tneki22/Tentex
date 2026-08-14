# Exam Wizard Material Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Восстановить пятишаговый экзаменационный мастер этапа 1 и подключить загрузку вопросов, ответов и учебных материалов к реальным API этапов 2–5.

**Architecture:** Мастер сохраняет пользовательские выборы в `WizardDraft.state`, а файлы сразу прикрепляет к черновому `Project` как существующие `Material`/`ProjectMaterial`. Текст вопросов использует текущий draft-import, файл вопросов проходит текущий парсер и новый draft-safe import; ответы и учебные источники запускаются после активации проекта.

**Tech Stack:** React 19, TypeScript, Vite, обычный CSS на токенах, FastAPI, Pydantic, SQLAlchemy, SQLite/WAL, pytest.

## Global Constraints

- Визуальная структура и основные взаимодействия берутся из `ui-stage-1-baseline`.
- `ExamFormat` включает `unknown`; проект без точного списка остаётся экзаменационным и может иметь пустую Программу.
- Без векторной БД учебные материалы обещают только разбор, Просмотрщик, FTS-поиск и ручную привязку.
- Один канонический источник структуры, один материал эталонных ответов, несколько учебных источников.
- Новых таблиц, миграций, зависимостей и ролей внешнего ИИ нет.
- Русские тексты интерфейса, английские идентификаторы, цвета только через существующие токены.
- После фронтенд-изменений обязателен `docker compose restart web`.

---

### Task 1: Draft-safe импорт разобранного файла вопросов

**Files:**
- Modify: `backend/app/materials/schemas.py`
- Modify: `backend/app/materials/router.py`
- Modify: `backend/app/materials/service.py`
- Modify: `backend/app/projects/program.py`
- Create: `backend/tests/test_exam_wizard_materials.py`

**Interfaces:**
- Consumes: `parse_exam_program()`, `program.replace_draft_program()`, текущий `MaterialPurpose.EXAM_STRUCTURE`.
- Produces: `POST /api/projects/{project_id}/materials/{material_id}/exam-draft-import` с `ExamProgramDraftImportWrite(expected_draft_revision, expected_program_revision) -> ProgramChangeResult`.

- [ ] **Step 1: Написать падающий сервисный тест**

```python
def test_ready_exam_material_replaces_draft_program(session: Session) -> None:
    project, draft, material = make_ready_exam_draft(session, "1. Индексы\n2. Транзакции")
    result = service.import_exam_draft_from_material(
        session,
        project.id,
        material.id,
        ExamProgramDraftImportWrite(
            expected_draft_revision=draft.revision,
            expected_program_revision=project.program_revision,
        ),
    )
    assert [node.title for node in result.program.nodes] == ["Индексы", "Транзакции"]
    assert {node.origin_material_id for node in result.program.nodes} == {material.id}
```

- [ ] **Step 2: Запустить тест и подтвердить отсутствие нового контракта**

Run: `cd backend && python -m pytest tests/test_exam_wizard_materials.py -q`
Expected: FAIL на отсутствующих `ExamProgramDraftImportWrite` или `import_exam_draft_from_material`.

- [ ] **Step 3: Добавить request-схему и тонкий роутер**

```python
class ExamProgramDraftImportWrite(ApiModel):
    expected_draft_revision: int = Field(ge=0)
    expected_program_revision: int = Field(ge=0)
```

Роутер передаёт оба id и команду в сервис; бизнес-логики в роутере нет.

- [ ] **Step 4: Разрешить preview черновика и реализовать draft-import**

`_parsed_exam_from_material()` допускает draft, но по-прежнему требует экзаменационный вариант, назначение `exam_structure` и `MaterialState.READY`. Новый сервис после парсинга вызывает:

```python
program.replace_draft_program(
    session,
    project_id,
    expected_draft_revision=command.expected_draft_revision,
    expected_program_revision=command.expected_program_revision,
    parsed=parsed,
    material_id=material.id,
    material_name=link.display_name or material.original_name,
)
```

- [ ] **Step 5: Сохранить происхождение узлов**

`replace_draft_program()` получает необязательные `material_id` и `material_name`. Для файлового импорта каждый узел получает `origin_material_id=material_id` и `origin_note=f"Материал: {material_name}"`; текстовый импорт сохраняет текущее `origin_note="Вставленный текст"`.

- [ ] **Step 6: Проверить тесты и линтер**

Run: `cd backend && python -m pytest tests/test_exam_wizard_materials.py -q && python -m ruff check app tests/test_exam_wizard_materials.py`
Expected: PASS, `All checks passed!`.

- [ ] **Step 7: Закоммитить backend-вертикаль**

```bash
git add backend/app/materials backend/app/projects/program.py backend/tests/test_exam_wizard_materials.py
git commit -m "feat: import exam files into wizard drafts"
```

### Task 2: Живая панель добавления материалов

**Files:**
- Create: `frontend/src/screens/project-wizard/ExamMaterialUploadPanel.tsx`
- Modify: `frontend/src/api/materials.ts`

**Interfaces:**
- Consumes: `MaterialRead`, `MaterialPurpose`, `uploadMaterial()`, `detachMaterial()`, состояния фоновой обработки.
- Produces: `ExamMaterialUploadPanel` с режимами `files | text`, реальными строками материалов и событиями upload/remove/retry; `importExamDraftProgramFromMaterial(projectId, materialId, expectedDraftRevision, expectedProgramRevision)`.

- [ ] **Step 1: Исправить структурированные ошибки multipart-загрузки**

`uploadResponse()` передаёт в `ProjectApiError` серверные `code` и `context`, как общий `request()`:

```ts
throw new ProjectApiError(
  response.status,
  detail,
  typeof record.code === "string" ? record.code : undefined,
  record.context && typeof record.context === "object" ? record.context as Record<string, unknown> : undefined,
);
```

- [ ] **Step 2: Добавить клиент draft-import**

```ts
export const importExamDraftProgramFromMaterial = (
  projectId: string,
  materialId: string,
  expectedDraftRevision: number,
  expectedProgramRevision: number,
): Promise<ProgramChangeResult> => request(
  `${materialPath(projectId, materialId)}/exam-draft-import`,
  { method: "POST", body: JSON.stringify({ expected_draft_revision: expectedDraftRevision, expected_program_revision: expectedProgramRevision }) },
);
```

- [ ] **Step 3: Реализовать baseline-панель на реальных данных**

Компонент повторно использует классы `wizard-upload-panel`, `wizard-upload-head`, `wizard-dropzone`, `wizard-file-list`, `wizard-file-row`, `wizard-paste-area`. Один `<input type="file">` принимает PDF/DOCX/TXT/MD/изображения; `multiple` управляется пропом. Строка показывает `Загружен`, `В очереди`, `Обрабатывается`, `Готов` или текст ошибки и имеет доступную кнопку удаления.

- [ ] **Step 4: Проверить типы компонента**

Run: `npm run typecheck`
Expected: PASS.

### Task 3: Восстановленный пятишаговый ExamWizard

**Files:**
- Modify: `frontend/src/screens/project-wizard/ExamWizard.tsx`
- Modify: `frontend/src/hooks/useWizardDraft.ts`
- Modify: `frontend/src/styles/layout.css` только для недостающих состояний живого файла.

**Interfaces:**
- Consumes: `useProjectMaterials(projectId)`, `ExamMaterialUploadPanel`, `WizardDraft.state`, draft-import из Task 2.
- Produces: четыре формата, независимые карточки ответов/материалов, детерминированное мнение, динамический шаг загрузки и живое резюме источников.

- [ ] **Step 1: Расширить состояние и гидратацию**

`ExamForm.format` становится `ExamFormat`; добавляются `hasAnswers`, `hasTheory`, `primaryMode`, `answersMode`, `answersText`. Поля сохраняются в state как `has_answers`, `has_theory`, `input_modes`, `answer_text`. Для `unknown` `hasTheory` принудительно true.

- [ ] **Step 2: Вернуть четвёртую карточку и контекст шага 1**

Добавить `LibraryBig` и option `unknown` с честной подписью: источники сохранятся, а Программа останется пустой до официального списка. Существующие три карточки и паспорт не перестраивать.

- [ ] **Step 3: Вернуть интерактивные карточки шага 2**

Список считается основой для известных форматов; ответы и учебные материалы включаются независимо. Под сеткой `getMaterialOpinion()` выдаёт одну из согласованных формулировок спецификации. Для `unknown` показывается обязательная карточка материалов и подсказка про режим «Изучение по учебнику».

- [ ] **Step 4: Подключить upload panels шага 3**

- primary: один файл или текст, purpose `exam_structure`, role `reference`;
- answers: один файл или текст, purpose `reference_answers`, role `reference`;
- theory: несколько файлов, purpose `study_source`, role `main` для первого и `additional` для остальных.

Primary-файл сразу запускается в `fast`. Переход дальше ждёт `ready`, затем вызывает draft-import. Primary-текст вызывает текущий `controller.importExam()`. Текст ответов создаётся один раз как `createTextMaterial()`; уже прикреплённый answer material не дублируется.

- [ ] **Step 5: Сохранить редактирование Программы и паспорт**

Текущий `ReviewProgramTree`, ревизионные команды, прогноз нагрузки, конфликт другой вкладки и autosave остаются. Для пустой Программы итог показывает честный маршрут добавления официального списка позже.

- [ ] **Step 6: Запустить вспомогательные материалы после активации**

После `controller.activate()` материалы `reference_answers` и `study_source` со статусом `ready_to_process` запускаются через `startMaterialProcessing(..., "fast")`. Уже готовый материал ответов проходит `importMaterialReferenceAnswers()`. Ошибка постобработки не создаёт второй проект: показывается предупреждение с маршрутом в «Материалы», затем вызывается `onActivated`.

- [ ] **Step 7: Проверить frontend**

Run: `npm run typecheck && npm run build && npm run lint`
Expected: все команды завершаются с кодом 0.

- [ ] **Step 8: Закоммитить интерфейс**

```bash
git add frontend/src/api/materials.ts frontend/src/hooks/useWizardDraft.ts frontend/src/screens/project-wizard frontend/src/styles/layout.css
git commit -m "feat: restore exam wizard material onboarding"
```

### Task 4: Сквозная проверка и документы

**Files:**
- Modify: `backend/scripts/check_stage5.py`
- Modify: `SCREENS.md`
- Create: `docs/architecture/exam-wizard-material-onboarding.md`

**Interfaces:**
- Consumes: живой контракт Tasks 1–3.
- Produces: воспроизводимая проверка draft file import и документированный регрессионный аудит.

- [ ] **Step 1: Расширить smoke-сценарий этапа 5**

До активации `empty_project_id` создать текстовый `exam_structure`, запустить worker, вызвать preview и `exam-draft-import` с обеими ревизиями; проверить titles и `origin_material_id`. Затем активировать проект и проверить сохранность узлов. Отдельно оставить существующую проверку пустой активации как маршрут `unknown`.

- [ ] **Step 2: Обновить SCREENS.md**

В разделе мастера отметить живые назначения, состояния обработки, мнение системы, пустую Программу для `unknown` и переходы после фоновой ошибки.

- [ ] **Step 3: Зафиксировать исторический аудит**

В архитектурном документе таблицей сравнить `ui-stage-1-baseline`, `19717f3`, `2b399d5`, `a1ee118`, `fce8973`, `4a7d43f` и итог. Отметить сохранённые черновики, ревизии, учебниковую ветку, пустую активацию, автолинк ответов, Просмотрщик, поиск и привязки.

- [ ] **Step 4: Выполнить backend-проверки**

Run:

```bash
cd backend
python -m ruff check .
python -m pytest -q
cd ..
python backend/scripts/check_stage2.py
python backend/scripts/check_stage3.py
python backend/scripts/check_stage4.py
python backend/scripts/check_stage5.py
python backend/scripts/check_manual_binding.py
python backend/scripts/check_exam_chat.py
```

Expected: все проверки завершаются успешно.

- [ ] **Step 5: Выполнить визуальную проверку**

Run: `docker compose restart web`, затем пройти известный список с каждым сочетанием входов и `unknown` на широком окне и 390 px, в светлой/тёмной теме, клавиатурой и после перезагрузки черновика.

- [ ] **Step 6: Закоммитить проверку и контракт**

```bash
git add backend/scripts/check_stage5.py SCREENS.md docs/architecture/exam-wizard-material-onboarding.md
git commit -m "docs: verify restored exam wizard flow"
```
