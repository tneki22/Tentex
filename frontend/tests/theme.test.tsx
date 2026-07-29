import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ThemeToggle } from "../src/app/ThemeToggle";

describe("переключатель темы", () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  afterEach(() => {
    delete document.documentElement.dataset.theme;
  });

  it("ходит по кругу: система → светлая → тёмная → система", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);

    expect(document.documentElement.dataset.theme).toBeUndefined();

    await user.click(screen.getByRole("button", { name: "Тема: как в системе" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("tentex:theme")).toBe("light");

    await user.click(screen.getByRole("button", { name: "Тема: светлая" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("tentex:theme")).toBe("dark");

    await user.click(screen.getByRole("button", { name: "Тема: тёмная" }));
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(localStorage.getItem("tentex:theme")).toBeNull();
  });

  it("поднимает сохранённую тему при загрузке", () => {
    localStorage.setItem("tentex:theme", "dark");

    render(<ThemeToggle />);

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(screen.getByRole("button", { name: "Тема: тёмная" })).toBeInTheDocument();
  });
});
