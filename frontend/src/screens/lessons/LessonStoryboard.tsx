import { useMemo } from "react";
import { ArrowDown, ArrowLeftRight, ArrowUp, BookOpen, Plus, X } from "lucide-react";
import {
  LESSON_LEVEL_LABELS,
  LESSON_STEP_KIND_LABELS,
  LESSON_TEMPLATE_LABELS,
  type LessonAiCandidateRead,
  type LessonAiPlanRead,
  type LessonAiPlanStep,
  type LessonPlanStepKind,
} from "../../api/lessons";
import { Button, IconButton, Menu, Select } from "../../components/ui";

/** Вызовы и верх цены сборки по плану из этих шагов. */
export function storyboardCost(plan: LessonAiPlanRead, steps: LessonAiPlanStep[]) {
  const calls = steps.length + plan.fixed_calls;
  const cost = plan.step_cost_usd === null
    ? null
    : Number(plan.step_cost_usd) * steps.length + Number(plan.fixed_cost_usd ?? 0);
  const limit = cost === null ? null : (Math.ceil(cost * 1000) / 1000).toFixed(3);
  return { calls, cost, limit };
}

interface LessonStoryboardProps {
  plan: LessonAiPlanRead;
  steps: LessonAiPlanStep[];
  onStepsChange(steps: LessonAiPlanStep[]): void;
  /** Предел расхода; `null` — верх оценки по текущему плану. */
  limit: string | null;
  onLimitChange(limit: string): void;
}

const KIND_OPTIONS = (Object.keys(LESSON_STEP_KIND_LABELS) as LessonPlanStepKind[])
  .map((value) => ({ value, label: LESSON_STEP_KIND_LABELS[value] }));
/** Вызов модели в среднем — столько секунд: оценка времени, а не обещание. */
const SECONDS_PER_CALL = 15;

function candidateLabel(item: LessonAiCandidateRead): string {
  const pages = item.page_from === item.page_to ? `${item.page_from}` : `${item.page_from}–${item.page_to}`;
  return `${item.material_name} ${pages}${item.title ? ` · ${item.title}` : ""}`;
}

