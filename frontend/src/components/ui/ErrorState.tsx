interface ErrorStateProps {
  message: string;
  title?: string;
}

export function ErrorState({ message, title = "Не удалось загрузить данные" }: ErrorStateProps) {
  return (
    <div className="error-state" role="alert">
      <strong>{title}</strong>
      <p>{message}</p>
    </div>
  );
}
