import { useEffect, useRef, useState } from "react";
import type { CSSProperties, DragEvent, ReactNode } from "react";
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
import { ProjectChip } from "../components/domain";
import type { ProjectColor, ProjectIconName } from "../components/domain";
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

/** Число сверху, склонённая подпись снизу — для ячейки сводки в подвале карточки. */
interface StripCell {
  value: ReactNode;
  label: string;
}

function sourcesCell(materials: number): StripCell {
  return { value: materials, label: plural(materials, "источник", "источника", "источников") };
}

/**
 * Ячейки сводки карточки. Всё, что не считается для этого типа проекта,
 * приходит `null` и по FR-P3 не показывается — нулём не подменяется.
 */
function cardStrip(project: ProjectSummary, stats: ProjectStats | undefined): StripCell[] {
  if (!stats) return [];
  const nodes = stats.program_nodes;
  if (project.template_key === "exam") {
    const cells: StripCell[] = [];
    if (nodes !== null) cells.push({ value: nodes, label: plural(nodes, "вопрос", "вопроса", "вопросов") });
    if (stats.reference_answers !== null && nodes !== null) {
      cells.push({
        value: (
          <>
            {stats.reference_answers}
            <span className="of"> из {nodes}</span>
          </>
        ),
        label: plural(stats.reference_answers, "ответ", "ответа", "ответов"),
      });
    }
    cells.push(sourcesCell(stats.materials));
    return cells;
  }
  if (project.template_key === "textbook") {
    /* «Тем» уже стоит крупной строкой headline — в сводке не дублируем. */
    const cells: StripCell[] = [sourcesCell(stats.materials)];
    if (stats.material_pages !== null) {
      cells.push({
        value: String(stats.material_pages),
        label: plural(stats.material_pages, "страница", "страницы", "страниц"),
      });
    }
    return cells;
  }
  /* Свободное изучение приезжает на этапе 7: считать по нему пока нечего. */
  return [];
}

type Urgency = "danger" | "warning" | "success";

/** Порог тревоги для отсчёта до экзамена: неделя — жёлтый, три дня — красный. */
function urgency(days: number): Urgency {
  if (days <= 3) return "danger";
  if (days <= 7) return "warning";
  return "success";
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

/**
 * Крупная строка карточки: у экзамена — отсчёт, у учебника — размер программы.
 * Число дней до экзамена красится по срочности (правка пользователя поверх
 * FR-D17: запрет красить касается метрик покрытия, а не самого дедлайна).
 * Прошедший срок и незаданная дата остаются фактом без тревожного тона.
 */
function CardCount({ project, stats }: { project: ProjectSummary; stats?: ProjectStats }) {
  if (project.template_key === "textbook") {
    if (stats?.program_nodes === null || stats?.program_nodes === undefined) return null;
    return (
      <div className="b-count">
        <span className="b-days">{stats.program_nodes}</span>
        <span className="b-cap">{plural(stats.program_nodes, "тема", "темы", "тем")} в программе</span>
      </div>
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
  if (days === 0) return <p className="dash-card-headline is-danger">Экзамен сегодня, {date}</p>;
  return (
    <div className="b-count">
      <span className={`b-days is-${urgency(days)}`}>{days}</span>
      <span className="b-cap">{plural(days, "день", "дня", "дней")} до экзамена</span>
      <span className="b-date">{date}</span>
    </div>
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

  if (loading) return <div className="screen"><LoadingState label="Загружаем проекты" placement="page" /></div>;
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
              className={`dash-card v-b ${draggedId === project.id ? "is-dragging" : ""}`.trim()}
              style={{ "--proj": `var(--project-color-${color(project.color)})` } as CSSProperties}
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

              <CardCount project={project} stats={stats[project.id]} />

              {(() => {
                const cells = cardStrip(project, stats[project.id]);
                if (cells.length === 0) return null;
                return (
                  <ul className="b-strip">
                    {cells.map((cell, cellIndex) => (
                      <li className="b-cell" key={cellIndex}>
                        <b>{cell.value}</b>
                        <span>{cell.label}</span>
                      </li>
                    ))}
                  </ul>
                );
              })()}

              <div className="dash-card-foot">
                <div className="b-swap">
                  <p className="dash-card-last">
                    {stats[project.id]?.last_activity_at
                      ? `Последняя работа — ${dayFormat.format(new Date(stats[project.id].last_activity_at as string))}`
                      : "Занятий пока не было"}
                  </p>
                  <div className="b-extra" aria-label={`Действия для проекта «${project.name}»`}>
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
                <Link className="primary-button" to={`/projects/${project.id}`}>Продолжить</Link>
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
        <p>Будут удалены паспорт цели, программа, рабочая раскладка и ответы проекта. Это действие нельзя отменить.</p>
        <p>Общие файлы библиотеки останутся на месте.</p>
      </ConfirmDialog>
    </div>
  );
}
