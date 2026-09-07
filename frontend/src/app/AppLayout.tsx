import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import {
  Activity,
  CircleCheck,
  Cpu,
  Palette,
  PanelLeftClose,
  PanelLeftOpen,
  PieChart,
} from "lucide-react";
import {
  Disclosure,
  PageHeadSlotProvider,
  Popover,
  Tooltip,
  TooltipProvider,
} from "../components/ui";
import { BrandMark } from "./BrandMark";
import { CommandPalette } from "./CommandPalette";
import { screenById } from "./screens";
import { SCREEN_VIEWS } from "./views";
import { ThemeToggle } from "./ThemeToggle";
import { getAiSettings, type AiSettingsRead } from "../api/ai";
import {
  ACTIVE_JOB_STATES,
  cancelBackgroundJob,
  listBackgroundJobs,
  resolveBackgroundJob,
  type BackgroundJobRead,
} from "../api/backgroundJobs";
import { TaskRow, type BackgroundTask, type TaskKind } from "../components/domain";

const BACKGROUND_POLL_MS = 4000;

/** Куда ведёт клик по строке — экран, где задача была вызвана. Опознаём по
 *  тому, что у задачи заполнено (project_id/material_id), а не по факту её
 *  вида: `parse` и `ai_cleanup` бывают и в проекте, и в общей Библиотеке. */
function backgroundJobPath(job: BackgroundJobRead): string | null {
  switch (job.kind) {
    case "parse":
    case "ai_cleanup":
      if (!job.material_id) return null;
      return job.project_id
        ? `/projects/${job.project_id}/materials/${job.material_id}`
        : `/library/${job.material_id}`;
    case "ai_grouping":
    case "ai_import_repair":
      return job.project_id ? `/projects/${job.project_id}/program` : null;
    case "ai_preparation":
      return job.project_id ? `/projects/new?draft=${job.project_id}` : null;
    case "link_answers":
    case "ai_answer_sections":
      return job.project_id && job.material_id
        ? `/projects/${job.project_id}/materials/${job.material_id}`
        : null;
    default:
      return null;
  }
}

/** Куда вести из корзины «ждут проверки»: тот же экран, но с номером задачи.
 *  Экран по этому параметру открывает свой диалог сразу на готовом
 *  предложении — иначе пользователь приходил бы на экран и гадал, что нажать.
 *  Одна договорённость на все роли ИИ, а не вкладка в каждом разделе. */
function backgroundJobReviewPath(job: BackgroundJobRead): string | null {
  const path = backgroundJobPath(job);
  return path ? `${path}?job=${job.id}` : null;
}

/** Имя файла или проекта; огрызок UUID — только если сервер не дал ничего. */
function backgroundJobSubject(job: BackgroundJobRead): string {
  if (job.subject) return job.subject;
  if (job.material_id) return `материал ${job.material_id.slice(0, 8)}`;
  if (job.project_id) return `проект ${job.project_id.slice(0, 8)}`;
  return "фоновая операция";
}

// Столько секунд уходит на страницу; та же оценка, что и в панели обработки
// материала (`LibraryProcessingPanel`), измерена прогоном `tentex-ocr-bench`.
const PARSE_SECONDS_PER_PAGE: Record<string, number> = { fast: 16, cloud: 19 };

function toBackgroundTask(job: BackgroundJobRead): BackgroundTask {
  const left = Math.max(0, job.total - job.done);
  const perPage = PARSE_SECONDS_PER_PAGE[job.parser_mode ?? ""] ?? 0;
  return {
    id: job.id,
    kind: job.kind as TaskKind,
    subject: backgroundJobSubject(job),
    detail: job.model_label,
    unit: job.kind === "parse" ? "страниц" : "",
    done: job.done,
    total: job.total,
    etaMinutes: perPage && left > 0 ? Math.ceil((left * perPage) / 60) : null,
    state: job.needs_review ? "review" : (job.state as BackgroundTask["state"]),
    error: job.error ?? undefined,
  };
}

interface BackgroundJobGroupProps {
  jobs: BackgroundJobRead[];
  navigate: (path: string) => void;
  onCancel?: (jobId: string) => void;
  onDismiss?: (jobId: string) => void;
}

/**
 * Группа строк в поповере фоновых задач: одинаковая и для идущих, и для тех,
 * что ждут проверки, — различаются они содержимым строки и тем, куда ведёт клик.
 *
 * Строка целиком ведёт на экран задачи, но клик по кнопке внутри неё
 * («Отменить», «Убрать») не должен ещё и переключать экран — клики,
 * начавшиеся на вложенной кнопке, отсекаются.
 */
