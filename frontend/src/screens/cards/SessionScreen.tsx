import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { ArrowRight, Check, ExternalLink, Pencil, RotateCcw, Undo2, X } from "lucide-react";
import { Button, Dialog, Field, Kbd, Progress } from "../../components/ui";
import { GRADES, type QueueQuestion, type StudyCard } from "./mockCards";

interface SessionScreenProps {
  projectId: string;
  initialQueue: QueueQuestion[];
  pace: "calm" | "fast" | "ticket";
  onExit: () => void;
  onReviewed: (card: StudyCard, result: 1 | 2 | 3 | 4) => void;
}

type Grade = 1 | 2 | 3 | 4;
type Phase = "study" | "question-summary" | "complete";

interface Attempt {
  cardId: string;
  questionId: string;
  grade: Grade | null;
}

interface Snapshot {
  questionIndex: number;
  cardIndex: number;
  attempts: Attempt[];
}

export function SessionScreen({ projectId, initialQueue, pace, onExit, onReviewed }: SessionScreenProps) {
  const [sessionQueue, setSessionQueue] = useState<QueueQuestion[]>(initialQueue);
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [currentCardIndex, setCurrentCardIndex] = useState(0);
  const [phase, setPhase] = useState<Phase>("study");
  const [revealed, setRevealed] = useState(false);
  const [hintLevel, setHintLevel] = useState(0);
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [history, setHistory] = useState<Snapshot[]>([]);
  const [questionGrade, setQuestionGrade] = useState<Grade | null>(null);
  const [notice, setNotice] = useState("");
  const [editOpen, setEditOpen] = useState(false);
  const [editedCards, setEditedCards] = useState<Record<string, Pick<StudyCard, "front" | "back">>>({});
  const [draftFront, setDraftFront] = useState("");
  const [draftBack, setDraftBack] = useState("");

  const currentQuestion = sessionQueue[currentQuestionIndex];
  const baseCard = currentQuestion?.cards[currentCardIndex];
  const currentCard = baseCard
    ? { ...baseCard, ...(editedCards[baseCard.id] ?? {}) }
    : undefined;
  const totalCards = sessionQueue.reduce((sum, item) => sum + item.cards.length, 0);
  const questionAttempts = attempts.filter((attempt) => attempt.questionId === currentQuestion?.id);
  const suggestedGrade = useMemo<Grade>(() => {
    const grades = questionAttempts.flatMap((attempt) => attempt.grade === null ? [] : [attempt.grade]);
    if (grades.length === 0) return 2;
    const average = grades.reduce((sum, grade) => sum + grade, 0) / grades.length;
    return Math.max(1, Math.min(4, Math.round(average))) as Grade;
  }, [questionAttempts]);

  const gradeOptions = hintLevel > 1 ? GRADES.filter((grade) => grade.value !== 4) : GRADES;

  function resetCard() {
    setRevealed(false);
    setHintLevel(0);
    setNotice("");
  }

  function finishCard(grade: Grade | null) {
    if (!currentQuestion || !currentCard || phase !== "study") return;
    setHistory((current) => [...current, { questionIndex: currentQuestionIndex, cardIndex: currentCardIndex, attempts }]);
    setAttempts((current) => [...current, { cardId: currentCard.id, questionId: currentQuestion.id, grade }]);
    if (grade) onReviewed(currentCard, grade);

    if (currentCardIndex === currentQuestion.cards.length - 1) {
      setPhase("question-summary");
      setQuestionGrade(null);
    } else {
      setCurrentCardIndex((index) => index + 1);
      resetCard();
    }
  }

  function continueAfterQuestion() {
    if (currentQuestionIndex === sessionQueue.length - 1) {
      setPhase("complete");
      return;
    }
    setCurrentQuestionIndex((index) => index + 1);
    setCurrentCardIndex(0);
    setPhase("study");
    resetCard();
  }

  function undoLast() {
    const snapshot = history.at(-1);
    if (!snapshot) return;
    setCurrentQuestionIndex(snapshot.questionIndex);
    setCurrentCardIndex(snapshot.cardIndex);
    setAttempts(snapshot.attempts);
    setHistory((current) => current.slice(0, -1));
    setPhase("study");
    setRevealed(true);
    setNotice("Последняя оценка отменена");
  }

  function deferCard() {
    finishCard(null);
    setNotice("Карточка отложена. Она попадёт в блок ошибок после сеанса.");
  }

  function openEditor() {
    if (!currentCard) return;
    setDraftFront(currentCard.front);
    setDraftBack(currentCard.back);
    setEditOpen(true);
  }

  function retryErrors() {
    const failedIds = new Set(attempts.filter((attempt) => attempt.grade === null || attempt.grade <= 2).map((attempt) => attempt.cardId));
    const retryQueue = sessionQueue.map((item) => ({ ...item, cards: item.cards.filter((card) => failedIds.has(card.id)) })).filter((item) => item.cards.length > 0);
    if (retryQueue.length === 0) return;
    setSessionQueue(retryQueue);
    setCurrentQuestionIndex(0);
    setCurrentCardIndex(0);
    setAttempts([]);
    setHistory([]);
    setPhase("study");
    resetCard();
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (editOpen || target?.matches("input, textarea, select, button, a")) return;
      if (event.key === "Escape") {
        onExit();
      } else if (event.ctrlKey && event.key.toLowerCase() === "z") {
        event.preventDefault();
        undoLast();
      } else if (phase === "study" && event.code === "Space" && !revealed) {
        event.preventDefault();
        setRevealed(true);
      } else if (phase === "study" && event.key.toLowerCase() === "h" && !revealed && currentCard?.hint) {
        setHintLevel((level) => Math.min(currentCard.hint?.length ?? 0, level + 1));
      } else if (phase === "study" && event.key.toLowerCase() === "e") {
        openEditor();
      } else if (phase === "study" && event.key.toLowerCase() === "s") {
        deferCard();
      } else if (phase === "study" && revealed && /^[1-4]$/.test(event.key)) {
        const grade = Number(event.key) as Grade;
        if (gradeOptions.some((candidate) => candidate.value === grade)) finishCard(grade);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  if (phase === "complete") {
    const failed = attempts.filter((attempt) => attempt.grade === null || attempt.grade <= 2).length;
    const cleanQuestions = sessionQueue.filter((item) => {
      const results = attempts.filter((attempt) => attempt.questionId === item.id);
      return results.length > 0 && results.every((attempt) => attempt.grade !== null && attempt.grade >= 3);
    }).length;
    return (
      <section className="session-complete">
        <div className="session-complete-check"><Check size={26} /></div>
        <p className="eyebrow">Сеанс завершён</p>
        <h1>Готово на сегодня</h1>
        <p>Вы разобрали {sessionQueue.length} вопросов и {attempts.length} карточек. Без ошибок — {cleanQuestions}; вернуться стоит к {failed} карточкам.</p>
        <dl className="session-complete-summary">
          <div><dt>Следующий сеанс</dt><dd>завтра · около 7 минут</dd></div>
          <div><dt>Сложнее всего</dt><dd>Нормальные формы · Уровни изоляции</dd></div>
        </dl>
        <div className="session-complete-actions">
          <Button onClick={onExit}>Закончить</Button>
          <Button variant="secondary" disabled={failed === 0} onClick={retryErrors}><RotateCcw size={15} /> Повторить ошибки · {failed}</Button>
        </div>
      </section>
    );
  }

  if (!currentQuestion || !currentCard) return null;

  if (phase === "question-summary") {
    const counts = GRADES.map((grade) => questionAttempts.filter((attempt) => attempt.grade === grade.value).length);
    const deferred = questionAttempts.filter((attempt) => attempt.grade === null).length;
    const chosen = questionGrade ?? suggestedGrade;
    return (
      <section className="question-summary">
        <p className="eyebrow">Вопрос {currentQuestionIndex + 1} из {sessionQueue.length}</p>
        <h1>{currentQuestion.title}</h1>
        <p>Карточки закончились. Проверьте общий результат вопроса — именно он обновит расписание SM-2.</p>
        <div className="question-result-line">
          {GRADES.map((grade, index) => <span key={grade.value}><b>{counts[index]}</b>{grade.label.toLocaleLowerCase("ru")}</span>)}
          {deferred > 0 && <span><b>{deferred}</b>отложено</span>}
        </div>
        <div className="question-summary-grade">
          <h2>Итог вопроса</h2>
          <p>Tentex предлагает «{GRADES[suggestedGrade - 1].label}». Можно изменить.</p>
          <div>
            {GRADES.map((grade) => (
              <button type="button" className={chosen === grade.value ? "is-selected" : ""} key={grade.value} onClick={() => setQuestionGrade(grade.value)}>
                <span>{grade.label}</span><small>{grade.interval}</small>
              </button>
            ))}
          </div>
        </div>
        <div className="question-summary-actions">
          <Button variant="secondary" onClick={undoLast}><Undo2 size={15} /> Вернуться к последней карточке</Button>
          <Link className="secondary-button" to={`/projects/${projectId}`}>Ответить на билет целиком <ExternalLink size={14} /></Link>
          <Button onClick={continueAfterQuestion}>{currentQuestionIndex === sessionQueue.length - 1 ? "Завершить сеанс" : "Следующий вопрос"}<ArrowRight size={15} /></Button>
        </div>
      </section>
    );
  }

  return (
    <div className={`session-screen is-${pace}`}>
      <header className="session-header">
        <button type="button" className="session-exit" onClick={onExit}><X size={16} /> Выйти</button>
        <div className="session-progress-copy">
          <span>Сегодня · {attempts.length + 1} из {totalCards}</span>
          <small>{pace === "fast" ? "быстрый темп" : pace === "ticket" ? "с итогом билета" : `≈ ${Math.max(1, 15 - Math.round(attempts.length / 2))} минут`}</small>
        </div>
        <Progress value={attempts.length} max={totalCards} label="Прогресс сеанса" size="thin" />
        <div className="session-tools">
          <button type="button" disabled={history.length === 0} onClick={undoLast}><Undo2 size={14} /> Отменить <Kbd>Ctrl Z</Kbd></button>
          <button type="button" onClick={openEditor}><Pencil size={14} /> Изменить <Kbd>E</Kbd></button>
          <button type="button" onClick={deferCard}>Отложить <Kbd>S</Kbd></button>
        </div>
      </header>

      <main className="session-content">
        <p className="session-breadcrumb">{currentQuestion.section} → {currentQuestion.title}</p>
        <article className="session-card" key={currentCard.id}>
          <header className="session-card-header">
            <span>{currentQuestion.title}</span>
            <small>карточка {currentCardIndex + 1} из {currentQuestion.cards.length}</small>
          </header>
          <div className="session-card-front"><h1>{currentCard.front}</h1></div>

          {currentCard.hint && !revealed && (
            <div className="session-hint-area">
              {currentCard.hint.slice(0, hintLevel).map((hint) => <p key={hint}>{hint}</p>)}
              <Button variant="ghost" onClick={() => setHintLevel((level) => Math.min(currentCard.hint?.length ?? 0, level + 1))} disabled={hintLevel === currentCard.hint.length}>
                {hintLevel === 0 ? "Показать подсказку" : hintLevel === currentCard.hint.length ? "Подсказка раскрыта" : "Ещё одна подсказка"} <Kbd>H</Kbd>
              </Button>
              {hintLevel > 1 && <small>После сильной подсказки оценка «Легко» недоступна.</small>}
            </div>
          )}

          {!revealed ? (
            <div className="session-reveal-area">
              <p>Сначала сформулируйте ответ про себя, затем сравните.</p>
              <Button onClick={() => setRevealed(true)}>Показать ответ <Kbd>Space</Kbd></Button>
            </div>
          ) : (
            <div className="session-card-back">
              <section><h2>Ответ</h2><p>{currentCard.back}</p></section>
              {currentCard.keyIdea && <aside><span>Ключевая мысль</span><p>{currentCard.keyIdea}</p></aside>}
              <div className="session-sources">
                {currentCard.sources.map((source) => source.href ? (
                  <Link key={source.label} to={`/projects/${projectId}/${source.href}`}><ExternalLink size={13} />{source.label}</Link>
                ) : <span className={source.kind === "lost" ? "is-lost" : ""} key={source.label}>{source.label}</span>)}
              </div>
              <div className="session-grade-area">
                <h2>Как вспомнилось?</h2>
                <div className="session-grade-buttons">
                  {gradeOptions.map((grade) => (
                    <button type="button" className={`tone-${grade.tone}`} key={grade.value} onClick={() => finishCard(grade.value)}>
                      <span><Kbd>{grade.value}</Kbd>{grade.label}</span><small>{grade.interval}</small>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </article>
        {notice && <p className="cards-inline-notice" role="status">{notice}</p>}
      </main>

      <Dialog
        open={editOpen}
        onOpenChange={setEditOpen}
        title="Изменить карточку"
        description="Правка сохранится в Банке и не прервёт текущий сеанс."
        footer={<><Button variant="ghost" onClick={() => setEditOpen(false)}>Отменить</Button><Button onClick={() => { setEditedCards((current) => ({ ...current, [currentCard.id]: { front: draftFront, back: draftBack } })); setEditOpen(false); setNotice("Карточка изменена"); }}>Сохранить</Button></>}
      >
        <div className="session-edit-fields">
          <Field label="Лицевая сторона" required><textarea rows={3} value={draftFront} onChange={(event) => setDraftFront(event.target.value)} /></Field>
          <Field label="Обратная сторона" required><textarea rows={6} value={draftBack} onChange={(event) => setDraftBack(event.target.value)} /></Field>
        </div>
      </Dialog>
    </div>
  );
}