function money(value: number): string {
  return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`;
}

function callsWord(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod100 >= 11 && mod100 <= 14) return "вызовов";
  if (mod10 === 1) return "вызов";
  if (mod10 >= 2 && mod10 <= 4) return "вызова";
  return "вызовов";
}

/**
 * Редактор плана урока: шаги по порядку, их опоры в материале и цена сборки.
 *
 * План — предложение модели, а не приговор: шаг убирают, переставляют,
 * переписывают намерение, опору меняют на другой кусок той же карты (⇄).
 * Цена пересчитывается на месте: шаг — один вызов по его опорам.
 */
export function LessonStoryboard({ plan, steps, onStepsChange, limit, onLimitChange }: LessonStoryboardProps) {
  const setSteps = (change: (current: LessonAiPlanStep[]) => LessonAiPlanStep[]) => onStepsChange(change(steps));
  const byLabel = useMemo(() => new Map(plan.candidates.map((item) => [item.label, item])), [plan.candidates]);
  const menuItems = (skip: string[], choose: (label: string) => void) => plan.candidates
    .filter((item) => !skip.includes(item.label))
    .map((item) => ({ label: `${item.label} · ${candidateLabel(item)}`, onSelect: () => choose(item.label) }));

  const { calls, cost, limit: suggestedLimit } = storyboardCost(plan, steps);
  const minutes = Math.max(1, Math.round((calls * SECONDS_PER_CALL) / 60 * 2) / 2);

  function update(index: number, change: Partial<LessonAiPlanStep>) {
    setSteps((current) => current.map((step, position) => (position === index ? { ...step, ...change } : step)));
  }

  function move(index: number, delta: number) {
    setSteps((current) => {
      const next = [...current];
      const [step] = next.splice(index, 1);
      next.splice(index + delta, 0, step);
      return next;
    });
  }

  function setSource(index: number, slot: number, label: string | null) {
    const step = steps[index];
    const sources = [...step.sources];
    if (label === null) sources.splice(slot, 1);
    else sources[slot] = label;
    update(index, { sources: [...new Set(sources)] });
  }

  return (
    <div className="lesson-storyboard">
      <header className="lesson-storyboard-head">
        <h3>План «{plan.title}»</h3>
        <p>
          {LESSON_TEMPLATE_LABELS[plan.template]} · {LESSON_LEVEL_LABELS[plan.level]}
          {plan.minutes ? ` · ≈${plan.minutes} мин` : ""}
        </p>
        {plan.concepts.length > 0 && (
          <p className="lesson-storyboard-concepts">Понятия: {plan.concepts.join(" → ")}</p>
        )}
        {plan.dropped.length > 0 && (
          <p className="lesson-build-note">Сервер убрал из плана: {plan.dropped.join("; ")}</p>
        )}
      </header>

      <ol className="lesson-storyboard-steps">
        {steps.map((step, index) => (
          <li key={index} className="lesson-storyboard-step">
            <span className="lesson-storyboard-number">{index + 1}</span>
            <div className="lesson-storyboard-body">
              <div className="lesson-storyboard-line">
                <Select ariaLabel={`Вид шага ${index + 1}`} className="lesson-storyboard-kind" value={step.kind}
                  options={KIND_OPTIONS} onValueChange={(value) => { if (value) update(index, { kind: value as LessonPlanStepKind }); }} />
                <input aria-label={`Название шага ${index + 1}`} className="lesson-storyboard-title" value={step.title} maxLength={120}
                  onChange={(event) => update(index, { title: event.target.value })} />
              </div>
              <textarea aria-label={`Что делает шаг ${index + 1}`} className="lesson-storyboard-intent" value={step.intent} maxLength={500} rows={2}
                onChange={(event) => update(index, { intent: event.target.value })} />
              {plan.basis !== "model_only" && (
                <div className="lesson-storyboard-sources">
                  {step.sources.map((label, slot) => {
                    const item = byLabel.get(label);
                    return (
                      <span key={label} className="lesson-storyboard-source">
                        <BookOpen size={12} aria-hidden="true" />
                        <span>{item ? `${candidateLabel(item)} · ${label}` : `${label} · кусок не найден`}</span>
                        <Menu label={`Заменить опору ${label}`} tooltip="Заменить другим куском"
                          trigger={<button type="button" aria-label={`Заменить опору ${label} шага ${index + 1}`}><ArrowLeftRight size={12} /></button>}
                          items={menuItems(step.sources, (next) => setSource(index, slot, next))} />
                        <button type="button" aria-label={`Убрать опору ${label}`} onClick={() => setSource(index, slot, null)}><X size={12} /></button>
                      </span>
                    );
                  })}
                  {step.sources.length < 3 && plan.candidates.length > step.sources.length && (
                    <Menu label={`Добавить опору шагу ${index + 1}`}
                      trigger={<button type="button" className="lesson-storyboard-add-source"><Plus size={12} />опора</button>}
                      items={menuItems(step.sources, (next) => setSource(index, step.sources.length, next))} />
                  )}
                  {step.sources.length === 0 && <small>без опоры — из знаний модели</small>}
                </div>
              )}
            </div>
            <div className="lesson-storyboard-tools">
              <IconButton label={`Шаг ${index + 1} выше`} disabled={index === 0} onClick={() => move(index, -1)}><ArrowUp size={14} /></IconButton>
              <IconButton label={`Шаг ${index + 1} ниже`} disabled={index === steps.length - 1} onClick={() => move(index, 1)}><ArrowDown size={14} /></IconButton>
              <IconButton label={`Убрать шаг ${index + 1}`} disabled={steps.length === 1} onClick={() => setSteps((current) => current.filter((_, position) => position !== index))}><X size={14} /></IconButton>
            </div>
          </li>
        ))}
      </ol>

      <div className="lesson-storyboard-footer">
        <Button variant="ghost" disabled={steps.length >= 16} onClick={() => setSteps((current) => [...current, {
          kind: "concept", title: "Новый шаг", intent: "Что объяснить в этом шаге", sources: [], collapsed: null, introduces: [],
        }])}><Plus size={14} />Шаг</Button>
        <span className="lesson-storyboard-cost">
          {calls} {callsWord(calls)} · {cost === null ? "цена неизвестна" : `≈${money(cost)}`} · ~{minutes} мин
        </span>
        <label className="lesson-storyboard-limit">
          <span>Предел, $</span>
          <input type="number" min={0.001} step={0.001} value={limit ?? suggestedLimit ?? ""} onChange={(event) => onLimitChange(event.target.value)} />
        </label>
      </div>
    </div>
  );
}