function BackgroundJobGroup({ jobs, navigate, onCancel, onDismiss }: BackgroundJobGroupProps) {
  return (
    <div className="popover-task-list">
      {jobs.map((job) => {
        const path = job.needs_review ? backgroundJobReviewPath(job) : backgroundJobPath(job);
        return (
          <div
            key={job.id}
            className={path ? "popover-task-row is-linked" : "popover-task-row"}
            role={path ? "button" : undefined}
            tabIndex={path ? 0 : undefined}
            onClick={path ? (event) => {
              if ((event.target as HTMLElement).closest("button")) return;
              navigate(path);
            } : undefined}
            onKeyDown={path ? (event) => {
              if (event.key !== "Enter" && event.key !== " ") return;
              if ((event.target as HTMLElement).closest("button")) return;
              event.preventDefault();
              navigate(path);
            } : undefined}
          >
            <TaskRow task={toBackgroundTask(job)} onCancel={onCancel} onDismiss={onDismiss} />
          </div>
        );
      })}
    </div>
  );
}

interface BackgroundJobsWidgetProps {
  backgroundJobs: BackgroundJobRead[];
  reviewJobs: BackgroundJobRead[];
  runningJobs: BackgroundJobRead[];
  navigate: (path: string) => void;
  onDismiss: (jobId: string) => void;
  onCancel: (jobId: string) => void;
}

/** Кнопка и всплывашка «Фоновые задачи» в панели слева. Отдельным компонентом —
 *  чтобы разметка кнопки и попапа не дублировалась там, где к ним обращаются. */
function BackgroundJobsWidget({
  backgroundJobs,
  reviewJobs,
  runningJobs,
  navigate,
  onDismiss,
  onCancel,
}: BackgroundJobsWidgetProps) {
  return (
    <Popover
      title="Фоновые задачи"
      trigger={
        <button type="button" className={reviewJobs.length > 0 ? "app-widget has-review" : "app-widget"}>
          <Activity size={15} aria-hidden="true" />
          <b className="nav-label">Фоновая задача</b>
          {backgroundJobs.length > 0 && (
            <span className={reviewJobs.length > 0 ? "app-widget-value is-review" : "app-widget-value"}>
              {backgroundJobs.length}
            </span>
          )}
        </button>
      }
    >
      {backgroundJobs.length === 0 ? (
        <p className="popover-note">Фон свободен.</p>
      ) : (
        <>
          {reviewJobs.length > 0 && (
            <section className="popover-task-group">
              <h4 className="popover-task-group-title">Ждут проверки</h4>
              <BackgroundJobGroup jobs={reviewJobs} navigate={navigate} onDismiss={onDismiss} />
            </section>
          )}
          {runningJobs.length > 0 && (
            <section className="popover-task-group">
              <h4 className="popover-task-group-title">Идут сейчас</h4>
              <BackgroundJobGroup jobs={runningJobs} navigate={navigate} onCancel={onCancel} />
            </section>
          )}
        </>
      )}
    </Popover>
  );
}

/**
 * Оболочка: панель установки слева, полоса действий сверху, контент справа.
 * Описание — SCREENS.md, раздел «Оболочка».
 *
 * Рабочая область проекта рисует собственную полноэкранную оболочку: дерево
 * вопросов там заменяет глобальную навигацию, а не становится третьей панелью.
 */

/** Глобальная навигация — уровень установки. */
const GLOBAL_NAV_IDS = ["projects", "library", "setup"];

const COLLAPSE_KEY = "tentex-panel-collapsed";

/** В навигацию попадают только сверстанные экраны: ссылка в никуда бесполезна. */
const NAV_SCREENS = GLOBAL_NAV_IDS.filter((id) => id in SCREEN_VIEWS).map(screenById);

/** Знак ведёт на входной экран — как и положено логотипу. */
const HOME_PATH = screenById("projects").navPath;

