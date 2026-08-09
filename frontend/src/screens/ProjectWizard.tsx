import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { ArrowLeft, BookOpen, GraduationCap, Sparkles, Trash2 } from "lucide-react";
import { listWizardDrafts, type TemplateKey, type WizardDraftSummary } from "../api/projects";
import { useWizardDraft } from "../hooks/useWizardDraft";
import { Button, Card, ConfirmDialog, ErrorState, LoadingState, PageHead } from "../components/ui";
import { ExamWizard } from "./project-wizard/ExamWizard";
import { TextbookWizard } from "./TextbookWizard";

type Track = "exam" | "textbook";

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
    setSearchParams({ track: nextTrack, draft: draft.project_id }, { replace: true });
  }

  function start(nextTrack: Track) {
    setResumeId(null);
    setTrack(nextTrack);
    setSearchParams({ track: nextTrack }, { replace: true });
  }

  function backToTracks() {
    setSearchParams({}, { replace: true });
    setTrack(null);
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

  if (!track) {
    return (
      <main className="wizard-screen">
        <header className="wizard-shell-head"><Link to="/projects"><ArrowLeft size={15} />К проектам</Link><strong>Tentex</strong></header>
        <div className="wizard-shell-content">
          <PageHead title="Как вы хотите учиться?" />
          <p className="lead">Выберите путь. Канонические данные будут сохранены в проекте, а не в браузере.</p>
          {loadingDrafts && <LoadingState label="Ищем сохранённые черновики" />}
          {draftError && <><ErrorState message={draftError} /><Button onClick={() => void loadDrafts()}>Повторить загрузку</Button></>}
          {drafts.length > 0 && <section className="wizard-resume"><h2>Продолжить черновик</h2>{drafts.map((draft) => <Card key={draft.project_id}><h3>{draft.name || (draft.template_key === "textbook" ? "Учебниковый черновик" : "Экзаменационный черновик")}</h3><p>Шаг {draft.current_step} из 5 · сохранён {new Date(draft.updated_at).toLocaleString("ru")}</p><Button onClick={() => resume(draft)}>Продолжить</Button></Card>)}</section>}
          <div className="wizard-track-grid">
            <Card className="wizard-track-card"><GraduationCap size={28} /><h2>Подготовка к экзамену</h2><p>Вставьте вопросы, задачи или билеты, проверьте программу и создайте проект.</p><Button onClick={() => start("exam")}>Начать подготовку</Button></Card>
            <Card className="wizard-track-card"><BookOpen size={28} /><h2>Изучение по учебнику</h2><p>Сохраните паспорт и ручную программу как черновик до подключения файлов.</p><Button onClick={() => start("textbook")}>Начать черновик</Button></Card>
            <Card className="wizard-track-card"><Sparkles size={28} /><h2>Свободное изучение</h2><p>Путь появится после каталога и проходов построения программы на этапе 7.</p><Button disabled>Недоступно до этапа 7</Button></Card>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="wizard-screen">
      <header className="wizard-shell-head">
        <Button variant="ghost" onClick={() => controller.detail ? void saveAndExit() : backToTracks()}><ArrowLeft size={15} />{controller.detail ? "Сохранить и выйти" : "К выбору"}</Button>
        <strong>Tentex</strong>
        {controller.detail && <Button variant="ghost" onClick={() => setDiscardOpen(true)}><Trash2 size={15} />Удалить черновик</Button>}
      </header>
      <div className="wizard-shell-content">
        {track === "exam" ? <ExamWizard controller={controller} /> : <TextbookWizard controller={controller} />}
      </div>
      <ConfirmDialog open={discardOpen} onOpenChange={setDiscardOpen} title="Удалить черновик?" confirmLabel="Удалить черновик" destructive onConfirm={() => void discard()}><p>Паспорт и ручная программа этого черновика будут удалены. Общие материалы других проектов не затрагиваются.</p></ConfirmDialog>
    </main>
  );
}
