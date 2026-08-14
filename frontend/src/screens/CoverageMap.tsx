import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import {
  ArrowLeft,
  Check,
  FileInput,
  FileText,
  Paperclip,
  Save,
  Trash2,
  X,
} from "lucide-react";
import { listBindings, type BindingFragmentRead } from "../api/bindings";
import { materialFragmentAssetUrl } from "../api/materials";
import {
  addAnswerAttachment,
  answerAttachmentUrl,
  confirmReferenceAnswer,
  deleteAnswerAttachment,
  deleteReferenceAnswer,
  getCoverageMap,
  getProject,
  getReferenceAnswer,
  importReferenceAnswers,
  listAnswerAttachments,
  ProjectApiError,
  putReferenceAnswer,
  type CoverageMapRead,
  type CoverageMapRow,
  type ProjectDetail,
  type ReferenceAnswerAttachment,
  type ReferenceAnswerImportResult,
  type ReferenceAnswerSlot,
} from "../api/projects";
import { GOAL_LEVELS, ProjectNav, ReferenceAnswerBadge } from "../components/domain";
import {
  Button,
  ConfirmDialog,
  Dialog,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  PageHead,
  Tooltip,
} from "../components/ui";
import { buildProgramTree, flattenProgramTree } from "./programTree";
import { useRecentAnswers } from "../hooks/useRecentAnswers";

type CoverageFilter = "all" | "with_answer" | "missing" | "needs_review" | "outside";

/** Так парсер помечает картинку во фрагменте (см. materials/parsers/native.py). */
const IMAGE_PLACEHOLDER = "[Изображение]";

function requestErrorMessage(error: unknown): string {
  return error instanceof ProjectApiError
    ? error.message
    : "Не удалось связаться с сервером. Проверьте, что Tentex запущен, и повторите.";
}

