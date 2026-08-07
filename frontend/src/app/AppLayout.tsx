import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import {
  Activity,
  CircleCheck,
  Cpu,
  Palette,
  PanelLeftClose,
  PanelLeftOpen,
  PieChart,
} from "lucide-react";
import { Disclosure, Popover, Tooltip, TooltipProvider } from "../components/ui";
import { TaskRow } from "../components/domain";
import type { BackgroundTask } from "../components/domain";
import { CommandPalette } from "./CommandPalette";
import { screenById } from "./screens";
import { SCREEN_VIEWS } from "./views";
import { ThemeToggle } from "./ThemeToggle";

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

const DEMO_COVERAGE = [
  { project: "ТРПС — курсовая", progress: "8 из 12 тем" },
  { project: "Базы данных — экзамен", progress: "18 из 25 тем" },
  { project: "Матанализ — учебник", progress: "2 из 9 тем" },
  { project: "Астрономия", progress: "4 из 10 тем" },
];

const DEMO_RECENT_TOPICS = [
  { id: "normal-forms", project: "Базы данных", topic: "Нормальные формы", progress: "2 из 5 шагов" },
  { id: "transactions", project: "Базы данных", topic: "Транзакции", progress: "повторить завтра" },
  { id: "limits", project: "Матанализ", topic: "Пределы последовательностей", progress: "1 из 3 шагов" },
];

/** Выдуманное состояние установки: API появится на этапе 3. */
const DEMO_TASKS: BackgroundTask[] = [
  {
    id: "t1",
    kind: "pass1",
    subject: "Матанализ — учебник",
    unit: "глава",
    done: 4,
    total: 12,
    etaMinutes: 3,
    state: "running",
  },
  {
    id: "t2",
    kind: "ocr",
    subject: "konspekt-scan.pdf",
    unit: "страница",
    done: 0,
    total: 46,
    etaMinutes: null,
    state: "queued",
  },
];

export function AppLayout() {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === "1");
  const [scrolled, setScrolled] = useState(false);

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

  if (/^\/projects\/[^/]+(?:\/.*)?$/.test(location.pathname)) {
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
          <div className="app-brand">
            <strong>{collapsed ? "T" : "Tentex"}</strong>
            <small>этап 1</small>
          </div>

          <div className="app-nav-group">
            {NAV_SCREENS.map((screen) => {
              const link = (
                <NavLink
                  to={screen.navPath}
                  end={screen.id === "projects"}
                  className={({ isActive }) => `app-nav-link ${isActive ? "is-active" : ""}`.trim()}
                >
                  <screen.icon size={15} aria-hidden="true" />
                  <span className="nav-text">
                    <span className="nav-label">{screen.title}</span>
                  </span>
                  {screen.id === "library" && (
                    <span className="nav-meta" aria-label="14 файлов, 1,8 гигабайта">
                      <span>14 файлов</span>
                      <span>1,8 ГБ</span>
                    </span>
                  )}
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
            <div className="sidebar-coverage-list">
              {DEMO_COVERAGE.map((item) => (
                <Link className="sidebar-coverage-row" key={item.project} to="/projects">
                  <span>{item.project}</span>
                  <small>{item.progress}</small>
                </Link>
              ))}
            </div>
          </Popover>

          <Disclosure className="sidebar-recent" summary="Последние темы">
            <div className="sidebar-recent-list">
              {DEMO_RECENT_TOPICS.map((topic) => (
                <Link className="sidebar-recent-row" key={topic.id} to="/projects">
                  <span>{topic.topic}</span>
                  <small>{topic.project} · {topic.progress}</small>
                </Link>
              ))}
            </div>
          </Disclosure>

          <div className="app-widgets" aria-label="Состояние установки">
            <Popover
              title="Фоновые задачи"
              trigger={
                <button type="button" className="app-widget">
                  <Activity size={15} aria-hidden="true" />
                  <b className="nav-label">Фоновая задача</b>
                </button>
              }
            >
              {DEMO_TASKS.length === 0 ? (
                <p className="popover-note">Фон свободен.</p>
              ) : (
                DEMO_TASKS.map((task) => <TaskRow key={task.id} task={task} />)
              )}
              <Link className="popover-link" to="/library">
                К материалам
              </Link>
            </Popover>

            <Popover
              title="Внешние модели"
              trigger={
                <button type="button" className="app-widget">
                  <Cpu size={15} aria-hidden="true" />
                  <b className="nav-label">Модели</b>
                </button>
              }
            >
              <p className="popover-note" style={{ marginTop: 0 }}>Текст · mock-text-model</p>
              <p className="popover-note">Аудио · mock-audio-model</p>
              <p className="popover-note">Фото · mock-vision-model</p>
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
              <Link className="popover-link" to="/library">
                Библиотека: 14 файлов · 3 120 страниц · 1,8 ГБ · 2 не используются
              </Link>
              <Link className="popover-link" to="/setup">
                Бот: привязан · сообщений сегодня 4 из 20
              </Link>
              <Link className="popover-link" to="/setup">
                Копия: вчера, 23:40
              </Link>
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

        <div className="app-frame">
          <header className={`app-topbar ${scrolled ? "is-scrolled" : ""}`.trim()}>
            <div className="app-topbar-inner">
              {/* Слева — место чипа «следующий шаг»: появится с проектным контекстом */}
              <span />
              <CommandPalette />
            </div>
          </header>

          <main className="app-main">
            <Outlet />
          </main>
        </div>
      </div>
    </TooltipProvider>
  );
}
