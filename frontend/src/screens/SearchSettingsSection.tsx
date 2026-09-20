import { Check, Cpu, Database, Download, Gauge, Play, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { getAiSettings, type AiSettingsRead } from "../api/ai";
import { ProjectApiError } from "../api/projects";
import {
  activateRetrievalIndex,
  buildRetrievalIndex,
  createEmbeddingProfile,
  deleteLocalEmbeddingModel,
  deleteRetrievalIndex,
  getRetrievalSettings,
  installLocalEmbeddingModel,
  listLocalEmbeddingModels,
  listRetrievalBenchmarks,
  listRetrievalIndexes,
  runRetrievalBenchmark,
  testEmbeddingProfile,
  updateRetrievalSettings,
  type BenchmarkRunRead,
  type LocalModelRead,
  type RetrievalIndexRead,
  type RetrievalPreset,
  type RetrievalSettingsRead,
} from "../api/retrieval";
import {
  Button,
  ErrorState,
  LoadingState,
  SegmentedTabs,
  Select,
  StatusBadge,
} from "../components/ui";
import type { SearchSettingsSubsection } from "./Setup";
import { useBackgroundJob } from "../hooks/useBackgroundJob";

const INDEX_STATUS: Record<RetrievalIndexRead["state"], { label: string; tone: "info" | "success" | "neutral" | "danger" }> = {
  building: { label: "Собирается", tone: "info" },
  ready: { label: "Готов к активации", tone: "neutral" },
  active: { label: "Активен", tone: "success" },
  failed: { label: "Ошибка", tone: "danger" },
};

function errorText(caught: unknown): string {
  return caught instanceof Error ? caught.message : "Не удалось выполнить действие";
}

/** «1 кусок», «2 куска», «5 кусков»: без склонения сводка читается как машинная. */
function plural(count: number, one: string, few: string, many: string): string {
  const tail = Math.abs(count) % 100;
  if (tail >= 11 && tail <= 14) return many;
  const last = tail % 10;
  if (last === 1) return one;
  if (last >= 2 && last <= 4) return few;
  return many;
}

export function SearchSettingsSection({
  subsection,
  onActiveSubsection,
}: {
  subsection: SearchSettingsSubsection;
  onActiveSubsection: (value: string) => void;
}) {
  const [settings, setSettings] = useState<RetrievalSettingsRead | null>(null);
  const [indexes, setIndexes] = useState<RetrievalIndexRead[]>([]);
  const [models, setModels] = useState<LocalModelRead[]>([]);
  const [benchmarks, setBenchmarks] = useState<BenchmarkRunRead[]>([]);
  const [aiSettings, setAiSettings] = useState<AiSettingsRead | null>(null);
  const [externalProvider, setExternalProvider] = useState<string | null>(null);
  const [externalModel, setExternalModel] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [watchedJobId, setWatchedJobId] = useState<string | null>(null);
  const watchedJob = useBackgroundJob(watchedJobId);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const [nextSettings, nextIndexes, nextModels, nextBenchmarks, nextAiSettings] = await Promise.all([
        getRetrievalSettings(signal),
        listRetrievalIndexes(),
        listLocalEmbeddingModels(),
        listRetrievalBenchmarks(),
        getAiSettings(signal).catch(() => null),
      ]);
      setSettings(nextSettings);
      setIndexes(nextIndexes);
      setModels(nextModels);
      setBenchmarks(nextBenchmarks);
      setAiSettings(nextAiSettings);
      setExternalProvider((current) => current ?? nextAiSettings?.providers[0]?.id ?? null);
      setError("");
    } catch (caught) {
      if (!signal?.aborted) setError(errorText(caught));
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    onActiveSubsection(subsection);
  }, [onActiveSubsection, subsection]);

  useEffect(() => {
    if (watchedJob.job) void load();
  }, [watchedJob.job?.state, watchedJob.job?.done, load]);

  // Скачивание идёт в воркере и переживает перезагрузку страницы: по флагу с сервера
  // список обновляется и тогда, когда `watchedJobId` уже потерян.
  const hasInstalling = models.some((model) => model.installing);
  useEffect(() => {
    if (!hasInstalling) return;
    const timer = window.setInterval(() => { void load(); }, 3000);
    return () => window.clearInterval(timer);
  }, [hasInstalling, load]);

  async function action(key: string, operation: () => Promise<unknown>) {
    setBusy(key);
    setError("");
    try {
      const result = await operation();
      if (
        result
        && typeof result === "object"
        && "job_id" in result
        && typeof result.job_id === "string"
      ) setWatchedJobId(result.job_id);
      await load();
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy("");
    }
  }

  if (!settings) {
    return error
      ? <ErrorState message={error}><Button onClick={() => void load()}>Повторить</Button></ErrorState>
      : <LoadingState label="Загружаем настройки поиска" />;
  }

  const activeProfile = settings.profiles.find(
    (profile) => profile.id === settings.active_index?.profile_id,
  );
  const candidate = indexes.find((index) => index.state === "ready");
  const externalModels = aiSettings?.models.filter(
    (model) => model.provider_id === externalProvider && model.is_available,
  ) ?? [];

  function buildCandidate() {
    if (!settings) return;
    const profile = settings.profiles.find((item) => item.id === settings.default_profile_id);
    if (!profile) return;
    const cloud = profile.backend_kind === "openai_compatible";
    void action("build", async () => {
      if (!cloud) return buildRetrievalIndex({
        profile_id: profile.id,
        preset: settings.preset,
        cloud_consent: false,
      });
      try {
        return await buildRetrievalIndex({
          profile_id: profile.id,
          preset: settings.preset,
          cloud_consent: false,
        });
      } catch (caught) {
        if (!(caught instanceof ProjectApiError)
          || caught.code !== "retrieval_cloud_consent_required") throw caught;
        const materials = Array.isArray(caught.context.materials)
          ? caught.context.materials as Array<{ name?: string; size_bytes?: number }>
          : [];
        const totalMb = Number(caught.context.size_bytes ?? 0) / 1024 / 1024;
        const names = materials.slice(0, 8).map((item) => `• ${item.name ?? "Материал"}`).join("\n");
        const more = materials.length > 8 ? `\n…и ещё ${materials.length - 8}` : "";
        const confirmed = window.confirm(
          `Внешней модели ${profile.model_id} будут отправлены ${materials.length} материалов `
          + `(${totalMb.toFixed(1)} МБ), включая исходники Typst при их наличии.\n\n`
          + `${names}${more}\n\nТочная стоимость зависит от провайдера. Продолжить?`,
        );
        if (!confirmed) return undefined;
        return buildRetrievalIndex({
          profile_id: profile.id,
          preset: settings.preset,
          cloud_consent: true,
        });
      }
    });
  }

  return (
    <div className="ai-settings retrieval-settings">
      {error && <ErrorState message={error} />}
      {watchedJob.job?.state === "failed" && (
        <ErrorState message={`Модель не скачалась: ${watchedJob.job.error ?? "причина не указана"}`} />
      )}

      {subsection === "overview" && (
        <section id="search-overview" className="ai-settings-group is-first">
          <header className="ai-group-head">
            <div>
              <h2>Поиск по содержимому</h2>
              <p>Один retrieval-контур для чата, экзамена, Учебника и свободного изучения.</p>
            </div>
            <StatusBadge tone={settings.degraded ? "neutral" : "success"}>
              {settings.degraded ? "Частично готов" : "Готов"}
            </StatusBadge>
          </header>
          <div className="retrieval-overview-grid">
            <article>
              <Cpu size={18} aria-hidden="true" />
              <small>Embedding-модель</small>
              <strong>{activeProfile?.label ?? "Не выбрана"}</strong>
              <span>
                {activeProfile?.dimension
                  ? `${activeProfile.dimension} ${plural(activeProfile.dimension, "измерение", "измерения", "измерений")}`
                  : "Размерность не проверена"}
              </span>
            </article>
            <article>
              <Database size={18} aria-hidden="true" />
              <small>Активный индекс</small>
              <strong>
                {settings.active_index
                  ? `${settings.active_index.chunk_count} ${plural(settings.active_index.chunk_count, "кусок", "куска", "кусков")}`
                  : "Не собран"}
              </strong>
              <span>
                {settings.ready_materials} из {settings.total_ready_materials}{" "}
                {plural(settings.total_ready_materials, "материала", "материалов", "материалов")}{" "}
                {plural(settings.ready_materials, "готов", "готовы", "готовы")}
              </span>
            </article>
            <article>
              <Gauge size={18} aria-hidden="true" />
              <small>Профиль выдачи</small>
              <strong>{{ fast: "Быстро", balanced: "Сбалансированно", accurate: "Точно" }[settings.preset]}</strong>
              <span>BM25 + поиск по смыслу, RRF k=60</span>
            </article>
          </div>
          {settings.degradation_reasons.map((reason) => (
            <p className="retrieval-neutral-note" key={reason}>{reason}</p>
          ))}
        </section>
      )}

      {subsection === "models" && (
        <section id="search-models" className="ai-settings-group is-first">
          <header className="ai-group-head">
            <div>
              <h2>Модели</h2>
              <p>Локальные модели скачиваются с Hugging Face. Произвольный код репозитория не запускается.</p>
            </div>
          </header>
          <div className="retrieval-model-list">
            {models.map((model) => {
              const profile = settings.profiles.find((item) => item.model_id === model.model_id);
              return <article key={model.model_id}>
                <div>
                  <strong>{model.label}</strong>
                  <small>{model.model_id}</small>
                  <span>{model.recommended_for}</span>
                </div>
                <div className="ai-group-actions">
                  {model.installing ? <StatusBadge tone="info"><Download size={13} /> Скачивается…</StatusBadge>
                    : model.installed ? <><StatusBadge tone="success"><Check size={13} /> Установлена</StatusBadge>
                    <Button variant="ghost" disabled={busy !== ""} onClick={() => void action(`delete:${model.model_id}`, () => deleteLocalEmbeddingModel(model.model_id))}>Удалить</Button></> : (
                    <Button
                      variant="secondary"
                      disabled={busy !== ""}
                      onClick={() => void action(`install:${model.model_id}`, () => installLocalEmbeddingModel(model.model_id))}
                    ><Download size={14} /> Скачать</Button>
                  )}
                  {model.role === "embedding" && !profile && (
                    <Button
                      variant="ghost"
                      disabled={busy !== ""}
                      onClick={() => void action(`profile:${model.model_id}`, () => createEmbeddingProfile({
                        label: model.label,
                        backend_kind: "local_hf",
                        model_id: model.model_id,
                      }))}
                    >Добавить профиль</Button>
                  )}
                  {profile && (
                    <Button
                      variant="ghost"
                      disabled={busy !== "" || !model.installed || model.installing}
                      onClick={() => void action(`test:${profile.id}`, () => testEmbeddingProfile(profile.id))}
                    ><RefreshCw size={14} /> Проверить</Button>
                  )}
                </div>
              </article>;
            })}
          </div>
          <div className="ai-setting-row">
            <div>
              <strong>LM Studio или внешний API</strong>
              <small>Переиспользует подключение и секрет из раздела «ИИ»; размерность проверяется настоящим /embeddings-вызовом.</small>
            </div>
            <div className="ai-group-actions">
              <Select
                ariaLabel="Провайдер embedding-модели"
                value={externalProvider}
                emptyOption="Нет подключений"
                options={(aiSettings?.providers ?? []).map((provider) => ({ value: provider.id, label: provider.label }))}
                onValueChange={(value) => { setExternalProvider(value); setExternalModel(null); }}
              />
              <Select
                ariaLabel="Embedding-модель API"
                value={externalModel}
                emptyOption="Выберите модель"
                options={externalModels.map((model) => ({ value: model.model_id, label: model.display_name }))}
                onValueChange={setExternalModel}
              />
              <Button
                variant="secondary"
                disabled={!externalProvider || !externalModel || busy !== ""}
                onClick={() => externalProvider && externalModel && void action(
                  `external:${externalModel}`,
                  () => createEmbeddingProfile({
                    label: `Embeddings · ${externalModel}`,
                    backend_kind: "openai_compatible",
                    provider_id: externalProvider,
                    model_id: externalModel,
                  }),
                )}
              >Добавить профиль</Button>
            </div>
          </div>
        </section>
      )}

      {subsection === "index" && (
        <section id="search-index" className="ai-settings-group is-first">
          <header className="ai-group-head">
            <div>
              <h2>Индекс</h2>
              <p>Новый индекс строится рядом с активным. Переключение происходит только после вашей проверки.</p>
            </div>
            <Button
              disabled={!settings.default_profile_id || busy !== ""}
              onClick={buildCandidate}
            ><Play size={14} /> Собрать кандидат</Button>
          </header>
          {!settings.default_profile_id && (
            <p className="retrieval-neutral-note">
              {settings.profiles.length === 0
                ? "Сначала скачайте модель и добавьте профиль на вкладке «Модели»."
                : "Выберите профиль ниже — после этого кнопка «Собрать кандидат» станет активной."}
            </p>
          )}
          <div className="ai-setting-row">
            <div><strong>Профиль для новой сборки</strong><small>Смена модели или chunking требует нового индекса.</small></div>
            <Select
              ariaLabel="Embedding-профиль"
              value={settings.default_profile_id}
              emptyOption="Не выбран"
              options={settings.profiles.map((profile) => ({ value: profile.id, label: profile.label, description: profile.dimension ? `${profile.dimension}d` : "не проверен" }))}
              onValueChange={(value) => void action("default", async () => {
                setSettings(await updateRetrievalSettings({
                  default_profile_id: value,
                  preset: settings.preset,
                  expert_parameters: settings.expert_parameters,
                }));
              })}
            />
          </div>
          <div className="retrieval-index-list">
            {indexes.map((index) => <article key={index.id}>
              <div>
                <span className="retrieval-index-head">
                  <strong>{index.state === "active" ? "Активный индекс" : "Кандидат"}</strong>
                  <StatusBadge tone={INDEX_STATUS[index.state].tone}>{INDEX_STATUS[index.state].label}</StatusBadge>
                </span>
                <small>
                  {index.material_count} {plural(index.material_count, "материал", "материала", "материалов")}
                  {" · "}{index.chunk_count} {plural(index.chunk_count, "кусок", "куска", "кусков")}
                  {" · "}{index.preset}
                </small>
                {index.error && <span className="retrieval-error">{index.error}</span>}
              </div>
              {index.state === "ready" && (
                <Button disabled={busy !== ""} onClick={() => void action(`activate:${index.id}`, () => activateRetrievalIndex(index.id))}>
                  Активировать
                </Button>
              )}
              {index.state !== "active" && (
                <Button variant="ghost" disabled={busy !== ""} onClick={() => void action(`delete-index:${index.id}`, () => deleteRetrievalIndex(index.id))}>
                  Удалить
                </Button>
              )}
            </article>)}
            {indexes.length === 0 && <p className="ai-muted">Индексов ещё нет. Выберите проверенный профиль и соберите первый кандидат.</p>}
          </div>
        </section>
      )}

      {subsection === "quality" && (
        <section id="search-quality" className="ai-settings-group is-first">
          <header className="ai-group-head">
            <div><h2>Качество</h2><p>Контрольные запросы сравнивают релевантность, задержку и zero-hit на одном корпусе.</p></div>
            <Button
              variant="secondary"
              disabled={!candidate || busy !== ""}
              onClick={() => candidate && void action(`benchmark:${candidate.id}`, () => runRetrievalBenchmark(candidate.id))}
            >Запустить на кандидате</Button>
          </header>
          <div className="retrieval-benchmark-list">
            {benchmarks.map((run) => <article key={run.id}>
              <strong>NDCG@10 {((run.metrics.ndcg_at_10 ?? 0) * 100).toFixed(1)}%</strong>
              <span>Recall@10 {((run.metrics.recall_at_10 ?? 0) * 100).toFixed(1)}%</span>
              <span>MRR@10 {((run.metrics.mrr_at_10 ?? 0) * 100).toFixed(1)}%</span>
              <span>p95 {Math.round(run.metrics.p95_ms ?? 0)} мс</span>
              <small>{run.case_count} контрольных запросов</small>
            </article>)}
            {benchmarks.length === 0 && <p className="ai-muted">Добавьте контрольные запросы через API — здесь появятся сравнимые запуски.</p>}
          </div>
        </section>
      )}

      {subsection === "advanced" && (
        <section id="search-advanced" className="ai-settings-group is-first">
          <header className="ai-group-head"><div><h2>Дополнительно</h2><p>Пресет применяется сразу. Модель и размеры кусков меняются только через новый индекс.</p></div></header>
          <div className="ai-setting-row">
            <div><strong>Профиль retrieval</strong><small>Количество кандидатов, финальных мест и reranker.</small></div>
            <SegmentedTabs
              label="Профиль retrieval"
              value={settings.preset}
              tabs={[
                { value: "fast", label: "Быстро" },
                { value: "balanced", label: "Сбалансированно" },
                { value: "accurate", label: "Точно" },
              ]}
              onChange={(value) => void action("preset", async () => setSettings(await updateRetrievalSettings({
                default_profile_id: settings.default_profile_id,
                preset: value as RetrievalPreset,
                expert_parameters: settings.expert_parameters,
              })))}
            />
          </div>
          <p className="retrieval-neutral-note">Chunking активного индекса: цель 384, максимум 480, overlap 64 токена. Для изменения нужна пересборка.</p>
        </section>
      )}
    </div>
  );
}
