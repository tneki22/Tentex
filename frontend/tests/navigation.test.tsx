import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { App } from "../src/App";
import { SCREENS } from "../src/app/screens";

function renderApp(initialPath = "/") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <App />
    </MemoryRouter>,
  );
}

describe("навигация этапа 0", () => {
  it("показывает ссылку на каждый экран из реестра", () => {
    renderApp();
    const nav = screen.getByRole("navigation", { name: "Экраны" });

    for (const meta of SCREENS) {
      expect(nav).toHaveTextContent(meta.title);
    }
  });

  it("с корня уводит на «Проекты»", () => {
    renderApp();

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Проекты");
  });

  it("открывает экран по клику в навигации", async () => {
    const user = userEvent.setup();
    renderApp();

    await user.click(screen.getByRole("link", { name: /Карта покрытия/ }));

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Карта покрытия");
  });

  it("каждый экран открывается по своему пути", () => {
    for (const meta of SCREENS) {
      const view = renderApp(meta.navPath);
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(meta.title);
      view.unmount();
    }
  });
});
