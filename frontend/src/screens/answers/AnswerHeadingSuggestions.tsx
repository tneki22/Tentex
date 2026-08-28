import { Link2, X } from "lucide-react";
import type { HeadingSuggestion } from "../../api/bindings";
import { Button, IconButton } from "../../components/ui";

interface AnswerHeadingSuggestionsProps {
  suggestions: HeadingSuggestion[];
  nodeNumberById: Map<string, string>;
  busy: boolean;
  onResolve: (anchorFragmentId: string, nodeId: string) => void;
  onDismiss: () => void;
}

function preview(text: string, max = 90): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

/**
 * Заголовки файла ответов, для которых автоматика не выбрала вопрос сама.
 *
 * Без этого блока автопривязка с вкладки «Ответы» была бы тупиком: «связано 38
 * из 42» и никакой возможности доразобрать оставшиеся, не уходя в Материалы.
 * Выбор запоминается в самом эталоне, повторная привязка его не потеряет.
 */
export function AnswerHeadingSuggestions({
  suggestions,
  nodeNumberById,
  busy,
  onResolve,
  onDismiss,
}: AnswerHeadingSuggestionsProps) {
  if (suggestions.length === 0) return null;

  return (
    <section className="answer-suggestions" aria-label="Заголовки без вопроса">
      <header>
        <b>Не нашли вопрос · {suggestions.length}</b>
        <IconButton label="Скрыть" onClick={onDismiss}><X size={14} /></IconButton>
      </header>
      <small>Заголовок разошёлся с формулировкой сильнее, чем можно решить без вас.</small>
      {suggestions.map((suggestion) => (
        <article className="answer-suggestion" key={suggestion.anchor_fragment_id}>
          <b>{suggestion.heading}</b>
          <small>
            стр. {suggestion.page_from}
            {suggestion.preview ? ` · ${preview(suggestion.preview)}` : ""}
          </small>
          <div className="answer-suggestion-actions">
            {suggestion.candidates.length === 0
              ? <small>Похожих вопросов не нашлось — выберите вопрос в списке и впишите ответ вручную.</small>
              : suggestion.candidates.map((candidate) => (
                <Button
                  key={candidate.node_id}
                  variant="secondary"
                  disabled={busy}
                  onClick={() => onResolve(suggestion.anchor_fragment_id, candidate.node_id)}
                >
                  <Link2 size={13} />
                  {nodeNumberById.get(candidate.node_id)
                    ? `${nodeNumberById.get(candidate.node_id)}. ${candidate.node_title}`
                    : candidate.node_title}
                </Button>
              ))}
          </div>
        </article>
      ))}
    </section>
  );
}
