import { useMemo, useState } from "react";
import { ArrowRight, Clock3, Play, Settings as SettingsIcon } from "lucide-react";
import { Button, Checkbox, Dialog, PageHead, RadioCards, SegmentedTabs } from "../../components/ui";
import { QUEUE_SUMMARY } from "./mockCards";

interface RepetitionModeProps {
  onStart: (config?: SessionConfig) => void;
}

type QueueKind = "today" | "new" | "hard" | "selected" | "exam";
type Duration = "5" | "10" | "15" | "all";
type Pace = "calm" | "fast" | "ticket";

export interface SessionConfig {
  questionIds: string[];
  pace: Pace;
  duration: Duration;
}

const queueOptions = [
  { value: "today" as const, title: "На сегодня", description: "Просроченные, запланированные, затем новые." },
  { value: "new" as const, title: "Только новые", description: "Карточки, которые вы ещё не изучали." },
  { value: "hard" as const, title: "Сложные", description: "Недавние ответы «не вспомнил» и «частично»." },
  { value: "selected" as const, title: "Выбранные вопросы", description: "Соберите разовый набор вручную." },
  { value: "exam" as const, title: "Перед экзаменом", description: "Свободный прогон без изменения расписания." },
];

export function RepetitionMode({ onStart }: RepetitionModeProps) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [queueKind, setQueueKind] = useState<QueueKind>("today");
  const [duration, setDuration] = useState<Duration>("15");
  const [pace, setPace] = useState<Pace>("calm");
  const [selectedQuestions, setSelectedQuestions] = useState(() => new Set(QUEUE_SUMMARY.slice(0, 3).map((item) => item.id)));

  const totalCards = QUEUE_SUMMARY.reduce((sum, item) => sum + item.cards, 0);
  const configuredCount = useMemo(() => {
    const available = queueKind === "new" ? 3 : queueKind === "hard" ? 4 : queueKind === "selected" ? selectedQuestions.size : QUEUE_SUMMARY.length;
    return Math.min(available, duration === "5" ? 2 : duration === "10" ? 5 : available);
  }, [duration, queueKind, selectedQuestions]);

  function toggleQuestion(id: string, checked: boolean) {
    setSelectedQuestions((current) => {
      const next = new Set(current);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  function startConfigured() {
    const byKind = queueKind === "new"
      ? QUEUE_SUMMARY.filter((item) => item.due === "новые")
      : queueKind === "hard"
        ? QUEUE_SUMMARY.slice(0, 4)
        : queueKind === "selected"
          ? QUEUE_SUMMARY.filter((item) => selectedQuestions.has(item.id))
          : QUEUE_SUMMARY;
    const maxQuestions = duration === "5" ? 2 : duration === "10" ? 5 : byKind.length;
    onStart({ questionIds: byKind.slice(0, maxQuestions).map((item) => item.id), pace, duration });
  }

  return (
    <div className="repetition-mode">
      <PageHead
        eyebrow="Очередь SM-2"
        title="Повторение"
        actions={
          <Button variant="secondary" onClick={() => setSettingsOpen(true)}>
            <SettingsIcon size={15} /> Настроить сеанс
          </Button>
        }
      />

      <section className="repetition-intro" aria-labelledby="today-heading">
        <h2 id="today-heading">
          На сегодня у нас <mark>{QUEUE_SUMMARY.length} вопросов</mark>. По ним <mark>{totalCards} карточка</mark>.
          Это примерно займёт <mark>15 минут</mark>.
        </h2>
        <p>Идём вопрос за вопросом: сначала вспоминаете отдельные мысли, затем оцениваете билет целиком.</p>
        <div className="repetition-intro-actions">
          <Button onClick={() => onStart()}><Play size={16} /> Начать повторение</Button>
          <span><Clock3 size={14} /> Спокойный темп · без таймера</span>
        </div>
      </section>

      <section className="repetition-queue" aria-label="Очередь вопросов на сегодня">
        <header className="repetition-queue-header">
          <div>
            <h3>Сегодняшние вопросы</h3>
            <p>Просроченный вопрос идёт первым, новые — после запланированных.</p>
          </div>
          <span>{QUEUE_SUMMARY.length} вопросов · {totalCards} карточка</span>
        </header>
        <ol className="repetition-queue-list">
          {QUEUE_SUMMARY.map((item, index) => (
            <li key={item.id} className="repetition-queue-item">
              <span className="repetition-queue-number">{index + 1}</span>
              <span className="repetition-queue-copy">
                <small>{item.section}</small>
                <strong>{item.title}</strong>
              </span>
              <span className="repetition-queue-count">{item.cards} карт.</span>
              <span className={`repetition-queue-due ${item.due.startsWith("просрочено") ? "is-overdue" : item.due === "новые" ? "is-new" : ""}`.trim()}>{item.due}</span>
              <ArrowRight size={15} aria-hidden="true" />
            </li>
          ))}
        </ol>
      </section>

      <Dialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        title="Настроить повторение"
        description="Настройка действует только на ближайший сеанс. Режим перед экзаменом не меняет интервалы SM-2."
        className="cards-session-dialog"
        footer={
          <>
            <Button variant="ghost" onClick={() => setSettingsOpen(false)}>Отменить</Button>
            <Button disabled={configuredCount === 0} onClick={() => { setSettingsOpen(false); startConfigured(); }}>Начать · {configuredCount} {configuredCount === 1 ? "вопрос" : configuredCount < 5 ? "вопроса" : "вопросов"}</Button>
          </>
        }
      >
        <div className="cards-session-settings">
          <section>
            <h3>Что повторяем</h3>
            <RadioCards label="Состав очереди" value={queueKind} options={queueOptions} onChange={setQueueKind} layout="rows" />
          </section>

          {queueKind === "selected" && (
            <section className="cards-question-picker">
              <h3>Вопросы</h3>
              {QUEUE_SUMMARY.map((item) => (
                <div key={item.id}>
                  <Checkbox checked={selectedQuestions.has(item.id)} onCheckedChange={(checked) => toggleQuestion(item.id, checked)} label={item.title} />
                  <small>{item.cards} карточек</small>
                </div>
              ))}
            </section>
          )}

          <section className="cards-setting-row">
            <div><h3>Длительность</h3><p>Остановимся после текущего вопроса.</p></div>
            <SegmentedTabs label="Длительность сеанса" value={duration} onChange={setDuration} tabs={[
              { value: "5", label: "5 мин" }, { value: "10", label: "10 мин" }, { value: "15", label: "15 мин" }, { value: "all", label: "Всё" },
            ]} />
          </section>
          <section className="cards-setting-row">
            <div><h3>Темп</h3><p>{pace === "ticket" ? "После карточек воспроизводим билет целиком." : pace === "fast" ? "Компактно, преимущественно с клавиатуры." : "Источники и редактирование всегда под рукой."}</p></div>
            <SegmentedTabs label="Темп повторения" value={pace} onChange={setPace} tabs={[
              { value: "calm", label: "Спокойный" }, { value: "fast", label: "Быстрый" }, { value: "ticket", label: "Билет" },
            ]} />
          </section>
        </div>
      </Dialog>
    </div>
  );
}
