import { useEffect, useMemo, useState } from "react";
import { Check, FileText, LibraryBig, Search } from "lucide-react";
import {
  attachLibraryMaterial,
  listLibraryMaterials,
  type LibraryMaterialDetailRead,
  type LibraryMaterialRead,
  type MaterialPurpose,
  type SourceRole,
} from "../../api/materials";
import {
  Button,
  ConfirmDialog,
  Dialog,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  Select,
} from "../ui";

const PURPOSE_OPTIONS: Array<{ value: MaterialPurpose; label: string; description: string }> = [
  { value: "study_source", label: "Учебный источник", description: "Материал, по которому занимаются" },
  { value: "exam_structure", label: "Список вопросов", description: "Из него собирается программа экзамена" },
  { value: "reference_answers", label: "Эталонные ответы", description: "Такой файл у проекта один" },
];

const ROLE_OPTIONS: Array<{ value: SourceRole; label: string }> = [
  { value: "main", label: "Основной" },
  { value: "additional", label: "Дополнительный" },
  { value: "reference", label: "Справочный" },
];

const STATUS_LABEL: Record<LibraryMaterialRead["status"], string> = {
  ready: "Текст готов",
  ready_to_process: "Текст не подготовлен",
  queued: "В очереди",
  processing: "Обрабатывается",
  paused: "На паузе",
  failed: "Ошибка обработки",
};

const SOURCE_LABEL: Record<LibraryMaterialRead["source_kind"], string> = {
  file: "Файл",
  text: "Текст",
  url: "Веб-страница",
  youtube: "YouTube",
  audio: "Аудио",
};

const STATUS_ORDER: Record<LibraryMaterialRead["status"], number> = {
  ready: 0,
  processing: 1,
  queued: 1,
  paused: 1,
  ready_to_process: 2,
  failed: 3,
};

type LoadMaterials = (signal?: AbortSignal) => Promise<LibraryMaterialRead[]>;
type AttachMaterial = (
  materialId: string,
  command: {
    project_id: string;
    display_name?: string | null;
    source_role: SourceRole;
    purposes: MaterialPurpose[];
  },
) => Promise<LibraryMaterialDetailRead>;

interface LibraryMaterialPickerDialogProps {
  open: boolean;
  projectId: string;
  title: string;
  purpose?: MaterialPurpose;
  multiple?: boolean;
  allowPurposeSelection?: boolean;
  existingStudySourceCount?: number;
  studyRoleMode?: "first-main" | "selected";
  defaultStudyRole?: SourceRole;
  answersMaterial?: { display_name: string } | null;
  onReplaceAnswers?: () => Promise<boolean>;
  onOpenChange: (open: boolean) => void;
  onAttached: (materials: LibraryMaterialRead[]) => void | Promise<void>;
  onCreateNew?: () => void;
  /** Dependency overrides keep the UI-kit example local and deterministic. */
  loadMaterials?: LoadMaterials;
  attachMaterial?: AttachMaterial;
}

function usageLabel(material: LibraryMaterialRead) {
  if (material.usage.length === 0) return "Не подключён к проектам";
  const names = material.usage.slice(0, 2).map((usage) => usage.project_name).join(", ");
  const rest = material.usage.length - 2;
  return rest > 0 ? `${names} и ещё ${rest}` : names;
}

function pageLabel(count: number | null) {
  if (count === null) return "число страниц неизвестно";
  return `${count} стр.`;
}

