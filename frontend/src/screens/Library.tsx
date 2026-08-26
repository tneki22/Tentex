import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AudioLines,
  FileImage,
  FileText,
  FileType2,
  Globe,
  Plus,
  Trash2,
  Video,
} from "lucide-react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import {
  deleteLibraryMaterial,
  getMaterialDeletePreview,
  listLibraryMaterials,
  type LibraryMaterialRead,
  type MaterialDeletePreview,
  type MaterialPresentationKind,
  type MaterialPurpose,
} from "../api/materials";
import { QualityBadge } from "../components/domain";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  IconButton,
  LoadingState,
  PageHead,
  StatusBadge,
} from "../components/ui";
import { AddLibraryMaterialDialog } from "./library/AddLibraryMaterialDialog";
import {
  DEFAULT_FILTERS,
  LibraryFilters,
  type LibraryFilterState,
  type LibraryKindFilter,
  type LibraryQualityFilter,
  type LibrarySort,
  type LibraryStatusFilter,
  type LibraryUsageFilter,
} from "./library/LibraryFilters";

const PURPOSE: Record<MaterialPurpose, string> = {
  exam_structure: "список вопросов",
  reference_answers: "эталонные ответы",
  study_source: "учебный источник",
};

const STATUS_LABEL: Record<LibraryMaterialRead["status"], string> = {
  ready_to_process: "Не подготовлен",
  queued: "В очереди",
  processing: "Обрабатывается",
  paused: "На паузе",
  ready: "Готов",
  failed: "Ошибка",
};

const SCROLL_KEY = "tentex-library-scroll";

/** Тот же вывод, что у сервера, но по данным списка: отдельная ручка не нужна. */
function kindOf(material: LibraryMaterialRead): MaterialPresentationKind {
  if (material.source_kind === "youtube") return "youtube";
  if (material.source_kind === "audio" || material.media_type.startsWith("audio/")) return "audio";
  if (material.source_kind === "url") return "web";
  if (material.media_type === "application/pdf") return "pdf";
  if (material.media_type.startsWith("image/")) return "image";
  if (material.media_type.includes("wordprocessingml") || material.media_type === "application/msword") {
    return "document";
  }
  return "plain_text";
}

const KIND_ICON: Record<MaterialPresentationKind, typeof FileText> = {
  pdf: FileText,
  image: FileImage,
  document: FileType2,
  plain_text: FileText,
  web: Globe,
  youtube: Video,
  audio: AudioLines,
};

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} КБ`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} МБ`;
  return `${(bytes / 1024 ** 3).toFixed(1)} ГБ`;
}

function pageLabel(count: number | null): string {
  if (count === null) return "";
  const mod100 = count % 100;
  const mod10 = count % 10;
  if (mod100 >= 11 && mod100 <= 14) return `${count} страниц`;
  if (mod10 === 1) return `${count} страница`;
  if (mod10 >= 2 && mod10 <= 4) return `${count} страницы`;
  return `${count} страниц`;
}

function readFilters(params: URLSearchParams): LibraryFilterState {
  return {
    q: params.get("q") ?? "",
    kind: (params.get("kind") ?? "all") as LibraryKindFilter,
    status: (params.get("status") ?? "all") as LibraryStatusFilter,
    quality: (params.get("quality") ?? "all") as LibraryQualityFilter,
    usage: (params.get("usage") ?? "all") as LibraryUsageFilter,
    sort: (params.get("sort") ?? DEFAULT_FILTERS.sort) as LibrarySort,
  };
}

