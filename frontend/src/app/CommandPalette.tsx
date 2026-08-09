import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { Dialog as RadixDialog } from "radix-ui";
import { FolderOpen, Search, SquareDashed } from "lucide-react";
import { listProjects, type ProjectSummary } from "../api/projects";
import { Kbd } from "../components/ui";
import { SCREENS } from "./screens";
import { SCREEN_VIEWS } from "./views";

/**
 * Палитра поиска (Ctrl+K). Ищет по названиям — проекты, экраны, файлы, — и не
 * лезет в текст материалов: полнотекстовый поиск по фрагментам проектный, у него
 * своё место внутри проекта.
 *
 * Файлы появятся здесь после подключения Материалов на этапе 5.
 */

interface PaletteItem {
  id: string;
  group: "Проекты" | "Экраны";
  label: string;
  hint?: string;
  to: string;
  icon: typeof Search;
}

/** ё=е: иначе «Пробелы» не найдутся по «проб», а «Учёбник» — по «уче». */
function normalize(text: string): string {
  return text.toLowerCase().replaceAll("ё", "е");
}

const GROUP_ORDER: PaletteItem["group"][] = ["Проекты", "Экраны"];
const PER_GROUP = 7;

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const navigate = useNavigate();
  const listRef = useRef<HTMLDivElement>(null);

  const screens: PaletteItem[] = useMemo(
    () =>
      SCREENS.filter((screen) => screen.id in SCREEN_VIEWS && !screen.path.includes(":"))
        .map((screen) => ({
        id: `s-${screen.id}`,
        group: "Экраны" as const,
        label: screen.title,
        hint: screen.summary,
        to: screen.navPath,
        icon: SquareDashed,
      })),
    [],
  );

  const projectItems: PaletteItem[] = useMemo(() => projects.map((project) => ({
    id: `p-${project.id}`,
    group: "Проекты" as const,
    label: project.name,
    hint: project.status === "active" ? "активный проект" : project.status === "archived" ? "в архиве" : "завершён",
    to: `/projects/${project.id}`,
    icon: FolderOpen,
  })), [projects]);

  const results = useMemo(() => {
    const all = [...projectItems, ...screens];
    const needle = normalize(query.trim());
    const matched = needle ? all.filter((item) => normalize(item.label).includes(needle)) : screens;

    return GROUP_ORDER.flatMap((group) => matched.filter((item) => item.group === group).slice(0, PER_GROUP));
  }, [projectItems, query, screens]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    void listProjects(controller.signal).then(setProjects).catch(() => undefined);
    return () => controller.abort();
  }, [open]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    setActive(0);
  }, [query]);

  function go(item: PaletteItem) {
    setOpen(false);
    setQuery("");
    navigate(item.to);
  }

  function onInputKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((prev) => (results.length === 0 ? 0 : (prev + 1) % results.length));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((prev) => (results.length === 0 ? 0 : (prev - 1 + results.length) % results.length));
    } else if (event.key === "Enter" && results[active]) {
      event.preventDefault();
      go(results[active]);
    }
  }

  let lastGroup: string | null = null;

  return (
    <>
      <button
        type="button"
        className="topbar-search"
        onClick={() => setOpen(true)}
        aria-label="Поиск по проектам и экранам"
      >
        <Search size={15} aria-hidden="true" />
        Поиск
        <Kbd>Ctrl K</Kbd>
      </button>

      <RadixDialog.Root open={open} onOpenChange={setOpen}>
        <RadixDialog.Portal>
          <RadixDialog.Overlay className="dialog-overlay" />
          <RadixDialog.Content className="palette" aria-label="Поиск">
            <RadixDialog.Title hidden>Поиск</RadixDialog.Title>
            <RadixDialog.Description hidden>
              Поиск по названиям проектов и экранов
            </RadixDialog.Description>

            <div className="palette-input">
              <Search size={16} aria-hidden="true" />
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={onInputKeyDown}
                placeholder="Проект или экран"
                aria-label="Что искать"
              />
              <Kbd>Esc</Kbd>
            </div>

            <div className="palette-list" ref={listRef} role="listbox" aria-label="Результаты">
              {results.length === 0 && <p className="palette-empty">Ничего с таким названием</p>}
              {results.map((item, index) => {
                const header = item.group !== lastGroup ? item.group : null;
                lastGroup = item.group;
                return (
                  <div key={item.id}>
                    {header && <p className="palette-group">{header}</p>}
                    <button
                      type="button"
                      role="option"
                      aria-selected={index === active}
                      className={`palette-item ${index === active ? "is-active" : ""}`.trim()}
                      onMouseEnter={() => setActive(index)}
                      onClick={() => go(item)}
                    >
                      <item.icon size={15} aria-hidden="true" />
                      <span className="palette-item-label">{item.label}</span>
                      {item.hint && <span className="palette-item-hint">{item.hint}</span>}
                    </button>
                  </div>
                );
              })}
            </div>
          </RadixDialog.Content>
        </RadixDialog.Portal>
      </RadixDialog.Root>
    </>
  );
}
