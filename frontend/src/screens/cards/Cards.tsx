import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { ArrowLeft, CalendarDays, Files, Layers, ListTree, Settings } from "lucide-react";
import { StatusBadge, Tooltip } from "../../components/ui";
import { RepetitionMode, type SessionConfig } from "./RepetitionMode";
import { CreationMode, type CreationPath } from "./CreationMode";
import { BankMode } from "./BankMode";
import { SessionScreen } from "./SessionScreen";
import { GRADES, QUEUE, RECENT_REVIEWS, type RecentReview, type StudyCard } from "./mockCards";

type CardMode = "repetition" | "creation" | "bank";

const MODES: Array<{ value: CardMode; label: string }> = [
  { value: "repetition", label: "Повторение" },
  { value: "creation", label: "Создание" },
  { value: "bank", label: "Банк" },
];

function resultTone(result: RecentReview["result"]) {
  return GRADES.find((grade) => grade.value === result)?.tone ?? "neutral";
}

export function Cards() {
  const { projectId = "demo" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [mode, setMode] = useState<CardMode>("repetition");
  const [inSession, setInSession] = useState(searchParams.get("session") === "today");
  const [sessionConfig, setSessionConfig] = useState<SessionConfig | null>(null);
  const [creationPath, setCreationPath] = useState<CreationPath | null>(null);
  const [recent, setRecent] = useState(RECENT_REVIEWS);

  function selectMode(next: CardMode) {
    setMode(next);
    setInSession(false);
    setSearchParams({});
    if (next !== "creation") setCreationPath(null);
  }

  function openCreation(path: CreationPath) {
    setCreationPath(path);
    setMode("creation");
    setInSession(false);
  }

  function startSession(config?: SessionConfig) {
    setSessionConfig(config ?? null);
    setInSession(true);
  }

  function recordReview(card: StudyCard, result: 1 | 2 | 3 | 4) {
    const grade = GRADES.find((candidate) => candidate.value === result);
    const question = QUEUE.find((item) => item.id === card.questionId);
    setRecent((current) => [
      {
        id: `${card.id}-${Date.now()}`,
        front: card.front,
        question: question?.title ?? card.questionId,
        result,
        nextDue: grade?.interval ?? "позже",
      },
      ...current,
    ].slice(0, 6));
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
          <strong>Базы данных — экзамен</strong>
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

        <section className="cards-recent" aria-label="Последние разобранные карточки">
          <header>
            <span>Недавние карточки</span>
            <small>{recent.length}</small>
          </header>
          <div className="cards-recent-list">
            {recent.map((item) => (
              <button type="button" className="cards-recent-item" key={item.id} onClick={() => selectMode("bank")}>
                <span className="cards-recent-front">{item.front}</span>
                <span className="cards-recent-meta">
                  <StatusBadge tone={resultTone(item.result)}>{GRADES[item.result - 1].label}</StatusBadge>
                  <small>{item.nextDue}</small>
                </span>
                <span className="cards-recent-question">{item.question}</span>
              </button>
            ))}
          </div>
        </section>

        <nav className="workspace-project-nav cards-project-nav" aria-label="Разделы проекта">
          <Link className="workspace-project-link" to={`/projects/${projectId}/materials`}><Files size={15} /><span>Материалы</span><small>3</small></Link>
          <Link className="workspace-project-link" to={`/projects/${projectId}/program`}><ListTree size={15} /><span>Вопросы экзамена</span><small>10</small></Link>
          <Link className="workspace-project-link" to={`/projects/${projectId}/plan`}><CalendarDays size={15} /><span>План подготовки</span><small>7 дней</small></Link>
          <span className="workspace-project-link is-active"><Layers size={15} /><span>Карточки</span><small>31</small></span>
          <button type="button" disabled><Settings size={15} /><span>Настройки</span></button>
        </nav>
      </aside>

      <main className={`cards-main ${inSession ? "is-session" : ""}`.trim()}>
        {inSession ? (
          <SessionScreen
            projectId={projectId}
            initialQueue={sessionConfig ? QUEUE.filter((item) => sessionConfig.questionIds.includes(item.id)) : QUEUE}
            pace={sessionConfig?.pace ?? "calm"}
            onExit={() => {
              setInSession(false);
              setSearchParams({});
            }}
            onReviewed={recordReview}
          />
        ) : mode === "repetition" ? (
          <RepetitionMode onStart={startSession} />
        ) : mode === "creation" ? (
          <CreationMode
            key={creationPath ?? "choose"}
            projectId={projectId}
            initialPath={creationPath}
            onOpenBank={() => selectMode("bank")}
            onStartStudy={() => startSession({ questionIds: QUEUE.slice(0, 2).map((item) => item.id), pace: "calm", duration: "5" })}
          />
        ) : (
          <BankMode
            onCreate={() => openCreation("manual")}
            onGenerate={() => openCreation("ai")}
          />
        )}
      </main>
    </div>
  );
}
