import { NavLink, Outlet } from "react-router";
import { SCREEN_GROUPS, SCREENS } from "./screens";
import { ThemeToggle } from "./ThemeToggle";

export function AppLayout() {
  return (
    <div className="app-shell">
      <nav className="app-nav" aria-label="Экраны">
        <div className="app-brand">
          <strong>Tentex</strong>
          <small>этап 0</small>
        </div>

        {SCREEN_GROUPS.map((group) => {
          const screens = SCREENS.filter((screen) => screen.group === group);
          if (screens.length === 0) return null;
          return (
            <section className="app-nav-group" key={group}>
              <h2>{group}</h2>
              {screens.map((screen) => (
                <NavLink
                  key={screen.id}
                  to={screen.navPath}
                  end={screen.path === "/projects/:projectId"}
                  className={({ isActive }) =>
                    `app-nav-link ${isActive ? "is-active" : ""}`.trim()}
                >
                  <screen.icon size={15} aria-hidden="true" />
                  {screen.title}
                </NavLink>
              ))}
            </section>
          );
        })}

        <div className="app-nav-footer">
          <span>14 экранов · §21</span>
          <ThemeToggle />
        </div>
      </nav>

      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
