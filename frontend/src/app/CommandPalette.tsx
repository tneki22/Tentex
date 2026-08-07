import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { Dialog as RadixDialog } from "radix-ui";
import { FileText, FolderOpen, Search, SquareDashed } from "lucide-react";
import { Kbd } from "../components/ui";
import { SCREENS } from "./screens";
import { SCREEN_VIEWS } from "./views";

/**
 * Палитра поиска (Ctrl+K). Ищет по названиям — проекты, экраны, файлы, — и не
 * лезет в текст материалов: полнотекстовый поиск по фрагментам проектный, у него
 * своё место внутри проекта.
 *
 * Данные проектов и файлов пока выдуманные: API появится на этапе 3.
 */

interface PaletteItem {
  id: string;
  group: "Проекты" | "Экраны" | "Файлы";
  label: string;
  hint?: string;
  to: string;
  icon: typeof Search;
}

const DEMO_PROJECTS: PaletteItem[] = [
  { id: "p1", group: "Проекты", label: "Базы данных — экзамен", hint: "34 дня до дедлайна", to: "/projects", icon: FolderOpen },
  { id: "p2", group: "Проекты", label: "Матанализ — учебник", hint: "идёт проход 1", to: "/projects", icon: FolderOpen },
  { id: "p3", group: "Проекты", label: "ТРПС — курсовая", hint: "настройка не завершена", to: "/projects", icon: FolderOpen },
];

const DEMO_FILES: PaletteItem[] = [
  { id: "f1", group: "Файлы", label: "lections.pdf", hint: "320 страниц", to: "/library", icon: FileText },
  { id: "f2", group: "Файлы", label: "konspekt-scan.pdf", hint: "46 страниц, ocr", to: "/library", icon: FileText },
  { id: "f3", group: "Файлы", label: "voprosy.docx", hint: "список билетов", to: "/library", icon: FileText },
];

/** ё=е: иначе «Пробелы» не найдутся по «проб», а «Учёбник» — по «уче». */
function normalize(text: string): string {
  return text.toLowerCase().replaceAll("ё", "е");
}

const GROUP_ORDER: PaletteItem["group"][] = ["Проекты", "Экраны", "Файлы"];
const PER_GROUP = 7;

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const navigate = useNavigate();
  const listRef = useRef<HTMLDivElement>(null);

  const screens: PaletteItem[] = useMemo(
    () =>
      SCREENS.filter((screen) => screen.id in SCREEN_VIEWS).map((screen) => ({
        id: `s-${screen.id}`,
        group: "Экраны" as const,
        label: screen.title,
        hint: screen.summary,
        to: screen.navPath,
        icon: SquareDashed,
      })),
    [],
  );

  const results = useMemo(() => {
    const all = [...DEMO_PROJECTS, ...screens, ...DEMO_FILES];
    const needle = normalize(query.trim());
    const matched = needle ? all.filter((item) => normalize(item.label).includes(needle)) : screens;

    return GROUP_ORDER.flatMap((group) => matched.filter((item) => item.group === group).slice(0, PER_GROUP));
  }, [query, screens]);

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
        aria-label="Поиск по проектам, экранам и файлам"
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
              Поиск по названиям проектов, экранов и файлов
            </RadixDialog.Description>

            <div className="palette-input">
              <Search size={16} aria-hidden="true" />
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={onInputKeyDown}
                placeholder="Проект, экран или файл"
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
