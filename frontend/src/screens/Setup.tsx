import { Image, Bot, BrainCircuit, HardDrive, ScanText, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { EmptyState, PageHead } from "../components/ui";
import { AiSettingsSection } from "./AiSettingsSection";
import { OcrSettingsSection } from "./OcrSettingsSection";
import { SearchSettingsSection } from "./SearchSettingsSection";
import { StorageSettingsSection } from "./StorageSettingsSection";

import { BackgroundSettingsSection } from "./BackgroundSettingsSection";

const SECTIONS = [
  { id: "background", label: "Задний фон", icon: Image },
  { id: "ai", label: "ИИ", icon: BrainCircuit },
  { id: "search", label: "Поиск", icon: Search },
  { id: "ocr", label: "Распознавание", icon: ScanText },
  { id: "bot", label: "Бот", icon: Bot },
  { id: "storage", label: "Хранилище", icon: HardDrive },
] as const;

type SetupSection = typeof SECTIONS[number]["id"];

const AI_SUBSECTIONS = [
  { id: "overview", label: "Обзор" },
  { id: "providers", label: "Провайдеры" },
  { id: "models", label: "Модели" },
  { id: "defaults", label: "По умолчанию" },
  { id: "functions", label: "Функции" },
  { id: "limits", label: "Расходы" },
  { id: "usage", label: "История" },
] as const;

export type AiSettingsSubsection = typeof AI_SUBSECTIONS[number]["id"];

const OCR_SUBSECTIONS = [
  { id: "overview", label: "Обзор" },
  { id: "engines", label: "Режимы" },
  { id: "models", label: "Установка" },
  { id: "quality", label: "Качество" },
] as const;

export type OcrSettingsSubsection = typeof OCR_SUBSECTIONS[number]["id"];

const SEARCH_SUBSECTIONS = [
  { id: "overview", label: "Обзор" },
  { id: "models", label: "Модели" },
  { id: "index", label: "Индекс" },
  { id: "advanced", label: "Дополнительно" },
] as const;

export type SearchSettingsSubsection = typeof SEARCH_SUBSECTIONS[number]["id"];

const STORAGE_SUBSECTIONS = [
  { id: "overview", label: "Обзор" },
  { id: "backups", label: "Резервные копии" },
  { id: "projects", label: "Проекты" },
  { id: "maintenance", label: "Обслуживание" },
] as const;

export type StorageSettingsSubsection = typeof STORAGE_SUBSECTIONS[number]["id"];

/** Разделы без подсекций (`bot`) сюда не входят — у них нет якорей для прокрутки. */
const SUBSECTIONS: Partial<Record<SetupSection, readonly { id: string; label: string }[]>> = {
  ai: AI_SUBSECTIONS,
  ocr: OCR_SUBSECTIONS,
  search: SEARCH_SUBSECTIONS,
  storage: STORAGE_SUBSECTIONS,
};

const LAST_SETUP_KEY = "tentex-last-setup-location";

function readLastSetupLocation(): { section: SetupSection; subsection: string | null } | null {
  try {
    const parsed = JSON.parse(localStorage.getItem(LAST_SETUP_KEY) ?? "null") as { section?: string; subsection?: string } | null;
    if (!parsed || !SECTIONS.some((item) => item.id === parsed.section)) return null;
    return { section: parsed.section as SetupSection, subsection: parsed.subsection ?? null };
  } catch {
    return null;
  }
}

const FUTURE_COPY: Record<Exclude<SetupSection, "ai" | "ocr" | "search" | "background" | "storage">, { title: string; body: string }> = {
  bot: {
    title: "Бот пока не настроен",
    body: "Здесь появятся подключение Telegram, расписание сообщений и тихие часы — после отдельного серверного среза.",
  },
};

export function Setup() {
  const [searchParams, setSearchParams] = useSearchParams();
  const remembered = readLastSetupLocation();
  const rawRequested = searchParams.get("section");
  const legacyBackups = rawRequested === "backups";
  const requested = (legacyBackups ? "storage" : rawRequested) as SetupSection | null;
  const rememberedSection = remembered?.section ?? "ai";
  const active = SECTIONS.some((section) => section.id === requested)
    ? requested!
    : rememberedSection;
  const requestedSubsection = legacyBackups
    ? "backups"
    : searchParams.get("subsection") ?? (requested ? null : remembered?.subsection);
  const activeSubsections = SUBSECTIONS[active];
  const initialSubsection = activeSubsections?.some((item) => item.id === requestedSubsection)
    ? requestedSubsection!
    : (activeSubsections?.[0]?.id ?? "");
  const [activeSubsection, setActiveSubsection] = useState<string>(initialSubsection);

  useEffect(() => {
    if (legacyBackups) {
      setSearchParams({ section: "storage", subsection: "backups" }, { replace: true });
      return;
    }
    if (!requested) {
      const rememberedSubsections = SUBSECTIONS[active];
      setSearchParams(
        rememberedSubsections
          ? { section: active, subsection: rememberedSubsection(active, remembered?.subsection) }
          : { section: active },
        { replace: true },
      );
      return;
    }
    const subsections = SUBSECTIONS[active];
    if (subsections && !subsections.some((item) => item.id === requestedSubsection)) {
      setSearchParams({ section: active, subsection: subsections[0].id }, { replace: true });
    }
  }, [active, legacyBackups, requested, requestedSubsection, setSearchParams]);

  useEffect(() => {
    localStorage.setItem(LAST_SETUP_KEY, JSON.stringify({
      section: active,
      subsection: rememberedSubsection(active, requestedSubsection),
    }));
  }, [active, requestedSubsection]);

  useEffect(() => {
    const subsections = SUBSECTIONS[active];
    if (subsections?.some((item) => item.id === requestedSubsection)) {
      setActiveSubsection(requestedSubsection!);
    }
  }, [active, requestedSubsection]);

  function selectSection(section: SetupSection) {
    const subsections = SUBSECTIONS[section];
    localStorage.setItem(LAST_SETUP_KEY, JSON.stringify({ section, subsection: subsections?.[0]?.id ?? null }));
    setSearchParams(subsections ? { section, subsection: subsections[0].id } : { section });
  }

  function selectSubsection(section: SetupSection, subsection: string) {
    setActiveSubsection(subsection);
    localStorage.setItem(LAST_SETUP_KEY, JSON.stringify({ section, subsection }));
    setSearchParams({ section, subsection }, { replace: true });
    window.requestAnimationFrame(() => {
      document.getElementById(`${section}-${subsection}`)?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
  }

  const future = active === "ai" || active === "ocr" || active === "search" || active === "background" || active === "storage" ? null : FUTURE_COPY[active];

  return (
    <div className="screen setup-screen">
      <PageHead placement="topbar" title="Параметры" />
      <div className="setup-layout">
        <nav className="setup-nav" aria-label="Разделы параметров">
          {SECTIONS.map((section) => {
            const Icon = section.icon;
            const subsections = SUBSECTIONS[section.id];
            return <div className="setup-nav-group" key={section.id}>
              <button
                type="button"
                className={active === section.id ? "is-active" : ""}
                aria-current={active === section.id ? "page" : undefined}
                onClick={() => selectSection(section.id)}
              >
                <Icon size={15} aria-hidden="true" />
                {section.label}
              </button>
              {subsections && active === section.id && (
                <div className="setup-subnav" aria-label={`Подразделы «${section.label}»`}>
                  {subsections.map((item) => (
                    <a
                      key={item.id}
                      href={`#${section.id}-${item.id}`}
                      className={activeSubsection === item.id ? "is-active" : ""}
                      aria-current={activeSubsection === item.id ? "location" : undefined}
                      onClick={(event) => { event.preventDefault(); selectSubsection(section.id, item.id); }}
                    >
                      {item.label}
                    </a>
                  ))}
                </div>
              )}
            </div>;
          })}
        </nav>
        <div className="setup-content">
          {active === "ai" ? (
            <AiSettingsSection
              subsection={activeSubsection as AiSettingsSubsection}
              onActiveSubsection={setActiveSubsection}
            />
          ) : active === "ocr" ? (
            <OcrSettingsSection
              subsection={activeSubsection as OcrSettingsSubsection}
              onActiveSubsection={setActiveSubsection}
            />
          ) : active === "search" ? (
            <SearchSettingsSection
              subsection={activeSubsection as SearchSettingsSubsection}
              onActiveSubsection={setActiveSubsection}
            />
          ) : active === "storage" ? (
            <StorageSettingsSection
              subsection={activeSubsection as StorageSettingsSubsection}
              onActiveSubsection={setActiveSubsection}
            />
          ) : active === "background" ? <BackgroundSettingsSection /> : future ? (
            <EmptyState title={future.title}>
              <p>{future.body}</p>
            </EmptyState>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function rememberedSubsection(section: SetupSection, value: string | null | undefined): string {
  const subsections = SUBSECTIONS[section];
  return subsections?.some((item) => item.id === value) ? value! : subsections?.[0]?.id ?? "";
}
