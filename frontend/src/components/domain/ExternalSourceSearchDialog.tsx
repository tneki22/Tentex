import { useEffect, useState, type FormEvent } from "react";
import { ExternalLink, Globe, Search } from "lucide-react";
import { Link } from "react-router";
import {
  cancelBackgroundJob,
  findResumableBackgroundJob,
  getBackgroundJobResult,
  resolveBackgroundJob,
} from "../../api/backgroundJobs";
import { createExternalMaterial, listMaterials } from "../../api/materials";
import { startSourceSearch, type SourceCandidate, type SourceKind, type SourceSearchResult } from "../../api/sourceSearch";
import { useAiRoleAvailability } from "../../hooks/useAiRoleAvailability";
import { useBackgroundJob } from "../../hooks/useBackgroundJob";
import { Button, Checkbox, Dialog, Field, LoadingState, StatusBadge } from "../ui";
import { OfflineNotice } from "./OfflineNotice";

const KIND_LABELS: Record<SourceKind, string> = {
  article: "Статья",
  video: "Видео",
  pdf: "PDF",
  course: "Курс",
  book: "Книга",
  other: "Страница",
};

function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function errorText(caught: unknown, fallback: string): string {
  return caught instanceof Error && caught.message ? caught.message : fallback;
}

interface ExternalSourceSearchDialogProps {
  open: boolean;
  onOpenChange(open: boolean): void;
  projectId: string;
  /** Предзаполненный запрос: цель проекта или тема с подсказкой ИИ. */
  initialQuery: string;
  programNodeId?: string | null;
  /** Первый материал проекта становится основным; не известно — спросим сервер. */
  hasProjectMaterials?: boolean;
  /** Прийти к конкретной задаче — из корзины «ждут проверки». */
  jobId?: string | null;
  onAdded?(materialIds: string[]): void;
}

type RowStatus = { added: true } | { error: string };

/**
 * Поиск материалов в интернете по явной кнопке. Модель ищет в сети через
 * OpenRouter; сервер оставляет только адреса из выдачи поиска. Кандидат
 * становится материалом, только когда пользователь его отметил и добавил.
 * Результат живёт в фоновой задаче: окно можно закрыть и вернуться к нему.
 */
