import { useId } from "react";

interface ConfirmDialogProps {
  title: string;
  description: string;
  cancelLabel: string;
  confirmLabel: string;
  eyebrow?: string;
  error?: string;
  busy?: boolean;
  busyLabel?: string;
  onCancel: () => void;
  onConfirm: () => void;
}

export function ConfirmDialog({
  title,
  description,
  cancelLabel,
  confirmLabel,
  eyebrow,
  error,
  busy = false,
  busyLabel = "Выполняем…",
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  const titleId = useId();
  const descriptionId = useId();

  return (
    <div className="confirm-dialog-backdrop">
      <section
        className="confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
      >
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h2 id={titleId}>{title}</h2>
        <p id={descriptionId}>{description}</p>
        {error && (
          <p className="confirm-dialog-error" role="alert">
            {error}
          </p>
        )}
        <div className="confirm-dialog-actions">
          <button type="button" className="secondary-button" disabled={busy} onClick={onCancel}>
            {cancelLabel}
          </button>
          <button type="button" className="primary-button" disabled={busy} onClick={onConfirm}>
            {busy ? busyLabel : confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
