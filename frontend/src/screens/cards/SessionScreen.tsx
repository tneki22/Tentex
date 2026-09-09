import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Check, ExternalLink, Pencil, RotateCcw, X } from "lucide-react";
import { Link } from "react-router";
import type { CardSessionRead } from "../../api/cards";
import { Button, ErrorState, Kbd, LoadingState, Progress } from "../../components/ui";
import { useCardSession } from "../../hooks/useCardSession";

interface SessionScreenProps {
  projectId: string;
  initialSession: CardSessionRead | null;
  onExit: () => void;
}

type Grade = 1 | 2 | 3 | 4;
type Phase = "study" | "unit-summary" | "complete";

const GRADES: Array<{ value: Grade; label: string; note: string; tone: string }> = [
  { value: 1, label: "Не вспомнил", note: "Вернём в конце", tone: "danger" },
  { value: 2, label: "Частично", note: "Есть пробелы", tone: "warning" },
  { value: 3, label: "Вспомнил", note: "Ответ восстановлен", tone: "success" },
  { value: 4, label: "Легко", note: "Без усилий", tone: "accent" },
];

function useActiveSeconds(enabled: boolean) {
  const [seconds, setSeconds] = useState(0);
  const lastActivity = useRef(Date.now());

  useEffect(() => {
    if (!enabled) return;
    const markActive = () => { lastActivity.current = Date.now(); };
    const events = ["keydown", "pointerdown", "mousemove", "touchstart"] as const;
    events.forEach((event) => window.addEventListener(event, markActive, { passive: true }));
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible" && Date.now() - lastActivity.current < 300_000) {
        setSeconds((current) => current + 1);
      }
    }, 1_000);
    return () => {
      window.clearInterval(timer);
      events.forEach((event) => window.removeEventListener(event, markActive));
    };
  }, [enabled]);

  return { seconds, reset: () => setSeconds(0) };
}

function sourceLink(projectId: string, fragmentId: string): string {
  return `/projects/${projectId}/materials?fragment=${encodeURIComponent(fragmentId)}`;
}

