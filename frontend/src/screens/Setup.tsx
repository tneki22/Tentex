import { Bot, BrainCircuit, DatabaseBackup, HardDrive, ScanText } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { EmptyState, PageHead } from "../components/ui";
import { AiSettingsSection } from "./AiSettingsSection";
import { OcrSettingsSection } from "./OcrSettingsSection";

const SECTIONS = [
  { id: "ai", label: "ИИ", icon: BrainCircuit },
  { id: "ocr", label: "Распознавание", icon: ScanText },
  { id: "bot", label: "Бот", icon: Bot },
  { id: "backups", label: "Резервные копии", icon: DatabaseBackup },
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
  { id: "models", label: "Модели" },
  { id: "quality", label: "Качество" },
] as const;

export type OcrSettingsSubsection = typeof OCR_SUBSECTIONS[number]["id"];

/** Разделы без подсекций (`bot`/`backups`/`storage`) сюда не входят — у них нет якорей для прокрутки. */
const SUBSECTIONS: Partial<Record<SetupSection, readonly { id: string; label: string }[]>> = {
  ai: AI_SUBSECTIONS,
  ocr: OCR_SUBSECTIONS,
};

const FUTURE_COPY: Record<Exclude<SetupSection, "ai" | "ocr">, { title: string; body: string }> = {
  bot: {
    title: "Бот пока не настроен",
    body: "Здесь появятся подключение Telegram, расписание сообщений и тихие часы — после отдельного серверного среза.",
  },
  backups: {
    title: "Резервные копии появятся позже",
    body: "Раздел будет управлять расписанием, хранением копий и ручным запуском. Сейчас фиктивных дат и статусов нет.",
  },
  storage: {
    title: "Хранилище пока не настраивается",
    body: "Здесь появятся папка данных, занятое место и правила очистки, когда для них будет настоящий API.",
  },
};

export function Setup() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get("section") as SetupSection | null;
  const active = SECTIONS.some((section) => section.id === requested) ? requested! : "ai";
  const requestedSubsection = searchParams.get("subsection");
  const activeSubsections = SUBSECTIONS[active];
  const initialSubsection = activeSubsections?.some((item) => item.id === requestedSubsection)
    ? requestedSubsection!
    : (activeSubsections?.[0]?.id ?? "");
  const [activeSubsection, setActiveSubsection] = useState<string>(initialSubsection);

  useEffect(() => {
    if (!requested) {
      setSearchParams({ section: "ai", subsection: "overview" }, { replace: true });
      return;
    }
    const subsections = SUBSECTIONS[active];
    if (subsections && !subsections.some((item) => item.id === requestedSubsection)) {
      setSearchParams({ section: active, subsection: subsections[0].id }, { replace: true });
    }
  }, [active, requested, requestedSubsection, setSearchParams]);

  useEffect(() => {
    const subsections = SUBSECTIONS[active];
    if (subsections?.some((item) => item.id === requestedSubsection)) {
      setActiveSubsection(requestedSubsection!);
    }
  }, [active, requestedSubsection]);

  function selectSection(section: SetupSection) {
    const subsections = SUBSECTIONS[section];
    setSearchParams(subsections ? { section, subsection: subsections[0].id } : { section });
  }

  function selectSubsection(section: SetupSection, subsection: string) {
    setActiveSubsection(subsection);
    setSearchParams({ section, subsection }, { replace: true });
    window.requestAnimationFrame(() => {
      document.getElementById(`${section}-${subsection}`)?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
  }

  const future = active === "ai" || active === "ocr" ? null : FUTURE_COPY[active];

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
          ) : future ? (
            <EmptyState title={future.title}>
              <p>{future.body}</p>
            </EmptyState>
          ) : null}
        </div>
      </div>
    </div>
  );
}
