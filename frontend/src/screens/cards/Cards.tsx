import { useEffect, useMemo, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router";
import type { CardSessionRead } from "../../api/cards";
import { getProject } from "../../api/projects";
import { ProjectNav } from "../../components/domain";
import { Button, ErrorState, LoadingState, StatusBadge, Tooltip } from "../../components/ui";
import { useCardsOverview } from "../../hooks/useCardsOverview";
import { BankMode } from "./BankMode";
import { CreationMode, type CreationPath } from "./CreationMode";
import { RepetitionMode } from "./RepetitionMode";
import { SessionScreen } from "./SessionScreen";

type CardMode = "repetition" | "creation" | "bank";

const MODES: Array<{ value: CardMode; label: string }> = [
  { value: "repetition", label: "Повторение" },
  { value: "creation", label: "Создание" },
  { value: "bank", label: "Банк" },
];

const GRADE_LABELS = ["Не вспомнил", "Частично", "Вспомнил", "Легко"];

function relativeTime(value: string | null): string {
  if (!value) return "без оценки";
  const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return "только что";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} мин назад`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} ч назад`;
  return `${Math.floor(seconds / 86400)} дн назад`;
}

function queryMode(value: string | null): CardMode {
  return value === "creation" || value === "bank" ? value : "repetition";
}

export function Cards() {
  const { projectId = "demo" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [period, setPeriod] = useState<7 | 30>(7);
  const [projectName, setProjectName] = useState("Карточки проекта");
  const [session, setSession] = useState<CardSessionRead | null>(null);
  const mode = queryMode(searchParams.get("mode"));
  const inSession = searchParams.has("session");
  const { data: overview, loading, error, refresh } = useCardsOverview(projectId, period);

  useEffect(() => {
    const controller = new AbortController();
    void getProject(projectId, controller.signal)
      .then((detail) => setProjectName(detail.project.name ?? "Без названия"))
      .catch(() => undefined);
    return () => controller.abort();
  }, [projectId]);

  const programCount = useMemo(() => overview?.units.length ?? 0, [overview]);

  function selectMode(next: CardMode, extra: Record<string, string> = {}) {
    setSession(null);
    setSearchParams(new URLSearchParams({ mode: next, ...extra }));
  }

  function openCreation(path: CreationPath, unitId?: string | null) {
    const extra: Record<string, string> = { path };
    if (unitId) extra.unit = unitId;
    selectMode("creation", extra);
  }

  function openBank(cardId?: string) {
    selectMode("bank", cardId ? { card: cardId } : {});
  }

  function openSession(next: CardSessionRead | null = null) {
    setSession(next);
    setSearchParams({ mode: "repetition", session: next?.id ?? "active" });
  }

  function exitSession() {
    setSession(null);
    setSearchParams({ mode: "repetition" });
    refresh();
  }

  return (
    <div className="cards-screen">
      <aside className="cards-project-panel">
        <header className="cards-project-title">
          <Tooltip label="Вернуться в рабочую область">
            <Link className="workspace-back-button" to={`/projects/${projectId}`} aria-label="Вернуться в рабочую область">
              <ArrowLeft size={15} />
            </Link>
          </Tooltip>
          <strong>{projectName}</strong>
        </header>

        <nav className="cards-mode-switcher" aria-label="Режим карточек">
          {MODES.map((item) => (
            <button
              type="button"
              className={mode === item.value && !inSession ? "is-active" : ""}
              key={item.value}
              aria-current={mode === item.value && !inSession ? "page" : undefined}
              onClick={() => selectMode(item.value)}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <section className="cards-recent" aria-label="Недавние карточки">
          <header><span>Недавние карточки</span><small>{overview?.recent_cards.length ?? 0}</small></header>
          <div className="cards-recent-list">
            {overview?.recent_cards.length ? overview.recent_cards.map((card) => (
              <button type="button" className="cards-recent-item" key={card.id} onClick={() => openBank(card.id)}>
                <span className="cards-recent-front">{card.front}</span>
                <span className="cards-recent-meta">
                  <StatusBadge tone={card.last_confidence && card.last_confidence <= 2 ? "warning" : "success"}>
                    {card.last_confidence ? GRADE_LABELS[card.last_confidence - 1] : "Без оценки"}
                  </StatusBadge>
                  <small>{relativeTime(card.last_reviewed_at)}</small>
                </span>
                <span className="cards-recent-question">{card.unit?.title ?? "Без вопроса"}</span>
              </button>
            )) : <p className="cards-recent-empty">После первого ответа здесь появятся последние карточки.</p>}
          </div>
        </section>

        <ProjectNav
          projectId={projectId}
          active="cards"
          counts={{ program: programCount, cards: overview?.active_card_count ?? 0 }}
          className="cards-project-nav"
        />
      </aside>

      <main className={`cards-main ${inSession ? "is-session" : ""}`.trim()}>
        {inSession ? (
          <SessionScreen projectId={projectId} initialSession={session} onExit={exitSession} />
        ) : loading && !overview ? (
          <LoadingState label="Загружаем карточки…" />
        ) : error || !overview ? (
          <ErrorState title="Не удалось открыть карточки" message={error || "Нет данных"}>
            <Button variant="secondary" onClick={refresh}>Повторить</Button>
          </ErrorState>
        ) : mode === "repetition" ? (
          <RepetitionMode
            projectId={projectId}
            overview={overview}
            period={period}
            onPeriodChange={setPeriod}
            onStart={openSession}
            onContinue={() => openSession()}
            onOpenBank={openBank}
            onCreate={(unitId) => openCreation("manual", unitId)}
          />
        ) : mode === "creation" ? (
          <CreationMode
            projectId={projectId}
            units={overview.units}
            initialPath={(searchParams.get("path") as CreationPath | null) ?? null}
            initialUnitId={searchParams.get("unit")}
            fragmentId={searchParams.get("fragment")}
            onOpenBank={openBank}
            onChanged={refresh}
          />
        ) : (
          <BankMode
            projectId={projectId}
            initialCardId={searchParams.get("card")}
            onCreate={(unitId) => openCreation("manual", unitId)}
            onChanged={refresh}
          />
        )}
      </main>
    </div>
  );
}
