/** Очередь вопросов на сегодня: открыл — зелёный, без отдельной отметки выполнения. */
import { useState } from "react";
import { Check, ListChecks } from "lucide-react";
import { Button, EmptyState, Tooltip } from "../../components/ui";
import { PurposeDot, purposeLabel } from "../../components/domain";
import { durationLabel } from "./dates";
import type { QueueCard } from "./model";

interface TodayQueueProps {
  cards: QueueCard[];
  title: string;
  onOpen: (topicId: string) => void;
  onPickDay: () => void;
  disabled?: boolean;
}

const VISIBLE = 12;

/**
 * Сетка карточек дня.
 *
 * Порядок остаётся программным и не меняется по мере открытия: перескакивающие
 * карточки мешают вернуться к тому, что читал.
 */
export function TodayQueue({
  cards,
  title,
  onOpen,
  onPickDay,
  disabled = false,
}: TodayQueueProps) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? cards : cards.slice(0, VISIBLE);

  if (!cards.length)
    return (
      <section className="prep-queue-area" aria-label={title}>
        <h2 className="prep-area-title">{title}</h2>
        <EmptyState title="На этот день ничего не назначено" icon={<ListChecks size={20} />}>
          <div className="prep-actions">
            <Button variant="secondary" onClick={onPickDay} disabled={disabled}>
              Выбрать вопросы на этот день
            </Button>
          </div>
        </EmptyState>
      </section>
    );

  return (
    <section className="prep-queue-area" aria-label={title}>
      <h2 className="prep-area-title">
        {title}
        <small>
          {cards.filter((card) => card.opened).length} из {cards.length} открыто
        </small>
      </h2>
      <ul className="prep-queue-grid">
        {shown.map((card) => (
          <li
            key={card.unitId}
            className={`prep-queue-card${card.opened ? " is-opened" : ""}${
              card.kind === "ticket" ? " is-ticket" : ""
            }`}
          >
            <button type="button" onClick={() => onOpen(card.topicIds[0] ?? "")}>
              <span className="prep-queue-head">
                <PurposeDot purpose={card.purpose} withLabel />
                {durationLabel(card.seconds) && <em>{durationLabel(card.seconds)}</em>}
              </span>
              <Tooltip label={card.title} side="top">
                <strong>{card.title}</strong>
              </Tooltip>
              {card.kind === "ticket" ? (
                <span className="prep-queue-state">
                  {card.questions.filter((question) => question.opened).length} из {card.questions.length} вопросов
                </span>
              ) : (
                card.opened && (
                  <span className="prep-queue-state is-done">
                    <Check size={13} /> Открыт
                  </span>
                )
              )}
            </button>
            {card.kind === "ticket" && (
              <ul className="prep-ticket-questions">
                {card.questions.map((question) => (
                  <li key={question.nodeId}>
                    <button type="button" onClick={() => onOpen(question.nodeId)}>
                      {question.opened ? <Check size={12} /> : <i aria-hidden="true" />}
                      <span>{question.title}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <span className="sr-only">{purposeLabel[card.purpose]}</span>
          </li>
        ))}
      </ul>
      {cards.length > VISIBLE && !expanded && (
        <Button variant="ghost" onClick={() => setExpanded(true)}>
          Показать все {cards.length} вопросов
        </Button>
      )}
    </section>
  );
}