export function SessionScreen({ projectId, initialSession, onExit }: SessionScreenProps) {
  const { session, saving, error, assess, defer, finish, retry } = useCardSession(projectId, initialSession);
  const [phase, setPhase] = useState<Phase>("study");
  const [revealed, setRevealed] = useState(false);
  const [hintOpen, setHintOpen] = useState(false);
  const [ignoreLimit, setIgnoreLimit] = useState(false);
  const timer = useActiveSeconds(Boolean(session && phase === "study" && !saving));

  const current = session?.queue[session.position];
  const completedItem = session?.queue[Math.max(0, session.position - 1)];
  const summaryUnitId = completedItem?.unit_id ?? null;
  const unitItems = useMemo(
    () => session?.queue.filter((item) => item.unit_id === summaryUnitId) ?? [],
    [session?.queue, summaryUnitId],
  );
  const completedUnit = session?.position === session?.queue.length
    || session?.queue[session.position]?.unit_id !== summaryUnitId;

  function resetCard() {
    setRevealed(false);
    setHintOpen(false);
    timer.reset();
  }

  async function record(confidence: Grade | null) {
    if (!session || !current || saving) return;
    const isUnitEnd = session.position === session.queue.length - 1
      || session.queue[session.position + 1]?.unit_id !== current.unit_id;
    const next = confidence === null
      ? await defer(timer.seconds)
      : await assess(confidence, timer.seconds);
    if (!next) return;
    resetCard();
    setPhase(isUnitEnd ? "unit-summary" : "study");
  }

  async function continueAfterUnit() {
    if (!session) return;
    if (session.position >= session.queue.length) {
      setPhase("complete");
      return;
    }
    setIgnoreLimit(true);
    setPhase("study");
    resetCard();
  }

  async function stopAtLimit() {
    await finish("complete");
    setPhase("complete");
  }

  async function finishAndExit() {
    if (session?.state === "active") await finish("complete");
    onExit();
  }

  async function cancelAndExit() {
    if (session?.state === "active") await finish("cancel");
    onExit();
  }

  async function repeatDifficult() {
    const next = await retry();
    if (!next) return;
    setIgnoreLimit(false);
    setPhase("study");
    resetCard();
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target?.matches("input, textarea, select, button, a")) return;
      if (event.key === "Escape") onExit();
      if (phase !== "study" || !current || saving) return;
      if (event.code === "Space" && !revealed) {
        event.preventDefault();
        setRevealed(true);
      } else if (event.key.toLowerCase() === "h" && current.hint) {
        setHintOpen(true);
      } else if (event.key.toLowerCase() === "s") {
        void record(null);
      } else if (revealed && /^[1-4]$/.test(event.key)) {
        void record(Number(event.key) as Grade);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  if (!session) {
    return error
      ? <ErrorState title="Не удалось продолжить сеанс" message={error}><Button variant="secondary" onClick={onExit}>Вернуться</Button></ErrorState>
      : <LoadingState label="Восстанавливаем сеанс…" />;
  }

  const counts = GRADES.map((grade) => session.queue.filter((item) => item.confidence === grade.value).length);
  const deferredCount = session.queue.filter((item) => item.state === "deferred").length;
  const difficultCount = counts[0] + counts[1] + deferredCount;
  const unitIds = [...new Set(session.queue.flatMap((item) => item.unit_id ? [item.unit_id] : []))];
  const cleanUnits = unitIds.filter((unitId) => {
    const items = session.queue.filter((item) => item.unit_id === unitId);
    return items.length > 0 && items.every((item) => item.confidence && item.confidence >= 3);
  }).length;

  if (phase === "complete" || session.position >= session.queue.length) {
    return (
      <section className="session-complete">
        <div className="session-complete-check"><Check size={26} /></div>
        <p className="eyebrow">Сеанс завершён</p>
        <h1>Результат сохранён</h1>
        <p>{session.position} из {session.queue.length} карточек разобрано. Оценки обновили аналитику, но не календарь.</p>
        <div className="session-result-grid">
          {GRADES.map((grade, index) => (
            <div key={grade.value} className={`tone-${grade.tone}`}>
              <span>{grade.label}</span><strong>{counts[index]}</strong>
            </div>
          ))}
          <div><span>Отложено</span><strong>{deferredCount}</strong></div>
          <div><span>Вопросов без ошибок</span><strong>{cleanUnits}</strong></div>
        </div>
        {error && <p className="cards-form-error" role="alert">{error}</p>}
        <div className="session-complete-actions">
          <Button onClick={() => void finishAndExit()}>Закончить</Button>
          <Button variant="secondary" disabled={!difficultCount || saving} onClick={() => void repeatDifficult()}>
            <RotateCcw size={15} /> Повторить сложные и отложенные · {difficultCount}
          </Button>
        </div>
      </section>
    );
  }

  if (phase === "unit-summary" && completedItem && completedUnit) {
    const unitCounts = GRADES.map((grade) => unitItems.filter((item) => item.confidence === grade.value).length);
    const unitDeferred = unitItems.filter((item) => item.state === "deferred").length;
    const atLimit = session.limit_reached && !ignoreLimit;
    return (
      <section className="question-summary">
        <p className="eyebrow">Карточки вопроса закончились</p>
        <h1>{completedItem.unit_title ?? "Карточки без вопроса"}</h1>
        <p>Результат уже сохранён. Отдельной итоговой оценки нет.</p>
        <div className="question-result-line">
          {GRADES.map((grade, index) => <span key={grade.value}><b>{unitCounts[index]}</b>{grade.label.toLocaleLowerCase("ru")}</span>)}
          {unitDeferred > 0 && <span><b>{unitDeferred}</b>отложено</span>}
        </div>
        {atLimit && (
          <div className="session-limit-notice">
            <strong>Выбранное время закончилось</strong>
            <p>Текущий вопрос завершён. Можно закончить сеанс или продолжить без жёсткой остановки.</p>
          </div>
        )}
        <div className="question-summary-actions">
          {completedItem.unit_id && (
            <Link className="secondary-button" to={`/projects/${projectId}?topic=${completedItem.unit_id}&tab=answer`}>
              Ответить на вопрос целиком <ExternalLink size={14} />
            </Link>
          )}
          {atLimit && <Button variant="secondary" onClick={() => void stopAtLimit()}>Завершить сейчас</Button>}
          <Button onClick={() => void continueAfterUnit()}>
            {session.position >= session.queue.length ? "К итогам" : "Следующий вопрос"}<ArrowRight size={15} />
          </Button>
        </div>
      </section>
    );
  }

  if (!current) {
    return <LoadingState label="Готовим итог сеанса…" />;
  }

  const source = current.source;
  return (
    <div className={`session-screen is-${session.pace}`}>
      <header className="session-header">
        <button type="button" className="session-exit" onClick={onExit}><X size={16} /> Выйти и продолжить позже</button>
        <div className="session-progress-copy">
          <span>{session.position + 1} из {session.queue.length}</span>
          <small>{session.pace === "fast" ? "быстрый темп" : `активно ${Math.floor((session.active_seconds + timer.seconds) / 60)} мин`}</small>
        </div>
        <Progress value={session.position} max={session.queue.length} label="Прогресс сеанса" size="thin" />
        <div className="session-tools">
          {session.pace === "calm" && (
            <Link to={`/projects/${projectId}/cards?mode=bank&card=${current.card_id}`}>
              <Pencil size={14} /> Изменить
            </Link>
          )}
          <button type="button" disabled={saving} onClick={() => void record(null)}>Отложить <Kbd>S</Kbd></button>
          <button type="button" disabled={saving} onClick={() => void cancelAndExit()}>Завершить сеанс</button>
        </div>
      </header>

      <main className="session-content">
        <p className="session-breadcrumb">{current.unit_title ?? "Без вопроса"}</p>
        <article className="session-card" key={`${session.id}:${current.card_id}`}>
          <header className="session-card-header">
            <span>{current.unit_title ?? "Личная карточка"}</span>
            <small>{session.pace === "fast" ? "клавиши 1–4" : "оцените, насколько легко вспомнился ответ"}</small>
          </header>
          <div className="session-card-front"><h1>{current.front}</h1></div>

          {current.hint && !revealed && (
            <div className="session-hint-area">
              {hintOpen && <p>{current.hint}</p>}
              <Button variant="ghost" onClick={() => setHintOpen(true)} disabled={hintOpen}>
                {hintOpen ? "Подсказка показана" : "Показать подсказку"} <Kbd>H</Kbd>
              </Button>
            </div>
          )}

          {!revealed ? (
            <div className="session-reveal-area">
              <p>Сначала сформулируйте ответ про себя, затем сравните.</p>
              <Button onClick={() => setRevealed(true)}>Показать ответ <Kbd>Space</Kbd></Button>
            </div>
          ) : (
            <div className="session-card-back">
              <section><h2>Ответ</h2><p>{current.back}</p></section>
              {session.pace === "calm" ? (
                <div className="session-sources">
                  {source.fragment_id ? (
                    <Link to={sourceLink(projectId, source.fragment_id)}><ExternalLink size={13} />{source.label}</Link>
                  ) : <span className={source.lost ? "is-lost" : ""}>{source.label}</span>}
                </div>
              ) : (
                <details className="session-secondary"><summary>Подсказка и источник</summary><p>{current.hint || "Без подсказки"}</p><p>{source.label}</p></details>
              )}
              <div className="session-grade-area">
                <h2>Как вспомнилось?</h2>
                <div className="session-grade-buttons">
                  {GRADES.map((grade) => (
                    <button type="button" disabled={saving} className={`tone-${grade.tone}`} key={grade.value} onClick={() => void record(grade.value)}>
                      <span><Kbd>{grade.value}</Kbd>{grade.label}</span><small>{grade.note}</small>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </article>
        {error && <p className="cards-form-error" role="alert">{error}</p>}
      </main>
    </div>
  );
}
