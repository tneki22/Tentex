import { useEffect, useState } from "react";
import {
  attachLibraryMaterial,
  type LibraryMaterialDetailRead,
  type MaterialPurpose,
  type SourceRole,
} from "../../api/materials";
import { listProjects, type ProjectSummary } from "../../api/projects";
import { Button, Dialog, ErrorState, Field, LoadingState, Select } from "../../components/ui";

const PURPOSES: Array<{ value: MaterialPurpose; label: string; description: string }> = [
  {
    value: "study_source",
    label: "Учебный источник",
    description: "Материал, по которому занимаются",
  },
  {
    value: "exam_structure",
    label: "Список вопросов",
    description: "Из него собирается программа экзамена",
  },
  {
    value: "reference_answers",
    label: "Эталонные ответы",
    description: "Такой файл у проекта один",
  },
];

const ROLES: Array<{ value: SourceRole; label: string }> = [
  { value: "main", label: "Основной" },
  { value: "additional", label: "Дополнительный" },
  { value: "reference", label: "Справочный" },
];

interface AddToProjectDialogProps {
  open: boolean;
  materialId: string;
  materialName: string;
  /** Проекты, где материал уже есть: второй раз подключать нечего. */
  attachedProjectIds: string[];
  onOpenChange: (open: boolean) => void;
  onAttached: (detail: LibraryMaterialDetailRead) => void;
}

/**
 * Подключение общего материала к проекту. Создаётся только связь: файл не
 * копируется и разбор не перезапускается.
 */
export function AddToProjectDialog({
  open,
  materialId,
  materialName,
  attachedProjectIds,
  onOpenChange,
  onAttached,
}: AddToProjectDialogProps) {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [role, setRole] = useState<SourceRole>("additional");
  const [purpose, setPurpose] = useState<MaterialPurpose>("study_source");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setError("");
    void listProjects(controller.signal)
      .then((all) => {
        const active = all.filter((project) => project.status === "active");
        setProjects(active);
        setProjectId((current) => current
          ?? active.find((project) => !attachedProjectIds.includes(project.id))?.id
          ?? null);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setError(caught instanceof Error ? caught.message : "Проекты не загрузились");
        setProjects([]);
      });
    return () => controller.abort();
  }, [open, attachedProjectIds]);

  const available = (projects ?? []).filter((project) => !attachedProjectIds.includes(project.id));

  async function attach() {
    if (!projectId) return;
    setBusy(true);
    setError("");
    try {
      const detail = await attachLibraryMaterial(materialId, {
        project_id: projectId,
        display_name: displayName.trim() || null,
        source_role: purpose === "study_source" ? role : "reference",
        purposes: [purpose],
      });
      setDisplayName("");
      onOpenChange(false);
      onAttached(detail);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось подключить материал");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Подключить к проекту"
      description="Создаётся только связь: файл не копируется и обработка не запускается заново."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Отменить</Button>
          <Button disabled={busy || !projectId} onClick={() => void attach()}>Подключить</Button>
        </>
      }
    >
      {error && <ErrorState message={error} />}
      {projects === null ? (
        <LoadingState label="Загружаем проекты" />
      ) : available.length === 0 ? (
        <p className="dialog-lead">
          {projects.length === 0
            ? "Активных проектов пока нет — создайте проект, чтобы подключить материал."
            : "Материал уже подключён ко всем активным проектам."}
        </p>
      ) : (
        <div className="materials-text-form">
          <Field label="Проект" required>
            <Select
              ariaLabel="Проект"
              value={projectId}
              options={available.map((project) => ({
                value: project.id,
                label: project.name ?? "Без названия",
              }))}
              onValueChange={setProjectId}
            />
          </Field>
          <Field label="Использовать как" required>
            <Select
              ariaLabel="Назначение материала"
              value={purpose}
              options={PURPOSES.map((item) => ({
                value: item.value,
                label: item.label,
                description: item.description,
              }))}
              onValueChange={(next) => {
                const nextPurpose = (next ?? "study_source") as MaterialPurpose;
                setPurpose(nextPurpose);
                setRole(nextPurpose === "study_source" ? "additional" : "reference");
              }}
            />
          </Field>
          {purpose === "study_source" && (
            <Field label="Роль источника">
              <Select
                ariaLabel="Роль источника"
                value={role}
                options={ROLES}
                onValueChange={(next) => setRole((next ?? "additional") as SourceRole)}
              />
            </Field>
          )}
          <Field label="Имя в проекте" hint={`По умолчанию — «${materialName}»`}>
            <input
              value={displayName}
              placeholder={materialName}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </Field>
        </div>
      )}
    </Dialog>
  );
}
