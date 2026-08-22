import { TriangleAlert } from "lucide-react";
import { Link } from "react-router";
import { describeAiFailure } from "../../api/ai";
import { OfflineNotice } from "./OfflineNotice";

interface AiFailureNoticeProps {
  /** Пойманная ошибка вызова ИИ. Не ошибка ИИ — ничего не рисуем. */
  error: unknown;
  /** Офлайновый путь к той же цели: «Формулировки можно исправить вручную.» */
  manualAlternative: string;
  /** Куда вести в Параметрах ИИ. По умолчанию — «Функции», где у каждой роли
      выбирается своя модель: именно там правится причина misconfigured. */
  settingsSubsection?: "functions" | "defaults" | "providers" | "models";
}

/**
 * Честное объяснение, почему вызов ИИ не прошёл. Три состояния различаются по
 * смыслу: модели выключены глобально, провайдер молчит, или ИИ включён, но
 * модель именно этой функции не может выполнить вызов. Последнее раньше
 * показывалось как «модели выключены» — и вводило в заблуждение пользователя,
 * у которого ИИ включён.
 */
export function AiFailureNotice({
  error,
  manualAlternative,
  settingsSubsection = "functions",
}: AiFailureNoticeProps) {
  const failure = describeAiFailure(error);
  if (!failure) return null;

  if (failure.kind === "disabled") {
    return <OfflineNotice reason="disabled" alternative={manualAlternative} />;
  }
  if (failure.kind === "unreachable") {
    return <OfflineNotice reason="unreachable" alternative={`${failure.message} ${manualAlternative}`} />;
  }

  const settingsHref = `/setup?section=ai&subsection=${settingsSubsection}`;
  return (
    <div className="ai-failure-notice" role="alert">
      <TriangleAlert size={16} aria-hidden="true" />
      <div>
        <strong>{failure.title}</strong>
        <p>{failure.message}</p>
        <p className="ai-failure-notice-actions">
          <Link to={settingsHref}>Открыть Параметры ИИ</Link>
          <span>{manualAlternative}</span>
        </p>
      </div>
    </div>
  );
}
