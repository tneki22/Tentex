import { Check, Sparkles, X } from "lucide-react";
import { LESSON_BASIS_LABELS, type LessonProposalRead } from "../../api/lessons";
import { Button, Disclosure } from "../../components/ui";

interface LessonProposalBarProps {
  proposal: LessonProposalRead;
  chosen: number;
  busy: boolean;
  onApply(): void;
  onReject(): void;
}

function changesWord(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod100 >= 11 && mod100 <= 14) return "изменений";
  if (mod10 === 1) return "изменение";
  if (mod10 >= 2 && mod10 <= 4) return "изменения";
  return "изменений";
}

/**
 * Шапка предложения модели над уроком. Сами изменения стоят в документе на своих
 * местах; здесь — сколько их, на чём они основаны, во что обошлись и два решения.
 */
export function LessonProposalBar({ proposal, chosen, busy, onApply, onReject }: LessonProposalBarProps) {
  const count = proposal.ops.length;
  const cost = proposal.cost_usd === null ? null : Number(proposal.cost_usd);
  return (
    <section className="lesson-proposal-bar" aria-label="Предложение ИИ">
      <div className="lesson-proposal-bar-row">
        <Sparkles size={15} aria-hidden="true" />
        <strong>{count > 0 ? `Предложение ИИ · ${count} ${changesWord(count)}` : "Модель не нашла, что дополнить"}</strong>
        <span>{LESSON_BASIS_LABELS[proposal.basis].toLowerCase()}</span>
        {cost !== null && <span>${cost < 0.01 ? cost.toFixed(4) : cost.toFixed(2)}</span>}
        <span className="lesson-proposal-bar-actions">
          {count > 0 && (
            <Button disabled={busy || chosen === 0} onClick={onApply}><Check size={14} />Принять выбранное · {chosen}</Button>
          )}
          <Button variant="ghost" disabled={busy} onClick={onReject}><X size={14} />{count > 0 ? "Отклонить" : "Закрыть"}</Button>
        </span>
      </div>
      {proposal.summary && <p className="lesson-proposal-summary">{proposal.summary}</p>}
      {proposal.dropped.length > 0 && (
        <Disclosure summary={`Сервер отбросил ${proposal.dropped.length}: не легли на урок`}>
          <ul className="lesson-proposal-dropped">{proposal.dropped.map((item, index) => <li key={index}>{item}</li>)}</ul>
        </Disclosure>
      )}
    </section>
  );
}
