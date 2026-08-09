import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { ArrowRight, BookOpen, GraduationCap, Sparkles } from "lucide-react";
import { listWizardDrafts, type TemplateKey, type WizardDraftSummary } from "../api/projects";
import { useWizardDraft } from "../hooks/useWizardDraft";
import { Button, Card, ConfirmDialog, ErrorState, LoadingState, StatusBadge } from "../components/ui";
import { ExamWizard } from "./project-wizard/ExamWizard";
import { WizardChrome } from "./project-wizard/WizardChrome";
import { TextbookWizard } from "./TextbookWizard";

type Track = "exam" | "textbook";

const STEP_LABELS = ["Формат", "Материалы", "Загрузка", "Паспорт", "Проверка"];

const TRACKS = [
  {
    id: "exam",
    icon: GraduationCap,
    eyebrow: "До конкретной даты",
    title: "Подготовка к экзамену",
    description: "Есть вопросы, задачи, билеты или только учебные материалы. Соберём программу и распределим работу до экзамена.",
    need: "Список формулировок или материалы по предмету",
    result: "Структура экзамена, программа и понятный темп подготовки",
    available: true,
  },
  {
    id: "textbook",
    icon: BookOpen,
    eyebrow: "Источник + ваша цель",
    title: "Изучение по учебнику",
    description: "Есть учебник, методичка или курс и своя цель. Найдём в материалах нужные темы, предпосылки и связи.",
    need: "Один или несколько основных учебных материалов",
    result: "Программа под цель с привязкой к главам и честными пробелами",
    available: true,
  },
  {
    id: "free",
    icon: Sparkles,
    eyebrow: "От цели к программе",
    title: "Свободное изучение",
    description: "Есть цель, но нет обязательной программы или одного главного источника. Начнём с ориентира и дополним его по ходу.",
    need: "Цель и примерное представление о желаемом результате",
    result: "Гибкая программа, которую можно уточнять материалами",
    available: false,
  },
] as const;

function draftBranch(draft: WizardDraftSummary): string {
  return draft.template_key === "textbook" ? "Изучение по учебнику" : "Подготовка к экзамену";
}

function draftName(draft: WizardDraftSummary): string {
  return draft.name || (draft.template_key === "textbook" ? "Учебниковый черновик" : "Экзаменационный черновик");
}

