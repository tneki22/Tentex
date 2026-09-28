import { useEffect, useMemo, useState } from "react";
import { Sparkles } from "lucide-react";
import type { AiModelSelection } from "../../api/ai";
import { getBackgroundJobResult } from "../../api/backgroundJobs";
import {
  LESSON_BASIS_LABELS,
  previewLessonEnrich,
  startLessonEnrich,
  type LessonBasis,
  type LessonEnrichDepth,
  type LessonEnrichPreflightRead,
  type LessonProposalRead,
} from "../../api/lessons";
import { OfflineNotice } from "../../components/domain";
import { Button, Checkbox, Dialog, ErrorState, Field, LoadingState, Progress, SegmentedTabs } from "../../components/ui";
import { useBackgroundJob } from "../../hooks/useBackgroundJob";
import { ChatModelControl } from "../workspace/chat/ChatModelControl";
import { errorText } from "./lessonTree";

interface LessonEnrichDialogProps {
  open: boolean;
  onOpenChange(open: boolean): void;
  projectId: string;
  lesson: { id: string; title: string; revision: number };
  /** Выбранный блок урока и его подпись: просьба может касаться только его. */
  selectedBlock: { id: string; label: string } | null;
  /** Предложение готово — его показывает документ урока. */
  onProposal(jobId: string, proposal: LessonProposalRead): void;
}

const QUICK_REQUESTS = ["Объясни проще", "Добавь примеры", "Определи термины"];
const BASIS_ORDER: LessonBasis[] = ["sources_and_model", "sources", "model_only"];
const DEPTH_TABS: Array<{ value: LessonEnrichDepth; label: string; tooltip: string }> = [
  { value: "economy", label: "Экономно", tooltip: "Одна порция текста урока — один вызов" },
  { value: "full", label: "Полностью", tooltip: "Весь урок, до четырёх порций" },
];
const MODEL_KEY = (projectId: string) => `tentex:lesson-ai-model:${projectId}`;

function readModel(projectId: string): AiModelSelection | null {
  try {
    const raw = window.localStorage.getItem(MODEL_KEY(projectId));
    return raw ? (JSON.parse(raw) as AiModelSelection) : null;
  } catch {
    return null;
  }
}

function usd(value: string | null): string {
  if (value === null) return "цена неизвестна";
  const number = Number(value);
  return number < 0.01 ? `≈$${number.toFixed(4)}` : `≈$${number.toFixed(2)}`;
}

/**
 * «Дополнить с ИИ»: модель читает урок и предлагает пояснения, примеры и
 * определения между блоками. Предложение приходит в документ урока — там его
 * принимают частично и отменяют одним действием; материал модель не удаляет.
 */
