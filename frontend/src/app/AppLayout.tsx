import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import {
  Activity,
  CircleCheck,
  Cpu,
  Palette,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { Popover, Tooltip, TooltipProvider } from "../components/ui";
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
            <small>локально</small>
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
              <p className="popover-note">Фон свободен.</p>
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
              <p className="popover-note" style={{ marginTop: 0 }}>Внешние модели не настроены.</p>
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
