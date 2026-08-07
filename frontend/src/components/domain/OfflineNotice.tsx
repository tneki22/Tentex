import { PlugZap } from "lucide-react";
import { Link } from "react-router";

interface OfflineNoticeProps {
  /** Почему недоступно: «выключены» — воля пользователя, «недоступен» — провайдер молчит. */
  reason: "disabled" | "unreachable";
  /** Что делать вместо: офлайновый путь к той же цели. */
  alternative?: string;
}

/**
 * Объяснение, почему действие недоступно без внешних моделей — и что работает
 * вместо него.
 *
 * Два состояния различаются тоном сознательно: выключенные модели — законный
 * режим и рисуются нейтрально; недоступный провайдер — предупреждение, но всё
 * равно штатное состояние, а не авария на весь экран.
 */
export function OfflineNotice({ reason, alternative }: OfflineNoticeProps) {
  const disabled = reason === "disabled";

  return (
    <p className={`offline-notice ${disabled ? "is-neutral" : "is-warning"}`}>
      <PlugZap size={14} aria-hidden="true" />
      <span>
        {disabled ? (
          <>
            Внешние модели выключены — включаются в <Link to="/setup">Установке</Link>.
          </>
        ) : (
          <>Провайдер не отвечает — работаем в детерминированном режиме.</>
        )}
        {alternative && <> {alternative}</>}
      </span>
    </p>
  );
}
