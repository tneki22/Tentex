import type { PropsWithChildren } from "react";
import { useLocation } from "react-router";
import { screenById } from "../app/screens";

interface ScreenStubProps {
  /** Идентификатор из SCREENS в src/app/screens.ts. */
  id: string;
}

/**
 * Заглушка экрана на этап 0: заголовок, строка из §21 требований и текущий путь.
 * Когда экран доходит до проектирования (этап 1), содержимое файла заменяется
 * настоящей вёрсткой, а этот компонент из него уходит.
 */
export function ScreenStub({ id, children }: PropsWithChildren<ScreenStubProps>) {
  const screen = screenById(id);
  const location = useLocation();

  return (
    <article className="screen-stub">
      <p className="eyebrow">{screen.group}</p>
      <h1>{screen.title}</h1>
      <p className="lead">{screen.summary}</p>
      {children}
      <div className="screen-stub-meta">
        <span>
          путь: <code>{location.pathname}</code>
        </span>
        <span>
          шаблон: <code>{screen.path}</code>
        </span>
        <span>проработка на этапе 1: {screen.depth}</span>
      </div>
    </article>
  );
}
