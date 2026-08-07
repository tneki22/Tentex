import type { PropsWithChildren, ReactNode } from "react";

interface PageHeadProps {
  title: string;
  /** Надзаголовок: группа экрана или имя проекта. */
  eyebrow?: string;
  /** Подводка: одна-две строки о том, что здесь делают. */
  lead?: string;
  /** Действия справа от заголовка: главная кнопка экрана. */
  actions?: ReactNode;
}

/**
 * Шапка экрана. Один компонент на все семнадцать: заголовки не разъедутся
 * по кеглю и отступам, а действие экрана всегда в одном месте.
 */
export function PageHead({
  title,
  eyebrow,
  lead,
  actions,
  children,
}: PropsWithChildren<PageHeadProps>) {
  return (
    <header className={`page-head ${actions ? "has-actions" : ""}`.trim()}>
      <div className="page-head-text">
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {lead && <p className="lead">{lead}</p>}
        {children}
      </div>
      {actions && <div className="page-head-actions">{actions}</div>}
    </header>
  );
}
