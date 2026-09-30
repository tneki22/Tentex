import { Check, Cpu, Database, Download, Gauge, Pause, Play, RefreshCw, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { getAiSettings, type AiSettingsRead } from "../api/ai";
import { ProjectApiError } from "../api/projects";
import {
  activateRetrievalIndex,
  buildRetrievalIndex,
  createEmbeddingProfile,
  deleteLocalEmbeddingModel,
  deleteRetrievalIndex,
  getRetrievalSettings,
  pauseRetrievalIndexBuild,
  resumeRetrievalIndexBuild,
  installLocalEmbeddingModel,
  listLocalEmbeddingModels,
  listRetrievalIndexes,
  testEmbeddingProfile,
  updateRetrievalSettings,
  type LocalModelRead,
  type ModelSupport,
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
import { ACTIVE_JOB_STATES, cancelBackgroundJob, listBackgroundJobs } from "../api/backgroundJobs";

const INDEX_STATUS: Record<RetrievalIndexRead["state"], { label: string; tone: "info" | "success" | "neutral" | "danger" }> = {
  building: { label: "Собирается", tone: "info" },
  ready: { label: "Готов к активации", tone: "neutral" },
  active: { label: "Активен", tone: "success" },
  failed: { label: "Ошибка", tone: "danger" },
};

/** Честная подпись к модели: с какими моделями поиск по смыслу проверен, а с какими — нет. */
const MODEL_SUPPORT: Record<ModelSupport, { label: string; hint: string; tone: "success" | "info" | "warning" } | null> = {
  verified: {
    label: "Проверена в Tentex",
    hint: "Прогнана на контрольных запросах по Библиотеке с текущей нарезкой",
    tone: "success",
  },
  recipe: {
    label: "Настройки подготовлены",
    hint: "Tentex подставляет нужные настройки запроса и текста. Качество поиска по учебным материалам ещё не проверено",
    tone: "info",
  },
  short_window: {
    label: "Для коротких текстов",
    hint: "Модель рассчитана на короткие тексты. Качество поиска по длинным отрывкам в Tentex не проверено",
    tone: "warning",
  },
  unknown: {
    label: "Настройки неизвестны",
    hint: "Для этой модели не заданы специальные настройки запроса и текста. Получение вектора не гарантирует хорошего поиска",
    tone: "warning",
  },
  not_embedding: null,
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
  const [aiSettings, setAiSettings] = useState<AiSettingsRead | null>(null);
  const [externalProvider, setExternalProvider] = useState<string | null>(null);
  const [externalModel, setExternalModel] = useState<string | null>(null);
  const [manualModelId, setManualModelId] = useState("");
  const [manualModelLabel, setManualModelLabel] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [watchedJobId, setWatchedJobId] = useState<string | null>(null);
  const [testingProfileId, setTestingProfileId] = useState<string | null>(null);
  const [testFeedback, setTestFeedback] = useState<{ tone: "success" | "danger"; text: string } | null>(null);
  const watchedJob = useBackgroundJob(watchedJobId);
  const initialSubsection = useRef(subsection);
  const initialScrollDone = useRef(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const [nextSettings, nextIndexes, nextModels, nextAiSettings] = await Promise.all([
        getRetrievalSettings(signal),
        listRetrievalIndexes(),
        listLocalEmbeddingModels(),
        getAiSettings(signal).catch(() => null),
      ]);
      setSettings(nextSettings);
      setIndexes(nextIndexes);
      setModels(nextModels);
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
    let active = true;
    const restoreIndexJob = () => void listBackgroundJobs({ activeOnly: true }).then((jobs) => {
      const job = jobs.find((item) => item.kind === "retrieval_index");
      if (active && job) setWatchedJobId(job.id);
    }).catch(() => undefined);
    restoreIndexJob();
    const timer = window.setInterval(restoreIndexJob, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    onActiveSubsection(subsection);
  }, [onActiveSubsection, subsection]);

  useEffect(() => {
    if (!settings || initialScrollDone.current || initialSubsection.current === "overview") return;
    initialScrollDone.current = true;
    window.requestAnimationFrame(() => {
      document.getElementById(`search-${initialSubsection.current}`)?.scrollIntoView({ block: "start" });
    });
  }, [settings]);

  useEffect(() => {
    if (!settings) return;
    const sections = ["overview", "models", "index", "advanced"]
      .map((id) => document.getElementById(`search-${id}`))
      .filter((section): section is HTMLElement => section !== null);
    const observer = new IntersectionObserver((entries) => {
      const active = entries
        .filter((entry) => entry.isIntersecting)
        .sort((left, right) => left.boundingClientRect.top - right.boundingClientRect.top)[0];
      if (active) onActiveSubsection(active.target.id.replace("search-", ""));
    }, { rootMargin: "-12% 0px -72% 0px", threshold: 0 });
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, [onActiveSubsection, settings]);

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

  async function testProfile(profileId: string) {
    setTestingProfileId(profileId);
    setTestFeedback(null);
    setError("");
    try {
      const profile = await testEmbeddingProfile(profileId);
      setTestFeedback({
        tone: "success",
        text: `Модель вернула вектор: ${profile.dimension ?? "?"} измерений. Можно собирать индекс; качество поиска эта проверка не оценивает.`,
      });
      await load();
    } catch (caught) {
      setTestFeedback({ tone: "danger", text: errorText(caught) });
    } finally {
      setTestingProfileId(null);
    }
  }

  async function addManualModel() {
    const modelId = manualModelId.trim();
    if (!modelId || !modelId.includes("/")) {
      setError("Укажите идентификатор Hugging Face в формате owner/model");
      return;
    }
    setBusy("manual-model");
    setError("");
    try {
      const profile = await createEmbeddingProfile({
        label: manualModelLabel.trim() || modelId,
        backend_kind: "local_hf",
        model_id: modelId,
      });
      const started = await installLocalEmbeddingModel(modelId);
      setWatchedJobId(started.job_id);
      setManualModelId("");
      setManualModelLabel("");
      setTestFeedback({ tone: "success", text: `Модель «${profile.label}» добавлена и поставлена на скачивание.` });
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
  const rerankerInstalled = models.some((model) => model.role === "reranker" && model.installed);
  const externalModels = aiSettings?.models.filter(
    (model) => model.provider_id === externalProvider && model.is_available,
  ) ?? [];
  const embeddingModels = externalModels.filter((model) => (
    model.supported_parameters.some((parameter) => /embed/i.test(parameter))
      || model.input_modalities.some((modality) => /embed/i.test(modality))
      || /embed/i.test(`${model.model_id} ${model.display_name}`)
  ) && !/rerank|cross.?encoder|chat|instruct|completion/i.test(`${model.model_id} ${model.display_name}`));
  // OpenAI-compatible каталоги (в том числе LM Studio) иногда не отдают capability-поля.
  // В этом случае оставляем только модели с явным признаком embedding: reranker/LLM
  // нельзя предлагать в профиле, который вызывает /embeddings.
  const externalEmbeddingModels = embeddingModels;
  const watchedJobActive = watchedJob.job !== null && ACTIVE_JOB_STATES.has(watchedJob.job.state);
  const watchedIncrementalIndex = watchedJob.job?.kind === "retrieval_index"
    && watchedJob.job.material_id !== null;

  async function addExternalProfile() {
    if (!externalProvider || !externalModel) return;
    setBusy(`external:${externalModel}`);
    setError("");
    setTestFeedback(null);
    try {
      const profile = await createEmbeddingProfile({
        label: `Embeddings · ${externalModel}`,
        backend_kind: "openai_compatible",
        provider_id: externalProvider,
        model_id: externalModel,
      });
      try {
        const tested = await testEmbeddingProfile(profile.id);
        setTestFeedback({
          tone: "success",
          text: `Профиль «${profile.label}» добавлен и отвечает: ${tested.dimension ?? "?"} измерений.`,
        });
      } catch (caught) {
        setTestFeedback({
          tone: "danger",
          text: `Профиль «${profile.label}» добавлен, но проверка провайдера не прошла: ${errorText(caught)}`,
        });
      }
      await load();
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy("");
    }
  }

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
        <ErrorState message={watchedJob.job.kind === "retrieval_index"
          ? `Сборка индекса остановилась после ${watchedJob.job.done} из ${watchedJob.job.total} материалов: ${watchedJob.job.error ?? "причина не указана"}`
          : `Модель не скачалась: ${watchedJob.job.error ?? "причина не указана"}`} />
      )}

      <div id="search-overview" className="ai-anchor-section">
        <section className="ai-settings-group is-first">
          <header className="ai-group-head">
            <div>
              <h2>Поиск по содержимому</h2>
              <p>Один retrieval-контур для чата, экзамена, Учебника и свободного изучения.</p>
            </div>
            <StatusBadge tone={settings.degraded ? "neutral" : "success"}>
              {settings.degraded ? "Частично готов" : "Готов"}
            </StatusBadge>
          </header>
          {watchedJob.job?.kind === "retrieval_index" && watchedJobActive && (
            <div className="retrieval-download-progress" role="status">
              <strong>{watchedIncrementalIndex
                ? watchedJob.job.pause_requested ? "Отменяем обновление индекса…" : `Обновляем индекс · ${watchedJob.job.subject}`
                : watchedJob.job.state === "paused" ? "Сбор индекса на паузе" : watchedJob.job.control_action === "finish" ? "Завершаем сбор индекса…" : watchedJob.job.control_action === "pause" ? "Ставим сбор на паузу…" : "Собираем индекс для поиска по содержимому"}</strong>
              <span>{watchedJob.job.done} из {watchedJob.job.total || "?"} материалов</span>
              <div className="retrieval-progress-track"><span style={{ width: watchedJob.job.total ? `${Math.round((watchedJob.job.done / watchedJob.job.total) * 100)}%` : "0%" }} /></div>
              <div className="lib-content-source-actions">
                {!watchedIncrementalIndex && watchedJob.job.state === "running" && <Button variant="ghost" onClick={() => void pauseRetrievalIndexBuild(watchedJob.job!.id).catch((caught) => setError(errorText(caught)))}><Pause size={14} /> Пауза</Button>}
                {!watchedIncrementalIndex && watchedJob.job.state === "paused" && <Button variant="ghost" onClick={() => void resumeRetrievalIndexBuild(watchedJob.job!.id).catch((caught) => setError(errorText(caught)))}><Play size={14} /> Продолжить</Button>}
                <Button variant="ghost" disabled={watchedJob.job.pause_requested} onClick={() => void cancelBackgroundJob(watchedJob.job!.id).catch((caught) => setError(errorText(caught)))}><X size={14} /> {watchedIncrementalIndex ? "Отменить" : "Завершить сейчас"}</Button>
              </div>
            </div>
          )}
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
      </div>

      <div id="search-models" className="ai-anchor-section">
        <section className="ai-settings-group is-first">
          <header className="ai-group-head">
            <div>
              <h2>Модели</h2>
              <p>Локальные модели скачиваются с Hugging Face. Произвольный код репозитория не запускается.</p>
              <p>Рекомендуем модели из этого списка; стандартный выбор — Multilingual E5 Base, проверенная в Tentex.</p>
            </div>
          </header>
          <div className="retrieval-model-list">
            {models.map((model) => {
              const profile = settings.profiles.find((item) => item.model_id === model.model_id);
              const support = MODEL_SUPPORT[model.support];
              return <article key={model.model_id}>
                <div>
                  <span className="retrieval-model-title">
                    <strong>{model.label}</strong>
                    {support && <span title={support.hint}><StatusBadge tone={support.tone}>{support.label}</StatusBadge></span>}
                  </span>
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
                      disabled={busy !== "" || testingProfileId !== null || !model.installed || model.installing}
                      onClick={() => void testProfile(profile.id)}
                    >{testingProfileId === profile.id ? <RefreshCw className="is-spinning" size={14} /> : <RefreshCw size={14} />} {testingProfileId === profile.id ? "Проверяем…" : "Проверить"}</Button>
                  )}
                </div>
              </article>;
            })}
          </div>
          {watchedJob.job?.kind === "retrieval_model_install" && watchedJobActive && (
            <div className="retrieval-download-progress" role="status">
              <strong>{watchedJob.job.subject || "Embedding-модель"}</strong>
              <span>{watchedJob.job.done} из {watchedJob.job.total || "?"} файлов</span>
              <div className="retrieval-progress-track"><span style={{ width: watchedJob.job.total ? `${Math.round((watchedJob.job.done / watchedJob.job.total) * 100)}%` : "35%" }} /></div>
            </div>
          )}
          <div className="retrieval-manual-model">
            <div><strong>Добавить модель вручную</strong><small>Текстовая embedding-модель для Transformers, без кода из репозитория. Совместимость и качество поиска нужно проверять.</small></div>
            <input value={manualModelId} onChange={(event) => setManualModelId(event.target.value)} placeholder="owner/model" aria-label="Идентификатор embedding-модели" />
            <input value={manualModelLabel} onChange={(event) => setManualModelLabel(event.target.value)} placeholder="Название (необязательно)" aria-label="Название embedding-модели" />
            <Button variant="secondary" disabled={busy !== "" || !manualModelId.trim()} onClick={() => void addManualModel()}><Download size={14} /> Добавить модель</Button>
          </div>
          <div className="ai-setting-row">
            <div>
              <strong>LM Studio или внешний API</strong>
              <small>Подключение из раздела «ИИ». Нужна embedding-модель с OpenAI-совместимым API. «Проверить» проверяет получение вектора, а не качество поиска. При внешнем API текст отправляется провайдеру.</small>
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
                options={externalEmbeddingModels.map((model) => ({ value: model.model_id, label: model.display_name }))}
                onValueChange={setExternalModel}
              />
              <Button
                variant="secondary"
                disabled={!externalProvider || !externalModel || busy !== ""}
                onClick={() => void addExternalProfile()}
              >Добавить профиль</Button>
            </div>
          </div>
          {testFeedback && <p className={`retrieval-test-feedback is-${testFeedback.tone}`} role="status">{testFeedback.text}</p>}
        </section>
      </div>

      <div id="search-index" className="ai-anchor-section">
        <section className="ai-settings-group is-first">
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
              options={settings.profiles.map((profile) => ({
                value: profile.id,
                label: profile.label,
                description: [
                  profile.dimension ? `${profile.dimension}d` : "не проверен",
                  MODEL_SUPPORT[profile.support]?.label.toLowerCase(),
                ].filter(Boolean).join(" · "),
              }))}
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
                  <strong>{index.state === "active" ? "Активный индекс" : "Кандидат"} · {settings.profiles.find((profile) => profile.id === index.profile_id)?.label ?? "модель не найдена"}</strong>
                  <StatusBadge tone={INDEX_STATUS[index.state].tone}>{INDEX_STATUS[index.state].label}</StatusBadge>
                </span>
                <small>
                  {index.material_count} {plural(index.material_count, "материал", "материала", "материалов")}
                  {index.indexed_material_count < index.material_count && ` · проиндексировано ${index.indexed_material_count} из ${index.material_count}`}
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
          {watchedJob.job?.kind === "retrieval_index" && watchedJobActive && (
            <div className="retrieval-download-progress" role="status">
              <strong>{watchedJob.job.subject || "Сбор индекса"}</strong>
              <span>{watchedJob.job.done} из {watchedJob.job.total || "?"} материалов</span>
              <div className="retrieval-progress-track"><span style={{ width: watchedJob.job.total ? `${Math.round((watchedJob.job.done / watchedJob.job.total) * 100)}%` : "35%" }} /></div>
            </div>
          )}
        </section>
      </div>

      <div id="search-advanced" className="ai-anchor-section">
        <section className="ai-settings-group is-first">
          <header className="ai-group-head"><div><h2>Дополнительно</h2><p>Пресет применяется сразу. Модель и размеры кусков меняются только через новый индекс.</p></div></header>
          <div className="ai-setting-row">
            <div><strong>Профиль retrieval</strong><small>Количество кандидатов, финальных мест и reranker.</small></div>
            <SegmentedTabs
              label="Профиль retrieval"
              value={settings.preset}
              tabs={[
                { value: "fast", label: "Быстро" },
                { value: "balanced", label: "Сбалансированно" },
                {
                  value: "accurate",
                  label: "Точно",
                  disabled: !rerankerInstalled && settings.preset !== "accurate",
                  tooltip: !rerankerInstalled ? "Нужна установленная модель reranker: скачайте её на вкладке «Модели»" : undefined,
                },
              ]}
              onChange={(value) => void action("preset", async () => setSettings(await updateRetrievalSettings({
                default_profile_id: settings.default_profile_id,
                preset: value as RetrievalPreset,
                expert_parameters: settings.expert_parameters,
              })))}
            />
          </div>
          <p className="retrieval-neutral-note">{({
            fast: "Быстро: минимум кандидатов и без reranker — подходит для коротких запросов и слабого компьютера.",
            balanced: "Сбалансированно: равный вклад поиска по словам и смыслу, обычно лучший повседневный режим.",
            accurate: "Точно: локальный Qwen3 Reranker перечитывает 10 лучших мест вместе с вопросом, ставит выше отвечающие и отказывает, если ответа нет ни в одном. Нужна установленная модель reranker (вкладка «Модели»); на процессоре это ≈ 15–20 с на запрос.",
          } as Record<RetrievalPreset, string>)[settings.preset]}</p>
          {settings.active_index && (
            <p className="retrieval-neutral-note">Нарезка активного индекса: цель {settings.active_index.chunk_target_tokens}, максимум {settings.active_index.chunk_max_tokens}, перекрытие {settings.active_index.chunk_overlap_tokens} токенов. Для изменения нужна пересборка.</p>
          )}
        </section>
      </div>
    </div>
  );
}
