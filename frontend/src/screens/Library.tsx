import { useEffect, useMemo, useRef, useState } from "react";
import { AudioLines, FileText, Globe, Image, Trash2, Upload, Video } from "lucide-react";
import { Link } from "react-router";
import {
  deleteLibraryMaterial,
  getMaterialDeletePreview,
  listLibraryMaterials,
  uploadMaterial,
  type LibraryMaterialRead,
  type MaterialDeletePreview,
  type MaterialPurpose,
} from "../api/materials";
import { listProjects, type ProjectSummary } from "../api/projects";
import { QualityBadge } from "../components/domain";
import {
  Button,
  Card,
  ConfirmDialog,
  Dialog,
  Disclosure,
  EmptyState,
  ErrorState,
  Field,
  IconButton,
  LoadingState,
  PageHead,
  StatusBadge,
} from "../components/ui";

const PURPOSE: Record<MaterialPurpose, string> = {
  exam_structure: "список вопросов",
  reference_answers: "эталонные ответы",
  study_source: "учебный источник",
};

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} КБ`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} МБ`;
  return `${(bytes / 1024 ** 3).toFixed(1)} ГБ`;
}

function MaterialIcon({ material }: { material: LibraryMaterialRead }) {
  if (material.source_kind === "youtube") return <Video size={16} aria-hidden="true" />;
  if (material.source_kind === "url") return <Globe size={16} aria-hidden="true" />;
  if (material.source_kind === "audio") return <AudioLines size={16} aria-hidden="true" />;
  if (material.media_type.startsWith("image/")) return <Image size={16} aria-hidden="true" />;
  return <FileText size={16} aria-hidden="true" />;
}

