import { CalendarClock, CheckCircle2, RotateCcw } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { PersonalMark } from "../../hooks/usePersonalMarks";
import { Tooltip } from "../ui";

const PERSONAL_MARKS: Record<PersonalMark, { label: string; icon: LucideIcon; tone: "success" | "info" | "warning" }> = {
  done: { label: "Пройден", icon: CheckCircle2, tone: "success" },
  today: { label: "Запланировано на сегодня", icon: CalendarClock, tone: "info" },
  review: { label: "Повторить сегодня", icon: RotateCcw, tone: "warning" },
};

export const PERSONAL_MARK_OPTIONS = (Object.keys(PERSONAL_MARKS) as PersonalMark[])
  .map((value) => ({ value, ...PERSONAL_MARKS[value] }));

/** Значок личной пометки в дереве вопросов. Пометка живёт только в этом браузере. */
export function PersonalMarkIcon({ mark, size = 14 }: { mark: PersonalMark; size?: number }) {
  const { label, icon: Icon, tone } = PERSONAL_MARKS[mark];
  return (
    <Tooltip label={`Личная пометка: ${label}`}>
      <span className={`personal-mark tone-${tone}`}>
        <Icon size={size} aria-label={`Личная пометка: ${label}`} />
      </span>
    </Tooltip>
  );
}
