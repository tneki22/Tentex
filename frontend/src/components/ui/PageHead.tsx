import { createContext, useContext, useMemo } from "react";
import type { PropsWithChildren, ReactNode } from "react";
import { createPortal } from "react-dom";

interface PageHeadProps {
  title: string;
  /** Надзаголовок: группа экрана или имя проекта. */
  eyebrow?: string;
  /** Подводка: одна-две строки о том, что здесь делают. */
  lead?: string;
  /** Действия справа от заголовка: главная кнопка экрана. */
  actions?: ReactNode;
  /** Элемент слева от заголовка: кнопка «назад» там, где нет боковой панели. */
  leading?: ReactNode;
  /**
   * «topbar» — заголовок и действие переезжают в верхнюю полосу оболочки, на одну
   * строку с поиском. Вне оболочки (мастер, Рабочая область) слотов нет, и шапка
   * молча остаётся на странице.
   */
  placement?: "page" | "topbar";
}

export interface PageHeadSlots {
  title: HTMLElement | null;
  actions: HTMLElement | null;
}

const SlotContext = createContext<PageHeadSlots | null>(null);

/** Оболочка отдаёт сюда узлы своей верхней полосы. */
export function PageHeadSlotProvider({
  title,
  actions,
  children,
}: PropsWithChildren<PageHeadSlots>) {
  const slots = useMemo(() => ({ title, actions }), [title, actions]);
  return <SlotContext.Provider value={slots}>{children}</SlotContext.Provider>;
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
  leading,
  placement = "page",
  children,
}: PropsWithChildren<PageHeadProps>) {
  const slots = useContext(SlotContext);

  if (placement === "topbar" && slots?.title && slots.actions) {
    /* В полосу уезжают только заголовок и действие: надзаголовку и подводке
       в 64 пикселях места нет, они остаются началом страницы. */
    return (
      <>
        {createPortal(<h1 className="topbar-title">{title}</h1>, slots.title)}
        {actions && createPortal(actions, slots.actions)}
        {(eyebrow || lead || children) && (
          <header className="page-head is-lifted">
            <div className="page-head-text">
              {eyebrow && <p className="eyebrow">{eyebrow}</p>}
              {lead && <p className="lead">{lead}</p>}
              {children}
            </div>
          </header>
        )}
      </>
    );
  }

  return (
    <header className={`page-head ${actions ? "has-actions" : ""} ${leading ? "has-leading" : ""}`.trim()}>
      {leading && <div className="page-head-leading">{leading}</div>}
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
