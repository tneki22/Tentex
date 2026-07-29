interface ToastProps {
  message: string;
  tone?: "success" | "danger" | "info";
}

export function Toast({ message, tone = "success" }: ToastProps) {
  return (
    <div className={`toast tone-${tone}`} role="status" aria-live="polite">
      {message}
    </div>
  );
}
