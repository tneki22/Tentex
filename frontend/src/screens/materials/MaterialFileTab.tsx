import { ExternalLink, Save, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type {
  MaterialPurpose,
  MaterialRead,
  MaterialSourceKind,
  MaterialUpdateCommand,
  SourceRole,
} from "../../api/materials";
import { Button, Checkbox, ConfirmDialog, Field, Select, StatusBadge } from "../../components/ui";

const PURPOSE_OPTIONS: Array<{ value: MaterialPurpose; label: string }> = [
  { value: "study_source", label: "Учебный источник" },
  { value: "exam_structure", label: "Список вопросов" },
  { value: "reference_answers", label: "Эталонные ответы" },
];

const ROLE_OPTIONS = [
  { value: "main", label: "Основной", description: "Главный источник для изучения" },
  { value: "additional", label: "Дополнительный", description: "Расширяет основной материал" },
  { value: "reference", label: "Справочный", description: "Для ответов и пояснений" },
];

const SOURCE_LABEL: Record<MaterialSourceKind, string> = {
  file: "Загруженный файл",
  text: "Вставленный текст",
  url: "Веб-страница",
  youtube: "YouTube-транскрипт",
  audio: "Аудиофайл",
};

const STATUS_LABEL: Record<MaterialRead["status"], string> = {
  ready_to_process: "Ожидает обработки",
  queued: "В очереди",
  processing: "Обрабатывается",
  paused: "На паузе",
  ready: "Готов",
  failed: "Ошибка",
};

const STATUS_TONE: Record<
  MaterialRead["status"],
  "neutral" | "info" | "warning" | "success" | "danger"
> = {
  ready_to_process: "neutral",
  queued: "info",
  processing: "info",
  paused: "warning",
  ready: "success",
  failed: "danger",
};

interface MaterialDraft {
  displayName: string;
  purposes: MaterialPurpose[];
  sourceRole: SourceRole;
  priority: string;
  instruction: string;
}

function draftFrom(material: MaterialRead): MaterialDraft {
  return {
    displayName: material.display_name,
    purposes: [...material.purposes],
    sourceRole: material.source_role,
    priority: String(material.priority),
    instruction: material.instruction ?? "",
  };
}

function normalizedPurposes(purposes: MaterialPurpose[]): MaterialPurpose[] {
  return PURPOSE_OPTIONS.map((option) => option.value).filter((purpose) => purposes.includes(purpose));
}

function sameDraft(left: MaterialDraft, right: MaterialDraft): boolean {
  return left.displayName === right.displayName
    && left.sourceRole === right.sourceRole
    && left.priority === right.priority
    && left.instruction === right.instruction
    && normalizedPurposes(left.purposes).join("|") === normalizedPurposes(right.purposes).join("|");
}

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / 1024 ** 2).toFixed(1)} МБ`;
}

function dateLabel(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

interface MaterialFileTabProps {
  material: MaterialRead;
  answersMaterial: MaterialRead | null;
  busy: boolean;
  onSave: (command: MaterialUpdateCommand) => Promise<MaterialRead | null>;
  onRemove: () => void;
}

export function MaterialFileTab({
  material,
  answersMaterial,
  busy,
  onSave,
  onRemove,
}: MaterialFileTabProps) {
  const [draft, setDraft] = useState<MaterialDraft>(() => draftFrom(material));
  const [replaceOpen, setReplaceOpen] = useState(false);
  const initial = useMemo(() => draftFrom(material), [material]);

  useEffect(() => {
    setDraft(draftFrom(material));
    setReplaceOpen(false);
    // Фоновое обновление статуса не должно стирать ввод: сбрасываем только при смене файла.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [material.id]);

  const priority = Number(draft.priority);
  const nameError = draft.displayName.trim() ? undefined : "Введите название";
  const priorityError = !draft.priority.trim() || !Number.isInteger(priority) || priority < 0
    ? "Укажите целое число от 0"
    : undefined;
  const purposesError = draft.purposes.length ? undefined : "Выберите хотя бы одно назначение";
  const dirty = !sameDraft(draft, initial);
  const valid = !nameError && !priorityError && !purposesError;

  function togglePurpose(purpose: MaterialPurpose, checked: boolean) {
    setDraft((current) => ({
      ...current,
      purposes: checked
        ? [...current.purposes, purpose]
        : current.purposes.filter((item) => item !== purpose),
    }));
  }

  function command(replaceReferenceAnswers = false): MaterialUpdateCommand {
    return {
      display_name: draft.displayName.trim(),
      purposes: normalizedPurposes(draft.purposes),
      source_role: draft.sourceRole,
      priority,
      instruction: draft.instruction.trim() || null,
      replace_reference_answers: replaceReferenceAnswers || undefined,
    };
  }

  async function save(replaceReferenceAnswers = false) {
    const result = await onSave(command(replaceReferenceAnswers));
    if (result) setDraft(draftFrom(result));
    return result;
  }

  function requestSave() {
    const addsAnswers = draft.purposes.includes("reference_answers")
      && !material.purposes.includes("reference_answers");
    if (addsAnswers && answersMaterial && answersMaterial.id !== material.id) {
      setReplaceOpen(true);
      return;
    }
    void save();
  }

  return (
    <div className="materials-file-tab">
      <section className="materials-file-section">
        <div className="materials-file-section-head">
          <div>
            <h3>Настройки в проекте</h3>
            <p>Как этот файл используется именно в текущем проекте.</p>
          </div>
        </div>

        <div className="materials-file-form">
          <Field label="Название" error={nameError} required>
            <input
              value={draft.displayName}
              disabled={busy}
              onChange={(event) => setDraft((current) => ({
                ...current,
                displayName: event.target.value,
              }))}
            />
          </Field>

          <fieldset className={`materials-purpose-field ${purposesError ? "is-invalid" : ""}`}>
            <legend>Используется как</legend>
            <div className="materials-purpose-options">
              {PURPOSE_OPTIONS.map((option) => (
                <Checkbox
                  key={option.value}
                  label={option.label}
                  checked={draft.purposes.includes(option.value)}
                  disabled={busy}
                  onCheckedChange={(checked) => togglePurpose(option.value, checked)}
                />
              ))}
            </div>
            {purposesError && <small role="alert">{purposesError}</small>}
          </fieldset>

          <Field label="Роль источника" hint="Роль влияет на построение программы и порядок источников.">
            <Select
              value={draft.sourceRole}
              options={ROLE_OPTIONS}
              ariaLabel="Роль источника"
              disabled={busy}
              onValueChange={(value) => {
                if (value) setDraft((current) => ({ ...current, sourceRole: value as SourceRole }));
              }}
            />
          </Field>

          <Field label="Приоритет" hint="0 — раньше остальных источников той же роли." error={priorityError}>
            <input
              type="number"
              min="0"
              step="1"
              value={draft.priority}
              disabled={busy}
              onChange={(event) => setDraft((current) => ({
                ...current,
                priority: event.target.value,
              }))}
            />
          </Field>

          <Field label="Пояснение" hint="Например: брать отсюда теорию, а таблицы считать приложениями.">
            <textarea
              rows={4}
              value={draft.instruction}
              disabled={busy}
              onChange={(event) => setDraft((current) => ({
                ...current,
                instruction: event.target.value,
              }))}
            />
          </Field>

          <Button disabled={busy || !dirty || !valid} onClick={requestSave}>
            <Save size={14} /> Сохранить
          </Button>
        </div>
      </section>

      <section className="materials-file-section">
        <div className="materials-file-section-head">
          <div>
            <h3>Сведения о файле</h3>
            <p>Физический файл общий для установки и здесь не изменяется.</p>
          </div>
          <StatusBadge tone={STATUS_TONE[material.status]}>{STATUS_LABEL[material.status]}</StatusBadge>
        </div>

        <dl className="materials-file-details">
          <div><dt>Исходное имя</dt><dd>{material.original_name}</dd></div>
          <div><dt>Источник</dt><dd>{SOURCE_LABEL[material.source_kind]}</dd></div>
          <div><dt>Формат</dt><dd>{material.media_type}</dd></div>
          <div><dt>Размер</dt><dd>{sizeLabel(material.size_bytes)}</dd></div>
          <div><dt>Страницы</dt><dd>{material.page_count ?? "—"}</dd></div>
          <div><dt>Сканы</dt><dd>{material.scan_page_count}</dd></div>
          <div><dt>Низкое качество</dt><dd>{material.ocr_low_page_count || "нет"}</dd></div>
          <div><dt>Режим разбора</dt><dd>{material.parser_mode === "fast" ? "Быстро" : material.parser_mode === "textbook" ? "Учебник" : "Не запускался"}</dd></div>
          <div><dt>Добавлен в проект</dt><dd>{dateLabel(material.attached_at)}</dd></div>
          <div><dt>Загружен</dt><dd>{dateLabel(material.created_at)}</dd></div>
          <div><dt>Изменён</dt><dd>{dateLabel(material.updated_at)}</dd></div>
          {material.retrieved_at && <div><dt>Получен</dt><dd>{dateLabel(material.retrieved_at)}</dd></div>}
        </dl>

        {material.source_url && (
          <a className="materials-text-link" href={material.source_url} target="_blank" rel="noreferrer">
            Открыть исходную ссылку <ExternalLink size={13} aria-hidden="true" />
          </a>
        )}

        {material.outline.length > 0 && (
          <details className="materials-outline">
            <summary>Оглавление · {material.outline.length}</summary>
            <ol>{material.outline.map((item, index) => (
              <li
                key={`${item.page}-${index}`}
                style={{ paddingInlineStart: `${Math.max(0, item.level - 1) * 12}px` }}
              >
                <span>{item.title}</span><small>с. {item.page}</small>
              </li>
            ))}</ol>
          </details>
        )}

        <details className="materials-file-technical">
          <summary>Технические сведения</summary>
          <dl className="materials-file-details">
            <div><dt>ID</dt><dd><code>{material.id}</code></dd></div>
            <div><dt>MIME</dt><dd><code>{material.media_type}</code></dd></div>
            <div><dt>Ревизия</dt><dd>{material.active_parse_revision || "—"}</dd></div>
          </dl>
        </details>
      </section>

      <section className="materials-file-danger">
        <h3>Удаление из проекта</h3>
        <p>Общий файл останется в Библиотеке, но связи этого проекта будут сняты.</p>
        <Button variant="ghost" className="materials-remove-button" onClick={onRemove}>
          <Trash2 size={14} /> Убрать из проекта
        </Button>
      </section>

      <ConfirmDialog
        open={replaceOpen}
        onOpenChange={setReplaceOpen}
        title="Заменить файл эталонных ответов?"
        confirmLabel="Заменить"
        onConfirm={() => {
          void save(true).then((result) => {
            if (result) setReplaceOpen(false);
          });
        }}
      >
        <p>
          Сейчас эталонные ответы берутся из «{answersMaterial?.display_name}».
          С прежнего файла снимется это назначение, но сам файл останется в проекте.
        </p>
        <p>Уже созданные эталоны и привязки сохранятся.</p>
      </ConfirmDialog>
    </div>
  );
}
