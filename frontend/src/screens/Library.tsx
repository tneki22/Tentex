import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AudioLines,
  FileImage,
  FileText,
  FileType2,
  Globe,
  Play,
  Plus,
  Pencil,
  Pause,
  Search,
  Trash2,
  Video,
  X,
} from "lucide-react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import {
  deleteLibraryMaterials,
  getLibraryMaterial,
  getLibraryPage,
  libraryPageImageUrl,
  listLibraryMaterials,
  updateLibraryMaterialMetadata,
  previewMaterialsDelete,
  startLibraryProcessing,
  type LibraryMaterialRead,
  type MaterialPresentationKind,
  type MaterialPurpose,
  type MaterialsDeletePreview,
} from "../api/materials";
import {
  buildRetrievalIndex,
  addRetrievalIndexMaterials,
  activateRetrievalIndex,
  listRetrievalIndexes,
  pauseRetrievalIndexBuild,
  resumeRetrievalIndexBuild,
  searchLibraryContent,
  getRetrievalSettings,
  type RetrievalHitRead,
  type RetrievalIndexRead,
  type SearchStrategy,
} from "../api/retrieval";
import { cancelBackgroundJob, listBackgroundJobs, type BackgroundJobRead } from "../api/backgroundJobs";
import { ProjectApiError } from "../api/projects";
import { QualityBadge } from "../components/domain";
import { PageHighlights, PageNumberInput } from "../components/domain/material-viewer";
import {
  Button,
  Checkbox,
  ConfirmDialog,
  ContextMenu,
  Disclosure,
  Dialog,
  EmptyState,
  ErrorState,
  IconButton,
  LoadingState,
  PageHead,
  Select,
  StatusBadge,
  SegmentedTabs,
} from "../components/ui";
import { AddLibraryMaterialDialog } from "./library/AddLibraryMaterialDialog";
import { AddToProjectDialog } from "./library/AddToProjectDialog";
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
  reference_answers: "ответы",
  study_source: "учебный источник",
};

const STATUS_LABEL: Record<LibraryMaterialRead["status"], string> = {
  ready_to_process: "Не подготовлен",
  queued: "В очереди",
  processing: "Обрабатывается",
  paused: "На паузе",
  needs_input: "Нужны файлы",
  ready: "Готов",
  failed: "Ошибка",
};

const SCROLL_KEY = "tentex-library-scroll";
const CONTENT_CACHE_KEY = "tentex-library-content-search";
const LIBRARY_REUSE_MS = 15_000;
let librarySnapshot: LibraryMaterialRead[] | null = null;
let librarySnapshotAt = 0;

interface ContentSearchCache {
  surface: "names" | "content";
  query: string;
  strategy: SearchStrategy;
  hits: RetrievalHitRead[];
  reasons: string[];
  materialIds: string[];
  history: string[];
}

function readContentSearchCache(): ContentSearchCache {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(CONTENT_CACHE_KEY) ?? "null") as Partial<ContentSearchCache> | null;
    return {
      surface: parsed?.surface === "content" ? "content" : "names",
      query: parsed?.query ?? "",
      strategy: parsed?.strategy ?? "hybrid",
      hits: Array.isArray(parsed?.hits) ? parsed.hits : [],
      reasons: Array.isArray(parsed?.reasons) ? parsed.reasons : [],
      materialIds: Array.isArray(parsed?.materialIds) ? parsed.materialIds : [],
      history: Array.isArray(parsed?.history) ? parsed.history.slice(0, 8) : [],
    };
  } catch {
    return { surface: "names", query: "", strategy: "hybrid", hits: [], reasons: [], materialIds: [], history: [] };
  }
}

