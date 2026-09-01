import {
  Check,
  CircleAlert,
  Download,
  ExternalLink,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ParserMode } from "../api/materials";
import {
  cancelOcrModel,
  getOcrSettings,
  installOcrModel,
  removeOcrModel,
  updateOcrEngine,
  updateOcrSettings,
  type OcrEngineRead,
  type OcrEngineWrite,
  type OcrModelRead,
  type OcrReadiness,
  type OcrSettingsRead,
} from "../api/ocr";
import {
  Button,
  ErrorState,
  Field,
  LoadingState,
  Progress,
  SegmentedTabs,
  Select,
  StatusBadge,
} from "../components/ui";
import type { StatusTone } from "../components/ui";
import type { OcrSettingsSubsection } from "./Setup";

type NoteTone = "muted" | "success" | "danger";

interface Note {
  text: string;
  tone: NoteTone;
}

function errorText(caught: unknown, fallback: string): string {
  return caught instanceof Error ? caught.message : fallback;
}

function formatBytes(bytes: number): string {
  if (bytes <= 0) return "—";
  if (bytes >= 1_000_000_000) {
    return `${(bytes / 1_000_000_000).toFixed(1).replace(".", ",")} ГБ`;
  }
  return `${Math.round(bytes / 1_000_000)} МБ`;
}

function formatMb(megabytes: number | null): string {
  if (megabytes === null) return "неизвестно";
  if (megabytes >= 1000) return `${(megabytes / 1000).toFixed(1).replace(".", ",")} ГБ`;
  return `${megabytes} МБ`;
}

function StatusNote({ note }: { note: Note | null }) {
  if (!note?.text) return <span className="ai-save-state" role="status" aria-live="polite" />;
  return (
    <span className={`ai-save-state is-${note.tone}`} role="status" aria-live="polite">
      {note.tone === "success" && <Check size={15} aria-hidden="true" />}
      {note.tone === "danger" && <CircleAlert size={15} aria-hidden="true" />}
      {note.text}
    </span>
  );
}

/**
 * Состояние движка: короткое слово цветом и объяснение отдельной строкой.
 *
 * Раньше это была одна серая строка вида «Не готово · Локально · GPU ·
 * сервис не запущен». Слитно её никто не читал, а цвет — единственное, что
 * видно с расстояния.
 */
const READINESS: Record<OcrReadiness, { tone: StatusTone; label: string }> = {
  ready: { tone: "success", label: "Готов к работе" },
  downloading: { tone: "info", label: "Загружаются модели" },
  needs_models: { tone: "warning", label: "Нужны модели" },
  needs_service: { tone: "warning", label: "Сервис не запущен" },
  starting: { tone: "info", label: "Запускается" },
  error: { tone: "danger", label: "Ошибка" },
  unavailable: { tone: "neutral", label: "Пока не подключён" },
};

function StatusLine({
  tone,
  label,
  detail,
}: {
  tone: StatusTone;
  label: string;
  detail?: string;
}) {
  return (
    <div className={`ocr-status tone-${tone}`} role="status">
      <span className="ocr-status-dot" aria-hidden="true" />
      <div>
        <strong>{label}</strong>
        {detail ? <p>{detail}</p> : null}
      </div>
    </div>
  );
}

function EngineStatus({ engine }: { engine: OcrEngineRead }) {
  const { tone, label } = READINESS[engine.readiness];
  const detail = engine.status_detail || (engine.active_label ? `Работает: ${engine.active_label}.` : "");
  return <StatusLine tone={tone} label={label} detail={detail} />;
}

// ── Обзор ───────────────────────────────────────────────────────────────────

