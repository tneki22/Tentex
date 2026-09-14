import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { Dialog as RadixDialog } from "radix-ui";
import { FileText, FolderOpen, Search, SlidersHorizontal, SquareDashed } from "lucide-react";
import { listProjects, type ProjectSummary } from "../api/projects";
import { listLibraryMaterials, type LibraryMaterialRead } from "../api/materials";
import { Kbd } from "../components/ui";
import { SCREENS } from "./screens";
import { SCREEN_VIEWS } from "./views";

/**
 * Палитра поиска (Ctrl+X — Ctrl+K занят адресной строкой Chrome). Ищет по
 * названиям — проекты, материалы Библиотеки, разделы Параметров и экраны, —
 * и не лезет в текст материалов: полнотекстовый поиск по фрагментам
 * проектный, у него своё место внутри проекта. Пустой запрос показывает
 * недавно открытое отсюда же, а не статичный список по умолчанию.
 */

interface PaletteItem {
  id: string;
  group: "Проекты" | "Материалы" | "Параметры" | "Экраны";
  label: string;
  hint?: string;
  to: string;
  icon: typeof Search;
}

interface RecentEntry {
  id: string;
  group: PaletteItem["group"];
  label: string;
  hint?: string;
  to: string;
}

/** ё=е: иначе «Пробелы» не найдутся по «проб», а «Учёбник» — по «уче». */
function normalize(text: string): string {
  return text.toLowerCase().replaceAll("ё", "е");
}

const GROUP_ORDER: PaletteItem["group"][] = ["Проекты", "Материалы", "Параметры", "Экраны"];
const GROUP_ICON: Record<PaletteItem["group"], typeof Search> = {
  "Проекты": FolderOpen,
  "Материалы": FileText,
  "Параметры": SlidersHorizontal,
  "Экраны": SquareDashed,
};
const PER_GROUP = 7;
const RECENT_KEY = "tentex.palette.recent";
const RECENT_LIMIT = 7;

function loadRecent(): RecentEntry[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? (parsed as RecentEntry[]) : [];
  } catch {
    return [];
  }
}

function saveRecent(entries: RecentEntry[]) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(entries));
  } catch {
    // приватный режим или недоступный localStorage — просто не запоминаем
  }
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;
}

const STATUS_HINTS: Record<LibraryMaterialRead["status"], string> = {
  ready_to_process: "не разобран",
  queued: "в очереди",
  processing: "разбирается",
  paused: "на паузе",
  needs_input: "нужен выбор",
  ready: "готов",
  failed: "ошибка разбора",
};

const SETTINGS_ITEMS: { label: string; to: string }[] = [
  { label: "Параметры → ИИ → Обзор", to: "/setup?section=ai&subsection=overview" },
  { label: "Параметры → ИИ → Провайдеры", to: "/setup?section=ai&subsection=providers" },
  { label: "Параметры → ИИ → Модели", to: "/setup?section=ai&subsection=models" },
  { label: "Параметры → ИИ → По умолчанию", to: "/setup?section=ai&subsection=defaults" },
  { label: "Параметры → ИИ → Функции", to: "/setup?section=ai&subsection=functions" },
  { label: "Параметры → ИИ → Расходы", to: "/setup?section=ai&subsection=limits" },
  { label: "Параметры → ИИ → История", to: "/setup?section=ai&subsection=usage" },
  { label: "Параметры → Распознавание → Обзор", to: "/setup?section=ocr&subsection=overview" },
  { label: "Параметры → Распознавание → Режимы", to: "/setup?section=ocr&subsection=engines" },
  { label: "Параметры → Распознавание → Модели", to: "/setup?section=ocr&subsection=models" },
  { label: "Параметры → Распознавание → Качество", to: "/setup?section=ocr&subsection=quality" },
  { label: "Параметры → Бот", to: "/setup?section=bot" },
  { label: "Параметры → Резервные копии", to: "/setup?section=backups" },
  { label: "Параметры → Хранилище", to: "/setup?section=storage" },
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [materials, setMaterials] = useState<LibraryMaterialRead[]>([]);
  const [recent, setRecent] = useState<RecentEntry[]>(() => loadRecent());
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

  const materialItems: PaletteItem[] = useMemo(() => materials.map((material) => ({
    id: `m-${material.id}`,
    group: "Материалы" as const,
    label: material.original_name,
    hint: material.usage.length > 0
      ? `в ${material.usage.length} проект${material.usage.length === 1 ? "е" : material.usage.length < 5 ? "ах" : "ах"}`
      : STATUS_HINTS[material.status],
    to: `/library/${material.id}`,
    icon: FileText,
  })), [materials]);

  const settingsItems: PaletteItem[] = useMemo(() => SETTINGS_ITEMS.map((entry, index) => ({
    id: `set-${index}`,
    group: "Параметры" as const,
    label: entry.label,
    to: entry.to,
    icon: SlidersHorizontal,
  })), []);

  const recentItems: PaletteItem[] = useMemo(() => recent.map((entry) => ({
    ...entry,
    icon: GROUP_ICON[entry.group],
  })), [recent]);

  const showingRecent = query.trim() === "" && recentItems.length > 0;

  const results = useMemo(() => {
    const needle = normalize(query.trim());
    if (!needle) {
      return recentItems.length > 0 ? recentItems : screens;
    }
    const all = [...projectItems, ...materialItems, ...settingsItems, ...screens];
    const matched = all.filter((item) => normalize(item.label).includes(needle));
    return GROUP_ORDER.flatMap((group) => matched.filter((item) => item.group === group).slice(0, PER_GROUP));
  }, [projectItems, materialItems, settingsItems, query, screens, recentItems]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    void listProjects(controller.signal).then(setProjects).catch(() => undefined);
    void listLibraryMaterials(controller.signal).then(setMaterials).catch(() => undefined);
    return () => controller.abort();
  }, [open]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "x") {
        if (isEditableTarget(event.target)) return;
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
    const nextRecent = [
      { id: item.id, group: item.group, label: item.label, hint: item.hint, to: item.to },
      ...recent.filter((entry) => entry.id !== item.id),
    ].slice(0, RECENT_LIMIT);
    setRecent(nextRecent);
    saveRecent(nextRecent);
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
        aria-label="Поиск по проектам, материалам и параметрам"
      >
        <Search size={15} aria-hidden="true" />
        Поиск
        <Kbd>Ctrl X</Kbd>
      </button>

      <RadixDialog.Root open={open} onOpenChange={setOpen}>
        <RadixDialog.Portal>
          <RadixDialog.Overlay className="dialog-overlay" />
          <RadixDialog.Content className="palette" aria-label="Поиск">
            <RadixDialog.Title hidden>Поиск</RadixDialog.Title>
            <RadixDialog.Description hidden>
              Поиск по названиям проектов, материалов, разделов параметров и экранов
            </RadixDialog.Description>

            <div className="palette-input">
              <Search size={16} aria-hidden="true" />
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={onInputKeyDown}
                placeholder="Проект, материал, параметр или экран"
                aria-label="Что искать"
              />
              <Kbd>Esc</Kbd>
            </div>

            <div className="palette-list" ref={listRef} role="listbox" aria-label="Результаты">
              {results.length === 0 && <p className="palette-empty">Ничего с таким названием</p>}
              {results.length > 0 && showingRecent && <p className="palette-group">Недавние</p>}
              {results.map((item, index) => {
                const header = !showingRecent && item.group !== lastGroup ? item.group : null;
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
