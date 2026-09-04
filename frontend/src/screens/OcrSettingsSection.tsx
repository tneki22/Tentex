import {
  Check,
  CircleAlert,
  Download,
  ExternalLink,
  RefreshCw,
  Search,
  Settings2,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import type { ParserMode } from "../api/materials";
import {
  cancelOcrModel,
  getOcrCloudModels,
  getOcrSettings,
  installOcrModel,
  removeOcrModel,
  updateOcrCloudSettings,
  updateOcrEngine,
  updateOcrSettings,
  type OcrCloudModelRead,
  type OcrCloudRead,
  type OcrCloudSettingsWrite,
  type OcrCloudStrategy,
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
  RadioCards,
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
            tabs={settings.engines.map((engine) => ({
              value: engine.mode,
              label: engine.title,
            }))}
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

/**
 * Стоимость страницы у моделей отличается в десятки раз, а в прайсе она
 * записана за миллион токенов — сравнивать так невозможно. Приводим к тысяче
 * страниц: столько же примерно в трёх учебниках.
 */
function formatPagePrice(value: string | null): string {
  if (value === null) return "цена неизвестна";
  const perThousand = Number(value) * 1000;
  if (!Number.isFinite(perThousand)) return "цена неизвестна";
  if (perThousand === 0) return "бесплатно";
  const digits = perThousand < 1 ? 2 : perThousand < 10 ? 1 : 0;
  return `≈ $${perThousand.toFixed(digits).replace(".", ",")} за 1000 страниц`;
}

/**
 * Список моделей, которыми можно распознавать страницы.
 *
 * Непригодные не прячутся: рядом с каждой написано, чем именно она не подошла,
 * иначе отбор выглядит произволом. Поиск нужен потому, что в каталоге
 * OpenRouter таких моделей больше двух сотен.
 */
function CloudModelPicker({
  models,
  selected,
  disabled,
  onSelect,
}: {
  models: OcrCloudModelRead[];
  selected: string | null;
  disabled: boolean;
  onSelect: (model: OcrCloudModelRead) => void;
}) {
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const shown = needle
    ? models.filter(
        (model) =>
          model.model_id.toLowerCase().includes(needle) ||
          model.display_name.toLowerCase().includes(needle) ||
          model.provider_label.toLowerCase().includes(needle)
      )
    : models;

  if (models.length === 0) {
    return (
      <p className="inspector-note">
        Ни одна добавленная модель не принимает изображения. Добавьте такую в
        разделе «Модели» — там же поиск по каталогу провайдера.
      </p>
    );
  }

  return (
    <div className="ocr-cloud-picker">
      <Field label="Модель распознавания" hint="Годные — сверху, у остальных написана причина">
        <div className="ocr-inline-field">
          <Search size={15} aria-hidden="true" />
          <input
            type="search"
            value={query}
            placeholder="Название или идентификатор"
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      </Field>
      <div className="ocr-cloud-models" role="listbox" aria-label="Модель распознавания">
        {shown.map((model) => (
          <button
            key={`${model.provider_id}:${model.model_id}`}
            type="button"
            role="option"
            aria-selected={model.model_id === selected}
            className={`ocr-cloud-model${model.model_id === selected ? " is-selected" : ""}${
              model.suitable ? "" : " is-refused"
            }`}
            disabled={disabled || !model.suitable}
            onClick={() => onSelect(model)}
          >
            <span className="ocr-cloud-model-head">
              <strong>{model.display_name}</strong>
              {model.suitable ? (
                <span className="ocr-cloud-price">{formatPagePrice(model.price_per_page_usd)}</span>
              ) : (
                <StatusBadge tone="neutral">{model.reason}</StatusBadge>
              )}
            </span>
            <small>
              {model.provider_label} · {model.model_id}
            </small>
            {model.recommended_note && <em>{model.recommended_note}</em>}
          </button>
        ))}
        {shown.length === 0 && <p className="ai-muted">По запросу ничего не нашлось.</p>}
      </div>
    </div>
  );
}

/**
 * Режим «Облако»: что уходит наружу, какой моделью читается и почём.
 *
 * Выбор модели сохраняется в настройках шлюза — там же ключи, лимиты и учёт
 * стоимости, — поэтому экран не заводит второе место для того же факта.
 */
function CloudEngineCard({
  engine,
  cloud,
  isFirst,
  onSettings,
}: {
  engine: OcrEngineRead;
  cloud: OcrCloudRead;
  isFirst: boolean;
  onSettings: (settings: OcrSettingsRead) => void;
}) {
  const [models, setModels] = useState<OcrCloudModelRead[] | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getOcrCloudModels(controller.signal)
      .then(setModels)
      .catch(() => {
        if (!controller.signal.aborted) setModels([]);
      });
    return () => controller.abort();
  }, [cloud.model_id]);

  async function save(patch: Partial<OcrCloudSettingsWrite>) {
    setPending(true);
    setNote({ text: "Сохраняем…", tone: "muted" });
    try {
      onSettings(
        await updateOcrCloudSettings({
          provider_id: cloud.provider_id,
          model_id: cloud.model_id,
          strategy: cloud.strategy,
          ...patch,
        })
      );
      setNote({ text: "Сохранено", tone: "success" });
    } catch (caught) {
      setNote({ text: errorText(caught, "Не сохранено"), tone: "danger" });
    } finally {
      setPending(false);
    }
  }

  return (
    <section className={`ai-settings-group${isFirst ? " is-first" : ""}`} id="ocr-engine-cloud">
      <header className="ai-group-head">
        <div>
          <h3>{engine.title}</h3>
          <p>{engine.description}</p>
        </div>
      </header>
      <p className="ai-muted">{engine.trade_off}</p>
      <EngineStatus engine={engine} />

      {!cloud.external_models_enabled ? (
        <p className="inspector-note">
          <Link to="/setup?section=ai">
            <Settings2 size={14} aria-hidden="true" /> Открыть параметры моделей
          </Link>
        </p>
      ) : (
        <>
          <RadioCards
            className="ocr-cloud-strategies"
            label="Что отправлять наружу"
            layout="rows"
            value={cloud.strategy}
            options={cloud.strategies.map((item) => ({
              value: item.value,
              title: item.title,
              description: item.hint,
            }))}
            onChange={(next) => void save({ strategy: next as OcrCloudStrategy })}
          />
          <CloudModelPicker
            models={models ?? []}
            selected={cloud.model_id}
            disabled={pending}
            onSelect={(model) =>
              void save({ provider_id: model.provider_id, model_id: model.model_id })
            }
          />
          {cloud.model_id && (
            <dl className="ocr-facts">
              <div>
                <dt>Провайдер</dt>
                <dd>{cloud.provider_label || "не указан"}</dd>
              </div>
              <div>
                <dt>Стоимость разбора</dt>
                <dd>{formatPagePrice(cloud.price_per_page_usd)}</dd>
              </div>
            </dl>
          )}
          <p className="inspector-warning" role="note">
            Страницы и вырезы уходят на сервер провайдера. Учебник с чужими данными или
            закрытую методичку туда отправлять не стоит.
          </p>
        </>
      )}
      <StatusNote note={note} />
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
        if (engine.mode === "cloud") {
          return (
            <CloudEngineCard
              key={engine.mode}
              engine={engine}
              cloud={settings.cloud}
              isFirst={isFirst}
              onSettings={onSettings}
            />
          );
        }
        return (
          <FastEngineCard key={engine.mode} engine={engine} isFirst={isFirst} onSettings={onSettings} />
        );
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

// Значение — не зум, а требуемое разрешение картинки страницы: 150 точек на
// дюйм за единицу. Ниже 300 мелкий шрифт и индексы в формулах теряются.
const RASTER_SCALE_OPTIONS = [
  { value: "1.5", label: "225 точек на дюйм — быстрее" },
  { value: "2", label: "300 точек на дюйм — обычный" },
  { value: "3", label: "450 точек на дюйм — мелкий шрифт" },
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