export function Library() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [materials, setMaterials] = useState<LibraryMaterialRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [deletePreview, setDeletePreview] = useState<MaterialDeletePreview | null>(null);
  const restored = useRef(false);

  const filters = useMemo(() => readFilters(searchParams), [searchParams]);
  const scrollKey = `${SCROLL_KEY}:${searchParams.toString()}`;

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError("");
    try {
      setMaterials(await listLibraryMaterials(signal));
    } catch (caught) {
      if (!signal?.aborted) {
        setError(caught instanceof Error ? caught.message : "Не удалось загрузить Библиотеку");
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  /* Возврат из рабочей области должен вернуть и место в списке, иначе после
     каждой проверки материала приходится искать строку заново. */
  useEffect(() => {
    if (loading || restored.current) return;
    restored.current = true;
    const stored = Number(sessionStorage.getItem(scrollKey));
    if (Number.isFinite(stored) && stored > 0) {
      window.requestAnimationFrame(() => window.scrollTo({ top: stored }));
    }
  }, [loading, scrollKey]);

  function updateFilters(next: Partial<LibraryFilterState>) {
    const merged = { ...filters, ...next };
    const params = new URLSearchParams();
    if (merged.q.trim()) params.set("q", merged.q);
    if (merged.kind !== "all") params.set("kind", merged.kind);
    if (merged.status !== "all") params.set("status", merged.status);
    if (merged.quality !== "all") params.set("quality", merged.quality);
    if (merged.usage !== "all") params.set("usage", merged.usage);
    if (merged.sort !== DEFAULT_FILTERS.sort) params.set("sort", merged.sort);
    setSearchParams(params, { replace: true });
  }

  const visible = useMemo(() => {
    const needle = filters.q.trim().toLocaleLowerCase("ru");
    const list = materials.filter((material) => {
      if (needle && !material.original_name.toLocaleLowerCase("ru").includes(needle)) return false;
      if (filters.kind !== "all" && kindOf(material) !== filters.kind) return false;
      if (filters.status === "ready" && material.status !== "ready") return false;
      if (filters.status === "processing"
        && material.status !== "processing" && material.status !== "queued") return false;
      if (filters.status === "paused" && material.status !== "paused") return false;
      if (filters.status === "failed" && material.status !== "failed") return false;
      if (filters.quality === "needs_review" && (material.parser_mode === "fast" || material.ocr_low_page_count === 0)) return false;
      if (filters.usage === "attached" && material.usage.length === 0) return false;
      if (filters.usage === "unattached" && material.usage.length > 0) return false;
      return true;
    });
    if (filters.sort === "name_asc") {
      return [...list].sort((a, b) => a.original_name.localeCompare(b.original_name, "ru"));
    }
    if (filters.sort === "updated_desc") {
      return [...list].sort((a, b) => b.created_at.localeCompare(a.created_at));
    }
    return list;
  }, [materials, filters]);

  const totals = useMemo(() => ({
    pages: materials.reduce((sum, material) => sum + (material.page_count ?? 0), 0),
    bytes: materials.reduce((sum, material) => sum + material.size_bytes, 0),
    review: materials.reduce((sum, material) => sum + (material.parser_mode === "fast" ? 0 : material.ocr_low_page_count), 0),
  }), [materials]);

  /* Возврат живёт в query, а не только в `location.state`: рабочая область
     переписывает свой URL (версия, вкладка), и state при этом теряется. */
  function open(materialId: string) {
    sessionStorage.setItem(scrollKey, String(window.scrollY));
    const back = encodeURIComponent(`${location.pathname}${location.search}`);
    navigate(`/library/${materialId}?returnTo=${back}`, {
      state: { libraryReturnTo: `${location.pathname}${location.search}` },
    });
  }

  async function chooseDelete(materialId: string) {
    setBusy(true);
    setError("");
    try {
      setDeletePreview(await getMaterialDeletePreview(materialId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось проверить последствия удаления");
    } finally {
      setBusy(false);
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

  if (loading) return <LoadingState label="Загружаем Библиотеку" placement="page" />;

  return (
    <div className="screen lib-screen">
      <PageHead
        placement="topbar"
        title="Библиотека"
        lead={
          materials.length === 0
            ? "Общие материалы установки. Файл хранится один раз, проекты на него ссылаются."
            : `${materials.length} · ${totals.pages} стр. · ${sizeLabel(totals.bytes)}`
            + (totals.review ? ` · нужно проверить: ${totals.review}` : "")
        }
        actions={
          <Button onClick={() => setAddOpen(true)}>
            <Plus size={15} aria-hidden="true" /> Добавить материал
          </Button>
        }
      />
      {error && <ErrorState message={error} />}

      {materials.length > 0 && (
        <LibraryFilters
          value={filters}
          total={materials.length}
          shown={visible.length}
          onChange={updateFilters}
          onReset={() => setSearchParams(new URLSearchParams(), { replace: true })}
        />
      )}

      {materials.length === 0 ? (
        <EmptyState title="Библиотека пока пуста">
          <p>
            Здесь живут общие материалы установки: файлы, вставленный текст,
            сохранённые веб-страницы, субтитры и аудиозаписи. Проект не нужен —
            подключить материал к нему можно позже.
          </p>
          <Button onClick={() => setAddOpen(true)}>Добавить первый материал</Button>
        </EmptyState>
      ) : visible.length === 0 ? (
        <EmptyState title="Под фильтры ничего не подошло">
          <p>Попробуйте другой запрос или сбросьте фильтры.</p>
          <Button variant="secondary" onClick={() => setSearchParams(new URLSearchParams(), { replace: true })}>
            Сбросить фильтры
          </Button>
        </EmptyState>
      ) : (
        <div className="lib-list" role="list">
          {visible.map((material) => {
            const Icon = KIND_ICON[kindOf(material)];
            return (
              <div className="lib-row" role="listitem" key={material.id}>
                {/* Вся смысловая область строки — одна кнопка перехода;
                    вложенные действия останавливают её своим onClick. */}
                <button
                  type="button"
                  className="lib-row-open"
                  onClick={() => open(material.id)}
                >
                  <span className="lib-row-icon"><Icon size={17} aria-hidden="true" /></span>
                  <span className="lib-row-body">
                    <span className="lib-row-name">{material.original_name}</span>
                    <span className="lib-row-meta">
                      <span>{sizeLabel(material.size_bytes)}</span>
                      {material.page_count !== null && <span>{pageLabel(material.page_count)}</span>}
                      {material.block_count > 0 && <span>блоков {material.block_count}</span>}
                    </span>
                  </span>
                  <span className="lib-row-quality">
                    {material.status !== "ready" && (
                      <StatusBadge tone={material.status === "failed" ? "danger" : "neutral"}>
                        {STATUS_LABEL[material.status]}
                      </StatusBadge>
                    )}
                    {material.native_page_count > 0 && (
                      <QualityBadge quality="native" count={material.native_page_count} />
                    )}
                    {material.ocr_page_count > 0 && (
                      <QualityBadge quality="ocr" count={material.ocr_page_count} />
                    )}
                    {material.ocr_low_page_count > 0 && (
                      <QualityBadge quality="ocr_low" count={material.ocr_low_page_count} showReview={material.parser_mode !== "fast"} />
                    )}
                  </span>
                </button>

                <div className="lib-row-usage">
                  {material.usage.length > 0 ? material.usage.map((usage) => (
                    <Link
                      key={`${usage.project_id}-${usage.display_name}`}
                      to={`/projects/${usage.project_id}/materials/${material.id}`}
                      title={`${usage.display_name} · ${usage.purposes.map((item) => PURPOSE[item]).join(", ")}`}
                    >
                      {usage.project_name}
                    </Link>
                  )) : <span className="lib-unused">не используется</span>}
                </div>

                <IconButton
                  label={`Удалить ${material.original_name}`}
                  disabled={busy}
                  onClick={() => void chooseDelete(material.id)}
                >
                  <Trash2 size={15} />
                </IconButton>
              </div>
            );
          })}
        </div>
      )}

      <AddLibraryMaterialDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onCreated={(created) => {
          sessionStorage.setItem(scrollKey, "0");
          const back = encodeURIComponent(`${location.pathname}${location.search}`);
          navigate(`/library/${created.id}?returnTo=${back}`);
        }}
      />

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
          {deletePreview?.material.usage.map((usage) => (
            <li key={usage.project_id}>
              {usage.project_name}: {usage.purposes.map((item) => PURPOSE[item]).join(", ")}
            </li>
          ))}
          {deletePreview?.reference_answer_count ? (
            <li>Эталонов из файла: {deletePreview.reference_answer_count}. Текст сохранится, источник станет недоступен.</li>
          ) : null}
          {deletePreview?.binding_count ? (
            <li>Привязок к фрагментам: {deletePreview.binding_count}. Они уйдут вместе с файлом.</li>
          ) : null}
          {deletePreview?.affected_projects.map((affected) => (
            <li key={affected.project_id}>
              {affected.project_name}: без материала останутся — {affected.nodes_losing_material.join(", ")}.
            </li>
          ))}
          {deletePreview?.active_task && <li>Текущая обработка будет остановлена вместе с файлом.</li>}
          {deletePreview?.material.usage.length === 0
            && !deletePreview.reference_answer_count
            && !deletePreview.binding_count
            && <li>Файл не используется ни одним проектом.</li>}
        </ul>
      </ConfirmDialog>
    </div>
  );
}