export function LessonEnrichDialog({ open, onOpenChange, projectId, lesson, selectedBlock, onProposal }: LessonEnrichDialogProps) {
  const [basis, setBasis] = useState<LessonBasis>("sources_and_model");
  const [depth, setDepth] = useState<LessonEnrichDepth>("economy");
  const [request, setRequest] = useState("");
  const [onlySelected, setOnlySelected] = useState(true);
  const [model, setModel] = useState<AiModelSelection | null>(() => readModel(projectId));
  const [confirmUnknown, setConfirmUnknown] = useState(false);
  const [preview, setPreview] = useState<LessonEnrichPreflightRead | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const { job } = useBackgroundJob(jobId);

  useEffect(() => {
    if (!open) return;
    setJobId(null);
    setStartError("");
    setOnlySelected(Boolean(selectedBlock));
  }, [open, selectedBlock]);

  const order = useMemo(() => ({
    basis, depth, request: request.trim(),
    block_id: onlySelected && selectedBlock ? selectedBlock.id : null,
    model,
  }), [basis, depth, request, onlySelected, selectedBlock, model]);

  useEffect(() => {
    if (!open || jobId) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      previewLessonEnrich(projectId, lesson.id, order, controller.signal)
        .then((value) => { if (!controller.signal.aborted) { setPreview(value); setPreviewError(""); } })
        .catch((caught) => { if (!controller.signal.aborted) setPreviewError(errorText(caught, "Оценка не посчиталась")); });
    }, 300);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [open, jobId, projectId, lesson.id, order]);

  useEffect(() => {
    if (!jobId || job?.state !== "completed") return;
    const controller = new AbortController();
    getBackgroundJobResult<LessonProposalRead>(jobId, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        onProposal(jobId, result);
        onOpenChange(false);
      })
      .catch((caught) => { if (!controller.signal.aborted) setStartError(errorText(caught, "Предложение не прочиталось")); });
    return () => controller.abort();
  }, [jobId, job?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  function chooseModel(value: AiModelSelection | null) {
    setModel(value);
    try {
      if (value) window.localStorage.setItem(MODEL_KEY(projectId), JSON.stringify(value));
      else window.localStorage.removeItem(MODEL_KEY(projectId));
    } catch { /* выбор живёт до закрытия вкладки */ }
  }

  async function start() {
    setStarting(true);
    setStartError("");
    try {
      const upper = preview?.cost_usd ? (Math.ceil(Number(preview.cost_usd) * 1000) / 1000).toFixed(3) : null;
      const result = await startLessonEnrich(projectId, lesson.id, {
        ...order, expected_revision: lesson.revision, max_cost_usd: upper, confirm_unknown_price: confirmUnknown,
      });
      setJobId(result.job_id);
    } catch (caught) {
      setStartError(errorText(caught, "Дополнение не запустилось"));
    } finally {
      setStarting(false);
    }
  }

  const running = Boolean(jobId && job && ["queued", "running", "paused"].includes(job.state));
  const failed = Boolean(jobId && job && (job.state === "failed" || job.state === "cancelled"));
  const offline = preview && !preview.models_available;
  const priceBlocked = Boolean(preview && preview.models_available && !preview.price_known && !confirmUnknown);

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      className="lesson-enrich-dialog"
      title="Дополнить урок с ИИ"
      description={`«${lesson.title}». Изменения придут предложением: вы выберете, что принять, и отмените их одним действием.`}
      footer={jobId ? (
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{running ? "Свернуть — идёт в «Фоне»" : "Закрыть"}</Button>
          {failed && <Button onClick={() => setJobId(null)}>Попробовать снова</Button>}
        </>
      ) : (
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Отмена</Button>
          <Button disabled={!preview || Boolean(offline) || starting || priceBlocked} onClick={() => void start()}>
            <Sparkles size={15} />{starting ? "Ставим…" : "Предложить изменения"}
          </Button>
        </>
      )}
    >
      {jobId ? (
        <div className="lesson-build-progress" role="status">
          {!job && <LoadingState label="Узнаём состояние" />}
          {running && job && (
            <>
              <p>Модель читает урок{job.model_label ? ` · ${job.model_label}` : ""}. Можно закрыть окно — предложение вернётся в «ждут проверки».</p>
              <Progress value={job.done} max={Math.max(job.total, 1)} label="Дополнение урока" />
            </>
          )}
          {failed && job && <ErrorState title={job.state === "cancelled" ? "Отменено" : "Не удалось"} message={job.error ?? "Предложения нет"} />}
          {startError && <p className="inline-error" role="alert">{startError}</p>}
        </div>
      ) : (
        <div className="lesson-build-form">
          {offline && <OfflineNotice reason="disabled" alternative={`${preview?.models_unavailable_reason ?? ""} Пояснения можно добавить вручную: «Блок» в панели урока.`} />}
          {previewError && <p className="inline-error" role="alert">{previewError}</p>}
          <Field label="Основа">
            <SegmentedTabs label="Основа дополнения" value={basis} onChange={setBasis}
              tabs={BASIS_ORDER.map((value) => ({ value, label: LESSON_BASIS_LABELS[value] }))} />
          </Field>
          <Field label="Сколько урока читать">
            <SegmentedTabs label="Глубина дополнения" value={depth} onChange={setDepth} tabs={DEPTH_TABS} />
          </Field>
          <Field label="Просьба" hint="Необязательно. Пусто — модель сама найдёт, где читателю не хватает пояснений">
            <input value={request} maxLength={1000} onChange={(event) => setRequest(event.target.value)} placeholder="Например: объясни формат кадра на примере" />
          </Field>
          <div className="lesson-enrich-quick" aria-label="Быстрые просьбы">
            {QUICK_REQUESTS.map((item) => (
              <button key={item} type="button" className={`lesson-enrich-chip${request === item ? " is-active" : ""}`} onClick={() => setRequest(item)}>{item}</button>
            ))}
          </div>
          {selectedBlock && (
            <Checkbox checked={onlySelected} onCheckedChange={setOnlySelected} label={`Только выбранный блок: ${selectedBlock.label}`} />
          )}
          <div className="lesson-build-row is-two">
            <Field label="Модель" hint={model || !preview?.model_label ? "Модель роли «Дополнение урока»" : `Auto — ${preview.model_label}`}>
              <div className="lesson-build-model">
                <ChatModelControl role="lesson_enrich" capabilities={["structured_output"]} value={model} parameters={{}} messageCount={0} onChange={(value) => chooseModel(value)} />
              </div>
            </Field>
            <Field label="Оценка">
              <p className="lesson-build-cost">
                {preview ? `${preview.calls} ${preview.calls === 1 ? "вызов" : "вызова"} · ${usd(preview.cost_usd)} · верх оценки станет пределом` : "Считаем…"}
              </p>
            </Field>
          </div>
          {preview && preview.models_available && !preview.price_known && (
            <Checkbox checked={confirmUnknown} onCheckedChange={setConfirmUnknown} label="Цена модели неизвестна — запустить без оценки" />
          )}
          {startError && <p className="inline-error" role="alert">{startError}</p>}
        </div>
      )}
    </Dialog>
  );
}