export function Library() {
  const input = useRef<HTMLInputElement>(null);
  const [materials, setMaterials] = useState<LibraryMaterialRead[]>([]);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [projectId, setProjectId] = useState("");
  const [purpose, setPurpose] = useState<MaterialPurpose>("study_source");
  const [deletePreview, setDeletePreview] = useState<MaterialDeletePreview | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  async function load(signal?: AbortSignal) {
    setLoading(true);
    setError("");
    try {
      const [nextMaterials, nextProjects] = await Promise.all([
        listLibraryMaterials(signal),
        listProjects(signal),
      ]);
      setMaterials(nextMaterials);
      setProjects(nextProjects.filter((project) => project.status === "active"));
      setProjectId((current) => current || nextProjects.find((project) => project.status === "active")?.id || "");
    } catch (caught) {
      if (!signal?.aborted) setError(caught instanceof Error ? caught.message : "Не удалось загрузить Библиотеку");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, []);

  const totals = useMemo(() => ({
    pages: materials.reduce((sum, material) => sum + (material.page_count ?? 0), 0),
    bytes: materials.reduce((sum, material) => sum + material.size_bytes, 0),
  }), [materials]);

  async function chooseDelete(materialId: string) {
    setDeleteLoading(true);
    setError("");
    try {
      setDeletePreview(await getMaterialDeletePreview(materialId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось проверить последствия удаления");
    } finally {
      setDeleteLoading(false);
    }
  }

  async function removeMaterial() {
    if (!deletePreview) return;
    setBusy(true);
    try {
      await deleteLibraryMaterial(deletePreview.material.id);
      setDeletePreview(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось удалить материал");
    } finally {
      setBusy(false);
    }
  }

  async function upload(file: File) {
    if (!projectId) return;
    setBusy(true);
    setError("");
    try {
      await uploadMaterial(
        projectId,
        file,
        purpose === "study_source" ? "main" : "reference",
        [purpose],
      );
      setUploadOpen(false);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось загрузить материал");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <LoadingState label="Загружаем Библиотеку" placement="page" />;

  return (
    <div className="screen">
      <PageHead
        placement="topbar"
        title="Библиотека"
        lead={`${materials.length} файлов · ${totals.pages} страниц · ${sizeLabel(totals.bytes)}. Файл хранится один раз, проекты на него ссылаются.`}
        actions={<Button variant="secondary" disabled={projects.length === 0} onClick={() => setUploadOpen(true)}><Upload size={15} aria-hidden="true" />Загрузить файл</Button>}
      />
      {error && <ErrorState message={error} />}
      {deleteLoading && <LoadingState label="Проверяем последствия удаления" />}

      {materials.length === 0 ? (
        <EmptyState title="Библиотека пока пуста">
          <p>Добавьте материал в проект — общий файл появится здесь автоматически.</p>
          {projects.length > 0 && <Button onClick={() => setUploadOpen(true)}>Загрузить первый файл</Button>}
        </EmptyState>
      ) : (
        <div className="lib-list">
          {materials.map((material) => (
            <Card className="lib-row" key={material.id}>
              <div className="lib-row-main">
                <span className="lib-row-icon"><MaterialIcon material={material} /></span>
                <span className="lib-row-name">{material.original_name}</span>
                <span className="lib-row-meta">{sizeLabel(material.size_bytes)}</span>
                <span className="lib-row-meta">{material.page_count ?? "—"} стр.</span>
                <span className="lib-row-quality">
                  {material.native_page_count > 0 && <QualityBadge quality="native" count={material.native_page_count} />}
                  {material.ocr_page_count > 0 && <QualityBadge quality="ocr" count={material.ocr_page_count} />}
                  {material.ocr_low_page_count > 0 && <QualityBadge quality="ocr_low" count={material.ocr_low_page_count} />}
                  {material.status !== "ready" && <StatusBadge>{material.status === "failed" ? "Ошибка" : "Не разобран"}</StatusBadge>}
                </span>
                <span className="lib-row-usage">
                  {material.usage.length > 0 ? material.usage.map((usage, index) => (
                    <span key={`${usage.project_id}-${index}`}>
                      <Link to={`/projects/${usage.project_id}/materials/${material.id}`}>{usage.project_name}</Link>
                      <small>{usage.display_name} · {usage.purposes.map((item) => PURPOSE[item]).join(", ")}</small>
                    </span>
                  )) : <span className="lib-unused">не используется</span>}
                </span>
                <IconButton label={`Удалить ${material.original_name}`} disabled={busy} onClick={() => void chooseDelete(material.id)}><Trash2 size={15} /></IconButton>
              </div>
              <Disclosure summary="Подробности файла">
                <div className="lib-row-detail">
                  <span className="lib-row-meta">Добавлен {new Date(material.created_at).toLocaleDateString("ru-RU")}</span>
                  <span className="lib-row-meta">Хеш {material.sha256.slice(0, 8)}…{material.sha256.slice(-4)}</span>
                  <span className="lib-row-meta">Блоков {material.block_count} · фрагментов {material.fragment_count}</span>
                  {material.source_url && <a href={material.source_url} target="_blank" rel="noreferrer">Открыть исходную ссылку</a>}
                </div>
              </Disclosure>
            </Card>
          ))}
        </div>
      )}

      <p className="lib-note">«Не используется» — нейтральный факт: файл мог остаться после проекта или быть загружен впрок.</p>

      <Dialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        title="Загрузить материал"
        description="Материал сразу связывается с выбранным проектом. Разбор запускается в разделе Материалы после проверки оценки."
        footer={<><Button variant="ghost" onClick={() => setUploadOpen(false)}>Отменить</Button><Button disabled={busy || !projectId} onClick={() => input.current?.click()}>Выбрать файл</Button></>}
      >
        <input ref={input} className="materials-file-input" type="file" tabIndex={-1} aria-hidden="true" accept=".pdf,.docx,.txt,.md,.jpg,.jpeg,.png,.mp3,.wav,.m4a,.ogg,.flac" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); event.target.value = ""; }} />
        <div className="materials-text-form">
          <Field label="Проект" required><select value={projectId} onChange={(event) => setProjectId(event.target.value)}>{projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select></Field>
          <Field label="Использовать как" required><select value={purpose} onChange={(event) => setPurpose(event.target.value as MaterialPurpose)}><option value="study_source">Учебный источник</option><option value="exam_structure">Список вопросов</option><option value="reference_answers">Эталонные ответы</option></select></Field>
        </div>
      </Dialog>

      <ConfirmDialog
        open={deletePreview !== null}
        onOpenChange={(open) => !open && setDeletePreview(null)}
        title={`Удалить ${deletePreview?.material.original_name ?? "материал"}?`}
        confirmLabel="Удалить файл везде"
        destructive
        onConfirm={() => void removeMaterial()}
      >
        <p className="dialog-lead">Файл удалится из общей Библиотеки и отвяжется от всех проектов.</p>
        <ul className="consequences">
          {deletePreview?.material.usage.map((usage) => <li key={usage.project_id}>{usage.project_name}: {usage.purposes.map((item) => PURPOSE[item]).join(", ")}</li>)}
          {deletePreview?.reference_answer_count ? <li>Эталонов из файла: {deletePreview.reference_answer_count}. Текст сохранится, источник станет недоступен.</li> : null}
          {deletePreview?.binding_count ? <li>Привязок к фрагментам: {deletePreview.binding_count}. Они уйдут вместе с файлом.</li> : null}
          {deletePreview?.affected_projects.map((affected) => (
            <li key={affected.project_id}>
              {affected.project_name}: без материала останутся — {affected.nodes_losing_material.join(", ")}.
            </li>
          ))}
          {deletePreview?.active_task && <li>Текущая обработка будет остановлена вместе с файлом.</li>}
          {deletePreview?.material.usage.length === 0 && !deletePreview.reference_answer_count && !deletePreview.binding_count && <li>Файл не используется ни одним проектом.</li>}
        </ul>
      </ConfirmDialog>
    </div>
  );
}
