import { Pencil, Play, RotateCcw, Settings2, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import type {
  LibraryMaterialDetailRead,
  MaterialPageRead,
  ParserMode,
  ProcessingScope,
} from "../../api/materials";
import {
  getOcrSettings,
  updateOcrCloudSettings,
  type OcrCloudStrategy,
  type OcrSettingsRead,
} from "../../api/ocr";
import { getMaterialPresentation } from "../../components/domain/material-viewer";
import { TaskRow } from "../../components/domain";
import type { BackgroundTask } from "../../components/domain";
import {
  Button,
  Disclosure,
  ErrorState,
  Field,
  RadioCards,
} from "../../components/ui";

const STAGE_LABEL: Record<string, string> = {
  queued: "Ждём очереди",
  extract: "Разбираем страницы",
  segment: "Собираем блоки и фрагменты",
  complete: "Готово",
};

// Сколько секунд уходит на страницу. Измерено прогоном `tentex-ocr-bench` на
// 24 страницах: «Быстро» — 334–414 с, «Облако» — около 440 с. Оценка нужна,
// чтобы решить «ставить сейчас или на ночь», поэтому округлена вверх и не
// претендует на точность.
const SECONDS_PER_PAGE: Record<ParserMode, number> = { fast: 16, cloud: 19 };

/** Человеческие названия для диагностики страницы. */
const DIAGNOSTIC_LABEL: Record<string, string> = {
  formula_possible: "Возможны формулы — сверяйте с оригиналом",
  audio_transcription_required: "Нужна локальная расшифровка аудио",
  manual_correction: "Есть страницы, исправленные вручную",
  source_refreshed: "Снимок источника обновлялся",
  layout_fallback: "Разметка восстановлена упрощённо: колонки могли перепутаться",
  unbalanced_display_math: "У выносных формул не сошлись знаки $$ — часть могла не отрисоваться",
  unbalanced_inline_math: "У формул в тексте не сошлись знаки $",
  unbalanced_braces: "В формулах не сошлись фигурные скобки",
  unbalanced_environment: "В формулах не закрыто окружение LaTeX",
};

/** Счётчики страницы (`tables:3`) — здесь они про весь материал, и число
 *  теряет смысл: у материала это набор отметок со всех страниц сразу, где
 *  «формул: 3», «формул: 6» и «формул: 7» — три разные страницы, а не сумма.
 *  Поэтому остаётся сам факт. */
const DIAGNOSTIC_PRESENCE: Record<string, string> = {
  tables: "Есть распознанные таблицы",
  formulas: "Есть распознанные формулы",
  cloud_regions: "Часть страниц уходила во внешнюю модель вырезами",
  cloud_crops: "Картинки и формулы сохранены вырезками со страницы",
  bbox_missing: "Модель указала координаты не у всех элементов",
};

// Отметки для отладки конвейера, а не для человека: разрешение растра, число
// элементов, факт применения разметчика. Их место в логе.
const TECHNICAL_DIAGNOSTICS = new Set(["render_dpi", "structure_elements", "layout_markdown"]);

/** Строка диагностики по-русски или `null`, если её показывать не нужно. */
function diagnosticText(item: string): string | null {
  const [key, value] = item.split(":", 2);
  if (TECHNICAL_DIAGNOSTICS.has(key)) return null;
  if (value !== undefined && key in DIAGNOSTIC_PRESENCE) {
    // Ноль — это не факт, а его отсутствие: строку такое не заслуживает.
    return value === "0" ? null : DIAGNOSTIC_PRESENCE[key];
  }
  return DIAGNOSTIC_LABEL[item] ?? item;
}

/** «12 страниц» → «≈ 4 мин». Меньше минуты писать бессмысленно. */
function durationLabel(pages: number, mode: ParserMode): string {
  const minutes = Math.ceil((pages * SECONDS_PER_PAGE[mode]) / 60);
  if (minutes < 60) return `≈ ${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  return `≈ ${hours} ч ${minutes % 60} мин`;
}

/** Доллары ценой в тысячные доли: `0.0042` бесполезно, `0,004` — читаемо. */
function priceLabel(usd: number): string {
  if (usd >= 1) return `${usd.toFixed(2)} $`;
  if (usd >= 0.01) return `${usd.toFixed(3)} $`;
  return "меньше цента";
}

function projectCountLabel(count: number): string {
  const mod100 = count % 100;
  const mod10 = count % 10;
  if (mod100 >= 11 && mod100 <= 14) return `${count} проектах`;
  if (mod10 === 1) return `${count} проекте`;
  return `${count} проектах`;
}

interface LibraryProcessingPanelProps {
  material: LibraryMaterialDetailRead;
  page: MaterialPageRead | null;
  busy: boolean;
  readOnly: boolean;
  onStart: (command: {
    parser_mode: ParserMode;
    scope: ProcessingScope;
    page_from?: number;
    page_to?: number;
  }) => void;
  onControl: (action: "pause" | "resume" | "retry" | "cancel") => void;
  onEditPage: () => void;
  onCleanupPage: () => void;
  onConfirmPageReview: () => void;
}

export function LibraryProcessingPanel({
  material,
  page,
  busy,
  readOnly,
  onStart,
  onControl,
  onEditPage,
  onCleanupPage,
  onConfirmPageReview,
}: LibraryProcessingPanelProps) {
  const presentation = getMaterialPresentation(material.presentation_kind);
  // Режим не выбран, пока не пришли настройки: там лежит и список движков, и
  // выбранный пользователем режим по умолчанию (Параметры → Распознавание).
  const [mode, setMode] = useState<ParserMode | null>(null);
  const [ocr, setOcr] = useState<OcrSettingsRead | null>(null);
  const [scope, setScope] = useState<ProcessingScope>("all");
  const [range, setRange] = useState({ from: 1, to: material.page_count ?? 1 });

  const task = material.task;
  const running = task && (task.state === "running" || task.state === "queued" || task.state === "paused");
  const prepared = material.active_parse_revision > 0;
  const showOcrReview = material.parser_mode !== "fast";
  const reviewPages = showOcrReview ? material.ocr_low_page_count : 0;
  const processingScope = scope === "needs_review" && !showOcrReview ? "all" : scope;
  const pageCount = material.page_count ?? 1;
  const canScope = material.capabilities.can_run_ocr && prepared && pageCount > 1;
  const currentPageState = page
    ? material.page_states.find((item) => item.page_number === page.page_number)
    : null;
  const currentNeedsReview = showOcrReview && page?.quality === "ocr_low"
    && currentPageState?.reviewed_at === null;

  useEffect(() => {
    const controller = new AbortController();
    void getOcrSettings(controller.signal)
      .then((settings) => {
        setOcr(settings);
        // Режим по умолчанию задан один раз в Параметрах — здесь его только
        // подставляем, и только пока пользователь не выбрал другой руками.
        setMode((current) => current ?? settings.default_mode);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setMode((current) => current ?? "fast");
      });
    return () => controller.abort();
  }, [material.id, material.task?.updated_at]);

  const ocrModes = ocr?.engines ?? [];
  const selectedMode = ocrModes.find((item) => item.mode === mode);
  const modeUnavailable = Boolean(mode) && ocrModes.length > 0 && !selectedMode?.available;
  const cloud = ocr?.cloud ?? null;

  /** Стратегия — общая настройка режима «Облако», а не поле этого запуска:
   *  сохраняем сразу, чтобы выбор здесь и в Параметрах не разъезжался. */
  function chooseStrategy(next: OcrCloudStrategy) {
    if (!cloud || cloud.strategy === next) return;
    setOcr({ ...ocr!, cloud: { ...cloud, strategy: next } });
    void updateOcrCloudSettings({
      provider_id: cloud.provider_id,
      model_id: cloud.model_id,
      strategy: next,
    })
      .then(setOcr)
      .catch(() => undefined);
  }

  // Сколько страниц уйдёт в работу при выбранной области запуска — от этого
  // считаются и время, и деньги.
  const plannedPages = processingScope === "range"
    ? Math.max(0, range.to - range.from + 1)
    : processingScope === "needs_review"
      ? reviewPages
      : pageCount;
  const pagePrice = cloud?.price_per_page_usd ? Number(cloud.price_per_page_usd) : null;

  const backgroundTask: BackgroundTask | null = useMemo(() => {
    if (!task || task.state === "completed") return null;
    const left = Math.max(0, task.total - task.done);
    const perPage = SECONDS_PER_PAGE[task.parser_mode];
    return {
      id: task.id,
      kind: "parse",
      subject: material.original_name,
      unit: "страниц",
      done: task.done,
      total: task.total,
      etaMinutes: left > 0 ? Math.ceil((left * perPage) / 60) : null,
      state: task.state,
      error: task.error ?? undefined,
    };
  }, [task, material.original_name]);

  // Технические отметки конвейера человеку не нужны: список чистится, а не
  // печатается как есть. Пустой после чистки — раздела нет вовсе.
  const diagnostics = useMemo(
    () => [...new Set(
      material.diagnostics
        .map(diagnosticText)
        .filter((item): item is string => item !== null),
    )],
    [material.diagnostics],
  );

  const rangeInvalid = scope === "range"
    && (range.from < 1 || range.to > pageCount || range.from > range.to);

  return (
    <div className="inspector-content">
      <header className="inspector-section-head">
        <h3>{presentation.processingTitle}</h3>
      </header>

      {material.parser_mode === "fast" && prepared && (
        <p className="inspector-note">
          «Быстро» распознаёт обычный текст. Формулы он не читает — сохраняет вырезом,
          чтобы они не потерялись; сверяйтесь с изображением.
        </p>
      )}

      {reviewPages > 0 && (
        <p className="inspector-warning" role="status">
          {reviewPages === 1
            ? "На одной странице распознавание могло ошибиться."
            : `На ${reviewPages} страницах распознавание могло ошибиться.`}
          {" "}Откройте их рядом с оригиналом.
        </p>
      )}

      {currentNeedsReview && !readOnly && (
        <div className="inspector-page-review" role="status">
          <p>
            Страница {page.page_number} требует сверки с оригиналом.
            {page.confidence !== null
              ? ` Уверенность распознавания — ${Math.round(page.confidence * 100)}%.`
              : ""}
          </p>
          <Button variant="secondary" disabled={busy} onClick={onConfirmPageReview}>
            Подтвердить текст
          </Button>
        </div>
      )}

      {backgroundTask && (
        <>
          <p className="inspector-stage">
            {STAGE_LABEL[task?.stage ?? "queued"] ?? "Идёт обработка"}
            {task && task.total > 0 && task.stage === "extract"
              ? `: ${Math.min(task.done + 1, task.total)} из ${task.total}`
              : ""}
          </p>
          <TaskRow
            task={backgroundTask}
            onPause={() => onControl("pause")}
            onResume={() => onControl("resume")}
            onRetry={() => onControl("retry")}
            onCancel={() => onControl("cancel")}
          />
        </>
      )}

      {material.error && (
        <ErrorState title="Обработка остановилась" message={material.error}>
          <p>Текущая версия не изменилась.</p>
        </ErrorState>
      )}

      {!readOnly && !running && (
        <>
          {material.capabilities.can_run_ocr ? (
            <>
              <RadioCards
                className="ocr-modes"
                label="Режим распознавания"
                layout="rows"
                value={mode}
                options={ocrModes.map((item) => ({
                  value: item.mode,
                  title: item.title,
                  description: item.description,
                  unavailableReason: item.available
                    ? undefined
                    : item.status_detail || "Этот режим сейчас недоступен.",
                }))}
                onChange={(next) => setMode(next as ParserMode)}
              />
              {modeUnavailable && (
                <p className="inspector-note">
                  <Link to="/setup?section=ocr&subsection=engines">
                    <Settings2 size={14} aria-hidden="true" /> Открыть параметры распознавания
                  </Link>
                </p>
              )}

              {mode === "cloud" && cloud && (
                <div className="cloud-run-setup">
                  <p className="inspector-note">
                    Читать будет <b>{cloud.model_id ?? "модель не выбрана"}</b>
                    {cloud.provider_label ? ` · ${cloud.provider_label}` : ""}
                    {" — "}
                    <Link to="/setup?section=ocr&subsection=cloud">сменить модель</Link>
                  </p>
                  <RadioCards
                    className="cloud-strategies"
                    label="Что отдавать модели"
                    layout="rows"
                    value={cloud.strategy}
                    options={cloud.strategies.map((item) => ({
                      value: item.value,
                      title: item.title,
                      description: item.hint,
                    }))}
                    onChange={(next) => chooseStrategy(next as OcrCloudStrategy)}
                  />
                </div>
              )}
            </>
          ) : (
            <p className="inspector-note">
              {presentation.processingTitle} для этого источника выполняется целиком:
              страницы здесь нет, и режимы распознавания к нему не относятся.
            </p>
          )}

          {canScope && (
            <RadioCards
              className="scope-modes"
              label="Область запуска"
              layout="rows"
              value={processingScope}
              options={[
                {
                  value: "all",
                  title: "Весь документ",
                  description: `${pageCount} страниц заново`,
                },
                ...(showOcrReview ? [{
                  value: "needs_review" as const,
                  title: "Только страницы, которые нужно проверить",
                  description: `${reviewPages} страниц`,
                  unavailableReason: reviewPages === 0
                    ? "Все страницы уже подготовлены без предупреждений."
                    : undefined,
                }] : []),
                {
                  value: "range",
                  title: "Диапазон",
                  description: "Например, только пересканированные листы",
                  extra: (
                    <div className="scope-range">
                      <Field label="С">
                        <input
                          type="number"
                          min={1}
                          max={pageCount}
                          value={range.from}
                          onChange={(event) => setRange((current) => ({
                            ...current,
                            from: Number(event.target.value),
                          }))}
                        />
                      </Field>
                      <Field label="По">
                        <input
                          type="number"
                          min={1}
                          max={pageCount}
                          value={range.to}
                          onChange={(event) => setRange((current) => ({
                            ...current,
                            to: Number(event.target.value),
                          }))}
                        />
                      </Field>
                    </div>
                  ),
                },
              ]}
              onChange={(next) => setScope(next as ProcessingScope)}
            />
          )}

          {material.usage.length > 0 && (
            <div className="inspector-impact">
              <p>Новая версия будет использоваться в {projectCountLabel(material.usage.length)}.</p>
              <Disclosure summary="Какие это проекты">
                <ul>
                  {material.usage.map((usage) => (
                    <li key={`${usage.project_id}-${usage.display_name}`}>
                      {usage.project_name} — «{usage.display_name}»
                    </li>
                  ))}
                </ul>
              </Disclosure>
            </div>
          )}

          {mode && !rangeInvalid && plannedPages > 0 && (
            <p className="inspector-estimate">
              {plannedPages} стр. · {durationLabel(plannedPages, mode)}
              {mode === "cloud" && (
                pagePrice === null
                  ? " · цена модели неизвестна"
                  : cloud?.strategy === "page"
                    ? ` · ${priceLabel(pagePrice * plannedPages)}`
                    : ` · не дороже ${priceLabel(pagePrice * plannedPages)}: наружу уходят только вырезы`
              )}
            </p>
          )}

          <Button
            disabled={busy || !mode || !selectedMode?.available || rangeInvalid}
            onClick={() => mode && onStart(
              processingScope === "range"
                ? { parser_mode: mode, scope: processingScope, page_from: range.from, page_to: range.to }
                : { parser_mode: mode, scope: canScope ? processingScope : "all" },
            )}
          >
            {prepared
              ? <><RotateCcw size={14} aria-hidden="true" /> Запустить заново</>
              : <><Play size={14} aria-hidden="true" /> Подготовить материал</>}
          </Button>
          {rangeInvalid && (
            <p className="inspector-error" role="alert">
              Диапазон должен укладываться в 1—{pageCount} и идти по возрастанию.
            </p>
          )}
        </>
      )}

      {prepared && (
        <section className="inspector-section">
          <h4>Текущая страница</h4>
          {readOnly ? (
            <p className="inspector-note">
              Открыта прежняя версия — изменения в ней недоступны.
            </p>
          ) : (
            <div className="inspector-actions">
              <Button variant="secondary" disabled={busy || !page} onClick={onEditPage}>
                <Pencil size={14} aria-hidden="true" /> Исправить текст
              </Button>
              <Button
                variant="ghost"
                disabled={busy || !page || !(page.markdown || page.text).trim()}
                onClick={onCleanupPage}
              >
                <Sparkles size={14} aria-hidden="true" /> Прибрать текст с ИИ
              </Button>
            </div>
          )}
        </section>
      )}

      {diagnostics.length > 0 && (
        <section className="inspector-section">
          <h4>Что стоит знать о разборе</h4>
          <ul className="inspector-list">
            {diagnostics.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </section>
      )}
    </div>
  );
}
