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

  useEffect(() => {
    if (requested) return;
    setSearchParams({ section: "ai" }, { replace: true });
  }, [requested, setSearchParams]);

  function selectSection(section: SetupSection) {
    setSearchParams({ section });
  }

  const future = active === "ai" ? null : FUTURE_COPY[active];

  return (
    <div className="screen setup-screen">
      <PageHead placement="topbar" title="Параметры" />
      <div className="setup-layout">
        <nav className="setup-nav" aria-label="Разделы параметров">
          {SECTIONS.map((section) => {
            const Icon = section.icon;
            return (
              <button
                key={section.id}
                type="button"
                className={active === section.id ? "is-active" : ""}
                aria-current={active === section.id ? "page" : undefined}
                onClick={() => selectSection(section.id)}
              >
                <Icon size={15} aria-hidden="true" />
                {section.label}
              </button>
            );
          })}
        </nav>
        <div className="setup-content">
          {active === "ai" ? (
            <AiSettingsSection />
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