export function ProjectWizard() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const initialTrack = searchParams.get("track");
  const [track, setTrack] = useState<Track | null>(initialTrack === "exam" || initialTrack === "textbook" ? initialTrack : null);
  const [resumeId, setResumeId] = useState<string | null>(searchParams.get("draft"));
  const [drafts, setDrafts] = useState<WizardDraftSummary[]>([]);
  const [loadingDrafts, setLoadingDrafts] = useState(true);
  const [draftError, setDraftError] = useState("");
  const [discardOpen, setDiscardOpen] = useState(false);
  const [requestedStep, setRequestedStep] = useState<number | null>(null);
  const templateKey: TemplateKey = track ?? "exam";
  const controller = useWizardDraft({ templateKey, projectId: resumeId });

  async function loadDrafts(signal?: AbortSignal) {
    setLoadingDrafts(true);
    setDraftError("");
    try { setDrafts(await listWizardDrafts(signal)); }
    catch (error) { if (!signal?.aborted) setDraftError(error instanceof Error ? error.message : "Не удалось загрузить черновики"); }
    finally { if (!signal?.aborted) setLoadingDrafts(false); }
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadDrafts(controller.signal);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!controller.detail) return;
    setResumeId(controller.detail.project.id);
    if (searchParams.get("track") !== track || searchParams.get("draft") !== controller.detail.project.id) {
      setSearchParams({ track: track ?? controller.detail.project.template_key, draft: controller.detail.project.id }, { replace: true });
    }
    const onBeforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [controller.detail?.project.id, track]);

  function resume(draft: WizardDraftSummary) {
    const nextTrack = draft.template_key === "textbook" ? "textbook" : "exam";
    setTrack(nextTrack);
    setResumeId(draft.project_id);
    setRequestedStep(null);
    setSearchParams({ track: nextTrack, draft: draft.project_id }, { replace: true });
  }

  function start(nextTrack: Track) {
    setResumeId(null);
    setTrack(nextTrack);
    setRequestedStep(null);
    setSearchParams({ track: nextTrack }, { replace: true });
  }

  function backToTracks() {
    setSearchParams({}, { replace: true });
    setTrack(null);
    setRequestedStep(null);
  }

  async function saveAndExit() {
    await controller.flush();
    navigate("/projects");
  }

  async function discard() {
    await controller.discard();
    setDiscardOpen(false);
    navigate("/projects");
  }

  const currentStep = track ? requestedStep ?? controller.detail?.draft.current_step ?? 1 : 0;
  const maxStep = track ? controller.detail?.draft.max_completed_step ?? 1 : 0;
  const trackLabel = track === "exam" ? "Экзамен" : track === "textbook" ? "Учебник" : null;

  if (!track) {
    return (
      <WizardChrome
        trackLabel={null}
        step={0}
        maxStep={0}
        stepLabels={STEP_LABELS}
        onStepChange={setRequestedStep}
      >
        <div className="wizard-hero">
          <h1>Как вы хотите<br />учиться?</h1>
          <p>Расскажите, к чему готовитесь и что у вас уже есть. Tentex поможет собрать программу и следующий шаг.</p>
        </div>

        {loadingDrafts && <LoadingState label="Ищем сохранённые черновики" />}
        {draftError && <section className="wizard-resume"><ErrorState message={draftError} /><Button onClick={() => void loadDrafts()}>Повторить загрузку</Button></section>}
        {!loadingDrafts && !draftError && drafts.length > 0 && (
          <section className="wizard-resume" aria-labelledby="wizard-resume-heading">
            <h2 id="wizard-resume-heading">Продолжить черновик</h2>
            {drafts.map((draft) => (
              <Card key={draft.project_id}>
                <h3>{draftName(draft)}</h3>
                <p>{draftBranch(draft)} · шаг {draft.current_step} из {STEP_LABELS.length}</p>
                <time dateTime={draft.updated_at}>Обновлён {new Date(draft.updated_at).toLocaleString("ru-RU")}</time>
                <Button onClick={() => resume(draft)}>Продолжить</Button>
              </Card>
            ))}
          </section>
        )}

        <div className="wizard-track-grid">
          {TRACKS.map((item) => {
            const Icon = item.icon;
            return (
              <button
                type="button"
                className={`wizard-track-card ${item.available ? "is-available" : "is-soon"}`}
                key={item.id}
                disabled={!item.available}
                onClick={() => item.available && start(item.id)}
              >
                <span className="wizard-track-top">
                  <span className="wizard-track-icon"><Icon size={24} aria-hidden="true" /></span>
                  {!item.available && <StatusBadge>После этапа 7</StatusBadge>}
                </span>
                <small className="wizard-track-eyebrow">{item.eyebrow}</small>
                <h2>{item.title}</h2>
                <p>{item.description}</p>
                <span className="wizard-track-details">
                  <span><b>Что понадобится</b>{item.need}</span>
                  <span><b>Что получится</b>{item.result}</span>
                </span>
                <span className="wizard-track-action">
                  {item.available ? "Выбрать этот путь" : "После этапа 7"}
                  {item.available && <ArrowRight size={16} aria-hidden="true" />}
                </span>
              </button>
            );
          })}
        </div>
      </WizardChrome>
    );
  }

  return (
    <>
      <WizardChrome
        trackLabel={trackLabel}
        step={currentStep}
        maxStep={maxStep}
        stepLabels={STEP_LABELS}
        onStepChange={setRequestedStep}
        onBack={controller.detail ? undefined : backToTracks}
        onSaveAndExit={controller.detail ? () => void saveAndExit() : undefined}
        onDiscard={controller.detail ? () => setDiscardOpen(true) : undefined}
      >
        {track === "exam" ? <ExamWizard controller={controller} requestedStep={currentStep} onStepChange={setRequestedStep} /> : <TextbookWizard controller={controller} requestedStep={currentStep} onStepChange={setRequestedStep} />}
      </WizardChrome>
      <ConfirmDialog open={discardOpen} onOpenChange={setDiscardOpen} title="Удалить черновик?" confirmLabel="Удалить черновик" destructive onConfirm={() => void discard()}><p>Паспорт и ручная программа этого черновика будут удалены. Общие материалы других проектов не затрагиваются.</p></ConfirmDialog>
    </>
  );
}