export function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === "1");
  const [scrolled, setScrolled] = useState(false);
  const [aiSnapshot, setAiSnapshot] = useState<AiSettingsRead | null>(null);
  const [aiSnapshotFailed, setAiSnapshotFailed] = useState(false);
  const [backgroundJobs, setBackgroundJobs] = useState<BackgroundJobRead[]>([]);
  const [titleSlot, setTitleSlot] = useState<HTMLElement | null>(null);
  const [actionsSlot, setActionsSlot] = useState<HTMLElement | null>(null);

  useEffect(() => {
    let active = true;
    const loadBackgroundJobs = () => {
      // Обе корзины сразу: и то, что считается, и то, что уже досчиталось и
      // ждёт человека. Вторая держится в панели до тех пор, пока предложение
      // не приняли или не убрали, — раньше готовый результат просто исчезал.
      void listBackgroundJobs({ activeOnly: true, pendingReview: true }).then((jobs) => {
        if (active) setBackgroundJobs(jobs);
      }).catch(() => undefined);
    };
    loadBackgroundJobs();
    const timer = window.setInterval(loadBackgroundJobs, BACKGROUND_POLL_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  function cancelJob(jobId: string) {
    void cancelBackgroundJob(jobId)
      .then((updated) => setBackgroundJobs((current) => current.map((job) => job.id === updated.id ? updated : job)
        .filter((job) => ACTIVE_JOB_STATES.has(job.state) || job.needs_review)))
      .catch(() => undefined);
  }

  // Две корзины из одного списка: что считается и что уже посчитано, но ждёт
  // человека. Строка не может быть в обеих — `needs_review` бывает только у
  // завершённой задачи.
  const reviewJobs = backgroundJobs.filter((job) => job.needs_review);
  const runningJobs = backgroundJobs.filter((job) => ACTIVE_JOB_STATES.has(job.state));

  /** Убрать готовое предложение из панели, не открывая. Результат остаётся на
   *  сервере — уходит только напоминание о том, что его ждут. */
  function dismissJob(jobId: string) {
    void resolveBackgroundJob(jobId)
      .then(() => setBackgroundJobs((current) => current.filter((job) => job.id !== jobId)))
      .catch(() => undefined);
  }

  useEffect(() => {
    let active = true;
    const loadAiSnapshot = () => {
      void getAiSettings().then((snapshot) => {
        if (!active) return;
        setAiSnapshot(snapshot);
        setAiSnapshotFailed(false);
      }).catch(() => {
        if (active) setAiSnapshotFailed(true);
      });
    };
    loadAiSnapshot();
    window.addEventListener("tentex:ai-settings-updated", loadAiSnapshot);
    return () => {
      active = false;
      window.removeEventListener("tentex:ai-settings-updated", loadAiSnapshot);
    };
  }, []);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 0);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!event.ctrlKey || event.key.toLowerCase() !== "b") return;
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      event.preventDefault();
      toggle();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function toggle() {
    setCollapsed((prev) => {
      localStorage.setItem(COLLAPSE_KEY, prev ? "0" : "1");
      return !prev;
    });
  }

  if (location.pathname === screenById("project-new").path) {
    return (
      <TooltipProvider>
        <Outlet />
      </TooltipProvider>
    );
  }

  /* Рабочая область материала Библиотеки — такая же полноразмерная поверхность,
     как проектные: оглавление, две половины документа и панель обработки не
     помещаются в контентную колонку обычной оболочки. Сам список `/library`
     остаётся в ней. */
  if (
    /^\/projects\/[^/]+(?:\/.*)?$/.test(location.pathname)
    || /^\/library\/[^/]+$/.test(location.pathname)
  ) {
    return (
      <TooltipProvider>
        <Outlet />
      </TooltipProvider>
    );
  }

  return (
    <TooltipProvider>
      <div className={`app-shell ${collapsed ? "is-collapsed" : ""}`.trim()}>
        <nav className="app-nav" aria-label="Навигация">
          <Link className="app-brand" to={HOME_PATH} aria-label="Tentex — к проектам">
            <BrandMark />
            {!collapsed && <span className="app-brand-word">Tentex</span>}
          </Link>

          <div className="app-nav-group">
            {NAV_SCREENS.map((screen) => {
              /*
               * className строкой, а не функцией: в свёрнутой панели ссылку
               * оборачивает Tooltip, а Radix Slot склеивает className строками —
               * функция попала бы в атрибут своим исходным текстом, и класс
               * app-nav-link не применился бы вовсе.
               */
              const isActive =
                screen.id === "projects"
                  ? location.pathname === screen.navPath
                  : location.pathname === screen.navPath ||
                    location.pathname.startsWith(`${screen.navPath}/`);
              const link = (
                <NavLink
                  to={screen.navPath}
                  end={screen.id === "projects"}
                  className={`app-nav-link ${isActive ? "is-active" : ""}`.trim()}
                >
                  <screen.icon size={15} aria-hidden="true" />
                  <span className="nav-text">
                    <span className="nav-label">{screen.title}</span>
                  </span>
                </NavLink>
              );

              /* В свёрнутой панели подпись негде показать — её берёт подсказка */
              return collapsed ? (
                <Tooltip key={screen.id} label={screen.title}>
                  {link}
                </Tooltip>
              ) : (
                <div key={screen.id}>{link}</div>
              );
            })}
          </div>

          <Popover
            title="Покрытие материалов"
            trigger={
              <button type="button" className="app-nav-link app-coverage-button">
                <PieChart size={15} aria-hidden="true" />
                <span className="nav-text">Покрытие материалов</span>
              </button>
            }
          >
            <p className="sidebar-empty">Покрытие появится после привязок на этапе 8</p>
          </Popover>

          <Disclosure className="sidebar-recent" summary="Последние темы">
            <p className="sidebar-empty">Здесь появятся последние изученные темы</p>
          </Disclosure>

          <div className="app-widgets" aria-label="Состояние установки">
            <BackgroundJobsWidget
              backgroundJobs={backgroundJobs}
              reviewJobs={reviewJobs}
              runningJobs={runningJobs}
              navigate={navigate}
              onDismiss={dismissJob}
              onCancel={cancelJob}
            />

            <Popover
              title="Внешние модели"
              trigger={
                <button type="button" className="app-widget">
                  <Cpu size={15} aria-hidden="true" />
                  <b className="nav-label">Модели</b>
                </button>
              }
            >
              {aiSnapshot ? (
                <div className="app-models-summary">
                  <p>{aiSnapshot.external_models_enabled ? "Внешние модели включены" : "Внешние модели выключены"}</p>
                  <dl>
                    <div><dt>Текст</dt><dd>{aiSnapshot.default_text?.model_id ?? "не настроена"}</dd></div>
                    <div><dt>Речь</dt><dd>{aiSnapshot.default_speech?.model_id ?? "не настроена"}</dd></div>
                    <div><dt>Сегодня</dt><dd>${Number(aiSnapshot.today_usage.actual_cost_usd).toFixed(4)}</dd></div>
                  </dl>
                  <Link className="popover-link" to="/setup?section=ai&subsection=overview">Открыть параметры ИИ</Link>
                </div>
              ) : (
                <p className="popover-note" style={{ marginTop: 0 }}>{aiSnapshotFailed ? "Снимок моделей сейчас недоступен." : "Загружаем состояние моделей…"}</p>
              )}
            </Popover>

            <Popover
              title="Состояние"
              trigger={
                <button type="button" className="app-widget">
                  <CircleCheck size={15} aria-hidden="true" />
                  <b className="nav-label">Состояние</b>
                  <span className="app-widget-value">в порядке</span>
                </button>
              }
            >
              <p className="popover-note">API работает локально.</p>
              <Link className="popover-link" to="/setup">Бот и резервные копии не настроены</Link>
            </Popover>
          </div>

          <div className="app-nav-footer">
            <span className="app-nav-footer-actions">
              <ThemeToggle />
              <Tooltip label="UI-кит" side="top">
                <NavLink to="/ui-kit" className="footer-icon" aria-label="UI-кит">
                  <Palette size={15} aria-hidden="true" />
                </NavLink>
              </Tooltip>
              <Tooltip label={collapsed ? "Развернуть панель · Ctrl+B" : "Свернуть панель · Ctrl+B"} side="top">
                <button
                  type="button"
                  className="footer-icon"
                  onClick={toggle}
                  aria-label={collapsed ? "Развернуть панель" : "Свернуть панель"}
                >
                  {collapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
                </button>
              </Tooltip>
            </span>
          </div>
        </nav>

        <PageHeadSlotProvider title={titleSlot} actions={actionsSlot}>
          <div className="app-frame">
            <header className={`app-topbar ${scrolled ? "is-scrolled" : ""}`.trim()}>
              {/* Одна строка на экран: заголовок, поиск по центру, действие
                  справа. По краям сюда переезжает PageHead текущего экрана. */}
              <div className="app-topbar-inner">
                <div className="topbar-lead" ref={setTitleSlot} />
                <CommandPalette />
                <div className="topbar-actions" ref={setActionsSlot} />
              </div>
            </header>

            <main className="app-main">
              <Outlet />
            </main>
          </div>
        </PageHeadSlotProvider>
      </div>
    </TooltipProvider>
  );
}
