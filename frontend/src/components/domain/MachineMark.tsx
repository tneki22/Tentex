import { Sparkles, Undo2 } from "lucide-react";
import { Tooltip } from "../ui";

interface MachineMarkProps {
  /** Чем именно это сделано: «проход 2», «предложено моделью», «ИИ-судья». */
  origin: string;
  /** Отмена одним нажатием. Нет обработчика — значит отменять нечего. */
  onUndo?: () => void;
  undoLabel?: string;
}

/**
 * Метка машинного происхождения. Ключевой виджет продукта: всё, что сделала
 * модель, помечено, несёт свой источник и отменяется одним движением.
 *
 * Ставится на машинную привязку, предложенное значение паспорта, сгенерированную
 * карточку, оценку ИИ-судьи. Если метку негде поставить — значит машинное
 * действие спрятано, и это дефект, а не экономия места.
 */
export function MachineMark({ origin, onUndo, undoLabel = "Отменить" }: MachineMarkProps) {
  return (
    <span className="machine-mark">
      <Sparkles size={12} aria-hidden="true" />
      {origin}
      {onUndo && (
        <Tooltip label={undoLabel} side="top">
          <button type="button" className="machine-undo" onClick={onUndo} aria-label={undoLabel}>
            <Undo2 size={12} aria-hidden="true" />
          </button>
        </Tooltip>
      )}
    </span>
  );
}
