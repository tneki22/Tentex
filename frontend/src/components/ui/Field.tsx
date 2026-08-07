import { cloneElement, isValidElement, useId } from "react";
import type { PropsWithChildren, ReactNode } from "react";

interface FieldProps {
  label: string;
  /** Подсказка под подписью: единицы, границы, откуда значение берётся. */
  hint?: string;
  /** Текст ошибки. Задан — поле подсвечено и ошибка озвучена. */
  error?: string;
  /** Значение подставлено моделью и ещё не тронуто руками (П3). */
  suggested?: boolean;
  required?: boolean;
  /** Действие справа от подписи: «Предложить заполнение», «Очистить». */
  action?: ReactNode;
}

/**
 * Обёртка поля формы: подпись, подсказка, ошибка и метка машинного значения.
 *
 * Метка «предложено» — не украшение: система обязана помечать всё машинное,
 * чтобы правку было видно и можно было отменить. Правка снимает метку, поэтому
 * флагом владеет экран, а не поле.
 */
export function Field({
  label,
  hint,
  error,
  suggested = false,
  required = false,
  action,
  children,
}: PropsWithChildren<FieldProps>) {
  const id = useId();

  return (
    <div
      className={`field ${suggested ? "is-suggested" : ""} ${error ? "is-invalid" : ""}`
        .replace(/\s+/g, " ")
        .trim()}
    >
      <div className="field-head">
        <label htmlFor={id}>
          {label}
          {required && <i aria-hidden="true"> *</i>}
        </label>
        {suggested && <span className="field-mark">предложено</span>}
        {action && <span className="field-action">{action}</span>}
      </div>

      {/* id уезжает в поле ввода: подпись связывается с ним без ручного htmlFor на экране */}
      <div className="field-control">
        {isValidElement<{ id?: string; "aria-invalid"?: boolean }>(children)
          ? cloneElement(children, { id, "aria-invalid": error ? true : undefined })
          : children}
      </div>

      {hint && !error && <small className="field-hint">{hint}</small>}
      {error && (
        <small className="field-error" role="alert">
          {error}
        </small>
      )}
    </div>
  );
}
