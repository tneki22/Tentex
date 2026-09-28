import { useEffect, useMemo, useState } from "react";
import { BookOpenText, Compass, Dumbbell, ListChecks, Sparkles } from "lucide-react";
import type { AiModelSelection } from "../../api/ai";
import { getBackgroundJobResult } from "../../api/backgroundJobs";
import {
  LESSON_BASIS_LABELS,
  previewLessonAi,
  resumeLessonAiBuild,
  SOURCE_ROLE_LABELS,
  startLessonAiBuild,
  startLessonAiPlan,
  type LessonAiBuildResult,
  type LessonAiPlanRead,
  type LessonAiPlanStep,
  type LessonAiBulkResult,
  type LessonAiPreflightRead,
  type LessonProposalRead,
  type LessonBasis,
  type LessonLevel,
  type LessonTemplate,
} from "../../api/lessons";
import { OfflineNotice } from "../../components/domain";
import {
  Button, Checkbox, Dialog, Disclosure, ErrorState, Field, LoadingState, Progress, RadioCards,
  SegmentedTabs, type RadioCardOption,
} from "../../components/ui";
import { useBackgroundJob } from "../../hooks/useBackgroundJob";
import { ChatModelControl } from "../workspace/chat/ChatModelControl";
import { LessonStoryboard, storyboardCost } from "./LessonStoryboard";
import { errorText } from "./lessonTree";

interface LessonBuildDialogProps {
  open: boolean;
  onOpenChange(open: boolean): void;
  projectId: string;
  topic: { id: string; title: string };
  /** Уже идущая сборка — диалог открывается сразу на её прогрессе. */
  jobId?: string | null;
  /** Черновик готов: родитель перечитывает уроки и открывает новый. */
  onBuilt(lessonId: string, dropped: string[]): void;
  /** Из «Фона» открыли готовое предложение «Дополнить урок» — его показывает урок. */
  onProposal?(jobId: string, lessonId: string): void;
}

const TEMPLATE_OPTIONS: Array<RadioCardOption<LessonTemplate>> = [
  { value: "explain", title: "Объяснение с нуля", description: "Понятия по одному с примерами; учебник свёрнут под шагом", icon: <BookOpenText size={15} aria-hidden="true" /> },
  { value: "guide", title: "Путеводитель", description: "Куски учебника по порядку и что в них заметить", icon: <Compass size={15} aria-hidden="true" /> },
  { value: "practice", title: "Через практику", description: "Задача, решение по шагам, теория по ходу", icon: <Dumbbell size={15} aria-hidden="true" /> },
  { value: "cheatsheet", title: "Шпаргалка", description: "Определения, правила, сравнение, частые ошибки", icon: <ListChecks size={15} aria-hidden="true" /> },
];

const LEVEL_TEXT: Record<LessonLevel, { title: string; description: string }> = {
  draft: { title: "Черновик", description: "План и короткие тексты одним ответом" },
  standard: { title: "Обычный", description: "План, затем шаги с полным текстом опор" },
  detailed: { title: "Подробный", description: "То же плюс разбор ошибок и рецензент" },
};

const BASIS_ORDER: LessonBasis[] = ["sources_and_model", "sources", "model_only"];
const MODEL_KEY = (projectId: string) => `tentex:lesson-ai-model:${projectId}`;

function readModel(projectId: string): AiModelSelection | null {
  try {
    const raw = window.localStorage.getItem(MODEL_KEY(projectId));
    return raw ? (JSON.parse(raw) as AiModelSelection) : null;
  } catch {
    return null;
  }
}

function usd(value: string | number | null): string {
  if (value === null) return "цена неизвестна";
  const number = Number(value);
  return number < 0.01 ? `≈$${number.toFixed(4)}` : `≈$${number.toFixed(2)}`;
}

