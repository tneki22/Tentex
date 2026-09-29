import { useCallback, useEffect, useState, type FocusEvent } from "react";
import {
  createGeneratedCard, generateCards, getCardGenerationReview, updateCardProposal,
  type CardBatchReview, type CardGenerationMode, type CardRead, type GeneratedCard,
} from "../../api/cards";
import {
  listBackgroundJobs, resolveBackgroundJob, type BackgroundJobRead,
} from "../../api/backgroundJobs";
import { Button, Checkbox } from "../../components/ui";

interface AiCardCreatorProps {
  projectId: string;
  units: CardRead["unit"][];
  initialUnitId?: string | null;
  showControls: boolean;
  onChanged: () => void;
}

type Draft = Pick<GeneratedCard, "front" | "back" | "hint">;
type ReviewJob = { job: BackgroundJobRead; review: CardBatchReview };
const POLL_MS = 2500;
const pendingCount = (review: CardBatchReview) =>
  review.groups.reduce((count, group) =>
    count + group.candidates.filter((item) => item.status === "pending").length, 0);
const itemKey = (jobId: string, unitId: string, index: number) => `${jobId}:${unitId}:${index}`;

/** Показывает серверные предложения на странице способов и в режиме ИИ. */
export function AiCardCreator({
  projectId, units, initialUnitId, showControls, onChanged,
}: AiCardCreatorProps) {
  const [selected, setSelected] = useState<string[]>(initialUnitId ? [initialUnitId] : []);
  const [mode, setMode] = useState<CardGenerationMode>("connections");
  const [jobs, setJobs] = useState<ReviewJob[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [starting, setStarting] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState("");
  const available = units.filter((unit): unit is NonNullable<typeof unit> => unit !== null);

  const load = useCallback(async () => {
    const rows = await listBackgroundJobs({
      projectId, kind: "ai_cards", activeOnly: true, pendingReview: true, failedOnly: true,
    });
    const next = await Promise.all(rows.map(async (job) => ({
      job, review: await getCardGenerationReview(projectId, job.id),
    })));
    const ready = next.filter(({ job, review }) =>
      job.state === "completed" && pendingCount(review) === 0);
    await Promise.all(ready.map(({ job }) => resolveBackgroundJob(job.id)));
    setJobs(next.filter(({ job }) => !ready.some((item) => item.job.id === job.id)));
  }, [projectId]);

  useEffect(() => {
    void load().catch((reason: unknown) =>
      setError(reason instanceof Error ? reason.message : "Не удалось загрузить предложения"));
    const timer = window.setInterval(() => { void load().catch(() => undefined); }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  async function start() {
    if (!selected.length || starting) return;
    setStarting(true);
    setError("");
    try {
      await generateCards(projectId, selected, mode);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось запустить генерацию");
    } finally {
      setStarting(false);
    }
  }

  async function finish() {
    await load();
  }

  function currentDraft(jobId: string, unitId: string, item: GeneratedCard): Draft {
    return drafts[itemKey(jobId, unitId, item.index)] ?? item;
  }

  async function persist(jobId: string, unitId: string, item: GeneratedCard, rejected: boolean) {
    const draft = currentDraft(jobId, unitId, item);
    await updateCardProposal(projectId, jobId, unitId, item.index, {
      front: rejected ? item.front : draft.front.trim(),
      back: rejected ? item.back : draft.back.trim(),
      hint: rejected ? item.hint : draft.hint?.trim() || null,
      rejected,
    });
    if (rejected) await finish();
  }

  async function decide(
    jobId: string, unitId: string, runId: string, item: GeneratedCard, rejected: boolean,
  ) {
    const key = itemKey(jobId, unitId, item.index);
    const draft = currentDraft(jobId, unitId, item);
    if (!rejected && (!draft.front.trim() || !draft.back.trim())) return;
    setSaving(key);
    setError("");
    try {
      await persist(jobId, unitId, item, rejected);
      if (!rejected) {
        await createGeneratedCard(projectId, {
          program_node_id: unitId,
          front: draft.front.trim(), back: draft.back.trim(),
          hint: draft.hint?.trim() || null, source: item.source,
          state: "active",
          generation_run_id: runId, generation_candidate_index: item.index,
        });
        onChanged();
        await finish();
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось обработать предложение");
    } finally {
      setSaving(null);
    }
  }

  const hasWork = jobs.some(({ job, review }) =>
    job.state === "queued" || job.state === "running" || pendingCount(review) > 0);
  const running = jobs.some(({ job }) => job.state === "queued" || job.state === "running");
  if (!showControls && !hasWork) return null;

  return <section className="cards-ai-creator">
    {showControls && <>
      <p>Выберите вопросы или билеты. ИИ предложит до шести карточек для каждого. Проверьте их перед добавлением.</p>
      <div className="cards-ai-controls">
        <div className="cards-select-field cards-ai-unit-picker">
          <span>Вопросы и билеты</span>
          <details>
            <summary>{selected.length ? `Выбрано: ${selected.length}` : "Выберите вопросы"}</summary>
            <div className="cards-ai-unit-options">
              <Checkbox checked={available.length > 0 && selected.length === available.length}
                onCheckedChange={(checked) => setSelected(checked ? available.map((unit) => unit.id) : [])}
                label="Выбрать все" />
              {available.map((unit) => <Checkbox key={unit.id}
                checked={selected.includes(unit.id)}
                onCheckedChange={(checked) => setSelected((current) =>
                  checked ? [...current, unit.id] : current.filter((id) => id !== unit.id))}
                label={[...unit.path, unit.title].join(" · ")} />)}
            </div>
          </details>
        </div>
        <label className="cards-select-field">Режим
          <select value={mode} onChange={(event) => setMode(event.target.value as CardGenerationMode)}>
            <option value="connections">Основные связи</option>
            <option value="understanding">На понимание</option>
          </select>
        </label>
        <Button onClick={() => void start()} disabled={!selected.length || starting || running}>
          {starting ? "Ставим в очередь…" : running ? "Генерация уже идёт" : "Предложить карточки"}
        </Button>
      </div>
    </>}
    {hasWork && <h2>Предложения ИИ на проверку</h2>}
    {error && <p className="cards-ai-error" role="alert">{error}</p>}
    {jobs.map(({ job, review }) => {
      if (job.state === "completed" && pendingCount(review) === 0) return null;
      return <div className="cards-ai-job" key={job.id}>
        {["queued", "running"].includes(job.state) && <p role="status">
          ИИ готовит карточки · {job.done} из {job.total} вопросов. Можно уйти со страницы: предложения останутся здесь.
        </p>}
        {job.state === "failed" && <>
          <p role="alert">{job.error || "Генерация не удалась"}</p>
          {pendingCount(review) === 0 && <Button variant="ghost" onClick={() =>
            void resolveBackgroundJob(job.id).then(load).catch((reason: unknown) =>
              setError(reason instanceof Error ? reason.message : "Не удалось убрать ошибку"))}>
            Убрать ошибку
          </Button>}
        </>}
        {job.state !== "failed" && review.errors.map((message) =>
          <p className="cards-ai-note" key={message}>{message}</p>)}
        {review.groups.map((group) => group.candidates.filter((item) => item.status === "pending").map((item) => {
          const key = itemKey(job.id, group.program_node_id, item.index);
          const draft = currentDraft(job.id, group.program_node_id, item);
          const title = available.find((unit) => unit.id === group.program_node_id)?.title ?? "Вопрос";
          const change = (field: keyof Draft, value: string) =>
            setDrafts((current) => ({ ...current, [key]: { ...draft, [field]: value } }));
          const saveEdit = () => {
            if (!drafts[key] || !draft.front.trim() || !draft.back.trim()) return;
            void persist(job.id, group.program_node_id, item, false).catch((reason: unknown) =>
              setError(reason instanceof Error ? reason.message : "Не удалось сохранить правку"));
          };
          const onEditBlur = (event: FocusEvent) => {
            if (event.relatedTarget instanceof Element &&
              event.relatedTarget.closest(".cards-ai-actions")) return;
            saveEdit();
          };
          return <article className="cards-ai-candidate" key={key}>
            <div className="cards-ai-candidate-head">
              <strong>{title} · карточка {item.index + 1}</strong>
              <span>{item.source.kind === "reference" ? "По готовому ответу" : "По фрагменту"}</span>
            </div>
            <label>Вопрос
              <textarea value={draft.front} onChange={(event) => change("front", event.target.value)}
                onBlur={onEditBlur} />
            </label>
            <label>Ответ
              <textarea value={draft.back} onChange={(event) => change("back", event.target.value)}
                onBlur={onEditBlur} />
            </label>
            <label>Подсказка
              <input value={draft.hint ?? ""} placeholder="Направление мысли без готового ответа"
                onChange={(event) => change("hint", event.target.value)} onBlur={onEditBlur} />
            </label>
            {!draft.hint && <small className="cards-ai-note">
              ИИ не предложил полезную подсказку. Можно добавить свою или оставить поле пустым.
            </small>}
            <details className="cards-ai-evidence">
              <summary>Показать опору в источнике</summary>
              <blockquote>{item.evidence_quote}</blockquote>
            </details>
            <div className="cards-ai-actions">
              <Button disabled={saving !== null || !draft.front.trim() || !draft.back.trim()}
                onClick={() => void decide(job.id, group.program_node_id, group.run_id, item, false)}>
                {saving === key ? "Сохраняем…" : "Добавить в Банк"}
              </Button>
              <Button variant="ghost" disabled={saving !== null}
                onClick={() => void decide(job.id, group.program_node_id, group.run_id, item, true)}>
                Отклонить
              </Button>
            </div>
          </article>;
        }))}
      </div>;
    })}
  </section>;
}
