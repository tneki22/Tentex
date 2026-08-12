import { useEffect, useRef, useState } from "react";
import type { PropsWithChildren, ReactNode } from "react";
import { Dialog as RadixDialog } from "radix-ui";
import { Button } from "./Button";

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** Одна строка под заголовком: что произойдёт. */
  description?: string;
  /** Кнопки подвала. Если не задать — только «Закрыть». */
  footer?: ReactNode;
  className?: string;
}

/** Модальный диалог. Фокус-ловушка, Esc и возврат фокуса — на Radix. */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  footer,
  className = "",
  children,
}: PropsWithChildren<DialogProps>) {
  const opener = useRef<HTMLElement | null>(null);

  /**
   * Возврат фокуса туда, откуда диалог открыли. Radix делает это сам только для
   * своего Trigger, а у нас диалог управляется пропсом `open`: кнопка живёт на
   * экране и про диалог не знает. Без этого после Esc фокус уезжает на body, и
   * место в списке теряется — с клавиатуры пришлось бы идти сначала.
   */
  useEffect(() => {
    if (open) {
      opener.current = document.activeElement as HTMLElement | null;
      return;
    }
    const trigger = opener.current;
    opener.current = null;
    /* Триггер мог исчезнуть вместе с объектом — например, файл всё-таки удалили */
    if (trigger?.isConnected) trigger.focus();
  }, [open]);

  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="dialog-overlay" />
        <RadixDialog.Content className={`dialog ${className}`.trim()}>
          <RadixDialog.Title className="dialog-title">{title}</RadixDialog.Title>
          {description ? (
            <RadixDialog.Description className="dialog-lead">{description}</RadixDialog.Description>
          ) : (
            /* Radix требует описание или явный отказ от него, иначе предупреждает в консоли */
            <RadixDialog.Description hidden>{title}</RadixDialog.Description>
          )}
          {children}
          <footer className="dialog-actions">
            {footer ?? (
              <RadixDialog.Close asChild>
                <Button variant="secondary">Закрыть</Button>
              </RadixDialog.Close>
            )}
          </footer>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** Кнопка называет действие словом: «Удалить файл», а не «OK». */
  confirmLabel: string;
  onConfirm: () => void | Promise<void>;
  /** Необратимое действие красит кнопку в danger. */
  destructive?: boolean;
}

/**
 * Подтверждение с перечислением последствий. Последствия — обязательное
 * содержимое: по FR-M10 пользователь должен видеть, что осиротеет, ДО удаления.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  confirmLabel,
  onConfirm,
  destructive = false,
  children,
}: PropsWithChildren<ConfirmDialogProps>) {
  const [pending, setPending] = useState(false);

  async function confirm() {
    setPending(true);
    try {
      await onConfirm();
      onOpenChange(false);
    } catch {
      // Оставляем диалог открытым: вызывающий экран показывает свою ошибку.
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      className="dialog-confirm"
      footer={
        <>
          <Button variant="ghost" disabled={pending} onClick={() => onOpenChange(false)}>
            Отменить
          </Button>
          <Button
            className={destructive ? "is-destructive" : ""}
            disabled={pending}
            onClick={() => void confirm()}
          >
            {pending ? "Удаляем…" : confirmLabel}
          </Button>
        </>
      }
    >
      {children}
    </Dialog>
  );
}