export function LibraryMaterialPickerDialog({
  open,
  projectId,
  title,
  purpose: fixedPurpose,
  multiple = false,
  allowPurposeSelection = false,
  existingStudySourceCount = 0,
  studyRoleMode = "selected",
  defaultStudyRole = "main",
  answersMaterial = null,
  onReplaceAnswers,
  onOpenChange,
  onAttached,
  onCreateNew,
  loadMaterials = listLibraryMaterials,
  attachMaterial = attachLibraryMaterial,
}: LibraryMaterialPickerDialogProps) {
  const [materials, setMaterials] = useState<LibraryMaterialRead[] | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [purpose, setPurpose] = useState<MaterialPurpose>(fixedPurpose ?? "study_source");
  const [studyRole, setStudyRole] = useState<SourceRole>(defaultStudyRole);
  const [error, setError] = useState("");
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [replaceOpen, setReplaceOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setMaterials(null);
    setError("");
    setRowErrors({});
    void loadMaterials(controller.signal)
      .then((result) => setMaterials(result))
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setMaterials([]);
        setError(caught instanceof Error ? caught.message : "Не удалось загрузить Библиотеку");
      });
    return () => controller.abort();
  }, [open, reloadKey, loadMaterials]);

  useEffect(() => {
    if (!open) return;
    setSelected([]);
    setQuery("");
    setPurpose(fixedPurpose ?? "study_source");
    setStudyRole(defaultStudyRole);
  }, [open, fixedPurpose, defaultStudyRole]);

  const visible = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("ru");
    return [...(materials ?? [])]
      .filter((material) => !needle || material.original_name.toLocaleLowerCase("ru").includes(needle))
      .sort((left, right) => STATUS_ORDER[left.status] - STATUS_ORDER[right.status]
        || left.original_name.localeCompare(right.original_name, "ru"));
  }, [materials, query]);

  const allowsMultiple = purpose === "study_source" && multiple;
  const selectedCount = selected.length;

  function toggle(material: LibraryMaterialRead) {
    if (material.usage.some((usage) => usage.project_id === projectId) || busy) return;
    setRowErrors((current) => {
      const next = { ...current };
      delete next[material.id];
      return next;
    });
    setSelected((current) => {
      if (current.includes(material.id)) return current.filter((id) => id !== material.id);
      return allowsMultiple ? [...current, material.id] : [material.id];
    });
  }

  function roleFor(index: number): SourceRole {
    if (purpose !== "study_source") return "reference";
    if (studyRoleMode === "first-main") {
      return existingStudySourceCount + index === 0 ? "main" : "additional";
    }
    return studyRole;
  }

  async function performAttach() {
    setBusy(true);
    setError("");
    const attached: LibraryMaterialRead[] = [];
    const failures: Record<string, string> = {};
    for (const materialId of selected) {
      const material = materials?.find((item) => item.id === materialId);
      if (!material) continue;
      try {
        await attachMaterial(materialId, {
          project_id: projectId,
          source_role: roleFor(attached.length),
          purposes: [purpose],
        });
        attached.push(material);
      } catch (caught) {
        failures[materialId] = caught instanceof Error ? caught.message : "Не удалось подключить материал";
      }
    }
    if (attached.length > 0) {
      try {
        await onAttached(attached);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Материалы подключены, но список не обновился");
      }
      const attachedIds = new Set(attached.map((material) => material.id));
      setMaterials((current) => current?.map((material) => attachedIds.has(material.id)
        ? {
            ...material,
            usage: [...material.usage, {
              project_id: projectId,
              project_name: "Текущий проект",
              project_status: "active",
              display_name: material.original_name,
              source_role: roleFor(attached.findIndex((item) => item.id === material.id)),
              purposes: [purpose],
            }],
          }
        : material) ?? current);
    }
    const attachedIds = new Set(attached.map((material) => material.id));
    setSelected((current) => current.filter((id) => !attachedIds.has(id)));
    setRowErrors(failures);
    setBusy(false);
    if (Object.keys(failures).length === 0) onOpenChange(false);
  }

  function requestAttach() {
    if (purpose === "reference_answers" && answersMaterial && onReplaceAnswers) {
      setReplaceOpen(true);
      return;
    }
    void performAttach();
  }

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={onOpenChange}
        title={title}
        description="Подключение не копирует файл и не запускает готовую обработку заново."
        className="library-picker-dialog"
        footer={
          <>
            <Button variant="ghost" disabled={busy} onClick={() => onOpenChange(false)}>Отменить</Button>
            <Button disabled={busy || selectedCount === 0} onClick={requestAttach}>
              {busy ? "Подключаем…" : selectedCount > 1 ? `Подключить ${selectedCount}` : "Подключить"}
            </Button>
          </>
        }
      >
        {allowPurposeSelection && (
          <div className="library-picker-settings">
            <Field label="Использовать как" required>
              <Select
                ariaLabel="Назначение материала"
                value={purpose}
                options={PURPOSE_OPTIONS}
                onValueChange={(next) => {
                  const nextPurpose = (next ?? "study_source") as MaterialPurpose;
                  setPurpose(nextPurpose);
                  if (nextPurpose !== "study_source") setSelected((current) => current.slice(-1));
                }}
              />
            </Field>
            {purpose === "study_source" && (
              <Field label="Роль источника">
                <Select
                  ariaLabel="Роль источника"
                  value={studyRole}
                  options={ROLE_OPTIONS}
                  onValueChange={(next) => setStudyRole((next ?? "main") as SourceRole)}
                />
              </Field>
            )}
          </div>
        )}

        <label className="library-picker-search">
          <Search size={15} aria-hidden="true" />
          <span className="sr-only">Найти материал по названию</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Найти материал"
          />
        </label>

        {error && (
          <div className="library-picker-error">
            <ErrorState message={error} />
            {materials?.length === 0 && <Button variant="secondary" onClick={() => setReloadKey((current) => current + 1)}>Повторить</Button>}
          </div>
        )}
        {materials === null ? (
          <LoadingState label="Загружаем Библиотеку" />
        ) : materials.length === 0 ? (
          <EmptyState title="Библиотека пока пуста" icon={<LibraryBig size={24} aria-hidden="true" />}>
            <p>Загрузите новый файл — он сразу появится и в Библиотеке.</p>
            {onCreateNew && <Button variant="secondary" onClick={onCreateNew}>Загрузить новый файл</Button>}
          </EmptyState>
        ) : visible.length === 0 ? (
          <EmptyState title="Ничего не найдено">
            <p>Попробуйте изменить запрос.</p>
          </EmptyState>
        ) : (
          <div className="library-picker-list" aria-live="polite">
            {visible.map((material) => {
              const alreadyAttached = material.usage.some((usage) => usage.project_id === projectId);
              const checked = selected.includes(material.id);
              return (
                <button
                  type="button"
                  className={`library-picker-row${checked ? " is-selected" : ""}`}
                  key={material.id}
                  disabled={alreadyAttached || busy}
                  aria-pressed={checked}
                  onClick={() => toggle(material)}
                >
                  <span className="library-picker-check" aria-hidden="true">{checked && <Check size={13} />}</span>
                  <span className="library-picker-file"><FileText size={17} aria-hidden="true" /></span>
                  <span className="library-picker-copy">
                    <strong>{material.original_name}</strong>
                    <small>{SOURCE_LABEL[material.source_kind]} · {pageLabel(material.page_count)} · {STATUS_LABEL[material.status]}</small>
                    <small>{alreadyAttached ? "Уже в проекте" : usageLabel(material)}</small>
                    {rowErrors[material.id] && <small className="inline-error">{rowErrors[material.id]}</small>}
                  </span>
                </button>
              );
            })}
          </div>
        )}
        <p className="library-picker-selection" aria-live="polite">
          {selectedCount === 0 ? "Ничего не выбрано" : `Выбрано: ${selectedCount}`}
        </p>
      </Dialog>

      <ConfirmDialog
        open={replaceOpen}
        onOpenChange={setReplaceOpen}
        title="Заменить файл эталонных ответов?"
        confirmLabel="Заменить"
        onConfirm={async () => {
          if (!onReplaceAnswers || !(await onReplaceAnswers())) throw new Error("replacement_cancelled");
          await performAttach();
        }}
      >
        <p>
          Сейчас эталонные ответы берутся из «{answersMaterial?.display_name}».
          Прежний файл останется в проекте как учебный источник.
        </p>
        <p>Уже заполненные эталоны и привязки сохранятся.</p>
      </ConfirmDialog>
    </>
  );
}