export function ExternalSourceSearchDialog({
  open, onOpenChange, projectId, initialQuery, programNodeId = null, hasProjectMaterials, jobId: requestedJobId = null, onAdded,
}: ExternalSourceSearchDialogProps) {
  const availability = useAiRoleAvailability("source_web_search");
  const [query, setQuery] = useState(initialQuery);
  const [jobId, setJobId] = useState<string | null>(null);
  const [resumed, setResumed] = useState(false);
  const [result, setResult] = useState<SourceSearchResult | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [rows, setRows] = useState<Record<string, RowStatus>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { job } = useBackgroundJob(jobId);

  /* Открытие: к указанной задаче, к недоразобранному прошлому поиску или к чистому запросу. */
  useEffect(() => {
    if (!open) return;
    const abort = new AbortController();
    setQuery(initialQuery);
    setResult(null);
    setRows({});
    setError("");
    if (requestedJobId) {
      setJobId(requestedJobId);
      setResumed(true);
      return;
    }
    setJobId(null);
    setResumed(false);
    findResumableBackgroundJob("ai_source_search", { projectId }, abort.signal)
      .then((found) => {
        if (found && !abort.signal.aborted) {
          setJobId(found.id);
          setResumed(true);
        }
      })
      .catch(() => undefined);
    return () => abort.abort();
  }, [open, projectId, initialQuery, requestedJobId]);

  useEffect(() => {
    if (!jobId || job?.id !== jobId) return;
    if (job.state === "completed" && !result) {
      const abort = new AbortController();
      getBackgroundJobResult<SourceSearchResult>(jobId, abort.signal)
        .then((value) => {
          setResult(value);
          setSelected(new Set(value.candidates.filter((item) => item.import_kind !== "pdf_manual").map((item) => item.url)));
        })
        .catch((caught) => { if (!abort.signal.aborted) setError(errorText(caught, "Не удалось получить результат поиска")); });
      return () => abort.abort();
    }
    if (job.state === "cancelled") setJobId(null);
  }, [job, jobId, result]);

  async function start(event?: FormEvent) {
    event?.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError("");
    try {
      if (jobId && result) void resolveBackgroundJob(jobId).catch(() => undefined);
      setResult(null);
      setRows({});
      setResumed(false);
      const started = await startSourceSearch(projectId, { query: query.trim(), program_node_id: programNodeId });
      setJobId(started.job_id);
    } catch (caught) {
      setError(errorText(caught, "Не удалось начать поиск"));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!jobId) return;
    setBusy(true);
    try {
      await cancelBackgroundJob(jobId);
      setJobId(null);
    } catch (caught) {
      setError(errorText(caught, "Не удалось отменить поиск"));
    } finally {
      setBusy(false);
    }
  }

  function newSearch() {
    if (jobId && result) void resolveBackgroundJob(jobId).catch(() => undefined);
    setJobId(null);
    setResult(null);
    setRows({});
    setResumed(false);
    setQuery(initialQuery);
  }

  async function addSelected() {
    if (!result || !jobId) return;
    const picked = result.candidates.filter((item) => selected.has(item.url) && item.import_kind !== "pdf_manual" && !("added" in (rows[item.url] ?? {})));
    if (picked.length === 0) return;
    setBusy(true);
    setError("");
    const next = { ...rows };
    const created: string[] = [];
    try {
      let hasMaterials = hasProjectMaterials ?? (await listMaterials(projectId)).length > 0;
      for (const item of picked) {
        try {
          const material = await createExternalMaterial(projectId, {
            kind: item.import_kind === "youtube" ? "youtube" : "url",
            url: item.url,
            source_role: hasMaterials ? "additional" : "main",
            purposes: ["study_source"],
          });
          hasMaterials = true;
          created.push(material.id);
          next[item.url] = { added: true };
        } catch (caught) {
          next[item.url] = { error: errorText(caught, "Не удалось добавить") };
        }
        setRows({ ...next });
      }
      if (picked.every((item) => "added" in (next[item.url] ?? {}))) void resolveBackgroundJob(jobId).catch(() => undefined);
      if (created.length > 0) onAdded?.(created);
    } catch (caught) {
      setError(errorText(caught, "Не удалось добавить материалы"));
    } finally {
      setBusy(false);
    }
  }

  const running = jobId !== null && !result && (!job || job.state === "queued" || job.state === "running" || job.state === "paused");
  const failed = jobId !== null && job?.id === jobId && job.state === "failed";
  const openrouter = availability.state === "ready" && availability.providerProfile === "openrouter";
  const unsupported = availability.state === "ready" && availability.providerProfile !== null && !openrouter;
  const canSearch = availability.state === "ready" && !unsupported;
  const addable = result?.candidates.filter((item) => selected.has(item.url) && item.import_kind !== "pdf_manual" && !("added" in (rows[item.url] ?? {}))).length ?? 0;
  const addedCount = Object.values(rows).filter((row) => "added" in row).length;

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      className="external-source-dialog"
      title="Найти материалы в интернете"
      description="Модель поищет в сети статьи, лекции и видео под запрос. Предлагаются только страницы, которые поиск действительно нашёл."
    >
      {availability.state === "disabled" && <OfflineNotice reason="disabled" alternative="Материал можно загрузить файлом или ссылкой в разделе «Материалы»." />}
      {availability.state === "unavailable" && <p className="external-source-note" role="status">{availability.reason}</p>}
      {unsupported && (
        <p className="external-source-note" role="status">
          Поиск в интернете работает через OpenRouter. Выберите для функции «Поиск материалов в интернете» модель этого провайдера в <Link to="/setup?section=ai">Параметрах ИИ</Link>.
        </p>
      )}

      {!result && !running && (
        <form className="external-source-form" onSubmit={(event) => void start(event)}>
          <Field label="Что искать" hint="Короткая фраза ищется лучше: тема и, если нужно, «лекция», «конспект», «видео».">
            <input value={query} maxLength={300} onChange={(event) => setQuery(event.target.value)} disabled={!canSearch} />
          </Field>
          <p className="external-source-cost">
            <Globe size={14} aria-hidden="true" /> Запрос и цель проекта уйдут в OpenRouter. Платный вызов: поиск в сети стоит около цента сверх ответа модели.
          </p>
          {failed && <p className="inline-error" role="alert">Поиск не удался: {job?.error ?? "ошибка провайдера"}</p>}
          <div className="external-source-actions">
            <Button type="submit" disabled={!canSearch || busy || query.trim().length < 2}><Search size={15} />{failed ? "Повторить поиск" : "Найти"}</Button>
          </div>
        </form>
      )}

      {running && (
        <div className="external-source-running">
          <LoadingState label="Ищем в интернете — обычно одна-две минуты" />
          <p className="external-source-note">Окно можно закрыть: результат дождётся вас в фоновых задачах.</p>
          <Button variant="secondary" disabled={busy} onClick={() => void cancel()}>Отменить</Button>
        </div>
      )}

      {result && (
        <div className="external-source-result">
          <p className="external-source-summary">
            {resumed ? "Результат прошлого поиска" : "Найдено"} по запросу «{result.query}»
            <Button variant="ghost" onClick={newSearch}>Новый поиск</Button>
          </p>
          {result.candidates.length === 0 ? (
            <p className="external-source-note">Подходящего не нашлось. Уточните запрос: добавьте предмет или слово «лекция», «конспект».</p>
          ) : (
            <ul className="external-sources">
              {result.candidates.map((item) => (
                <CandidateRow
                  key={item.url}
                  item={item}
                  checked={selected.has(item.url)}
                  status={rows[item.url]}
                  disabled={busy}
                  onToggle={(checked) => setSelected((current) => {
                    const next = new Set(current);
                    if (checked) next.add(item.url);
                    else next.delete(item.url);
                    return next;
                  })}
                />
              ))}
            </ul>
          )}
          {result.unverified_count > 0 && (
            <p className="external-source-note">Скрыто ссылок вне выдачи поиска: {result.unverified_count}. Модель могла их придумать, поэтому мы их не показываем.</p>
          )}
          {result.already_attached_count > 0 && (
            <p className="external-source-note">Уже в проекте: {result.already_attached_count}.</p>
          )}
          {addedCount > 0 && (
            <p className="external-source-note is-success" role="status">
              Добавлено: {addedCount}. Страницы разбираются в «Материалах»; тема получит материал, когда вы соберёте урок из найденного.
            </p>
          )}
          {result.candidates.length > 0 && (
            <div className="external-source-actions">
              <Button disabled={busy || addable === 0} onClick={() => void addSelected()}>Добавить выбранные{addable > 0 ? ` (${addable})` : ""}</Button>
            </div>
          )}
        </div>
      )}
      {error && <p className="inline-error" role="alert">{error}</p>}
    </Dialog>
  );
}

