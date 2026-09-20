import { useState } from "react";
import { GraduationCap } from "lucide-react";
import type { ChatSessionDetail, ChatSettingsPatch, ExaminerPersona, ExaminerStrictness } from "../../../api/chat";
import { Popover, RadioCards, SegmentedTabs } from "../../../components/ui";

const PERSONA_OPTIONS: Array<{ value: ExaminerPersona; title: string; description: string }> = [
  { value: "calm_teacher", title: "Спокойный преподаватель", description: "Объясняет по шагам, поддерживает, задаёт наводящие вопросы." },
  { value: "neutral_examiner", title: "Нейтральный экзаменатор", description: "Отвечает кратко и формально." },
  { value: "strict_reviewer", title: "Придирчивый рецензент", description: "Указывает на оговорки, требует точных формулировок." },
];

const STRICTNESS_TABS: Array<{ value: ExaminerStrictness; label: string }> = [
  { value: "soft", label: "Мягко" },
  { value: "normal", label: "Обычно" },
  { value: "strict", label: "Строго" },
];

export function personaLabel(value: ExaminerPersona): string {
  return PERSONA_OPTIONS.find((option) => option.value === value)?.title ?? value;
}

export function strictnessLabel(value: ExaminerStrictness): string {
  return STRICTNESS_TABS.find((option) => option.value === value)?.label ?? value;
}

interface ExaminerControlProps {
  session: ChatSessionDetail;
  error: string;
  onChange: (patch: ChatSettingsPatch) => void | Promise<void>;
}

/**
 * Контрол экзаменатора: персона и строгость (SCREENS.md §«Чат экзамена»).
 * Модель выбирается в композере, а не здесь: два входа в одно значение
 * заставляли бы гадать, какой из них главный.
 *
 * На узкой ширине CSS сворачивает подпись триггера до одного слова
 * «Экзаменатор» — компонент этого не решает сам.
 */
export function ExaminerControl({ session, error, onChange }: ExaminerControlProps) {
  const [open, setOpen] = useState(false);

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      align="end"
      title="Экзаменатор"
      className="chat-examiner-popover"
      trigger={
        <button type="button" className="chat-examiner-control-trigger">
          <GraduationCap size={14} aria-hidden="true" />
          <span className="chat-examiner-control-trigger-full">
            {personaLabel(session.persona)} · {strictnessLabel(session.strictness).toLowerCase()}
          </span>
          <span className="chat-examiner-control-trigger-compact">Экзаменатор</span>
        </button>
      }
    >
      <div className="chat-examiner-control">
        <RadioCards
          label="Персона"
          value={session.persona}
          options={PERSONA_OPTIONS.map((option) => ({
            value: option.value, title: option.title, description: option.description,
          }))}
          layout="rows"
          onChange={(value) => void onChange({ persona: value })}
        />
        <SegmentedTabs
          label="Строгость"
          value={session.strictness}
          tabs={STRICTNESS_TABS}
          onChange={(value) => void onChange({ strictness: value })}
        />
        <p className="chat-examiner-control-note">
          Изменения действуют только на будущие ответы. Персона меняет тон, строгость — допустимые
          упущения; факты и ответ не меняются ни от чего из этого.
        </p>
        {error && <p className="inline-error" role="alert">{error}</p>}
      </div>
    </Popover>
  );
}
