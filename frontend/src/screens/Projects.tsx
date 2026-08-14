import { useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";
import { Link, useNavigate } from "react-router";
import {
  Archive,
  ArrowDown,
  ArrowUp,
  GripVertical,
  MoreHorizontal,
  RotateCcw,
  Trash2,
} from "lucide-react";
import {
  archiveProject,
  deleteProject,
  listProjectStats,
  listProjects,
  restoreProject,
  saveProjectOrder,
  type ProjectStats,
  type ProjectSummary,
} from "../api/projects";
import { MetricList, ProjectChip } from "../components/domain";
import type { Metric, ProjectColor, ProjectIconName } from "../components/domain";
import {
  Button,
  Card,
  ConfirmDialog,
  Disclosure,
  ErrorState,
  IconButton,
  LoadingState,
  Menu,
  PageHead,
  Tooltip,
} from "../components/ui";

const icon = (value: ProjectSummary["icon"]): ProjectIconName => value ?? "graduation-cap";
const color = (value: number | null): ProjectColor => (value && value >= 1 && value <= 8 ? value : 1) as ProjectColor;

const dayFormat = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long" });

/** Дата без времени: `2026-08-21` без суффикса разобралась бы как UTC-полночь. */
const asLocalDate = (isoDay: string): Date => new Date(`${isoDay}T00:00:00`);

/**
 * Считаем по локальным полуночам, а не по разнице таймстампов: иначе «7 дней»
 * превращается в «6» посреди рабочего дня.
 */
function daysUntil(isoDay: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((asLocalDate(isoDay).getTime() - today.getTime()) / 86_400_000);
}

function plural(count: number, one: string, few: string, many: string): string {
  const tail = count % 100;
  if (tail >= 11 && tail <= 14) return many;
  const last = count % 10;
  if (last === 1) return one;
  if (last >= 2 && last <= 4) return few;
  return many;
}

/**
 * Метрики карточки. Всё, что не считается для этого типа проекта, приходит
 * `null` и по FR-P3 просто не показывается — нулём не подменяется.
 */
function cardMetrics(project: ProjectSummary, stats: ProjectStats | undefined): Metric[] {
  if (!stats) return [];
  const nodes = stats.program_nodes;
  if (project.template_key === "exam") {
    return [
      { label: "Вопросов", value: nodes === null ? null : String(nodes) },
      {
        label: "Эталонов",
        value:
          stats.reference_answers === null || nodes === null
            ? null
            : `${stats.reference_answers} из ${nodes}`,
      },
      { label: "Материалов", value: String(stats.materials) },
    ];
  }
  if (project.template_key === "textbook") {
    return [
      { label: "Тем", value: nodes === null ? null : String(nodes) },
      { label: "Материалов", value: String(stats.materials) },
      {
        label: "Страниц",
        value: stats.material_pages === null ? null : String(stats.material_pages),
      },
    ];
  }
  /* Свободное изучение приезжает на этапе 7: считать по нему пока нечего. */
  return [];
}

type ProjectTemplate = {
  id: "exam" | "textbook";
  title: string;
  description: string;
  path: string;
  disabled: false;
} | {
  id: "free";
  title: string;
  description: string;
  disabled: true;
};

const TEMPLATES: ProjectTemplate[] = [
  {
    id: "exam",
    title: "Экзамен по билетам",
    description: "Дедлайн, вопросы и ответы, план до даты. Работает без внешних моделей.",
    path: "/projects/new?track=exam",
    disabled: false,
  },
  {
    id: "textbook",
    title: "Учебник",
    description: "Один большой файл, программа по оглавлению или проходом по материалу.",
    path: "/projects/new?track=textbook",
    disabled: false,
  },
  {
    id: "free",
    title: "Свободное изучение",
    description: "Без дедлайна, программа из каталога, материалы добавляются позже.",
    disabled: true,
  },
];

const statusLabel: Record<ProjectSummary["status"], string> = {
  active: "В работе",
  archived: "В архиве",
  completed: "Завершён",
};

/** Крупная строка карточки: у экзамена — отсчёт, у учебника — размер программы. */
function CardHeadline({ project, stats }: { project: ProjectSummary; stats?: ProjectStats }) {
  if (project.template_key === "textbook") {
    if (stats?.program_nodes === null || stats?.program_nodes === undefined) return null;
    return (
      <p className="dash-card-headline">
        <b>{stats.program_nodes}</b> {plural(stats.program_nodes, "тема", "темы", "тем")} в программе
      </p>
    );
  }
  if (project.template_key !== "exam") return null;

  if (project.deadline === null) {
    return (
      <p className="dash-card-headline is-quiet">
        Дата экзамена не задана,{" "}
        <Link to={`/projects/${project.id}/settings`}>укажите в настройках</Link>
      </p>
    );
  }

  const days = daysUntil(project.deadline);
  const date = dayFormat.format(asLocalDate(project.deadline));
  if (days < 0) return <p className="dash-card-headline is-quiet">Экзамен прошёл, {date}</p>;
  if (days === 0) return <p className="dash-card-headline is-quiet">Экзамен сегодня, {date}</p>;
  return (
    <p className="dash-card-headline">
      <b>{days}</b> {plural(days, "день", "дня", "дней")} до экзамена, {date}
    </p>
  );
}

export function Projects() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [stats, setStats] = useState<Record<string, ProjectStats>>({});
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
    void loadStats(signal);
    try {
      setProjects(await listProjects(signal));
    } catch (error) {
      if (signal?.aborted) return;
      setLoadError(error instanceof Error ? error.message : "Не удалось загрузить проекты");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  /* Сводка грузится отдельно и экран не задерживает: список пришёл — карточки
     уже видны. Если сводка не доехала, метрик просто нет (FR-P3), а не нули. */
  async function loadStats(signal?: AbortSignal) {
    try {
      const rows = await listProjectStats(signal);
      if (signal?.aborted) return;
      setStats(Object.fromEntries(rows.map((row) => [row.project_id, row])));
    } catch {
      if (!signal?.aborted) setStats({});
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
      <PageHead placement="topbar" title="Проекты" actions={<Link className="primary-button" to="/projects/new">Новый проект</Link>} />

      {operationError && <p className="inline-error" role="alert">{operationError}</p>}

      {active.length === 0 ? (
        <>
          <p className="lead dash-empty-lead">Первый проект начинается с шаблона.</p>
          <div className="dash-templates">
            {TEMPLATES.map((template) => (
              <Card
                className={`dash-template ${template.disabled ? "is-disabled" : ""}`.trim()}
                key={template.id}
                onClick={template.disabled ? undefined : () => navigate(template.path)}
              >
                <h3>{template.title}</h3>
                <p>{template.description}</p>
                {template.disabled && <small>После этапа 7</small>}
              </Card>
            ))}
          </div>
        </>
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
                <span
                  className="dash-drag-handle"
                  draggable
                  title="Перетащить проект мышью"
                  aria-hidden="true"
                  onDragEnd={() => setDraggedId(null)}
                  onDragStart={(event) => {
                    event.dataTransfer.effectAllowed = "move";
                    event.dataTransfer.setData("text/plain", project.id);
                    setDraggedId(project.id);
                  }}
                ><GripVertical size={15} /></span>
              </div>

              <CardHeadline project={project} stats={stats[project.id]} />
              <MetricList metrics={cardMetrics(project, stats[project.id])} />

              <div className="dash-card-foot">
                <p className="dash-card-last">
                  {stats[project.id]?.last_activity_at
                    ? `Последняя работа — ${dayFormat.format(new Date(stats[project.id].last_activity_at as string))}`
                    : "Занятий пока не было"}
                </p>
                <div className="dash-card-cta" aria-label={`Действия для проекта «${project.name}»`}>
                  <Link className="primary-button" to={`/projects/${project.id}`}>Продолжить</Link>
                  <Tooltip label="Повторения появятся на этапе 9" side="top">
                    <span className="dash-card-later">
                      <Button variant="secondary" disabled>Повторить</Button>
                    </span>
                  </Tooltip>
                  <Menu
                    label={`Ещё для проекта «${project.name}»`}
                    trigger={
                      <IconButton label="Ещё" className="dash-card-more">
                        <MoreHorizontal size={15} aria-hidden="true" />
                      </IconButton>
                    }
                    items={[
                      { label: "Вверх", icon: <ArrowUp size={15} />, disabled: index === 0, onSelect: () => moveProject(project.id, index - 1) },
                      { label: "Вниз", icon: <ArrowDown size={15} />, disabled: index === active.length - 1, onSelect: () => moveProject(project.id, index + 1) },
                      { label: "Архивировать", icon: <Archive size={15} />, onSelect: () => setArchiveCandidate(project) },
                      { label: "Удалить навсегда", icon: <Trash2 size={15} />, destructive: true, onSelect: () => setDeleteCandidate(project) },
                    ]}
                  />
                </div>
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
              <span className="dash-archive-note">{statusLabel[project.status]}</span>
              <Button variant="ghost" disabled={project.status === "completed" || busyId === project.id} onClick={() => void restore(project)}>
                <RotateCcw size={15} />Вернуть в работу
              </Button>
              <Button variant="ghost" disabled={busyId === project.id} onClick={() => setDeleteCandidate(project)}>
                <Trash2 size={15} />Удалить навсегда
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