function OverviewPanel({
  settings,
  onSettings,
  navigate,
}: {
  settings: OcrSettingsRead;
  onSettings: (settings: OcrSettingsRead) => void;
  navigate: (subsection: OcrSettingsSubsection) => void;
}) {
  const [note, setNote] = useState<Note | null>(null);

  async function setDefaultMode(mode: ParserMode) {
    if (mode === settings.default_mode) return;
    setNote({ text: "Сохраняем…", tone: "muted" });
    try {
      const next = await updateOcrSettings({
        default_mode: mode,
        quality_threshold: settings.quality_threshold,
        raster_scale: settings.raster_scale,
      });
      onSettings(next);
      setNote({ text: "Сохранено", tone: "success" });
    } catch (caught) {
      setNote({ text: errorText(caught, "Не сохранено"), tone: "danger" });
    }
  }

  return (
    <div className="ai-panel-stack">
      <section className="ai-settings-group is-first">
        <header className="ai-group-head">
          <div>
            <h2>Распознавание</h2>
            <p>
              Tentex достаёт текст из ваших файлов сам, на этом компьютере и без
              интернета. Модели в поставку не входят: вы ставите только те, что
              вам нужны, и видите заранее, откуда они приедут и сколько займут.
            </p>
          </div>
        </header>
        <div className="ai-setting-row">
          <div>
            <strong>Режим по умолчанию</strong>
            <small>Какой режим будет выбран, когда вы добавите новый материал.</small>
          </div>
          <SegmentedTabs
            label="Режим по умолчанию"
            value={settings.default_mode}
            tabs={[{ value: "fast", label: "Быстро" }]}
            onChange={(value) => void setDefaultMode(value as ParserMode)}
          />
        </div>
        <StatusNote note={note} />
      </section>

      <section className="ai-settings-group">
        <header className="ai-group-head">
          <div>
            <h3>Режимы</h3>
            <p>Нажмите на любой, чтобы открыть его настройки.</p>
          </div>
        </header>
        <div className="ocr-engine-summary">
          {settings.engines.map((engine) => {
            const { tone, label } = READINESS[engine.readiness];
            return (
              <button key={engine.mode} type="button" onClick={() => navigate("engines")}>
                <span className="ocr-engine-summary-head">
                  <strong>{engine.title}</strong>
                  <StatusBadge tone={tone}>{label}</StatusBadge>
                </span>
                <small>{engine.description}</small>
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}

// ── Движки ──────────────────────────────────────────────────────────────────

const FAST_VERSIONS = [
  { value: "PP-OCRv5", label: "PP-OCRv5, новее и точнее" },
  { value: "PP-OCRv4", label: "PP-OCRv4, старее и легче" },
];
const CUSTOM_MODEL = "__custom__";

function engineWrite(engine: OcrEngineRead, patch: Partial<OcrEngineWrite>): OcrEngineWrite {
  return {
    model_id: engine.model_id,
    device: engine.device,
    language: engine.language,
    executor: engine.executor,
    extra: engine.extra,
    ...patch,
  };
}

/**
 * Поле «своя модель»: выпадающий список известных вариантов плюс возможность
 * вписать любой другой идентификатор. Своё значение сохраняется кнопкой —
 * иначе запрос уходил бы на каждую букву.
 */
function ModelPicker({
  label,
  hint,
  value,
  options,
  disabled,
  onSave,
}: {
  label: string;
  hint: string;
  value: string;
  options: { value: string; label: string }[];
  disabled: boolean;
  onSave: (next: string) => void;
}) {
  const known = options.some((option) => option.value === value);
  const [custom, setCustom] = useState(!known);
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    setDraft(value);
    setCustom(!options.some((option) => option.value === value));
  }, [options, value]);

  return (
    <Field label={label} hint={hint}>
      {custom ? (
        <div className="ocr-inline-field">
          <input
            type="text"
            value={draft}
            placeholder="Например, PP-OCRv5_server_rec"
            onChange={(event) => setDraft(event.target.value)}
          />
          <Button
            variant="secondary"
            disabled={disabled || !draft.trim() || draft === value}
            onClick={() => onSave(draft.trim())}
          >
            Применить
          </Button>
        </div>
      ) : (
        <Select
          ariaLabel={label}
          value={value}
          options={[...options, { value: CUSTOM_MODEL, label: "Указать свою…" }]}
          disabled={disabled}
          onValueChange={(next) => {
            if (!next) return;
            if (next === CUSTOM_MODEL) {
              setCustom(true);
              return;
            }
            onSave(next);
          }}
        />
      )}
    </Field>
  );
}

function FastEngineCard({
  engine,
  isFirst,
  onSettings,
}: {
  engine: OcrEngineRead;
  isFirst: boolean;
  onSettings: (settings: OcrSettingsRead) => void;
}) {
  const [note, setNote] = useState<Note | null>(null);
  const [pending, setPending] = useState(false);

  async function save(patch: Partial<OcrEngineWrite>) {
    setPending(true);
    setNote({ text: "Сохраняем…", tone: "muted" });
    try {
      onSettings(await updateOcrEngine("fast", engineWrite(engine, patch)));
      setNote({ text: "Сохранено", tone: "success" });
    } catch (caught) {
      setNote({ text: errorText(caught, "Не сохранено"), tone: "danger" });
    } finally {
      setPending(false);
    }
  }

  return (
    <section className={`ai-settings-group${isFirst ? " is-first" : ""}`} id="ocr-engine-fast">
      <header className="ai-group-head">
        <div>
          <h3>{engine.title}</h3>
          <p>{engine.description}</p>
        </div>
      </header>
      <p className="ai-muted">{engine.trade_off}</p>
      <EngineStatus engine={engine} />
      <div className="ai-form-grid compact">
        <ModelPicker
          label="Версия распознавателя"
          hint="Применится к следующему разбору"
          value={engine.model_id ?? "PP-OCRv5"}
          options={FAST_VERSIONS}
          disabled={pending}
          onSave={(next) => void save({ model_id: next })}
        />
      </div>
      <StatusNote note={note} />
    </section>
  );
}

function StaticEngineCard({ engine, isFirst }: { engine: OcrEngineRead; isFirst: boolean }) {
  return (
    <section className={`ai-settings-group${isFirst ? " is-first" : ""}`}>
      <header className="ai-group-head">
        <div>
          <h3>{engine.title}</h3>
          <p>{engine.description}</p>
        </div>
      </header>
      <p className="ai-muted">{engine.trade_off}</p>
      <EngineStatus engine={engine} />
    </section>
  );
}

function EnginesPanel({
  settings,
  onSettings,
}: {
  settings: OcrSettingsRead;
  onSettings: (settings: OcrSettingsRead) => void;
}) {
  return (
    <div className="ai-panel-stack">
      {settings.engines.map((engine, index) => {
        const isFirst = index === 0;
        if (engine.mode === "fast") {
          return (
            <FastEngineCard key={engine.mode} engine={engine} isFirst={isFirst} onSettings={onSettings} />
          );
        }
        return <StaticEngineCard key={engine.mode} engine={engine} isFirst={isFirst} />;
      })}
    </div>
  );
}

// ── Модели ──────────────────────────────────────────────────────────────────

function modelStatus(model: OcrModelRead): { tone: StatusTone; label: string } {
  if (model.job_state === "running" && model.job_cancel_requested) {
    return { tone: "warning", label: "Останавливается" };
  }
  if (model.job_state === "running") return { tone: "info", label: "Загружается" };
  if (model.installed) return { tone: "success", label: "Установлен" };
  if (model.job_state === "cancelled") return { tone: "neutral", label: "Загрузка остановлена" };
  if (model.job_state === "failed") return { tone: "danger", label: "Не установился" };
  return { tone: "neutral", label: "Не установлен" };
}

function fitsLine(model: OcrModelRead) {
  if (model.fits === true) return <StatusLine tone="success" label="Подойдёт" detail={model.fits_note} />;
  if (model.fits === false) return <StatusLine tone="danger" label="Не подойдёт" detail={model.fits_note} />;
  return <StatusLine tone="warning" label="Проверить не удалось" detail={model.fits_note} />;
}

function ModelCard({
  model,
  onSettings,
}: {
  model: OcrModelRead;
  onSettings: (settings: OcrSettingsRead) => void;
}) {
  const [note, setNote] = useState<Note | null>(null);
  const [busy, setBusy] = useState(false);
  const status = modelStatus(model);
  const downloading = model.job_state === "running";
  const stopping = downloading && model.job_cancel_requested;
  const canResume = model.job_state === "cancelled" || model.installed_bytes > 0;

  async function act(action: () => Promise<OcrSettingsRead>, failure: string) {
    setBusy(true);
    setNote(null);
    try {
      onSettings(await action());
    } catch (caught) {
      setNote({ text: errorText(caught, failure), tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="ocr-model">
      <header className="ocr-model-head">
        <div>
          <h4>
            {model.title}
            {model.recommended && <span className="ocr-model-mark">обычный выбор</span>}
          </h4>
          <p>{model.summary}</p>
        </div>
        <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
      </header>

      <p className="ai-muted">{model.good_for}</p>

      <dl className="ocr-facts">
        <div>
          <dt>Занимает</dt>
          <dd>{formatBytes(model.installed ? model.installed_bytes : model.size_bytes)}</dd>
        </div>
        <div>
          <dt>Считает на</dt>
          <dd>{model.device === "gpu" ? "видеокарте" : "процессоре"}</dd>
        </div>
        <div>
          <dt>Языки</dt>
          <dd>{model.languages}</dd>
        </div>
        <div>
          <dt>Видеопамяти нужно</dt>
          <dd>
            {model.min_vram_mb === null
              ? "не нужна"
              : model.recommended_vram_mb
                ? `от ${formatMb(model.min_vram_mb)}, лучше ${formatMb(model.recommended_vram_mb)}`
                : `от ${formatMb(model.min_vram_mb)}`}
          </dd>
        </div>
        <div>
          <dt>Оперативной памяти</dt>
          <dd>от {formatMb(model.min_ram_mb)}</dd>
        </div>
        <div>
          <dt>Лицензия</dt>
          <dd>
            <a href={model.license_url} target="_blank" rel="noreferrer">
              {model.license_title} <ExternalLink size={12} aria-hidden="true" />
            </a>
          </dd>
        </div>
      </dl>

      {fitsLine(model)}

      <div className="ocr-source">
        <span>
          Загрузится с сайта{" "}
          <a href={model.source_url} target="_blank" rel="noreferrer">
            {model.source_title} <ExternalLink size={12} aria-hidden="true" />
          </a>
        </span>
        <ul>
          {model.repos.map((repo) => (
            <li key={repo}>
              <a href={`https://huggingface.co/${repo}`} target="_blank" rel="noreferrer">
                {repo}
              </a>
            </li>
          ))}
        </ul>
      </div>

      {model.notes.map((item) => (
        <p key={item} className="ocr-model-note">
          <CircleAlert size={14} aria-hidden="true" />
          {item}
        </p>
      ))}

      {downloading && (
        <div className="ocr-progress">
          <Progress
            value={model.job_done_bytes}
            max={model.job_total_bytes || model.size_bytes}
            label={`Загрузка набора «${model.title}»`}
          />
          <small>
            {formatBytes(model.job_done_bytes)} из{" "}
            {formatBytes(model.job_total_bytes || model.size_bytes)}
            {model.job_current ? ` — ${model.job_current}` : ""}
          </small>
        </div>
      )}

      {model.job_state === "failed" && model.job_error ? (
        <StatusLine tone="danger" label="Загрузка не удалась" detail={model.job_error} />
      ) : null}

      <div className="ai-group-actions">
        {downloading ? (
          <Button
            variant="secondary"
            disabled={busy || stopping}
            onClick={() => void act(() => cancelOcrModel(model.key), "Не удалось остановить")}
          >
            {stopping ? "Останавливаем…" : "Остановить загрузку"}
          </Button>
        ) : model.installed ? (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => void act(() => removeOcrModel(model.key), "Не удалось удалить")}
          >
            <Trash2 size={14} aria-hidden="true" /> Удалить
          </Button>
        ) : (
          <Button
            disabled={busy}
            onClick={() => void act(() => installOcrModel(model.key), "Не удалось начать загрузку")}
          >
            <Download size={14} aria-hidden="true" /> {canResume ? "Продолжить загрузку" : "Установить"}
          </Button>
        )}
        <StatusNote note={note} />
      </div>
    </article>
  );
}

function ModelsPanel({
  settings,
  onSettings,
}: {
  settings: OcrSettingsRead;
  onSettings: (settings: OcrSettingsRead) => void;
}) {
  const groups = settings.engines.filter((engine) => engine.models.length > 0);
  return (
    <div className="ai-panel-stack">
      <section className="ai-settings-group is-first">
        <header className="ai-group-head">
          <div>
            <h2>Модели</h2>
            <p>
              Файлы моделей не входят в поставку Tentex и качаются отдельно. Всё
              приходит с Hugging Face, из репозиториев организации PaddlePaddle —
              тех же, что публикует авторов PaddleOCR. Ссылку на каждый репозиторий
              можно открыть и посмотреть, что именно вы ставите.
            </p>
          </div>
        </header>
        <p className="ai-muted">
          Загруженные модели лежат рядом с вашими данными, работают без интернета и
          удаляются отсюда же.
        </p>
      </section>
      {groups.map((engine, index) => (
        <section
          key={engine.mode}
          className={`ai-settings-group${index === 0 ? "" : ""}`}
          id={`ocr-models-${engine.mode}`}
        >
          <header className="ai-group-head">
            <div>
              <h3>Для режима «{engine.title}»</h3>
              <p>{engine.description}</p>
            </div>
          </header>
          <div className="ocr-model-list">
            {engine.models.map((model) => (
              <ModelCard key={model.key} model={model} onSettings={onSettings} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

// ── Качество ────────────────────────────────────────────────────────────────

const RASTER_SCALE_OPTIONS = [
  { value: "1.5", label: "Пониже, быстрее" },
  { value: "2", label: "Обычный" },
  { value: "3", label: "Повыше, медленнее" },
];

function QualityPanel({
  settings,
  onSettings,
}: {
  settings: OcrSettingsRead;
  onSettings: (settings: OcrSettingsRead) => void;
}) {
  const [threshold, setThreshold] = useState(String(Math.round(settings.quality_threshold * 100)));
  const [scale, setScale] = useState(String(settings.raster_scale));
  const [note, setNote] = useState<Note | null>(null);

  async function save() {
    const percent = Number(threshold);
    if (!Number.isFinite(percent) || percent < 0 || percent > 100) {
      setNote({ text: "Введите число от 0 до 100.", tone: "danger" });
      return;
    }
    setNote({ text: "Сохраняем…", tone: "muted" });
    try {
      const next = await updateOcrSettings({
        default_mode: settings.default_mode,
        quality_threshold: percent / 100,
        raster_scale: Number(scale),
      });
      onSettings(next);
      setNote({ text: "Сохранено", tone: "success" });
    } catch (caught) {
      setNote({ text: errorText(caught, "Не сохранено"), tone: "danger" });
    }
  }

  return (
    <section className="ai-settings-group is-first">
      <header className="ai-group-head">
        <div>
          <h2>Качество</h2>
          <p>
            Общие настройки для всех режимов. Применяются со следующего запуска
            разбора, уже разобранные материалы не меняются.
          </p>
        </div>
      </header>
      <div className="ai-form-grid">
        <Field
          label="Когда просить проверить страницу"
          hint="Если распознавание уверено меньше чем на столько процентов, страница попадёт в список «нужно проверить»"
        >
          <input
            type="number"
            min="0"
            max="100"
            step="5"
            value={threshold}
            onChange={(event) => setThreshold(event.target.value)}
          />
        </Field>
        <Field
          label="Подробность картинки страницы"
          hint="Чем подробнее, тем лучше читается мелкий шрифт и тем дольше идёт разбор"
        >
          <Select
            ariaLabel="Подробность картинки страницы"
            value={scale}
            options={RASTER_SCALE_OPTIONS}
            onValueChange={(value) => value && setScale(value)}
          />
        </Field>
      </div>
      <div className="ai-group-actions">
        <Button onClick={() => void save()}>Сохранить</Button>
        <StatusNote note={note} />
      </div>
    </section>
  );
}

// ── Экран ───────────────────────────────────────────────────────────────────

const OCR_SUBSECTION_IDS: OcrSettingsSubsection[] = ["overview", "engines", "models", "quality"];
// Пока что-то качается или сервис поднимается, состояние меняется само —
// перечитываем его, а не заставляем нажимать «обновить».
const POLL_MS = 1500;

function needsPolling(settings: OcrSettingsRead): boolean {
  return settings.engines.some(
    (engine) =>
      engine.readiness === "downloading" ||
      engine.readiness === "starting" ||
      engine.models.some((model) => model.job_state === "running")
  );
}

export function OcrSettingsSection({
  subsection,
  onActiveSubsection,
}: {
  subsection: OcrSettingsSubsection;
  onActiveSubsection: (subsection: OcrSettingsSubsection) => void;
}) {
  const [settings, setSettings] = useState<OcrSettingsRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const initialSubsection = useRef(subsection);
  const initialScrollDone = useRef(false);

  function navigate(next: OcrSettingsSubsection) {
    onActiveSubsection(next);
    window.requestAnimationFrame(() => {
      document.getElementById(`ocr-${next}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      setSettings(await getOcrSettings(undefined, { refresh: true }));
    } catch (caught) {
      setError(errorText(caught, "Параметры распознавания не загрузились"));
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    getOcrSettings(controller.signal)
      .then(setSettings)
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setError(errorText(caught, "Параметры распознавания не загрузились"));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!settings || !needsPolling(settings)) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      getOcrSettings(controller.signal)
        .then(setSettings)
        .catch(() => undefined);
    }, POLL_MS);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [settings]);

  useEffect(() => {
    if (!settings || initialScrollDone.current) return;
    initialScrollDone.current = true;
    if (initialSubsection.current === "overview") return;
    window.requestAnimationFrame(() => {
      document.getElementById(`ocr-${initialSubsection.current}`)?.scrollIntoView({ block: "start" });
    });
  }, [settings]);

  useEffect(() => {
    if (!settings) return;
    const sections = OCR_SUBSECTION_IDS
      .map((id) => document.getElementById(`ocr-${id}`))
      .filter((section): section is HTMLElement => section !== null);
    const observer = new IntersectionObserver(
      (entries) => {
        const active = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => left.boundingClientRect.top - right.boundingClientRect.top)[0];
        if (!active) return;
        onActiveSubsection(active.target.id.replace("ocr-", "") as OcrSettingsSubsection);
      },
      { rootMargin: "-12% 0px -72% 0px", threshold: 0 }
    );
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, [onActiveSubsection, settings]);

  if (loading) return <LoadingState label="Загружаем параметры распознавания" placement="page" />;
  if (error && !settings) {
    return (
      <>
        <ErrorState message={error} />
        <Button onClick={() => window.location.reload()}>Загрузить ещё раз</Button>
      </>
    );
  }
  if (!settings) return null;

  return (
    <div className="ai-settings">
      <div id="ocr-overview" className="ai-anchor-section">
        <OverviewPanel settings={settings} onSettings={setSettings} navigate={navigate} />
        <div className="ai-group-actions">
          <Button variant="ghost" disabled={refreshing} onClick={() => void refresh()}>
            <RefreshCw size={14} aria-hidden="true" /> Проверить ещё раз
          </Button>
        </div>
      </div>
      <div id="ocr-engines" className="ai-anchor-section">
        <EnginesPanel settings={settings} onSettings={setSettings} />
      </div>
      <div id="ocr-models" className="ai-anchor-section">
        <ModelsPanel settings={settings} onSettings={setSettings} />
      </div>
      <div id="ocr-quality" className="ai-anchor-section">
        <QualityPanel settings={settings} onSettings={setSettings} />
      </div>
    </div>
  );
}
