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
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === "1");
  const [scrolled, setScrolled] = useState(false);
  const [aiSnapshot, setAiSnapshot] = useState<AiSettingsRead | null>(null);
  const [aiSnapshotFailed, setAiSnapshotFailed] = useState(false);
  const [titleSlot, setTitleSlot] = useState<HTMLElement | null>(null);
  const [actionsSlot, setActionsSlot] = useState<HTMLElement | null>(null);

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