function isStudyRow(row: CoverageMapRow): boolean {
  return row.node_type === "topic" || row.node_type === "subpoint";
}

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / 1024 ** 2).toFixed(1)} МБ`;
}

function filterRows(rows: CoverageMapRow[], filter: CoverageFilter, query: string): CoverageMapRow[] {
  const normalizedQuery = query.trim().toLocaleLowerCase("ru");
  const matchingIds = new Set(
    rows
      .filter((row) => !normalizedQuery || row.title.toLocaleLowerCase("ru").includes(normalizedQuery))
      .filter((row) => {
        if (filter === "outside") return !row.is_in_current_program;
        if (!row.is_in_current_program) return false;
        if (row.node_type === "section") return true;
        if (filter === "with_answer") return row.answer_status !== "missing";
        if (filter === "missing") return row.answer_status === "missing";
        if (filter === "needs_review") return row.answer_status === "needs_review";
        return true;
      })
      .map((row) => row.node_id),
  );

  // A section stays visible only when it matches itself or contains a matching descendant.
  const byId = new Map(rows.map((row) => [row.node_id, row]));
  for (const id of [...matchingIds]) {
    let parentId = byId.get(id)?.parent_id ?? null;
    while (parentId) {
      matchingIds.add(parentId);
      parentId = byId.get(parentId)?.parent_id ?? null;
    }
  }
  return rows.filter((row) => matchingIds.has(row.node_id));
}

function rowDepth(row: CoverageMapRow, byId: Map<string, CoverageMapRow>): number {
  let depth = 0;
  let parentId = row.parent_id;
  const visited = new Set<string>();
  while (parentId && !visited.has(parentId)) {
    visited.add(parentId);
    depth += 1;
    parentId = byId.get(parentId)?.parent_id ?? null;
  }
  return depth;
}

export function CoverageMap() {
  const { projectId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const preferredTopic = searchParams.get("topic");
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [coverage, setCoverage] = useState<CoverageMapRead | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(preferredTopic);
  const [slot, setSlot] = useState<ReferenceAnswerSlot | null>(null);
  const [answerDraft, setAnswerDraft] = useState("");
  const [sourceDraft, setSourceDraft] = useState("");
  const [filter, setFilter] = useState<CoverageFilter>("all");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [slotLoading, setSlotLoading] = useState(false);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [commandError, setCommandError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [importSource, setImportSource] = useState("");
  const [importResult, setImportResult] = useState<ReferenceAnswerImportResult | null>(null);
  const [attachments, setAttachments] = useState<ReferenceAnswerAttachment[]>([]);
  const [boundImages, setBoundImages] = useState<BindingFragmentRead[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { recent, recordSave } = useRecentAnswers(projectId);

  async function load(signal?: AbortSignal) {
    setLoading(true);
    setLoadError(null);
    try {
      const nextDetail = await getProject(projectId, signal);
      setDetail(nextDetail);
      if (nextDetail.project.workspace_variant === "exam") {
        const nextCoverage = await getCoverageMap(projectId, signal);
        setCoverage(nextCoverage);
        const availableIds = new Set(nextCoverage.rows.filter(isStudyRow).map((row) => row.node_id));
        setSelectedId((current) => current && availableIds.has(current)
          ? current
          : nextCoverage.rows.find((row) => isStudyRow(row) && row.is_in_current_program)?.node_id ?? null);
      }
    } catch (error) {
      if (!signal?.aborted) setLoadError(error);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [projectId]);

  useEffect(() => {
    if (!selectedId || detail?.project.workspace_variant !== "exam") {
      setSlot(null);
      return;
    }
    const controller = new AbortController();
    setSlotLoading(true);
    setCommandError("");
    getReferenceAnswer(projectId, selectedId, controller.signal)
      .then((next) => {
        setSlot(next);
        setAnswerDraft(next.answer?.is_active ? next.answer.text : "");
        setSourceDraft(next.answer?.is_active ? next.answer.source_label ?? "" : "");
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) setCommandError(requestErrorMessage(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setSlotLoading(false);
      });
    return () => controller.abort();
  }, [detail?.project.workspace_variant, projectId, selectedId]);

  useEffect(() => {
    if (!selectedId || detail?.project.workspace_variant !== "exam") {
      setAttachments([]);
      setBoundImages([]);
      return;
    }
    const controller = new AbortController();
    void listAnswerAttachments(projectId, selectedId, controller.signal)
      .then(setAttachments)
      .catch(() => undefined);
    // Картинки из материала копировать не надо: они уже привязаны к вопросу.
    void listBindings(projectId, { nodeId: selectedId }, controller.signal)
      .then((items) => setBoundImages(items.filter((item) => item.text === IMAGE_PLACEHOLDER)))
      .catch(() => undefined);
    return () => controller.abort();
  }, [detail?.project.workspace_variant, projectId, selectedId]);

  const byId = useMemo(() => new Map((coverage?.rows ?? []).map((row) => [row.node_id, row])), [coverage]);
  const numberByNodeId = useMemo(() => {
    const map = new Map<string, string>();
    try {
      for (const node of flattenProgramTree(buildProgramTree(detail?.program.nodes ?? []))) map.set(node.id, node.number);
    } catch {
      // некорректное дерево программы — список эталонов остаётся без номеров
    }
    return map;
  }, [detail?.program.nodes]);
  const shownRows = useMemo(
    () => filterRows(coverage?.rows ?? [], filter, query),
    [coverage?.rows, filter, query],
  );
  const recentRows = useMemo(() => recent.map((nodeId) => byId.get(nodeId)).filter((row): row is CoverageMapRow => Boolean(row)), [recent, byId]);
  const selectedRow = selectedId ? byId.get(selectedId) ?? null : null;
  const readOnly = detail?.project.status !== "active";
  const hasActiveAnswer = Boolean(slot?.answer?.is_active);
  const dirty = Boolean(slot) && (
    answerDraft !== (hasActiveAnswer ? slot?.answer?.text ?? "" : "")
    || sourceDraft !== (hasActiveAnswer ? slot?.answer?.source_label ?? "" : "")
  );


  async function refresh(nextCoverage?: CoverageMapRead) {
    const map = nextCoverage ?? await getCoverageMap(projectId);
    setCoverage(map);
    if (selectedId) {
      const nextSlot = await getReferenceAnswer(projectId, selectedId);
      setSlot(nextSlot);
      setAnswerDraft(nextSlot.answer?.is_active ? nextSlot.answer.text : "");
      setSourceDraft(nextSlot.answer?.is_active ? nextSlot.answer.source_label ?? "" : "");
    }
  }

  async function run(operation: () => Promise<ReferenceAnswerSlot>, successMessage: string, onSuccess?: () => void) {
    if (busy) return;
    setBusy(true);
    setCommandError("");
    setNotice("");
    try {
      const nextSlot = await operation();
      setSlot(nextSlot);
      setAnswerDraft(nextSlot.answer?.is_active ? nextSlot.answer.text : "");
      setSourceDraft(nextSlot.answer?.is_active ? nextSlot.answer.source_label ?? "" : "");
      setCoverage(await getCoverageMap(projectId));
      setNotice(successMessage);
      onSuccess?.();
    } catch (error) {
      if (error instanceof ProjectApiError && error.code === "stale_reference_answer_revision") {
        await refresh();
        setCommandError("Ответ уже изменился в другой вкладке. Показана серверная версия.");
      } else {
        setCommandError(requestErrorMessage(error));
      }
    } finally {
      setBusy(false);
    }
  }

  async function importAnswers() {
    if (!importText.trim() || busy) return;
    setBusy(true);
    setCommandError("");
    setImportResult(null);
    try {
      const result = await importReferenceAnswers(projectId, {
        raw_text: importText,
        source_label: importSource.trim() || null,
      });
      setImportResult(result);
      await refresh(result.coverage_map);
      setNotice(`Добавлено ответов: ${result.created}. Уже существующие ответы не изменены.`);
    } catch (error) {
      setCommandError(requestErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function addAttachments(files: FileList | null) {
    if (!files || files.length === 0 || !selectedRow) return;
    const nodeId = selectedRow.node_id;
    setBusy(true);
    setCommandError("");
    try {
      for (const file of Array.from(files)) {
        const created = await addAnswerAttachment(projectId, nodeId, file);
        setAttachments((current) => [...current, created]);
      }
      setNotice("Файл прикреплён к ответу.");
    } catch (error) {
      setCommandError(requestErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function removeAttachment(attachmentId: string) {
    setBusy(true);
    setCommandError("");
    try {
      await deleteAnswerAttachment(projectId, attachmentId);
      setAttachments((current) => current.filter((item) => item.id !== attachmentId));
    } catch (error) {
      setCommandError(requestErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <div className="screen"><LoadingState label="Загружаем ответы" placement="page" /></div>;
  if (loadError) {
    const notFound = loadError instanceof ProjectApiError && loadError.status === 404;
    return <div className="screen"><ErrorState title={notFound ? "Проект не найден" : undefined} message={notFound ? "Проверьте адрес или вернитесь к списку проектов." : requestErrorMessage(loadError)} /><Button onClick={() => void load()}>Повторить загрузку</Button><Link className="secondary-button" to="/projects">К проектам</Link></div>;
  }
  if (!detail) return null;
  if (detail.project.workspace_variant !== "exam") {
    return <div className="screen"><EmptyState title="Эталоны нужны для экзаменационных вопросов"><p>Для проекта по учебнику эта карта появится вместе с учебными сценариями следующих этапов.</p><Link className="secondary-button" to={`/projects/${projectId}`}><ArrowLeft size={15} />В рабочую область</Link></EmptyState></div>;
  }
  if (!coverage) return null;

  return (
    <div className="program-screen coverage-screen">
      <aside className="program-project-panel">
        <header className="program-project-title"><Link className="workspace-back-button" to={`/projects/${projectId}`} aria-label="Вернуться в рабочую область"><ArrowLeft size={15} /></Link><strong>{detail.project.name}</strong></header>
        <section className="coverage-recent" aria-label="Последние изменённые ответы">
          <header><span>Недавние ответы</span><small>{recentRows.length}</small></header>
          <div className="coverage-recent-list">
            {recentRows.length === 0
              ? <p className="sidebar-empty">Пока ничего не сохраняли — здесь появятся последние правки в этой вкладке.</p>
              : recentRows.map((row) => (
                <button type="button" className={`coverage-recent-item ${selectedId === row.node_id ? "is-active" : ""}`.trim()} key={row.node_id} onClick={() => setSelectedId(row.node_id)}>
                  <span>{numberByNodeId.get(row.node_id)}. {row.title}</span>
                  {row.answer_status && <ReferenceAnswerBadge status={row.answer_status} />}
                </button>
              ))}
          </div>
        </section>
        <ProjectNav
          projectId={projectId}
          active="answers"
          modules={detail.project.enabled_modules}
          counts={{ answers: `${coverage.totals.with_answer}/${coverage.totals.study_nodes}` }}
          className="program-project-nav"
        />
      </aside>

      <main className="program-main coverage-main">
        <PageHead
          title="Ответы"
          actions={<Button disabled={readOnly} onClick={() => { setImportResult(null); setImportOpen(true); }}><FileInput size={15} />Импортировать</Button>}
        />
        {readOnly && <p className="inline-warning">Проект доступен только для чтения. Верните его в активные, чтобы менять эталоны.</p>}
        {commandError && <p className="inline-error" role="alert">{commandError}</p>}
        {notice && <p className="coverage-notice" role="status">{notice}</p>}

        <section className="coverage-summary" aria-label="Сводка по эталонам">
          <span><strong>{coverage.totals.with_answer}</strong> из {coverage.totals.study_nodes}<small>есть ответ</small></span>
          <span><strong>{coverage.totals.confirmed}</strong><small>подтверждены или добавлены вручную</small></span>
          <span><strong>{coverage.totals.needs_review}</strong><small>нужно проверить</small></span>
          <span><strong>{coverage.totals.missing}</strong><small>без ответа</small></span>
        </section>

        <div className="coverage-toolbar">
          <label><span className="sr-only">Поиск по вопросам</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти вопрос" /></label>
          <label><span className="sr-only">Фильтр эталонов</span><select value={filter} onChange={(event) => setFilter(event.target.value as CoverageFilter)}><option value="all">Текущая программа</option><option value="with_answer">Есть ответ</option><option value="missing">Нет ответа</option><option value="needs_review">Нужно проверить</option><option value="outside">Вне текущей программы</option></select></label>
        </div>

        <div className="coverage-editor-grid">
          <section className="coverage-list" aria-label="Вопросы и эталоны">
            {shownRows.map((row) => {
              const study = isStudyRow(row);
              const number = numberByNodeId.get(row.node_id);
              return (
                <button
                  type="button"
                  className={`coverage-row ${study ? "is-study" : "is-section"} ${selectedId === row.node_id ? "is-selected" : ""}`.trim()}
                  style={{ "--coverage-depth": rowDepth(row, byId) } as CSSProperties}
                  disabled={!study}
                  onClick={() => setSelectedId(row.node_id)}
                  key={row.node_id}
                >
                  <span className="coverage-row-copy"><strong>{number ? `${number}. ` : ""}{row.title}</strong><small>{row.is_in_current_program ? row.node_type === "section" ? "Раздел" : row.exam_kind === "task" ? "Задача" : "Вопрос" : "Вне текущей программы"}</small></span>
                  {row.answer_status && <ReferenceAnswerBadge status={row.answer_status} />}
                </button>
              );
            })}
            {shownRows.length === 0 && <EmptyState title="По этому фильтру ничего нет"><Button variant="secondary" onClick={() => { setFilter("all"); setQuery(""); }}>Сбросить фильтр</Button></EmptyState>}
          </section>

          <aside className="coverage-inspector" aria-label="Эталонный ответ">
            {!selectedRow ? <p>Выберите вопрос.</p> : slotLoading ? <LoadingState label="Загружаем эталон" /> : slot ? <>
              <div className="coverage-inspector-head"><div><p className="eyebrow">{selectedRow.exam_kind === "task" ? "Задача" : "Вопрос"}</p><h2>{numberByNodeId.get(selectedRow.node_id)}. {selectedRow.title}</h2></div><ReferenceAnswerBadge status={slot.status} /></div>
              <p className="coverage-target-level">Целевой уровень: {GOAL_LEVELS.find((level) => level.value === selectedRow.target_level)?.label ?? "не задан"}</p>
              {slot.answer?.is_active && slot.answer.source_material_id && (
                <p className="coverage-answer-origin">
                  <FileInput size={14} aria-hidden="true" />
                  Заполнено из файла ответов
                  {slot.answer.source_page_from
                    ? slot.answer.source_page_from === slot.answer.source_page_to
                      ? `, стр. ${slot.answer.source_page_from}`
                      : `, стр. ${slot.answer.source_page_from}–${slot.answer.source_page_to}`
                    : ""}
                  <Link to={`/projects/${projectId}/materials/${slot.answer.source_material_id}?page=${slot.answer.source_page_from ?? 1}`}>
                    открыть в материалах
                  </Link>
                </p>
              )}
              <Field label="Эталонный ответ" required><textarea rows={12} value={answerDraft} disabled={readOnly || busy} onChange={(event) => { setAnswerDraft(event.target.value); setNotice(""); }} placeholder="Добавьте короткий образцовый ответ по вопросу" /></Field>
              <Field label="Источник" hint="Необязательно: название конспекта или документа"><input value={sourceDraft} disabled={readOnly || busy} onChange={(event) => setSourceDraft(event.target.value)} /></Field>

              {boundImages.length > 0 && (
                <div className="coverage-attachments-field">
                  <div className="field-head"><label>Картинки из материала</label></div>
                  <div className="coverage-bound-images">
                    {boundImages.map((binding) => (
                      <Link
                        className="coverage-bound-image"
                        key={binding.id}
                        to={`/projects/${projectId}/materials/${binding.material_id}?page=${binding.page_number}&focus=${binding.fragment_id}`}
                      >
                        <img
                          src={materialFragmentAssetUrl(projectId, binding.material_id, binding.fragment_id)}
                          alt={`Изображение со страницы ${binding.page_number}`}
                          loading="lazy"
                        />
                        <small>стр. {binding.page_number}</small>
                      </Link>
                    ))}
                  </div>
                  <small className="field-hint">
                    Приехали из привязок этого вопроса. Убрать — сняв привязку в материалах.
                  </small>
                </div>
              )}

              <div className="coverage-attachments-field">
                <div className="field-head"><label>Свои файлы к ответу</label></div>
                <div className="coverage-attachments">
                  {attachments.map((file) => (
                    <span className="coverage-attachment-chip" key={file.id}>
                      <Paperclip size={13} aria-hidden="true" />
                      <a className="coverage-attachment-name" href={answerAttachmentUrl(projectId, file.id)} target="_blank" rel="noreferrer">{file.file_name}</a>
                      <small>{sizeLabel(file.size_bytes)}</small>
                      <button type="button" disabled={readOnly || busy} onClick={() => void removeAttachment(file.id)} aria-label={`Убрать файл «${file.file_name}»`}><X size={12} /></button>
                    </span>
                  ))}
                  <button type="button" className="coverage-attachment-add" disabled={readOnly || busy} onClick={() => fileInputRef.current?.click()}>
                    <Paperclip size={14} />Прикрепить файл
                  </button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept="image/*,.pdf,.docx,.txt,.md"
                    className="materials-file-input"
                    onChange={(event) => { void addAttachments(event.target.files); event.target.value = ""; }}
                  />
                </div>
                <small className="field-hint">Изображения, PDF, DOCX, TXT и MD — до 20 МБ. Хранятся вместе с проектом.</small>
              </div>

              <Button
                className="coverage-primary-action"
                disabled={readOnly || busy || !answerDraft.trim() || !dirty}
                onClick={() => void run(
                  () => putReferenceAnswer(projectId, selectedRow.node_id, { expected_revision: slot.answer?.revision ?? null, text: answerDraft, source_label: sourceDraft.trim() || null }),
                  hasActiveAnswer ? "Ответ сохранён." : "Ответ добавлен.",
                  () => recordSave(selectedRow.node_id),
                )}
              >
                <Save size={16} />Сохранить
              </Button>

              {(slot.answer?.is_active) && (
                <div className="coverage-inspector-actions">
                  {slot.status !== "confirmed" && slot.status !== "manual" && <Button variant="secondary" disabled={readOnly || busy} onClick={() => void run(() => confirmReferenceAnswer(projectId, selectedRow.node_id, slot.answer!.revision), "Автоматическое сопоставление подтверждено.")}><Check size={15} />Подтвердить</Button>}
                  <Button variant="ghost" disabled={readOnly || busy} onClick={() => setDeleteOpen(true)}><Trash2 size={15} />Убрать ответ</Button>
                </div>
              )}

              <Tooltip label="Открыть тему в рабочей области">
                <Link className="coverage-primary-action is-secondary" to={`/projects/${projectId}?topic=${selectedRow.node_id}`}><FileText size={16} />Открыть вопрос в рабочей области</Link>
              </Tooltip>
            </> : <ErrorState message="Не удалось загрузить эталон" />}
          </aside>
        </div>
      </main>

      <Dialog
        open={importOpen}
        onOpenChange={setImportOpen}
        title="Импортировать эталонные ответы"
        description="Заголовок раздела должен точно совпасть с вопросом программы. Существующие ответы не перезаписываются."
        className="coverage-import-dialog"
        footer={<><Button variant="ghost" onClick={() => setImportOpen(false)}>Закрыть</Button><Button disabled={busy || !importText.trim()} onClick={() => void importAnswers()}>{busy ? "Импортируем…" : "Импортировать"}</Button></>}
      >
        <Field label="Текст с ответами" required hint="Пример: заголовок вопроса, затем абзацы ответа"><textarea rows={14} value={importText} onChange={(event) => setImportText(event.target.value)} placeholder={'Архитектура СУБД\nТрёхуровневая архитектура включает…\n\nРеляционная модель данных\nРеляционная модель представляет…'} /></Field>
        <Field label="Источник" hint="Необязательно"><input value={importSource} onChange={(event) => setImportSource(event.target.value)} placeholder="Например, конспект преподавателя" /></Field>
        {importResult && <div className="coverage-import-result" role="status"><strong>Добавлено: {importResult.created}</strong><span>Пропущено существующих: {importResult.skipped_existing.length}</span><span>Не найдено совпадений: {importResult.unmatched_sections.length}</span><span>Неоднозначных заголовков: {importResult.ambiguous.length}</span><span>Пустых разделов: {importResult.empty_sections.length}</span></div>}
      </Dialog>

      <ConfirmDialog open={deleteOpen} onOpenChange={setDeleteOpen} title="Убрать эталонный ответ?" confirmLabel="Убрать ответ" destructive onConfirm={() => { if (selectedRow && slot?.answer) void run(() => deleteReferenceAnswer(projectId, selectedRow.node_id, slot.answer!.revision), "Ответ убран. Его можно добавить снова."); }}><p>Текст перестанет отображаться в рабочей области. Узел программы останется без изменений.</p></ConfirmDialog>
    </div>
  );
}