function CandidateRow({ item, checked, status, disabled, onToggle }: {
  item: SourceCandidate;
  checked: boolean;
  status?: RowStatus;
  disabled: boolean;
  onToggle(checked: boolean): void;
}) {
  const added = status !== undefined && "added" in status;
  const manual = item.import_kind === "pdf_manual";
  return (
    <li className="external-source">
      <div className="external-source-head">
        <a href={item.url} target="_blank" rel="noreferrer noopener" className="external-source-title">
          {item.title}<ExternalLink size={13} aria-hidden="true" />
        </a>
        <StatusBadge tone="neutral">{KIND_LABELS[item.kind]}</StatusBadge>
        {added && <StatusBadge tone="success">Добавлено</StatusBadge>}
        {!manual && !added && <Checkbox label="Выбрать" checked={checked} disabled={disabled} onCheckedChange={onToggle} />}
      </div>
      <span className="external-source-host">{host(item.url)} · {item.why}</span>
      {item.snippet && <p className="external-source-snippet">{item.snippet}</p>}
      {manual && <p className="external-source-note">PDF по ссылке не загружается: откройте его, скачайте и добавьте файлом в «Материалах».</p>}
      {status && "error" in status && <p className="inline-error" role="alert">{status.error}</p>}
    </li>
  );
}