function calls(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod100 >= 11 && mod100 <= 14) return `${count} вызовов`;
  if (mod10 === 1) return `${count} вызов`;
  if (mod10 >= 2 && mod10 <= 4) return `${count} вызова`;
  return `${count} вызовов`;
}

/**
 * «Собрать урок с ИИ»: что пойдёт в модель и сколько это стоит — до запуска.
 *
 * Оценку, куски материала и паспорт урока считает сервер без модели при каждом
 * изменении выбора; тот же паспорт показан в «Что увидит модель». Верх оценки
 * становится пределом расхода, и его можно поменять.
 */
export function LessonBuildDialog({ open, onOpenChange, projectId, topic, jobId: initialJobId = null, onBuilt, onProposal }: LessonBuildDialogProps) {
  const [template, setTemplate] = useState<LessonTemplate>("explain");
  const [basis, setBasis] = useState<LessonBasis>("sources_and_model");
  const [level, setLevel] = useState<LessonLevel>("draft");
  const [materialIds, setMaterialIds] = useState<string[] | null>(null);
  const [minutes, setMinutes] = useState("");
  const [wishes, setWishes] = useState("");
  const [useConspect, setUseConspect] = useState<boolean | null>(null);
  const [model, setModel] = useState<AiModelSelection | null>(() => readModel(projectId));
  const [limit, setLimit] = useState("");
  const [limitTouched, setLimitTouched] = useState(false);
  const [confirmUnknown, setConfirmUnknown] = useState(false);
  const [preview, setPreview] = useState<LessonAiPreflightRead | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState("");
  const [jobId, setJobId] = useState<string | null>(initialJobId);
  const { job, refresh: refreshJob } = useBackgroundJob(jobId);
  // «Обычный» и «Подробный» сначала показывают план; флажок пропускает этот шаг.
  const [skipPlan, setSkipPlan] = useState(false);
  const [plan, setPlan] = useState<{ jobId: string; read: LessonAiPlanRead } | null>(null);
  const [planSteps, setPlanSteps] = useState<LessonAiPlanStep[]>([]);
  const [planLimit, setPlanLimit] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setJobId(initialJobId);
    setStartError("");
    setPlan(null);
    if (!initialJobId) {
      setMaterialIds(null);
      setUseConspect(null);
      setLimitTouched(false);
      setConfirmUnknown(false);
    }
  }, [open, initialJobId, topic.id]);

  const order = useMemo(() => ({
    program_node_id: topic.id,
    template,
    level,
    basis,
    material_ids: materialIds,
    minutes: minutes.trim() ? Number(minutes) : null,
    wishes: wishes.trim(),
    use_conspect: useConspect,
    model,
  }), [topic.id, template, level, basis, materialIds, minutes, wishes, useConspect, model]);

  // Оценка без модели при каждом выборе; ввод пожеланий не дёргает сервер на каждую букву.
  useEffect(() => {
    if (!open || jobId) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      previewLessonAi(projectId, order, controller.signal)
        .then((value) => {
          if (controller.signal.aborted) return;
          setPreview(value);
          setPreviewError("");
        })
        .catch((caught) => {
          if (!controller.signal.aborted) setPreviewError(errorText(caught, "Оценка не посчиталась"));
        });
    }, 300);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [open, jobId, projectId, order]);

  const chosenLevel = preview?.levels.find((item) => item.level === level) ?? null;
  useEffect(() => {
    if (limitTouched || !chosenLevel?.cost_usd) return;
    // Предел по умолчанию — верхняя граница оценки, с запасом до цента вверх.
    setLimit((Math.ceil(Number(chosenLevel.cost_usd) * 1000) / 1000).toFixed(3));
  }, [chosenLevel?.cost_usd, limitTouched]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (basis === "sources" && preview && !preview.sources_available) setBasis("sources_and_model");
  }, [basis, preview]);

  // Готово: план уходит в редактор плана, урок — родителю.
  useEffect(() => {
    if (!jobId || job?.state !== "completed") return;
    const controller = new AbortController();
    getBackgroundJobResult<LessonAiBuildResult | LessonAiPlanRead | LessonProposalRead | LessonAiBulkResult>(jobId, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        if ("lessons" in result) {
          // Массовая сборка из «Фона»: открыть первый собранный черновик.
          const first = result.lessons.find((item) => item.lesson_id);
          if (first?.lesson_id) onBuilt(first.lesson_id, first.dropped);
          setJobId(null);
          onOpenChange(false);
          return;
        }
        if ("ops" in result) {
          onProposal?.(jobId, result.lesson_id);
          setJobId(null);
          onOpenChange(false);
          return;
        }
        if ("steps" in result) {
          setPlan({ jobId, read: result });
          setPlanSteps(result.steps);
          setPlanLimit(null);
          setJobId(null);
          return;
        }
        if (!result.lesson_id) return;
        onBuilt(result.lesson_id, result.dropped);
        setJobId(null);
        onOpenChange(false);
      })
      .catch((caught) => { if (!controller.signal.aborted) setStartError(errorText(caught, "Итог сборки не прочитался")); });
    return () => controller.abort();
  }, [jobId, job?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  function chooseModel(value: AiModelSelection | null) {
    setModel(value);
    setLimitTouched(false);
    try {
      if (value) window.localStorage.setItem(MODEL_KEY(projectId), JSON.stringify(value));
      else window.localStorage.removeItem(MODEL_KEY(projectId));
    } catch { /* выбор живёт до закрытия вкладки */ }
  }

  function toggleMaterial(id: string, checked: boolean) {
    const current = materialIds ?? preview?.materials.filter((item) => item.selected).map((item) => item.material_id) ?? [];
    setMaterialIds(checked ? [...current, id] : current.filter((item) => item !== id));
  }

  async function launch(action: () => Promise<{ job_id: string }>, fallback: string): Promise<boolean> {
    setStarting(true);
    setStartError("");
    try {
      const result = await action();
      setJobId(result.job_id);
      return true;
    } catch (caught) {
      setStartError(errorText(caught, fallback));
      return false;
    } finally {
      setStarting(false);
    }
  }

  const command = () => ({
    ...order,
    max_cost_usd: limit.trim() ? limit.trim() : null,
    confirm_unknown_price: confirmUnknown,
  });
  const showsPlan = level !== "draft" && !skipPlan;

  function start() {
    void launch(
      () => (showsPlan ? startLessonAiPlan(projectId, command()) : startLessonAiBuild(projectId, command())),
      showsPlan ? "План не запустился" : "Сборка не запустилась",
    );
  }

  function buildFromPlan() {
    if (!plan) return;
    const limitValue = planLimit ?? storyboardCost(plan.read, planSteps).limit;
    const current = plan;
    void launch(() => startLessonAiBuild(projectId, {
      ...command(),
      max_cost_usd: limitValue || null,
      plan: {
        job_id: current.jobId, title: current.read.title, goal: current.read.goal,
        concepts: current.read.concepts,
        steps: planSteps.map((step) => ({ ...step, title: step.title.trim(), intent: step.intent.trim() })),
      },
    }), "Сборка не запустилась").then((started) => { if (started) setPlan(null); });
  }

  function resume() {
    if (!jobId) return;
    const current = jobId;
    void launch(() => resumeLessonAiBuild(projectId, current, null), "Сборку не удалось продолжить")
      .then(() => refreshJob());
  }

  const running = Boolean(jobId && job && (job.state === "queued" || job.state === "running" || job.state === "paused"));
  const failed = jobId && job && (job.state === "failed" || job.state === "cancelled");
  const offline = preview && !preview.models_available;
  const priceBlocked = Boolean(preview && !preview.price_known && !confirmUnknown);
  const levelOptions: Array<RadioCardOption<LessonLevel>> = (preview?.levels ?? []).map((item) => ({
    value: item.level,
    title: LEVEL_TEXT[item.level].title,
    description: LEVEL_TEXT[item.level].description,
    unavailableReason: item.available ? undefined : item.unavailable_reason ?? "Недоступно",
    extra: <span className="lesson-build-cost">{calls(item.calls)} · {usd(item.cost_usd)}</span>,
  }));

  const planInvalid = planSteps.some((step) => !step.title.trim() || !step.intent.trim());
  const footer = jobId ? (
    <>
      <Button variant="ghost" onClick={() => onOpenChange(false)}>{running ? "Свернуть — идёт в «Фоне»" : "Закрыть"}</Button>
      {failed && <Button variant="secondary" onClick={() => { setJobId(null); }}>Начать заново</Button>}
      {failed && <Button disabled={starting} onClick={resume}>Продолжить с места сбоя</Button>}
    </>
  ) : plan ? (
    <>
      <Button variant="ghost" onClick={() => { setPlan(null); }}>Назад к настройкам</Button>
      <Button disabled={starting || planInvalid || planSteps.length === 0} onClick={buildFromPlan}>
        <Sparkles size={15} />{starting ? "Ставим…" : "Собрать урок"}
      </Button>
    </>
  ) : (
    <>
      <Button variant="ghost" onClick={() => onOpenChange(false)}>Отмена</Button>
      <Button disabled={!preview || Boolean(offline) || starting || priceBlocked || !chosenLevel?.available} onClick={start}>
        <Sparkles size={15} />{starting ? "Ставим…" : showsPlan ? "Составить план" : "Собрать урок"}
      </Button>
    </>
  );
  const stage = job && job.total > 1 ? ` · шаг ${Math.min(job.done + 1, job.total)} из ${job.total}` : "";

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      className="lesson-build-dialog"
      title="Собрать урок с ИИ"
      description={jobId ? "Урок собирается фоном." : `«${topic.title}». Модель составит новый черновик; ваши уроки она не трогает.`}
      footer={footer}
    >
      {!jobId && plan ? (
        <LessonStoryboard plan={plan.read} steps={planSteps} onStepsChange={setPlanSteps}
          limit={planLimit} onLimitChange={setPlanLimit} />
      ) : jobId ? (
        <div className="lesson-build-progress" role="status">
          {!job && <LoadingState label="Узнаём состояние сборки" />}
          {running && job && (
            <>
              <p>Модель работает{job.model_label ? ` · ${job.model_label}` : ""}{stage}. Можно закрыть окно — работа продолжится в «Фоне»: план вернётся в «ждут проверки», урок появится в списке темы.</p>
              <Progress value={job.done} max={Math.max(job.total, 1)} label="Сборка урока" />
            </>
          )}
          {failed && job && <ErrorState title={job.state === "cancelled" ? "Сборка отменена" : "Сборка не удалась"} message={job.error ?? "Урок не создан"} />}
          {startError && <p className="inline-error" role="alert">{startError}</p>}
        </div>
      ) : (
        <div className="lesson-build-form">
          {offline && <OfflineNotice reason="disabled" alternative={`${preview.models_unavailable_reason ?? ""} Быстрый урок и ручная сборка работают без модели.`} />}
          {previewError && <p className="inline-error" role="alert">{previewError}</p>}

          <Field label="Как строить урок">
            <RadioCards label="Шаблон урока" value={template} options={TEMPLATE_OPTIONS} onChange={setTemplate} className="lesson-build-templates" />
          </Field>

          <Field label="Основа" hint={basis === "model_only" ? "Материалы не используются: урок из знаний модели, без ссылок на учебник" : undefined}>
            <SegmentedTabs
              label="Основа урока"
              value={basis}
              onChange={setBasis}
              tabs={BASIS_ORDER.map((value) => ({
                value,
                label: LESSON_BASIS_LABELS[value],
                disabled: value === "sources" && preview !== null && !preview.sources_available,
                tooltip: value === "sources" && preview !== null && !preview.sources_available
                  ? "По теме не нашлось материала — урок из одних материалов собрать не из чего"
                  : undefined,
              }))}
            />
          </Field>

          {basis !== "model_only" && (
            <Field label="Материалы" hint={preview ? `Найдено ${preview.candidates} кусков · ≈${preview.candidate_tokens.toLocaleString("ru-RU")} токенов · ${preview.material_state}` : "Считаем куски материала…"}>
              <div className="lesson-build-materials">
                {!preview && <LoadingState label="Ищем материал темы" />}
                {preview?.materials.map((item) => (
                  <Checkbox
                    key={item.material_id}
                    checked={materialIds ? materialIds.includes(item.material_id) : item.selected}
                    onCheckedChange={(checked) => toggleMaterial(item.material_id, checked)}
                    label={`${item.name} · ${SOURCE_ROLE_LABELS[item.role]}${item.page_from ? ` · стр. ${item.page_from}–${item.page_to}` : ""}${item.is_parsed ? "" : " · текст не распознан"}`}
                  />
                ))}
                {preview?.notes.map((note) => <p key={note} className="lesson-build-note">{note}</p>)}
              </div>
            </Field>
          )}

          <Field label="Глубина">
            {preview ? <RadioCards label="Глубина урока" value={level} options={levelOptions} onChange={setLevel} className="lesson-build-levels" /> : <LoadingState label="Оцениваем стоимость" />}
          </Field>
          {level !== "draft" && (
            <Checkbox checked={skipPlan} onCheckedChange={setSkipPlan}
              label="Собрать сразу, без плана — модель составит план сама и не покажет его" />
          )}

          <div className="lesson-build-row">
            <Field label="Длина, мин" hint={preview?.default_minutes ? `из паспорта: ${preview.default_minutes}` : "по объёму материала"}>
              <input type="number" min={5} max={240} value={minutes} placeholder={preview?.default_minutes ? String(preview.default_minutes) : "авто"} onChange={(event) => setMinutes(event.target.value)} />
            </Field>
            <Field label="Модель" hint={model || !preview?.model_label ? "Одна на всю сборку" : `Auto — ${preview.model_label}, модель роли из Параметров`}>
              <div className="lesson-build-model">
                <ChatModelControl role="lesson_builder" capabilities={["structured_output"]} value={model} parameters={{}} messageCount={0} onChange={(value) => chooseModel(value)} />
              </div>
            </Field>
            <Field label="Предел, $" hint="Сборка остановится, не превысив его">
              <input type="number" min={0.001} step={0.001} value={limit} onChange={(event) => { setLimit(event.target.value); setLimitTouched(true); }} />
            </Field>
          </div>

          <Field label="Пожелания к уроку" hint="Необязательно: «больше примеров из жизни, без истории протокола»">
            <input value={wishes} maxLength={1000} onChange={(event) => setWishes(event.target.value)} />
          </Field>

          {preview && preview.conspect_words > 0 && (
            <Checkbox
              checked={useConspect ?? preview.use_conspect}
              onCheckedChange={setUseConspect}
              label={`Учитывать мой конспект темы (${preview.conspect_words} слов)`}
            />
          )}
          {preview && !preview.price_known && preview.models_available && (
            <Checkbox checked={confirmUnknown} onCheckedChange={setConfirmUnknown} label="Цена модели неизвестна — запустить без оценки" />
          )}

          {preview && (
            <Disclosure summary={`Что увидит модель — паспорт урока, ${preview.candidates} кусков материала`}>
              <pre className="lesson-build-brief">{preview.brief_text}</pre>
            </Disclosure>
          )}
          {startError && <p className="inline-error" role="alert">{startError}</p>}
        </div>
      )}
    </Dialog>
  );
}
