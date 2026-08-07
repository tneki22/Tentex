import type { PropsWithChildren } from "react";

/**
 * Подпись клавиши. Нужна там, где работа идёт с клавиатуры: палитра поиска,
 * очередь предложений (разбор привязок клавишами), сессия занятия.
 */
export function Kbd({ children }: PropsWithChildren) {
  return <kbd className="kbd">{children}</kbd>;
}
