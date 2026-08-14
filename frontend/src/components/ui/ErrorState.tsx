import type { PropsWithChildren } from "react";

interface ErrorStateProps {
  message: string;
  title?: string;
}

/**
 * Ошибка называет действие и не отбирает то, что уже работает. В children
 * попадает следующий шаг: «Повторить», «Вернуться», технические сведения.
 */
export function ErrorState({
  message,
  title = "Не удалось загрузить данные",
  children,
}: PropsWithChildren<ErrorStateProps>) {
  return (
    <div className="error-state" role="alert">
      <strong>{title}</strong>
      <p>{message}</p>
      {children}
    </div>
  );
}
