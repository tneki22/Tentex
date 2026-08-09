import { useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";
import { Link } from "react-router";
import { Archive, ArrowDown, ArrowUp, GripVertical, RotateCcw, Trash2 } from "lucide-react";
import {
  archiveProject,
  deleteProject,
  listProjects,
  restoreProject,
  saveProjectOrder,
  type ProjectSummary,
} from "../api/projects";
import { ProjectChip } from "../components/domain";
import type { ProjectColor, ProjectIconName } from "../components/domain";
import {
  Button,
  ConfirmDialog,
  Disclosure,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHead,
} from "../components/ui";

const icon = (value: ProjectSummary["icon"]): ProjectIconName => value ?? "graduation-cap";
const color = (value: number | null): ProjectColor => (value && value >= 1 && value <= 8 ? value : 1) as ProjectColor;

export function Projects() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [operationError, setOperationError] = useState("");
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [archiveCandidate, setArchiveCandidate] = useState<ProjectSummary | null>(null);
  const [deleteCandidate, setDeleteCandidate] = useState<ProjectSummary | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const orderQueueRef = useRef<Promise<void>>(Promise.resolve());
  const orderGenerationRef = useRef(0);

  async function load(signal?: AbortSignal) {
    setLoading(true);
    setLoadError("");
    try {
      setProjects(await listProjects(signal));
    } catch (error) {
      if (signal?.aborted) return;
      setLoadError(error instanceof Error ? error.message : "Не удалось загрузить проекты");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, []);

  const active = [...projects]
    .filter((project) => project.status === "active")
    .sort((left, right) => left.sort_order - right.sort_order);
  const inactive = projects.filter((project) => project.status !== "active");

  function persistOrder(next: ProjectSummary[]) {
    const generation = ++orderGenerationRef.current;
    setProjects((current) => [
      ...next.map((project, index) => ({ ...project, sort_order: index })),
      ...current.filter((project) => project.status !== "active"),
    ]);
    setOperationError("");
    orderQueueRef.current = orderQueueRef.current
      .catch(() => undefined)
      .then(async () => {
        try {
          const saved = await saveProjectOrder(next.map((project) => project.id));
          if (orderGenerationRef.current === generation) {
            setProjects((current) => [...saved, ...current.filter((project) => project.status !== "active")]);
          }
        } catch (error) {
          if (orderGenerationRef.current === generation) {
            setOperationError(error instanceof Error ? error.message : "Не удалось сохранить порядок");
            await load();
          }
        }
      });
  }

  function moveProject(projectId: string, targetIndex: number) {
    const from = active.findIndex((project) => project.id === projectId);
    if (from < 0 || targetIndex < 0 || targetIndex >= active.length || from === targetIndex) return;
    const next = [...active];
    next.splice(targetIndex, 0, next.splice(from, 1)[0]);
    persistOrder(next);
  }

  function onDrop(event: DragEvent<HTMLElement>, targetId: string) {
    event.preventDefault();
    if (draggedId) moveProject(draggedId, active.findIndex((project) => project.id === targetId));
    setDraggedId(null);
  }

  async function archiveSelected() {
    if (!archiveCandidate) return;
    setBusyId(archiveCandidate.id);
    setOperationError("");
    try {
      await archiveProject(archiveCandidate.id);
      setArchiveCandidate(null);
      await load();
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : "Не удалось архивировать проект");
    } finally {
      setBusyId(null);
    }
  }

  async function restore(project: ProjectSummary) {
    setBusyId(project.id);
    setOperationError("");
    try {
      await restoreProject(project.id);
      await load();
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : "Не удалось вернуть проект");
    } finally {
      setBusyId(null);
    }
  }

  async function deleteSelected() {
    if (!deleteCandidate) return;
    setBusyId(deleteCandidate.id);
    setOperationError("");
    try {
      await deleteProject(deleteCandidate.id);
      setDeleteCandidate(null);
      await load();
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : "Не удалось удалить проект");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) return <div className="screen"><LoadingState label="Загружаем проекты" /></div>;
  if (loadError) {
    return (
      <div className="screen">
        <ErrorState message={loadError} />
        <Button onClick={() => void load()}>Повторить загрузку</Button>
      </div>
    );
  }

  return (
    <div className="screen">
      <PageHead title="Проекты" actions={<Link className="primary-button" to="/projects/new">Новый проект</Link>} />

      {operationError && <p className="inline-error" role="alert">{operationError}</p>}

      {active.length === 0 ? (
        <EmptyState title="Активных проектов пока нет">
          <p>Создайте экзаменационный проект или сохраните программу учебника как черновик.</p>
          <div>
            <Link className="primary-button" to="/projects/new?track=exam">Создать экзаменационный проект</Link>
            <Link className="secondary-button" to="/projects/new?track=textbook">Начать по учебнику</Link>
          </div>
        </EmptyState>
      ) : (
        <div className="dash-grid">
          {active.map((project, index) => (
            <article
              className={`dash-card ${draggedId === project.id ? "is-dragging" : ""}`.trim()}
              key={project.id}
              onDragEnd={() => setDraggedId(null)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => onDrop(event, project.id)}
            >
              <div className="dash-card-id">
                <ProjectChip icon={icon(project.icon)} color={color(project.color)} />
                <h2 className="dash-card-name">{project.name}</h2>
              </div>
              <div className="dash-card-actions" aria-label={`Действия для проекта «${project.name}»`}>
                <Link className="dash-card-action" to={`/projects/${project.id}`}>Продолжить изучение</Link>
                <button className="dash-card-action" disabled title="Повторения появятся на этапе 9">Повторить</button>
              </div>
              <div className="dash-card-order" aria-label="Порядок и архив">
                <span
                  className="dash-drag-handle"
                  draggable
                  title="Перетащить проект"
                  aria-hidden="true"
                  onDragEnd={() => setDraggedId(null)}
                  onDragStart={(event) => {
                    event.dataTransfer.effectAllowed = "move";
                    event.dataTransfer.setData("text/plain", project.id);
                    setDraggedId(project.id);
                  }}
                ><GripVertical size={15} /></span>
                <Button variant="ghost" aria-label="Поднять проект" disabled={index === 0} onClick={() => moveProject(project.id, index - 1)}><ArrowUp size={15} /></Button>
                <Button variant="ghost" aria-label="Опустить проект" disabled={index === active.length - 1} onClick={() => moveProject(project.id, index + 1)}><ArrowDown size={15} /></Button>
                <Button variant="ghost" onClick={() => setArchiveCandidate(project)}><Archive size={15} />В архив</Button>
                <Button variant="ghost" aria-label={`Удалить проект «${project.name}»`} onClick={() => setDeleteCandidate(project)}><Trash2 size={15} />Удалить</Button>
              </div>
            </article>
          ))}
        </div>
      )}

      {inactive.length > 0 && (
        <Disclosure className="dash-archive" summary={`Архив и завершённые (${inactive.length})`}>
          {inactive.map((project) => (
            <div className="dash-archive-row" key={project.id}>
              <ProjectChip icon={icon(project.icon)} color={color(project.color)} size="sm" />
              <span className="dash-archive-name">{project.name}</span>
              <span className="dash-archive-note">{project.status === "completed" ? "Завершён" : "В архиве"}</span>
              <Button variant="ghost" disabled={project.status === "completed" || busyId === project.id} onClick={() => void restore(project)}>
                <RotateCcw size={15} />Вернуть в работу
              </Button>
              <Button variant="ghost" disabled={busyId === project.id} onClick={() => setDeleteCandidate(project)}>
                <Trash2 size={15} />Удалить
              </Button>
            </div>
          ))}
        </Disclosure>
      )}

      <ConfirmDialog
        open={Boolean(archiveCandidate)}
        onOpenChange={(open) => !open && setArchiveCandidate(null)}
        title="Архивировать проект?"
        confirmLabel="Архивировать проект"
        onConfirm={() => void archiveSelected()}
      >
        <p>Проект останется в базе, и его можно будет вернуть в работу.</p>
      </ConfirmDialog>

      <ConfirmDialog
        open={Boolean(deleteCandidate)}
        onOpenChange={(open) => !open && setDeleteCandidate(null)}
        title={`Удалить «${deleteCandidate?.name ?? "проект"}»?`}
        confirmLabel="Удалить навсегда"
        destructive
        onConfirm={() => void deleteSelected()}
      >
        <p>Будут удалены паспорт цели, программа, рабочая раскладка и эталонные ответы проекта. Это действие нельзя отменить.</p>
        <p>Общие файлы библиотеки останутся на месте.</p>
      </ConfirmDialog>
    </div>
  );
}
