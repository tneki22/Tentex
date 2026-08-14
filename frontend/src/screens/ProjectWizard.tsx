import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { ArrowRight, BookOpen, GraduationCap, Sparkles, Trash2 } from "lucide-react";
import { discardWizardDraft, listWizardDrafts, type ProjectDetail, type TemplateKey, type WizardDraftSummary } from "../api/projects";
import { useWizardDraft } from "../hooks/useWizardDraft";
import { Button, Card, ConfirmDialog, ErrorState, IconButton, LoadingState, StatusBadge } from "../components/ui";
import { ExamWizard } from "./project-wizard/ExamWizard";
import { WizardChrome } from "./project-wizard/WizardChrome";
import { TextbookWizard } from "./TextbookWizard";

type Track = "exam" | "textbook";

const EXAM_STEP_LABELS = ["Формат", "Материалы", "Загрузка", "Паспорт", "Проверка"];
const TEXTBOOK_STEP_LABELS = ["Источники", "Профиль", "Проверка", "Программы", "Итог"];

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

function stepLabelsFor(templateKey: TemplateKey): readonly string[] {
  return templateKey === "textbook" ? TEXTBOOK_STEP_LABELS : EXAM_STEP_LABELS;
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
  const [deleteAllOpen, setDeleteAllOpen] = useState(false);
  const [deletingDraftId, setDeletingDraftId] = useState<string | null>(null);
  const [draftDeleteError, setDraftDeleteError] = useState("");
  const [requestedStep, setRequestedStep] = useState<number | null>(null);
  const [activatedProject, setActivatedProject] = useState<ProjectDetail | null>(null);
  const [activationWarning, setActivationWarning] = useState("");
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

  async function backToTracks() {
    await controller.flush();
    setResumeId(null);
    setSearchParams({}, { replace: true });
    setTrack(null);
    setRequestedStep(null);
    void loadDrafts();
  }

  async function saveAndExit() {
    await controller.flush();
    navigate("/projects");
  }

  async function discard() {
    setDraftDeleteError("");
    try {
      await controller.discard();
      navigate("/projects");
    } catch (error) {
      setDraftDeleteError(error instanceof Error ? error.message : "Не удалось удалить черновик");
      throw error;
    }
  }

  async function discardLandingDraft(draft: WizardDraftSummary) {
    setDraftDeleteError("");
    setDeletingDraftId(draft.project_id);
    try {
      await discardWizardDraft(draft.project_id, draft.revision);
      setDrafts((current) => current.filter((item) => item.project_id !== draft.project_id));
    } catch (error) {
      setDraftDeleteError(error instanceof Error ? error.message : "Не удалось удалить черновик");
    } finally {
      setDeletingDraftId(null);
    }
  }

  async function discardAllLandingDrafts() {
    setDraftDeleteError("");
    const results = await Promise.allSettled(drafts.map((draft) => discardWizardDraft(draft.project_id, draft.revision)));
    const failed = results.filter((result) => result.status === "rejected").length;
    if (failed > 0) {
      await loadDrafts();
      const message = `Не удалось удалить черновики: ${failed}. Список обновлён.`;
      setDraftDeleteError(message);
      throw new Error(message);
    }
    setDrafts([]);
  }

  const currentStep = track ? requestedStep ?? controller.detail?.draft.current_step ?? 1 : 0;
  const maxStep = track ? controller.detail?.draft.max_completed_step ?? 1 : 0;
  const trackLabel = track === "exam" ? "Экзамен" : track === "textbook" ? "Учебник" : null;
  const stepLabels = track === "textbook" ? TEXTBOOK_STEP_LABELS : EXAM_STEP_LABELS;

  if (activatedProject) {
    const textbook = activatedProject.project.workspace_variant === "textbook";
    const first = activatedProject.program.nodes.find((node) => ["topic", "subpoint"].includes(node.node_type) && node.is_in_current_program && !node.is_archived);
    const destination = textbook
      ? `/projects/${activatedProject.project.id}/program`
      : `/projects/${activatedProject.project.id}${first ? `?topic=${first.id}` : ""}`;
    return (
      <div className="project-wizard is-success">
        <Card className="wizard-success-card">
          <h1>Создан проект: {activatedProject.project.name || (textbook ? "Учебниковый проект" : "Экзаменационный проект")}</h1>
          <p>{first ? "Паспорт цели и программа сохранены." : textbook ? "Паспорт цели и источники сохранены. Программу можно составить позже." : "Паспорт цели сохранён. Вопросы можно импортировать позже."}</p>
          {activationWarning && <p className="inline-warning" role="status">{activationWarning}</p>}
          <p className="wizard-success-next">Следующий шаг — {textbook ? "открыть Программу и добавить первую тему, когда будете готовы" : "открыть проект, проверить программу и начать готовиться"}.</p>
          <div className="wizard-success-actions">
            <Button onClick={() => navigate(destination)}>{textbook ? "Открыть программу" : "Открыть проект"}</Button>
            {activationWarning && <Button variant="secondary" onClick={() => navigate(`/projects/${activatedProject.project.id}/materials`)}>Открыть Материалы</Button>}
            <Button variant="ghost" onClick={() => { setActivatedProject(null); setActivationWarning(""); }}>Вернуться к проверке</Button>
          </div>
        </Card>
      </div>
    );
  }

  if (!track) {
    return (
      <>
        <WizardChrome
          trackLabel={null}
          step={0}
          maxStep={0}
          stepLabels={EXAM_STEP_LABELS}
          onStepChange={setRequestedStep}
        >
          <div className="wizard-hero">
            <h1>Как вы хотите<br />учиться?</h1>
            <p>Расскажите, к чему готовитесь и что у вас уже есть. Tentex поможет собрать программу и следующий шаг.</p>
          </div>

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

          {loadingDrafts && <LoadingState label="Ищем сохранённые черновики" />}
          {draftError && <section className="wizard-resume"><ErrorState message={draftError} /><Button onClick={() => void loadDrafts()}>Повторить загрузку</Button></section>}
          {!loadingDrafts && !draftError && drafts.length > 0 && (
            <section className="wizard-resume" aria-labelledby="wizard-resume-heading">
              <div className="wizard-resume-head">
                <h2 id="wizard-resume-heading">Продолжить черновик</h2>
                <Button variant="ghost" className="wizard-delete-all" disabled={deletingDraftId !== null} onClick={() => setDeleteAllOpen(true)}><Trash2 size={15} aria-hidden="true" />Удалить все черновики</Button>
              </div>
              {draftDeleteError && <p className="inline-error" role="alert">{draftDeleteError}</p>}
              {drafts.map((draft) => (
                <Card key={draft.project_id}>
                  <h3>{draft.name?.trim() || draftBranch(draft)}</h3>
                  <p>{draftBranch(draft)}, шаг {draft.current_step} из {stepLabelsFor(draft.template_key).length}</p>
                  <div className="wizard-resume-actions">
                    <Button onClick={() => resume(draft)}>Продолжить</Button>
                    <IconButton label={`Удалить черновик «${draft.name?.trim() || draftBranch(draft)}»`} className="wizard-resume-delete" disabled={deletingDraftId !== null} onClick={() => void discardLandingDraft(draft)}><Trash2 size={16} aria-hidden="true" /></IconButton>
                  </div>
                </Card>
              ))}
            </section>
          )}
        </WizardChrome>
        <ConfirmDialog open={deleteAllOpen} onOpenChange={setDeleteAllOpen} title="Удалить все черновики?" confirmLabel="Удалить все черновики" destructive onConfirm={discardAllLandingDrafts}>
          <p>Будут удалены все сохранённые черновики: {drafts.length}. Это действие нельзя отменить.</p>
          {draftDeleteError && <p className="inline-error" role="alert">{draftDeleteError}</p>}
        </ConfirmDialog>
      </>
    );
  }

  return (
    <>
      <WizardChrome
        trackLabel={track === "textbook" ? null : trackLabel}
        step={currentStep}
        maxStep={maxStep}
        stepLabels={stepLabels}
        onStepChange={setRequestedStep}
        onBack={currentStep === 1 ? () => void backToTracks() : undefined}
        onSaveAndExit={controller.detail ? () => void saveAndExit() : undefined}
        onDiscard={controller.detail ? () => setDiscardOpen(true) : undefined}
      >
        {track === "exam"
          ? <ExamWizard controller={controller} requestedStep={currentStep} onStepChange={setRequestedStep} onActivated={(project, warning) => { setActivationWarning(warning ?? ""); setActivatedProject(project); }} />
          : <TextbookWizard controller={controller} requestedStep={currentStep} onStepChange={setRequestedStep} onActivated={(project) => { setActivationWarning(""); setActivatedProject(project); }} />}
      </WizardChrome>
      <ConfirmDialog open={discardOpen} onOpenChange={setDiscardOpen} title="Удалить черновик?" confirmLabel="Удалить черновик" destructive onConfirm={discard}>
        <p>Паспорт и ручная программа этого черновика будут удалены. Общие материалы других проектов не затрагиваются.</p>
        {draftDeleteError && <p className="inline-error" role="alert">{draftDeleteError}</p>}
      </ConfirmDialog>
    </>
  );
}
