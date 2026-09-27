import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import {
  Activity,
  BookOpenText,
  CircleCheck,
  Cpu,
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
import { getAiSettings, updateAiDefault, type AiModality, type AiSettingsRead } from "../api/ai";
import { listRecentStudy, type RecentStudyItem } from "../api/projects";
import {
  ACTIVE_JOB_STATES,
  cancelBackgroundJob,
  listBackgroundJobs,
  resolveBackgroundJob,
  type BackgroundJobRead,
} from "../api/backgroundJobs";
import { pauseRetrievalIndexBuild, resumeRetrievalIndexBuild } from "../api/retrieval";
import { TaskRow, type BackgroundTask } from "../components/domain/TaskRow";
import { estimateEtaSeconds } from "../hooks/backgroundTaskEta";

const BACKGROUND_POLL_MS = 4000;

/** Куда ведёт клик по строке — экран, где задача была вызвана. Опознаём по
 *  тому, что у задачи заполнено (project_id/material_id), а не по факту её
 *  вида: `parse` и `ai_cleanup` бывают и в проекте, и в общей Библиотеке. */
function backgroundJobPath(job: BackgroundJobRead): string | null {
  switch (job.kind) {
    case "parse":
    case "ai_cleanup":
    case "image_descriptions":
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
    case "coverage_research":
      return job.project_id ? `/projects/${job.project_id}/coverage` : null;
    case "retrieval_index":
      return "/setup?section=search&subsection=index";
    case "retrieval_model_install":
      return "/setup?section=search&subsection=models";
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
  if (!path) return null;
  const params = new URLSearchParams({ job: job.id });
  if (job.kind === "ai_cleanup" && job.page_number) params.set("page", String(job.page_number));
  return `${path}?${params.toString()}`;
}

/** Имя файла или проекта; огрызок UUID — только если сервер не дал ничего. */
function backgroundJobSubject(job: BackgroundJobRead): string {
  if (job.subject) return job.subject;
  if (job.material_id) return `материал ${job.material_id.slice(0, 8)}`;
  if (job.project_id) return `проект ${job.project_id.slice(0, 8)}`;
  return "фоновая операция";
}

/** Раздел «Хранилище» уже переводит эти причины падения в понятный текст
 *  локально (см. `StorageSettingsSection`); эта же панель глобальная и видит
 *  задачу до того, как пользователь открыл раздел — техническую строку
 *  (`sqlite3.OperationalError: ...`) сюда пропускать незачем. */
const STORAGE_JOB_FAILURE: Partial<Record<BackgroundJobRead["kind"], string>> = {
  backup_create: "Не удалось создать резервную копию.",
  project_export: "Не удалось подготовить пакет проекта.",
  project_import: "Не удалось импортировать пакет проекта.",
  storage_verify: "Не удалось проверить хранилище.",
  storage_cleanup: "Не удалось очистить временные файлы.",
};

function backgroundJobError(job: BackgroundJobRead): string | undefined {
  if (job.state !== "failed") return undefined;
  return STORAGE_JOB_FAILURE[job.kind] ?? job.error ?? undefined;
}

function toBackgroundTask(job: BackgroundJobRead, pendingIds: ReadonlySet<string>): BackgroundTask {
  return {
    id: job.id,
    kind: job.kind,
    subject: backgroundJobSubject(job),
    detail: job.model_label,
    // Единицу называет сервер: у записи это минуты, у разбора и сборки Typst — страницы.
    unit: job.progress_unit,
    done: job.done,
    total: job.total,
    etaSeconds: estimateEtaSeconds(job.id, job.done, job.total, job.updated_at),
    state: job.needs_review ? "review" : (job.state as BackgroundTask["state"]),
    error: backgroundJobError(job),
    finishable: job.kind === "retrieval_index" && job.material_id === null,
    finalizing: job.kind === "parse" && job.stage === "segment" && job.total > 0 && job.done === job.total,
    // `pause_requested` переживает опрос: отмена бегущей задачи не исчезает
    // мгновенно (воркер должен сам заметить флаг), и после клика строка не
    // должна выглядеть снова кликабельной, пока это не произойдёт на самом деле.
    pending: pendingIds.has(job.id) || job.pause_requested,
  };
}

interface BackgroundJobGroupProps {
  jobs: BackgroundJobRead[];
  pendingIds: ReadonlySet<string>;
  navigate: (path: string) => void;
  onCancel?: (jobId: string) => void;
  onPause?: (jobId: string) => void;
  onResume?: (jobId: string) => void;
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
function BackgroundJobGroup({ jobs, pendingIds, navigate, onCancel, onPause, onResume, onDismiss }: BackgroundJobGroupProps) {
  return (
    <div className="popover-task-list">
      {jobs.map((job) => {
        const reviewableKind = ["ai_cleanup", "ai_grouping", "ai_import_repair", "ai_answer_sections"].includes(job.kind);
        const path = job.needs_review || (job.state === "failed" && reviewableKind)
          ? backgroundJobReviewPath(job)
          : backgroundJobPath(job);
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
            <TaskRow
              task={toBackgroundTask(job, pendingIds)}
              onCancel={onCancel}
              onPause={job.kind === "retrieval_index" && !job.material_id ? onPause : undefined}
              onResume={job.kind === "retrieval_index" && !job.material_id ? onResume : undefined}
              onDismiss={onDismiss}
            />
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
  failedJobs: BackgroundJobRead[];
  pendingIds: ReadonlySet<string>;
  navigate: (path: string) => void;
  onDismiss: (jobId: string) => void;
  onCancel: (jobId: string) => void;
  onPause: (jobId: string) => void;
  onResume: (jobId: string) => void;
}

/** Кнопка и всплывашка «Фоновые задачи» в панели слева. Отдельным компонентом —
 *  чтобы разметка кнопки и попапа не дублировалась там, где к ним обращаются. */
function BackgroundJobsWidget({
  backgroundJobs,
  reviewJobs,
  runningJobs,
  failedJobs,
  pendingIds,
  navigate,
  onDismiss,
  onCancel,
  onPause,
  onResume,
}: BackgroundJobsWidgetProps) {
  return (
    <Popover
      title="Фоновые задачи"
      className="popover-tasks"
      trigger={
        <button type="button" className={reviewJobs.length > 0 || failedJobs.length > 0 ? "app-widget has-review" : "app-widget"}>
          <Activity size={15} aria-hidden="true" />
          <b className="nav-label">Фоновые задачи</b>
          {backgroundJobs.length > 0 && (
            <span className={reviewJobs.length > 0 || failedJobs.length > 0 ? "app-widget-value is-review" : "app-widget-value"}>
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
          {failedJobs.length > 0 && (
            <section className="popover-task-group">
              <h4 className="popover-task-group-title">Требуют внимания</h4>
              <BackgroundJobGroup jobs={failedJobs} pendingIds={pendingIds} navigate={navigate} onDismiss={onDismiss} />
            </section>
          )}
          {reviewJobs.length > 0 && (
            <section className="popover-task-group">
              <h4 className="popover-task-group-title">Ждут проверки</h4>
              <BackgroundJobGroup jobs={reviewJobs} pendingIds={pendingIds} navigate={navigate} onDismiss={onDismiss} />
            </section>
          )}
          {runningJobs.length > 0 && (
            <section className="popover-task-group">
              <h4 className="popover-task-group-title">Идут сейчас</h4>
              <BackgroundJobGroup jobs={runningJobs} pendingIds={pendingIds} navigate={navigate} onCancel={onCancel} onPause={onPause} onResume={onResume} />
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
  const [recentStudy, setRecentStudy] = useState<RecentStudyItem[]>([]);
  // Отмена или снятие уже отправлены, ответ ещё не пришёл — строка показывает
  // «Завершаем…» вместо того чтобы молча ничего не делать до следующего опроса.
  const [pendingJobIds, setPendingJobIds] = useState<Set<string>>(new Set());
  const [titleSlot, setTitleSlot] = useState<HTMLElement | null>(null);
  const [viewSlot, setViewSlot] = useState<HTMLElement | null>(null);
  const [actionsSlot, setActionsSlot] = useState<HTMLElement | null>(null);

  useEffect(() => {
    let active = true;
    const loadBackgroundJobs = () => {
      // Скрытая вкладка (в том числе отделённое окно зоны) не опрашивает
      // сервер: список обновится, как только её снова покажут.
      if (document.hidden) return;
      // Активные, готовые предложения и ошибки загружаются вместе. Последние
      // две корзины остаются до явного удаления пользователем.
      void listBackgroundJobs({ activeOnly: true, pendingReview: true, failedOnly: true }).then((jobs) => {
        if (active) setBackgroundJobs(jobs);
      }).catch(() => undefined);
    };
    loadBackgroundJobs();
    const timer = window.setInterval(loadBackgroundJobs, BACKGROUND_POLL_MS);
    document.addEventListener("visibilitychange", loadBackgroundJobs);
    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", loadBackgroundJobs);
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void listRecentStudy(controller.signal).then(setRecentStudy).catch(() => undefined);
    return () => controller.abort();
  }, []);

  function markPending(jobId: string) {
    setPendingJobIds((current) => new Set(current).add(jobId));
  }

  function clearPending(jobId: string) {
    setPendingJobIds((current) => {
      if (!current.has(jobId)) return current;
      const next = new Set(current);
      next.delete(jobId);
      return next;
    });
  }

  function cancelJob(jobId: string) {
    markPending(jobId);
    void cancelBackgroundJob(jobId)
      .then((updated) => setBackgroundJobs((current) => current.map((job) => job.id === updated.id ? updated : job)
        .filter((job) => ACTIVE_JOB_STATES.has(job.state) || job.needs_review)))
      .catch((error) => console.error("Не удалось отменить фоновую задачу", error))
      .finally(() => clearPending(jobId));
  }

  function updateJob(job: BackgroundJobRead) {
    setBackgroundJobs((current) => current.map((item) => item.id === job.id ? job : item)
      .filter((item) => ACTIVE_JOB_STATES.has(item.state) || item.needs_review));
  }

  function pauseJob(jobId: string) {
    void pauseRetrievalIndexBuild(jobId).then(updateJob).catch(() => undefined);
  }

  function resumeJob(jobId: string) {
    void resumeRetrievalIndexBuild(jobId).then(updateJob).catch(() => undefined);
  }

  // Две корзины из одного списка: что считается и что уже посчитано, но ждёт
  // человека. Строка не может быть в обеих — `needs_review` бывает только у
  // завершённой задачи.
  const reviewJobs = backgroundJobs.filter((job) => job.needs_review);
  const runningJobs = backgroundJobs.filter((job) => ACTIVE_JOB_STATES.has(job.state));
  const failedJobs = backgroundJobs.filter((job) => job.state === "failed");

  /** Убрать готовое предложение из панели, не открывая. Результат остаётся на
   *  сервере — уходит только напоминание о том, что его ждут. */
  function dismissJob(jobId: string) {
    markPending(jobId);
    void resolveBackgroundJob(jobId)
      .then(() => setBackgroundJobs((current) => current.filter((job) => job.id !== jobId)))
      .catch((error) => console.error("Не удалось убрать задачу из панели", error))
      .finally(() => clearPending(jobId));
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

  function changeDefault(modality: AiModality, value: string) {
    if (!aiSnapshot) return;
    const [provider_id, model_id] = value.split("::");
    void updateAiDefault(modality, provider_id && model_id ? { provider_id, model_id } : null)
      .then((snapshot) => {
        setAiSnapshot(snapshot);
        window.dispatchEvent(new Event("tentex:ai-settings-updated"));
      })
      .catch(() => undefined);
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

          <Disclosure className="sidebar-recent" summary="Последние занятия">
            {recentStudy.length === 0 ? <p className="sidebar-empty">Пройденные уроки и ответы появятся здесь.</p> : (
              <div className="sidebar-recent-list">
                {recentStudy.map((item) => (
                  <Link className="sidebar-recent-row" key={`${item.kind}-${item.item_id}`} to={item.kind === "lesson" ? `/projects/${item.project_id}/lessons?lesson=${item.item_id}` : `/projects/${item.project_id}?node=${item.item_id}`}>
                    <small><span className="sidebar-project-type">{item.template_key === "exam" ? "Э" : item.template_key === "textbook" ? "Уч" : "СИ"}</span>{item.project_name}</small>
                    <b>{item.kind === "lesson" ? "Урок:" : "Вопрос:"} {item.title}</b>
                    <small>{new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(item.happened_at))}</small>
                  </Link>
                ))}
              </div>
            )}
          </Disclosure>

          <div className="app-widgets" aria-label="Состояние установки">
            <BackgroundJobsWidget
              backgroundJobs={backgroundJobs}
              reviewJobs={reviewJobs}
              runningJobs={runningJobs}
              failedJobs={failedJobs}
              pendingIds={pendingJobIds}
              navigate={navigate}
              onDismiss={dismissJob}
              onCancel={cancelJob}
              onPause={pauseJob}
              onResume={resumeJob}
            />

            <Popover
              trigger={
                <button type="button" className="app-widget">
                  <Cpu size={15} aria-hidden="true" />
                  <b className="nav-label">Модели</b>
                </button>
              }
            >
              {aiSnapshot ? (
                <div className="app-models-summary">
                  <p className={aiSnapshot.external_models_enabled ? "is-ready" : "is-offline"}>{aiSnapshot.external_models_enabled ? "Внешние модели включены" : "Внешние модели выключены"}</p>
                  <dl>
                    <div><dt>Текст</dt><dd><select value={aiSnapshot.default_text ? `${aiSnapshot.default_text.provider_id}::${aiSnapshot.default_text.model_id}` : ""} onChange={(event) => changeDefault("text", event.target.value)}><option value="">не настроена</option>{aiSnapshot.models.filter((model) => model.input_modalities.includes("text") && model.output_modalities.includes("text")).map((model) => <option key={`${model.provider_id}::${model.model_id}`} value={`${model.provider_id}::${model.model_id}`}>{model.display_name}</option>)}</select></dd></div>
                    <div><dt>Речь</dt><dd><select value={aiSnapshot.default_speech ? `${aiSnapshot.default_speech.provider_id}::${aiSnapshot.default_speech.model_id}` : ""} onChange={(event) => changeDefault("speech", event.target.value)}><option value="">не настроена</option>{aiSnapshot.models.filter((model) => model.input_modalities.includes("audio")).map((model) => <option key={`${model.provider_id}::${model.model_id}`} value={`${model.provider_id}::${model.model_id}`}>{model.display_name}</option>)}</select></dd></div>
                    <div><dt>Сегодня</dt><dd>${Number(aiSnapshot.today_usage.actual_cost_usd).toFixed(4)}</dd></div>
                  </dl>
                  <div className="app-models-links"><Link to="/setup?section=search&subsection=models">Эмбеддинги и индекс</Link><Link to="/setup?section=ocr&subsection=engines">Распознавание</Link><Link to="/setup?section=ai&subsection=functions">Функции</Link></div>
                  <Link className="secondary-button app-models-open" to="/setup?section=ai&subsection=overview">Открыть параметры</Link>
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
              <Tooltip label="Инструкция по использованию" side="top">
                <NavLink to="/guide" className="footer-icon" aria-label="Инструкция по использованию">
                  <BookOpenText size={15} aria-hidden="true" />
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

        <PageHeadSlotProvider title={titleSlot} view={viewSlot} actions={actionsSlot}>
          <div className="app-frame">
            <header className={`app-topbar ${scrolled ? "is-scrolled" : ""}`.trim()}>
              {/* PageHead переносит сюда заголовок, выбор вида и действия.
                  На узком окне поиск переходит на следующую строку. */}
              <div className="app-topbar-inner">
                <div className="topbar-lead" ref={setTitleSlot} />
                <div className="topbar-view" ref={setViewSlot} />
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