/** Тот же вывод, что у сервера, но по данным списка: отдельная ручка не нужна. */
function kindOf(material: LibraryMaterialRead): MaterialPresentationKind {
  if (material.source_kind === "typst") return "typst";
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
  typst: FileType2,
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

/** Русское склонение по числу: одно правило на весь экран. */
function plural(count: number, one: string, few: string, many: string): string {
  const mod100 = count % 100;
  const mod10 = count % 10;
  if (mod100 >= 11 && mod100 <= 14) return many;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}

function pageLabel(count: number | null): string {
  if (count === null) return "";
  return `${count} ${plural(count, "страница", "страницы", "страниц")}`;
}

/** « · стр. 286» или « · стр. 286–287»: найденный кусок бывает на двух страницах. */
function pagesLabel(from: number | null, to: number | null): string {
  if (!from) return "";
  return to && to !== from ? ` · стр. ${from}–${to}` : ` · стр. ${from}`;
}

function readFilters(params: URLSearchParams): LibraryFilterState {
  return {
    q: params.get("q") ?? "",
    kind: (params.get("kind") ?? "all") as LibraryKindFilter,
    status: (params.get("status") ?? "all") as LibraryStatusFilter,
    quality: (params.get("quality") ?? "all") as LibraryQualityFilter,
    usage: (params.get("usage") ?? "all") as LibraryUsageFilter,
    subject: params.get("subject") ?? "all",
    sort: (params.get("sort") ?? DEFAULT_FILTERS.sort) as LibrarySort,
  };
}

export function Library() {
  const initialContentCache = useRef(readContentSearchCache()).current;
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [materials, setMaterials] = useState<LibraryMaterialRead[]>(() => librarySnapshot ?? []);
  const [loading, setLoading] = useState(() => librarySnapshot === null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [searchSurface, setSearchSurface] = useState<"names" | "content">(initialContentCache.surface);
  const [contentQuery, setContentQuery] = useState(initialContentCache.query);
  const [contentStrategy, setContentStrategy] = useState<SearchStrategy>(initialContentCache.strategy);
  const [contentHits, setContentHits] = useState<RetrievalHitRead[]>(initialContentCache.hits);
  const [expandedHits, setExpandedHits] = useState<ReadonlySet<string>>(new Set());
  const [contentReasons, setContentReasons] = useState<string[]>(initialContentCache.reasons);
  const [contentHistory, setContentHistory] = useState<string[]>(initialContentCache.history);
  const [contentMaterialIds, setContentMaterialIds] = useState<string[]>(initialContentCache.materialIds);
  const [retrievalSettings, setRetrievalSettings] = useState<Awaited<ReturnType<typeof getRetrievalSettings>> | null>(null);
  const [indexes, setIndexes] = useState<RetrievalIndexRead[]>([]);
  const [indexSwitching, setIndexSwitching] = useState(false);
  const [indexAddIds, setIndexAddIds] = useState<string[] | null>(null);
  const [indexAdding, setIndexAdding] = useState(false);
  const [indexCloudConsent, setIndexCloudConsent] = useState(false);
  const [contentProfileId, setContentProfileId] = useState<string | null>(null);
  const [indexBuildOpen, setIndexBuildOpen] = useState(false);
  const [indexBuilding, setIndexBuilding] = useState(false);
  const [indexJob, setIndexJob] = useState<BackgroundJobRead | null>(null);
  const [preview, setPreview] = useState<{ hit: RetrievalHitRead; material: Awaited<ReturnType<typeof getLibraryMaterial>> | null; page: Awaited<ReturnType<typeof getLibraryPage>> | null; error: string | null } | null>(null);
  const [previewPageLoading, setPreviewPageLoading] = useState(false);
  const [contentSearching, setContentSearching] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [metadataDialog, setMetadataDialog] = useState<{ material: LibraryMaterialRead; kind: "name" | "subject"; value: string } | null>(null);
  const [metadataSaving, setMetadataSaving] = useState(false);
  const [attachTarget, setAttachTarget] = useState<LibraryMaterialRead | null>(null);
  /* Кого сейчас подтверждают к удалению. Пустой массив — диалог закрыт. */
  const [deleteTargets, setDeleteTargets] = useState<LibraryMaterialRead[]>([]);
  const [deletePreview, setDeletePreview] = useState<MaterialsDeletePreview | null>(null);
  /* Занятость по строкам, а не по экрану: удаление одного файла не должно
     гасить кнопки у остальных двадцати. */
  const [pendingIds, setPendingIds] = useState<Set<string>>(new Set());
  const restored = useRef(false);
  /* Radix отдаёт только новое состояние флажка, без события. Модификатор
     запоминаем на mousedown — он приходит раньше клика. */
  const shiftHeld = useRef(false);
  const anchor = useRef<number | null>(null);
  const contentSourcesInitialized = useRef(false);

  const filters = useMemo(() => readFilters(searchParams), [searchParams]);
  const scrollKey = `${SCROLL_KEY}:${searchParams.toString()}`;

  const load = useCallback(async (options: { signal?: AbortSignal; silent?: boolean } = {}) => {
    const { signal, silent } = options;
    if (!silent) setLoading(true);
    setError("");
    try {
      const next = await listLibraryMaterials(signal);
      if (signal?.aborted) return;
      librarySnapshot = next;
      librarySnapshotAt = Date.now();
      setMaterials(next);
    } catch (caught) {
      if (!signal?.aborted) {
        setError(caught instanceof Error ? caught.message : "Не удалось загрузить Библиотеку");
      }
    } finally {
      if (!signal?.aborted && !silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (librarySnapshot && Date.now() - librarySnapshotAt < LIBRARY_REUSE_MS) return;
    const controller = new AbortController();
    void load({ signal: controller.signal, silent: librarySnapshot !== null });
    return () => controller.abort();
  }, [load]);

  const refreshIndexes = useCallback(async () => {
    const [next, available] = await Promise.all([getRetrievalSettings(), listRetrievalIndexes()]);
    setRetrievalSettings(next);
    setIndexes(available);
    setContentProfileId((current) => current ?? next.default_profile_id ?? next.active_index?.profile_id ?? null);
  }, []);

  useEffect(() => {
    if (!indexJob) void refreshIndexes().catch(() => setRetrievalSettings(null));
  }, [indexJob, refreshIndexes]);

  useEffect(() => {
    let active = true;
    const loadIndexJob = () => void listBackgroundJobs({ activeOnly: true }).then((jobs) => {
      if (!active) return;
      setIndexJob(jobs.find((job) => job.kind === "retrieval_index") ?? null);
    }).catch(() => undefined);
    loadIndexJob();
    const timer = window.setInterval(loadIndexJob, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (materials.length === 0 || contentSourcesInitialized.current) return;
    const ready = materials.filter((material) => material.status === "ready").map((material) => material.id);
    const cached = initialContentCache.materialIds.filter((id) => ready.includes(id));
    setContentMaterialIds(cached.length > 0 ? cached : ready);
    contentSourcesInitialized.current = true;
  }, [materials, initialContentCache]);

  useEffect(() => {
    sessionStorage.setItem(CONTENT_CACHE_KEY, JSON.stringify({
      surface: searchSurface,
      query: contentQuery,
      strategy: contentStrategy,
      hits: contentHits,
      reasons: contentReasons,
      materialIds: contentMaterialIds,
      history: contentHistory,
    } satisfies ContentSearchCache));
  }, [searchSurface, contentQuery, contentStrategy, contentHits, contentReasons, contentMaterialIds, contentHistory]);

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
    if (merged.subject !== "all") params.set("subject", merged.subject);
    if (merged.sort !== DEFAULT_FILTERS.sort) params.set("sort", merged.sort);
    setSearchParams(params, { replace: true });
  }

  const visible = useMemo(() => {
    const needle = filters.q.trim().toLocaleLowerCase("ru");
    const list = materials.filter((material) => {
      if (needle && !material.display_name.toLocaleLowerCase("ru").includes(needle)) return false;
      if (filters.kind !== "all" && kindOf(material) !== filters.kind) return false;
      if (filters.status === "ready" && material.status !== "ready") return false;
      if (filters.status === "processing"
        && material.status !== "processing" && material.status !== "queued") return false;
      if (filters.status === "paused" && material.status !== "paused") return false;
      if (filters.status === "failed" && material.status !== "failed") return false;
      if (filters.quality === "needs_review" && (material.parser_mode === "fast" || material.ocr_low_page_count === 0)) return false;
      if (filters.usage === "attached" && material.usage.length === 0) return false;
      if (filters.usage === "unattached" && material.usage.length > 0) return false;
      if (filters.subject === "none" && material.subject !== null) return false;
      if (filters.subject !== "all" && filters.subject !== "none" && material.subject !== filters.subject) return false;
      return true;
    });
    if (filters.sort === "name_asc") {
      return [...list].sort((a, b) => a.display_name.localeCompare(b.display_name, "ru"));
    }
    if (filters.sort === "updated_desc") {
      return [...list].sort((a, b) => b.created_at.localeCompare(a.created_at));
    }
    return list;
  }, [materials, filters]);

  /* Выделение живёт внутри текущей выборки: иначе массовое действие задело бы
     то, чего на экране не видно. */
  useEffect(() => {
    setSelectedIds(new Set());
    anchor.current = null;
  }, [searchParams]);

  const selected = useMemo(
    () => visible.filter((material) => selectedIds.has(material.id)),
    [visible, selectedIds],
  );
  const indexedMaterialIds = useMemo(
    () => new Set(retrievalSettings?.active_index?.corpus_manifest.map((item) => item.material_id) ?? []),
    [retrievalSettings?.active_index?.corpus_manifest],
  );
  const subjects = useMemo(() => [...new Set(materials.flatMap((material) => material.subject ? [material.subject] : []))].sort((a, b) => a.localeCompare(b, "ru")), [materials]);
  const readyContentMaterials = useMemo(
    () => materials.filter((material) => material.status === "ready"),
    [materials],
  );
  const contentSubjects = useMemo(
    () => [...new Set(readyContentMaterials.flatMap((material) => material.subject ? [material.subject] : []))].sort((a, b) => a.localeCompare(b, "ru")),
    [readyContentMaterials],
  );
  const selectedContentSubject = useMemo(() => {
    if (contentMaterialIds.length === 0 || contentMaterialIds.length === readyContentMaterials.length) return "all";
    const selected = new Set(contentMaterialIds);
    const subject = contentSubjects.find((candidate) => {
      const matchingIds = readyContentMaterials.filter((material) => material.subject === candidate).map((material) => material.id);
      return matchingIds.length === selected.size && matchingIds.every((id) => selected.has(id));
    });
    if (subject) return `subject:${subject}`;
    const noSubjectIds = readyContentMaterials.filter((material) => material.subject === null).map((material) => material.id);
    if (noSubjectIds.length === selected.size && noSubjectIds.every((id) => selected.has(id))) return "__no_subject__";
    return null;
  }, [contentMaterialIds, contentSubjects, readyContentMaterials]);
  /* Перезапуск после ошибки — такое же обычное массовое действие, как первый
     разбор: сервер отказывает только при уже активной задаче. */
  const processable = selected.filter(
    (material) => material.status === "ready_to_process" || material.status === "failed",
  );

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

  async function openPreview(hit: RetrievalHitRead) {
    setPreview({ hit, material: null, page: null, error: null });
    try {
      /* Паспорт файла и нужная страница независимы: параллельная загрузка
         убирает одну полную сетевую задержку до первого предпросмотра. */
      const [material, page] = await Promise.all([
        getLibraryMaterial(hit.locator.material_id),
        hit.locator.page_from ? getLibraryPage(hit.locator.material_id, hit.locator.page_from) : null,
      ]);
      setPreview({ hit, material, page, error: null });
    } catch (caught) {
      setPreview({ hit, material: null, page: null, error: caught instanceof Error ? caught.message : "Не удалось открыть страницу" });
    }
  }

  function toggleExpandedHit(chunkId: string) {
    setExpandedHits((current) => {
      const next = new Set(current);
      if (next.has(chunkId)) next.delete(chunkId); else next.add(chunkId);
      return next;
    });
  }

  useEffect(() => {
    /* У текстового материала найденное может быть ниже первого экрана страницы. */
    document.querySelector(".library-search-preview-text mark")?.scrollIntoView({ block: "nearest" });
  }, [preview?.page?.id]);

  async function changePreviewPage(pageNumber: number) {
    if (!preview?.material) return;
    const total = preview.material.page_count ?? 1;
    const page = Math.min(Math.max(1, pageNumber), total);
    if (page === preview.page?.page_number) return;
    setPreviewPageLoading(true);
    try {
      const next = await getLibraryPage(preview.material.id, page);
      setPreview((current) => current ? { ...current, page: next, error: null } : current);
    } catch (caught) {
      setPreview((current) => current ? { ...current, error: caught instanceof Error ? caught.message : "Не удалось открыть страницу" } : current);
    } finally {
      setPreviewPageLoading(false);
    }
  }

  useEffect(() => {
    if (!preview?.material || !preview.page) return;
    if (!["pdf", "image", "typst"].includes(preview.material.presentation_kind)) return;
    const total = preview.material.page_count ?? 1;
    const adjacent = [preview.page.page_number - 1, preview.page.page_number + 1]
      .filter((number) => number >= 1 && number <= total);
    for (const pageNumber of adjacent) {
      const image = new Image();
      image.src = libraryPageImageUrl(preview.material.id, pageNumber, preview.material.raster_token);
    }
  }, [preview?.material, preview?.page]);

  function toggleSelected(index: number, checked: boolean) {
    const range = shiftHeld.current && anchor.current !== null
      ? visible.slice(Math.min(anchor.current, index), Math.max(anchor.current, index) + 1)
      : [visible[index]];
    shiftHeld.current = false;
    anchor.current = index;
    setSelectedIds((current) => {
      const next = new Set(current);
      for (const material of range) {
        if (checked) next.add(material.id); else next.delete(material.id);
      }
      return next;
    });
  }

  async function askDelete(targets: LibraryMaterialRead[]) {
    if (targets.length === 0) return;
    /* Диалог открывается сразу, последствия догружаются в него: ждать ответа
       сервера с закрытым окном означало «нажал и ничего не происходит». */
    setDeleteTargets(targets);
    setDeletePreview(null);
    setError("");
    try {
      setDeletePreview(await previewMaterialsDelete(targets.map((material) => material.id)));
    } catch (caught) {
      setDeleteTargets([]);
      setError(caught instanceof Error ? caught.message : "Не удалось проверить последствия удаления");
    }
  }

  async function removeMaterials() {
    const targets = deleteTargets;
    if (targets.length === 0) return;
    const ids = targets.map((material) => material.id);
    const snapshot = materials;

    /* Удаляем из списка сразу: подтверждение уже получено, и ждать ответа
       сервера пользователю незачем. При ошибке строки возвращаются. */
    setMaterials((current) => current.filter((material) => !ids.includes(material.id)));
    librarySnapshot = null;
    setSelectedIds(new Set());
    setDeleteTargets([]);
    setDeletePreview(null);
    setPendingIds((current) => new Set([...current, ...ids]));
    setNotice(`Удалено: ${ids.length} ${plural(ids.length, "файл", "файла", "файлов")}`);

    try {
      await deleteLibraryMaterials(ids);
    } catch (caught) {
      setMaterials(snapshot);
      librarySnapshot = null;
      setNotice("");
      setError(caught instanceof Error ? caught.message : "Не удалось удалить материалы");
    } finally {
      setPendingIds((current) => {
        const next = new Set(current);
        for (const id of ids) next.delete(id);
        return next;
      });
    }
  }

  async function processSelected() {
    const targets = processable;
    if (targets.length === 0) return;
    const ids = targets.map((material) => material.id);
    setPendingIds((current) => new Set([...current, ...ids]));
    setError("");
    let started = 0;
    try {
      /* По очереди, а не пачкой: у SQLite один писатель, и параллельные запуски
         только выстраиваются в ту же очередь, но с риском таймаута. */
      for (const id of ids) {
        await startLibraryProcessing(id, { parser_mode: "fast", scope: "all" });
        started += 1;
      }
      setNotice(`Поставлено в обработку: ${started}`);
      setSelectedIds(new Set());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось поставить в обработку");
    } finally {
      setPendingIds((current) => {
        const next = new Set(current);
        for (const id of ids) next.delete(id);
        return next;
      });
      await load({ silent: true });
    }
  }

  async function runContentSearch(queryOverride?: string) {
    const query = (queryOverride ?? contentQuery).trim();
    if (!query) return;
    setContentSearching(true);
    setError("");
    try {
      const response = await searchLibraryContent(
        query,
        contentMaterialIds,
        contentStrategy,
      );
      setContentHits(response.results);
      setContentReasons([
        ...response.degradation_reasons,
        ...(response.no_relevant_match
          ? [response.missing_terms.length
            ? `В выбранных материалах не встречается: ${response.missing_terms.map((term) => `«${term}»`).join(", ")}.`
            : "В выбранных материалах нет достаточно надёжного совпадения."]
          : []),
      ]);
      setContentHistory((current) => [query, ...current.filter((item) => item !== query)].slice(0, 8));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось выполнить поиск по содержимому");
    } finally {
      setContentSearching(false);
    }
  }

  async function buildSelectedContentIndex() {
    if (!contentProfileId || contentMaterialIds.length === 0) return;
    const profile = retrievalSettings?.profiles.find((item) => item.id === contentProfileId);
    if (!profile) return;
    setIndexBuilding(true);
    setError("");
    try {
      let started;
      try {
        started = await buildRetrievalIndex({
          profile_id: profile.id,
          preset: retrievalSettings?.preset ?? "balanced",
          cloud_consent: false,
          material_ids: contentMaterialIds,
        });
      } catch (caught) {
        if (!(caught instanceof ProjectApiError) || caught.code !== "retrieval_cloud_consent_required") throw caught;
        if (!window.confirm("Текст выбранных материалов будет отправлен внешней embedding-модели. Продолжить?")) return;
        started = await buildRetrievalIndex({
          profile_id: profile.id,
          preset: retrievalSettings?.preset ?? "balanced",
          cloud_consent: true,
          material_ids: contentMaterialIds,
        });
      }
      setNotice(`Сбор индекса запущен: ${contentMaterialIds.length} материалов · ${profile.label} · задача ${started.job_id.slice(0, 8)}`);
      void listBackgroundJobs({ activeOnly: true }).then((jobs) => {
        setIndexJob(jobs.find((job) => job.id === started.job_id) ?? null);
      });
      setIndexBuildOpen(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось запустить сбор индекса");
    } finally {
      setIndexBuilding(false);
    }
  }

  async function switchIndex(indexId: string | null) {
    if (!indexId || indexId === retrievalSettings?.active_index?.id) return;
    setIndexSwitching(true);
    setError("");
    try {
      await activateRetrievalIndex(indexId);
      await refreshIndexes();
      setContentHits([]);
      setContentReasons([]);
      if (contentQuery.trim()) await runContentSearch();
      setNotice("Активный индекс переключён для всей установки.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось переключить индекс");
    } finally {
      setIndexSwitching(false);
    }
  }

  function askAddToIndex(ids: string[]) {
    const ready = ids.filter((id) => readyContentMaterials.some((item) => item.id === id));
    if (ready.length === 0) return;
    setIndexCloudConsent(false);
    setIndexAddIds(ready);
  }

  async function addSelectedToIndex() {
    const active = retrievalSettings?.active_index;
    if (!active || !indexAddIds?.length) return;
    setIndexAdding(true);
    setError("");
    try {
      const result = await addRetrievalIndexMaterials(active.id, indexAddIds, indexCloudConsent);
      setNotice(`В индекс поставлено ${result.job_ids.length} ${plural(result.job_ids.length, "материал", "материала", "материалов")}.`);
      setIndexAddIds(null);
      void listBackgroundJobs({ activeOnly: true }).then((jobs) => {
        setIndexJob(jobs.find((job) => result.job_ids.includes(job.id)) ?? null);
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось добавить материалы в индекс");
    } finally {
      setIndexAdding(false);
    }
  }

  async function saveListMetadata() {
    if (!metadataDialog) return;
    const { material, kind, value } = metadataDialog;
    const normalized = value.trim();
    if (kind === "name" && !normalized) return;
    const command = kind === "name" ? { display_name: normalized } : { subject: normalized || null };
    const previous = material;
    setMetadataSaving(true);
    setError("");
    setMaterials((current) => current.map((item) => item.id === material.id ? { ...item, ...command } : item));
    librarySnapshot = null;
    try {
      const saved = await updateLibraryMaterialMetadata(material.id, command);
      setMaterials((current) => current.map((item) => item.id === material.id ? { ...item, ...saved } : item));
      setMetadataDialog(null);
    } catch (caught) {
      setMaterials((current) => current.map((item) => item.id === material.id ? previous : item));
      setError(caught instanceof Error ? caught.message : "Не удалось сохранить метаданные");
    } finally {
      setMetadataSaving(false);
    }
  }

  if (loading) return <LoadingState label="Загружаем Библиотеку" placement="page" />;

  const allVisibleSelected = visible.length > 0 && selected.length === visible.length;

  return (
    <div className="screen lib-screen">
      <PageHead
        placement="topbar"
        title="Библиотека"
        lead={
          materials.length === 0
            ? "Общие материалы установки. Файл хранится один раз, проекты на него ссылаются."
            : undefined
        }
        actions={<>
          <Button variant="secondary" onClick={() => navigate("/library/search")}>
            <Globe size={15} aria-hidden="true" /> Поиск
          </Button>
          <Button onClick={() => setAddOpen(true)}>
            <Plus size={15} aria-hidden="true" /> Добавить материал
          </Button>
        </>}
      />
      {error && <ErrorState message={error} />}

      {materials.length > 0 && (
        <section className="lib-search-surface" aria-label="Режим поиска в Библиотеке">
          <SegmentedTabs
            label="Где искать"
            value={searchSurface}
            tabs={[
              { value: "names", label: "По названиям" },
              { value: "content", label: "По содержимому" },
            ]}
            onChange={(value) => setSearchSurface(value as "names" | "content")}
          />
          {searchSurface === "content" && (
            <div className="lib-content-search">
              <div className="lib-active-index">
                <div role="status">
                  <strong>Активный индекс</strong>
                  <Select
                    ariaLabel="Активный индекс поиска"
                    value={retrievalSettings?.active_index?.id ?? null}
                    placeholder="Индекс не собран"
                    disabled={indexSwitching || indexes.every((item) => item.state !== "ready" && item.state !== "active")}
                    options={indexes.filter((item) => item.state === "ready" || item.state === "active").map((item) => ({
                      value: item.id,
                      label: retrievalSettings?.profiles.find((profile) => profile.id === item.profile_id)?.label ?? "Embedding-модель",
                      description: `${new Date(item.completed_at ?? item.created_at).toLocaleDateString("ru-RU")} · ${item.indexed_material_count} из ${item.material_count} материалов`,
                    }))}
                    onValueChange={(value) => void switchIndex(value)}
                  />
                </div>
                <div className="lib-active-index-actions">
                  <Button variant="secondary" disabled={!retrievalSettings?.profiles.length || readyContentMaterials.length === 0} onClick={() => setIndexBuildOpen(true)}>Собрать индекс по выбранным</Button>
                  <Button variant="secondary" disabled={!retrievalSettings?.active_index || contentMaterialIds.length === 0} onClick={() => askAddToIndex(contentMaterialIds)}>Добавить выбранные в индекс</Button>
                </div>
              </div>
              {indexJob && (
                <div className="retrieval-download-progress" role="status">
                  <strong>{indexJob.material_id
                    ? indexJob.pause_requested ? "Отменяем обновление индекса…" : `Обновляем индекс · ${indexJob.subject}`
                    : indexJob.state === "paused" ? "Сбор индекса на паузе" : indexJob.control_action === "finish" ? "Завершаем сбор индекса…" : indexJob.control_action === "pause" ? "Ставим сбор на паузу…" : "Собираем индекс для поиска по содержимому"}</strong>
                  <span>{indexJob.done} из {indexJob.total} материалов</span>
                  <div className="retrieval-progress-track"><span style={{ width: indexJob.total ? `${Math.round((indexJob.done / indexJob.total) * 100)}%` : "0%" }} /></div>
                  <div className="lib-content-source-actions">
                    {!indexJob.material_id && indexJob.state === "running" && <Button variant="ghost" onClick={() => void pauseRetrievalIndexBuild(indexJob.id).then(setIndexJob).catch((caught) => setError(caught instanceof Error ? caught.message : "Не удалось поставить сбор на паузу"))}><Pause size={14} /> Пауза</Button>}
                    {!indexJob.material_id && indexJob.state === "paused" && <Button variant="ghost" onClick={() => void resumeRetrievalIndexBuild(indexJob.id).then(setIndexJob).catch((caught) => setError(caught instanceof Error ? caught.message : "Не удалось возобновить сбор"))}><Play size={14} /> Продолжить</Button>}
                    <Button variant="ghost" disabled={indexJob.pause_requested} onClick={() => void cancelBackgroundJob(indexJob.id).then(setIndexJob).catch((caught) => setError(caught instanceof Error ? caught.message : "Не удалось отменить обновление индекса"))}><X size={14} /> {indexJob.material_id ? "Отменить" : "Завершить сейчас"}</Button>
                  </div>
                </div>
              )}
              <div className="lib-content-search-form">
                <Search size={16} aria-hidden="true" />
                <input
                  value={contentQuery}
                  onChange={(event) => setContentQuery(event.target.value)}
                  onKeyDown={(event) => { if (event.key === "Enter") void runContentSearch(); }}
                  placeholder="Термин, вопрос или формулировка"
                  aria-label="Запрос по содержимому Библиотеки"
                />
                <SegmentedTabs
                  label="Стратегия поиска"
                  value={contentStrategy}
                  tabs={[
                    { value: "hybrid", label: "Оба" },
                    { value: "lexical", label: "По словам" },
                    { value: "semantic", label: "По смыслу" },
                  ]}
                  onChange={(value) => setContentStrategy(value as SearchStrategy)}
                />
                <Button disabled={contentSearching || !contentQuery.trim() || contentMaterialIds.length === 0} onClick={() => void runContentSearch()}>
                  <Search size={14} aria-hidden="true" /> {contentSearching ? "Ищем…" : "Искать"}
                </Button>
              </div>
              <div className="lib-content-sources">
                <div className="lib-content-sources-head">
                  <Disclosure summary={`Искать в источниках · ${contentMaterialIds.length} из ${readyContentMaterials.length}`}>
                    <div className="lib-content-source-list">
                      {readyContentMaterials.map((material) => (
                        <div key={material.id} className={indexedMaterialIds.has(material.id) ? "" : "lib-source-missing"}>
                          <Checkbox
                            checked={contentMaterialIds.includes(material.id)}
                            onCheckedChange={(checked) => setContentMaterialIds((current) => checked ? [...new Set([...current, material.id])] : current.filter((id) => id !== material.id))}
                            label={material.display_name}
                          />
                          {!indexedMaterialIds.has(material.id) && <small>Нет в индексе</small>}
                        </div>
                      ))}
                    </div>
                  </Disclosure>
                  <div className="lib-content-source-actions">
                    <Select
                      ariaLabel="Выбрать источники по предмету"
                      className="lib-content-subject-select"
                      value={selectedContentSubject}
                      placeholder="Выбраны вручную"
                      options={[
                        { value: "all", label: "По предмету: все" },
                        ...contentSubjects.map((subject) => ({ value: `subject:${subject}`, label: subject })),
                        ...(readyContentMaterials.some((material) => material.subject === null)
                          ? [{ value: "__no_subject__", label: "Без предмета" }]
                          : []),
                      ]}
                      onValueChange={(value) => {
                        if (value === "all") setContentMaterialIds(readyContentMaterials.map((material) => material.id));
                        else if (value === "__no_subject__") setContentMaterialIds(readyContentMaterials.filter((material) => material.subject === null).map((material) => material.id));
                        else if (value?.startsWith("subject:")) {
                          const subject = value.slice("subject:".length);
                          setContentMaterialIds(readyContentMaterials.filter((material) => material.subject === subject).map((material) => material.id));
                        }
                      }}
                    />
                    <Button variant="ghost" onClick={() => setContentMaterialIds(readyContentMaterials.map((material) => material.id))}>Выбрать все</Button>
                    <Button variant="ghost" onClick={() => setContentMaterialIds([])}>Снять все выборы</Button>
                  </div>
                </div>
              </div>
              {contentHistory.length > 0 && (
                <div className="lib-content-history" aria-label="Последние запросы">
                  <span>Последние запросы</span>
                  {contentHistory.map((item) => <button key={item} type="button" onClick={() => { setContentQuery(item); void runContentSearch(item); }}>{item}</button>)}
                </div>
              )}
              {contentSearching && <LoadingState label="Ищем по содержимому выбранных материалов" />}
              {contentReasons.map((reason) => <p className="retrieval-neutral-note" key={reason}>{reason}</p>)}
              {contentHits.length > 0 && (
                <div className="lib-content-results">
                  {contentHits.map((hit) => (
                    <article key={hit.locator.chunk_id}>
                      <span className="lib-content-result-head">
                        <strong>{hit.locator.material_name}</strong>
                        <StatusBadge tone="neutral">
                          {hit.signals.length === 2 ? "слова + смысл" : hit.signals[0] === "semantic" ? "по смыслу" : "по словам"}
                        </StatusBadge>
                      </span>
                      <small>{hit.locator.block_title ?? hit.locator.typst_path ?? "Фрагмент материала"}{pagesLabel(hit.locator.page_from, hit.locator.page_to)}</small>
                      {(hit.also_in?.length ?? 0) > 0 && <small>Тот же текст: {hit.also_in?.join(", ")}</small>}
                      <span className={expandedHits.has(hit.locator.chunk_id) ? "is-expanded" : undefined}>{hit.text}</span>
                      {hit.warning && <em>{hit.warning}</em>}
                      <div className="lib-content-result-actions">
                        <Button variant="secondary" onClick={() => navigate(`/library/${hit.locator.material_id}${hit.locator.page_from ? `?page=${hit.locator.page_from}` : ""}`)}>Открыть страницу файла</Button>
                        <Button variant="ghost" onClick={() => void openPreview(hit)}>Предпросмотр</Button>
                        <Button variant="ghost" aria-expanded={expandedHits.has(hit.locator.chunk_id)} onClick={() => toggleExpandedHit(hit.locator.chunk_id)}>
                          {expandedHits.has(hit.locator.chunk_id) ? "Свернуть" : "Показать целиком"}
                        </Button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {materials.length > 0 && searchSurface === "names" && (
        <section className="lib-summary" aria-label="Сводка Библиотеки">
          <span>
            <strong>{materials.length}</strong>
            <small>{plural(materials.length, "файл", "файла", "файлов")}</small>
          </span>
          <span>
            <strong>{totals.pages}</strong>
            <small>{plural(totals.pages, "страница", "страницы", "страниц")}</small>
          </span>
          <span>
            <strong>{sizeLabel(totals.bytes)}</strong>
            <small>общий объём</small>
          </span>
          {totals.review > 0 && (
            <span>
              <strong>{totals.review}</strong>
              <small>нужно проверить</small>
            </span>
          )}
        </section>
      )}

      {materials.length > 0 && searchSurface === "names" && (
        <LibraryFilters
          value={filters}
          total={materials.length}
          shown={visible.length}
          subjects={subjects}
          onChange={updateFilters}
          onReset={() => setSearchParams(new URLSearchParams(), { replace: true })}
        />
      )}

      {selected.length > 0 && searchSurface === "names" && (
        <div className="lib-bulk-bar" role="group" aria-label="Действия над выбранными файлами">
          <strong>Выбрано: {selected.length}</strong>
          {!allVisibleSelected && (
            <Button
              variant="ghost"
              onClick={() => setSelectedIds(new Set(visible.map((material) => material.id)))}
            >
              Выбрать все {visible.length}
            </Button>
          )}
          <Button variant="ghost" onClick={() => setSelectedIds(new Set())}>
            <X size={14} aria-hidden="true" /> Снять
          </Button>
          <span className="lib-bulk-spacer" />
          {processable.length > 0 && (
            <Button variant="ghost" onClick={() => void processSelected()}>
              <Play size={14} aria-hidden="true" /> Поставить в обработку ({processable.length})
            </Button>
          )}
          <Button variant="ghost" onClick={() => void askDelete(selected)}>
            <Trash2 size={14} aria-hidden="true" /> Удалить
          </Button>
        </div>
      )}

      {notice && <p className="lib-notice" role="status">{notice}</p>}

      {materials.length === 0 ? (
        <EmptyState title="Библиотека пока пуста">
          <p>
            Здесь живут общие материалы установки: файлы, вставленный текст,
            сохранённые веб-страницы, субтитры и аудиозаписи. Проект не нужен —
            подключить материал к нему можно позже.
          </p>
          <Button onClick={() => setAddOpen(true)}>Добавить первый материал</Button>
        </EmptyState>
      ) : searchSurface === "content" ? (
        contentHits.length === 0 && !contentSearching ? (
          <EmptyState title="Поиск по содержимому">
            <p>Спросите своими словами или найдите точный термин во всех готовых материалах.</p>
          </EmptyState>
        ) : null
      ) : visible.length === 0 ? (
        <EmptyState title="Под фильтры ничего не подошло">
          <p>Попробуйте другой запрос или сбросьте фильтры.</p>
          <Button variant="secondary" onClick={() => setSearchParams(new URLSearchParams(), { replace: true })}>
            Сбросить фильтры
          </Button>
        </EmptyState>
      ) : (
        <div className="lib-list" role="list">
          {visible.map((material, index) => {
            const Icon = KIND_ICON[kindOf(material)];
            const busy = pendingIds.has(material.id);
            return (
              <ContextMenu
                key={material.id}
                label={`Действия с «${material.display_name}»`}
                items={[
                  { label: "Открыть", onSelect: () => open(material.id) },
                  { label: "Переименовать в Библиотеке", icon: <Pencil size={15} />, onSelect: () => setMetadataDialog({ material, kind: "name", value: material.display_name }) },
                  { label: "Задать предмет", onSelect: () => setMetadataDialog({ material, kind: "subject", value: material.subject ?? "" }) },
                  { label: "Добавить в проект", onSelect: () => setAttachTarget(material) },
                  { label: "Добавить в активный индекс", disabled: material.status !== "ready" || !retrievalSettings?.active_index, onSelect: () => askAddToIndex([material.id]) },
                  { label: "Удалить", icon: <Trash2 size={15} />, destructive: true, onSelect: () => void askDelete([material]) },
                ]}
                trigger={<div
                className={`lib-row${selectedIds.has(material.id) ? " is-selected" : ""}`}
                role="listitem"
              >
                <span
                  className="lib-row-select"
                  onMouseDown={(event) => { shiftHeld.current = event.shiftKey; }}
                >
                  <Checkbox
                    checked={selectedIds.has(material.id)}
                    onCheckedChange={(checked) => toggleSelected(index, checked)}
                    label={`Выбрать ${material.display_name}`}
                  />
                </span>

                {/* Вся смысловая область строки — одна кнопка перехода;
                    вложенные действия останавливают её своим onClick. */}
                <button
                  type="button"
                  className="lib-row-open"
                  onClick={(event) => {
                    /* Ctrl/⌘ — привычный жест «добавить в выделение», а не переход. */
                    if (event.ctrlKey || event.metaKey) {
                      toggleSelected(index, !selectedIds.has(material.id));
                      return;
                    }
                    open(material.id);
                  }}
                >
                  <span className="lib-row-icon"><Icon size={17} aria-hidden="true" /></span>
                  <span className="lib-row-body">
                    <span className="lib-row-name">{material.display_name}</span>
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
                    {material.status === "ready" && !indexedMaterialIds.has(material.id) && (
                      <StatusBadge tone="danger">Нет индекса</StatusBadge>
                    )}
                    {material.ocr_page_count + (material.parser_mode === "fast" ? material.ocr_low_page_count : 0) > 0 && (
                      <QualityBadge quality="ocr" count={material.ocr_page_count + (material.parser_mode === "fast" ? material.ocr_low_page_count : 0)} />
                    )}
                    {material.parser_mode !== "fast" && material.ocr_low_page_count > 0 && (
                      <QualityBadge quality="ocr_low" count={material.ocr_low_page_count} />
                    )}
                  </span>
                </button>

                <div className="lib-row-usage">
                  {material.usage.length > 0 ? (
                    material.usage.length > 2 ? (
                      <span className="lib-usage-more" title={material.usage.map((usage) => usage.project_name).join(", ")}>в {material.usage.length} проектах</span>
                    ) : material.usage.map((usage) => (
                        <Link
                          key={`${usage.project_id}-${usage.display_name}`}
                          to={`/projects/${usage.project_id}/materials/${material.id}`}
                          title={`${usage.display_name} · ${usage.purposes.map((item) => PURPOSE[item]).join(", ")}`}
                        >
                          {usage.project_name}
                        </Link>
                      ))
                  ) : <span className="lib-unused">не используется</span>}
                </div>

                <span className="lib-row-subject" title={material.subject ?? "Без предмета"}>{material.subject ?? "Без предмета"}</span>

                <IconButton
                  label={`Удалить ${material.display_name}`}
                  disabled={busy}
                  onClick={() => void askDelete([material])}
                >
                  <Trash2 size={15} />
                </IconButton>
              </div>}
              />
            );
          })}
        </div>
      )}

      <AddLibraryMaterialDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onCreated={(created) => {
          librarySnapshot = null;
          sessionStorage.setItem(scrollKey, "0");
          const back = encodeURIComponent(`${location.pathname}${location.search}`);
          navigate(`/library/${created.id}?returnTo=${back}`);
        }}
      />

      {attachTarget && <AddToProjectDialog
        open
        materialId={attachTarget.id}
        materialName={attachTarget.display_name}
        attachedProjectIds={attachTarget.usage.map((usage) => usage.project_id)}
        onOpenChange={(open) => { if (!open) setAttachTarget(null); }}
        onAttached={() => { setAttachTarget(null); void load({ silent: true }); }}
      />}

      <Dialog
        open={metadataDialog !== null}
        onOpenChange={(open) => { if (!open && !metadataSaving) setMetadataDialog(null); }}
        title={metadataDialog?.kind === "subject" ? "Задать предмет" : "Переименовать в Библиотеке"}
        footer={<><Button variant="ghost" disabled={metadataSaving} onClick={() => setMetadataDialog(null)}>Отмена</Button><Button disabled={metadataSaving || (metadataDialog?.kind === "name" && !metadataDialog.value.trim())} onClick={() => void saveListMetadata()}>{metadataSaving ? "Сохраняем…" : "Сохранить"}</Button></>}
      >
        {metadataDialog && <label className="library-metadata-dialog-field">
          {metadataDialog.kind === "subject" ? "Предмет" : "Название"}
          <input
            autoFocus
            list={metadataDialog.kind === "subject" ? "library-context-subjects" : undefined}
            value={metadataDialog.value}
            onChange={(event) => setMetadataDialog((current) => current ? { ...current, value: event.target.value } : current)}
            onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void saveListMetadata(); } }}
          />
          {metadataDialog.kind === "subject" && <datalist id="library-context-subjects">{subjects.map((subject) => <option key={subject} value={subject} />)}</datalist>}
        </label>}
      </Dialog>

      <Dialog
        open={indexAddIds !== null}
        onOpenChange={(open) => { if (!open && !indexAdding) setIndexAddIds(null); }}
        title="Добавить выбранные в активный индекс"
        footer={<><Button variant="ghost" disabled={indexAdding} onClick={() => setIndexAddIds(null)}>Отмена</Button><Button disabled={indexAdding || !indexAddIds?.length || (retrievalSettings?.profiles.find((item) => item.id === retrievalSettings.active_index?.profile_id)?.backend_kind === "openai_compatible" && !indexCloudConsent)} onClick={() => void addSelectedToIndex()}>{indexAdding ? "Ставим в очередь…" : "Добавить в индекс"}</Button></>}
      >
        {indexAddIds && <div className="library-index-add-summary">
          <p>Выбрано: {indexAddIds.length}. Новых: {indexAddIds.filter((id) => !indexedMaterialIds.has(id)).length}. Уже в индексе: {indexAddIds.filter((id) => indexedMaterialIds.has(id)).length}.</p>
          <p>Материалы, уже входящие в индекс, будут обработаны повторно. Поиск продолжит работать во время обновления.</p>
          {retrievalSettings?.profiles.find((item) => item.id === retrievalSettings.active_index?.profile_id)?.backend_kind === "openai_compatible" && <Checkbox checked={indexCloudConsent} onCheckedChange={setIndexCloudConsent} label="Подтверждаю отправку текста выбранных материалов внешней embedding-модели" />}
        </div>}
      </Dialog>

      <Dialog
        open={indexBuildOpen}
        onOpenChange={setIndexBuildOpen}
        title="Собрать индекс по выбранным"
        description="Новый индекс строится рядом с текущим и не заменит его сам."
        className="library-index-build-dialog"
        footer={<Button variant="ghost" disabled={indexBuilding} onClick={() => setIndexBuildOpen(false)}>Отменить</Button>}
      >
        <div className="library-index-build-model">
          <Select
            ariaLabel="Модель для сборки индекса"
            value={contentProfileId}
            options={retrievalSettings?.profiles.map((profile) => ({ value: profile.id, label: profile.label, description: profile.model_id })) ?? []}
            onValueChange={setContentProfileId}
          />
          <Button disabled={indexBuilding || !contentProfileId || contentMaterialIds.length === 0} onClick={() => void buildSelectedContentIndex()}>
            {indexBuilding ? "Собираем индекс…" : "Собрать индекс"}
          </Button>
        </div>
        <div className="library-index-build-materials">
          <div>
            <strong>Материалы</strong>
            <small>По умолчанию выбраны все готовые материалы.</small>
          </div>
          <div className="lib-content-source-actions">
            <Button variant="ghost" onClick={() => setContentMaterialIds(readyContentMaterials.map((material) => material.id))}>Выбрать все</Button>
            <Button variant="ghost" onClick={() => setContentMaterialIds([])}>Снять все выборы</Button>
          </div>
          <div className="library-index-build-source-list">
            {readyContentMaterials.map((material) => (
              <Checkbox
                key={material.id}
                checked={contentMaterialIds.includes(material.id)}
                onCheckedChange={(checked) => setContentMaterialIds((current) => checked ? [...new Set([...current, material.id])] : current.filter((id) => id !== material.id))}
                label={material.display_name}
              />
            ))}
          </div>
        </div>
      </Dialog>

      <Dialog
        open={preview !== null}
        onOpenChange={(open) => !open && setPreview(null)}
        title={preview ? `Предпросмотр · ${preview.hit.locator.material_name}` : "Предпросмотр страницы"}
        className="library-search-preview"
        footer={preview?.hit ? (
          <>
            <Button variant="ghost" onClick={() => setPreview(null)}>Закрыть</Button>
            <Button onClick={() => {
              if (!preview) return;
              const page = preview.hit.locator.page_from;
              setPreview(null);
              navigate(`/library/${preview.hit.locator.material_id}${page ? `?page=${page}` : ""}`);
            }}>Открыть страницу файла</Button>
          </>
        ) : undefined}
      >
        {!preview?.material && !preview?.error && <LoadingState label="Загружаем страницу" />}
        {preview?.error && <ErrorState message={preview.error} />}
        {preview?.material && !preview.page && !preview.error && (
          <div className="library-search-preview-empty">
            <strong>Страница для этого результата не определена</strong>
            <p>Откройте материал в библиотеке, чтобы перейти к нужному месту вручную.</p>
          </div>
        )}
        {preview?.material && preview.page && (
          <div className="library-search-preview-grid">
            <aside className="library-search-preview-outline" aria-label="Оглавление">
              <strong>Оглавление</strong>
              {preview.material.outline.length > 0
                ? preview.material.outline.map((item) => <button key={`${item.page}-${item.title}`} type="button" onClick={() => void changePreviewPage(item.page)}>{item.title}<small>стр. {item.page}</small></button>)
                : <span>Оглавление отсутствует</span>}
            </aside>
            <section className="library-search-preview-page">
              <div className="library-search-preview-toolbar" aria-busy={previewPageLoading}>
                <Button variant="ghost" disabled={previewPageLoading || preview.page.page_number <= 1} onClick={() => void changePreviewPage(preview.page!.page_number - 1)}>Назад</Button>
                <PageNumberInput
                  page={preview.page.page_number}
                  pageCount={preview.material.page_count ?? 1}
                  onPageChange={(pageNumber) => void changePreviewPage(pageNumber)}
                />
                <Button variant="ghost" disabled={previewPageLoading || preview.page.page_number >= (preview.material.page_count ?? 1)} onClick={() => void changePreviewPage(preview.page!.page_number + 1)}>Вперёд</Button>
              </div>
              {(() => {
                /* Выделяются фрагменты найденного куска, лежащие на открытой странице:
                   кусок бывает на двух страницах, и листание не теряет выделение. */
                const found = new Set(preview.hit.locator.fragment_ids);
                const hitFragments = preview.page.fragments.filter((fragment) => found.has(fragment.id));
                if (preview.material.presentation_kind === "pdf" || preview.material.presentation_kind === "image" || preview.material.presentation_kind === "typst") {
                  return (
                    <PageHighlights
                      pageUrl={libraryPageImageUrl(preview.material.id, preview.page.page_number, preview.material.raster_token)}
                      boxes={hitFragments.map((fragment) => fragment.bbox).filter((bbox) => bbox.length === 4 && bbox[2] > bbox[0] && bbox[3] > bbox[1])}
                      alt={`Страница ${preview.page.page_number}`}
                    />
                  );
                }
                if (preview.page.fragments.length === 0) return <pre>{preview.page.markdown || preview.page.text}</pre>;
                return (
                  <div className="library-search-preview-text">
                    {preview.page.fragments.map((fragment) => found.has(fragment.id)
                      ? <mark key={fragment.id}>{fragment.text}</mark>
                      : <p key={fragment.id}>{fragment.text}</p>)}
                  </div>
                );
              })()}
            </section>
          </div>
        )}
      </Dialog>

      <ConfirmDialog
        open={deleteTargets.length > 0}
        onOpenChange={(open) => {
          if (!open) { setDeleteTargets([]); setDeletePreview(null); }
        }}
        title={
          deleteTargets.length === 1
            ? `Удалить ${deleteTargets[0].display_name}?`
            : `Удалить ${deleteTargets.length} ${plural(deleteTargets.length, "файл", "файла", "файлов")}?`
        }
        confirmLabel={deleteTargets.length === 1 ? "Удалить файл везде" : "Удалить все выбранные"}
        destructive
        /* Кнопка ждёт последствий: по FR-M10 их надо увидеть ДО удаления. */
        confirmDisabled={deletePreview === null}
        onConfirm={removeMaterials}
      >
        <p className="dialog-lead">
          {deleteTargets.length === 1
            ? "Файл удалится из общей Библиотеки и отвяжется от всех проектов."
            : "Файлы удалятся из общей Библиотеки и отвяжутся от всех проектов."}
        </p>

        {deletePreview === null ? (
          <LoadingState label="Считаем последствия" />
        ) : (
          <>
            {deleteTargets.length > 1 && (
              <ul className="consequences-topics">
                {deletePreview.materials.map((material) => (
                  <li key={material.id}>{material.display_name}</li>
                ))}
              </ul>
            )}

            {deletePreview.materials.some((material) => material.usage.length > 0)
              || deletePreview.reference_answer_count
              || deletePreview.binding_count ? (
              <dl className="consequences-facts">
                {deleteTargets.length === 1 && deletePreview.materials[0].usage.map((usage) => (
                  <div className="consequences-fact" key={usage.project_id}>
                    <dt>{usage.project_name}</dt>
                    <dd>{usage.purposes.map((item) => PURPOSE[item]).join(", ")}</dd>
                  </div>
                ))}
                {deletePreview.reference_answer_count ? (
                  <div className="consequences-fact">
                    <dt>Ответов из файлов</dt>
                    <dd>{deletePreview.reference_answer_count} — текст сохранится, источник станет недоступен</dd>
                  </div>
                ) : null}
                {deletePreview.binding_count ? (
                  <div className="consequences-fact">
                    <dt>Привязок к фрагментам</dt>
                    <dd>{deletePreview.binding_count} — уйдут вместе с файлами</dd>
                  </div>
                ) : null}
              </dl>
            ) : null}

            {deletePreview.affected_projects.map((affected) => (
              <div className="consequences-topics-block" key={affected.project_id}>
                <p className="consequences-topics-label">
                  {affected.project_name}: без материала останутся
                </p>
                <ul className="consequences-topics">
                  {affected.nodes_losing_material.map((node) => (
                    <li key={node}>{node}</li>
                  ))}
                </ul>
              </div>
            ))}

            {deletePreview.active_task_count > 0 && (
              <p className="consequences-note">
                Текущая обработка будет остановлена вместе с файлами: {deletePreview.active_task_count}.
              </p>
            )}

            {deletePreview.materials.every((material) => material.usage.length === 0)
              && !deletePreview.reference_answer_count
              && !deletePreview.binding_count
              && (
                <p className="consequences-note">
                  {deleteTargets.length === 1
                    ? "Файл не используется ни одним проектом."
                    : "Ни один из файлов не используется проектами."}
                </p>
              )}
          </>
        )}
      </ConfirmDialog>
    </div>
  );
}
