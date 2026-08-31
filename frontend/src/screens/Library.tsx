import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AudioLines,
  FileImage,
  FileText,
  FileType2,
  Globe,
  Play,
  Plus,
  Trash2,
  Video,
  X,
} from "lucide-react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import {
  deleteLibraryMaterials,
  listLibraryMaterials,
  previewMaterialsDelete,
  startLibraryProcessing,
  type LibraryMaterialRead,
  type MaterialPresentationKind,
  type MaterialPurpose,
  type MaterialsDeletePreview,
} from "../api/materials";
import { QualityBadge } from "../components/domain";
import {
  Button,
  Checkbox,
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
/** Проектов в строке видно два: дальше строка растёт и уводит кнопку удаления. */
const USAGE_SHOWN = 2;

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
  const [notice, setNotice] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
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

  const filters = useMemo(() => readFilters(searchParams), [searchParams]);
  const scrollKey = `${SCROLL_KEY}:${searchParams.toString()}`;

  const load = useCallback(async (options: { signal?: AbortSignal; silent?: boolean } = {}) => {
    const { signal, silent } = options;
    if (!silent) setLoading(true);
    setError("");
    try {
      setMaterials(await listLibraryMaterials(signal));
    } catch (caught) {
      if (!signal?.aborted) {
        setError(caught instanceof Error ? caught.message : "Не удалось загрузить Библиотеку");
      }
    } finally {
      if (!signal?.aborted && !silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load({ signal: controller.signal });
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
    setSelectedIds(new Set());
    setDeleteTargets([]);
    setDeletePreview(null);
    setPendingIds((current) => new Set([...current, ...ids]));
    setNotice(`Удалено: ${ids.length} ${plural(ids.length, "файл", "файла", "файлов")}`);

    try {
      await deleteLibraryMaterials(ids);
    } catch (caught) {
      setMaterials(snapshot);
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
        actions={
          <Button onClick={() => setAddOpen(true)}>
            <Plus size={15} aria-hidden="true" /> Добавить материал
          </Button>
        }
      />
      {error && <ErrorState message={error} />}

      {materials.length > 0 && (
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

      {materials.length > 0 && (
        <LibraryFilters
          value={filters}
          total={materials.length}
          shown={visible.length}
          onChange={updateFilters}
          onReset={() => setSearchParams(new URLSearchParams(), { replace: true })}
        />
      )}

      {selected.length > 0 && (
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
            const shown = material.usage.slice(0, USAGE_SHOWN);
            const hidden = material.usage.slice(USAGE_SHOWN);
            return (
              <div
                className={`lib-row${selectedIds.has(material.id) ? " is-selected" : ""}`}
                role="listitem"
                key={material.id}
              >
                <span
                  className="lib-row-select"
                  onMouseDown={(event) => { shiftHeld.current = event.shiftKey; }}
                >
                  <Checkbox
                    checked={selectedIds.has(material.id)}
                    onCheckedChange={(checked) => toggleSelected(index, checked)}
                    label={`Выбрать ${material.original_name}`}
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
                    <>
                      {shown.map((usage) => (
                        <Link
                          key={`${usage.project_id}-${usage.display_name}`}
                          to={`/projects/${usage.project_id}/materials/${material.id}`}
                          title={`${usage.display_name} · ${usage.purposes.map((item) => PURPOSE[item]).join(", ")}`}
                        >
                          {usage.project_name}
                        </Link>
                      ))}
                      {hidden.length > 0 && (
                        <span
                          className="lib-usage-more"
                          title={hidden.map((usage) => usage.project_name).join(", ")}
                        >
                          +{hidden.length}
                        </span>
                      )}
                    </>
                  ) : <span className="lib-unused">не используется</span>}
                </div>

                <IconButton
                  label={`Удалить ${material.original_name}`}
                  disabled={busy}
                  onClick={() => void askDelete([material])}
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
        open={deleteTargets.length > 0}
        onOpenChange={(open) => {
          if (!open) { setDeleteTargets([]); setDeletePreview(null); }
        }}
        title={
          deleteTargets.length === 1
            ? `Удалить ${deleteTargets[0].original_name}?`
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
                  <li key={material.id}>{material.original_name}</li>
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
                    <dt>Эталонов из файлов</dt>
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
