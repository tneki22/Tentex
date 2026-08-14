import { Bot, BrainCircuit, DatabaseBackup, HardDrive } from "lucide-react";
import { useEffect } from "react";
import { useSearchParams } from "react-router";
import { EmptyState, PageHead } from "../components/ui";
import { AiSettingsSection } from "./AiSettingsSection";

const SECTIONS = [
  { id: "ai", label: "ИИ", icon: BrainCircuit },
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
  { id: "limits", label: "Лимиты" },
  { id: "usage", label: "Расход и журнал" },
] as const;

export type AiSettingsSubsection = typeof AI_SUBSECTIONS[number]["id"];

const FUTURE_COPY: Record<Exclude<SetupSection, "ai">, { title: string; body: string }> = {
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
  const requestedSubsection = searchParams.get("subsection") as AiSettingsSubsection | null;
  const activeSubsection = AI_SUBSECTIONS.some((item) => item.id === requestedSubsection)
    ? requestedSubsection!
    : "overview";

  useEffect(() => {
    if (!requested) {
      setSearchParams({ section: "ai", subsection: "overview" }, { replace: true });
      return;
    }
    if (active === "ai" && !AI_SUBSECTIONS.some((item) => item.id === requestedSubsection)) {
      setSearchParams({ section: "ai", subsection: "overview" }, { replace: true });
    }
  }, [active, requested, requestedSubsection, setSearchParams]);

  function selectSection(section: SetupSection) {
    setSearchParams(section === "ai" ? { section, subsection: activeSubsection } : { section });
  }

  function selectAiSubsection(subsection: AiSettingsSubsection) {
    setSearchParams({ section: "ai", subsection });
  }

  const future = active === "ai" ? null : FUTURE_COPY[active];

  return (
    <div className="screen setup-screen">
      <PageHead placement="topbar" title="Параметры" />
      <div className="setup-layout">
        <nav className="setup-nav" aria-label="Разделы параметров">
          {SECTIONS.map((section) => {
            const Icon = section.icon;
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
              {section.id === "ai" && active === "ai" && (
                <div className="setup-subnav" aria-label="Подразделы ИИ">
                  {AI_SUBSECTIONS.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className={activeSubsection === item.id ? "is-active" : ""}
                      aria-current={activeSubsection === item.id ? "page" : undefined}
                      onClick={() => selectAiSubsection(item.id)}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              )}
            </div>;
          })}
        </nav>
        <div className="setup-content">
          {active === "ai" ? (
            <AiSettingsSection subsection={activeSubsection} />
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
