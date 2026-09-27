import {
  Clock3,
  FileUp,
  ImageIcon,
  Pencil,
  Play,
  RotateCcw,
  ScanLine,
  Settings2,
  Sparkles,
} from "lucide-react";
import { hasYoutubeTimestamps } from "./youtubeTranscript";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import {
  estimateLibraryProcessing,
  PARSER_MODE_TITLES,
  type LibraryMaterialDetailRead,
  type LibraryProcessingCommand,
  type MaterialPageRead,
  type ParserMode,
  type ProcessingEstimateRead,
  type ProcessingScope,
} from "../../api/materials";
import {
  getOcrSettings,
  type OcrCloudStrategy,
  type OcrImageMode,
  type OcrSettingsRead,
} from "../../api/ocr";
import { getMaterialPresentation } from "../../components/domain/material-viewer";
import { TaskRow } from "../../components/domain";
import type { BackgroundTask } from "../../components/domain";
import { estimateEtaSeconds } from "../../hooks/backgroundTaskEta";
import { ImageDescriptionsDialog } from "./ImageDescriptionsDialog";
import { usdLabel } from "./imageLabels";
import {
  Button,
  Checkbox,
  Disclosure,
  ErrorState,
  Field,
  RadioCards,
  Tooltip,
} from "../../components/ui";

const STAGE_LABEL: Record<string, string> = {
  queued: "Ждём очереди",
  extract: "Разбираем страницы",
  segment: "Собираем блоки и фрагменты",
  complete: "Готово",
};

const STRATEGY_LABEL: Record<OcrCloudStrategy, string> = {
  economy: "Экономно", auto: "Адаптивно", page: "Каждую страницу целиком",
};
const IMAGE_MODE_LABEL: Record<OcrImageMode, string> = {
  describe: "Описывать изображения", text_only: "Только текст изображений", skip: "Не распознавать изображения",
};

// Сколько секунд уходит на страницу. Измерено прогоном `tentex-ocr-bench` на
// 24 страницах: «Быстро» — 334–414 с, «Облако» — около 440 с. Оценка нужна,
// чтобы решить «ставить сейчас или на ночь», поэтому округлена вверх и не
// претендует на точность.
const SECONDS_PER_PAGE: Record<ParserMode, number> = { fast: 16, cloud: 19 };

/** Человеческие названия для диагностики страницы. */
const DIAGNOSTIC_LABEL: Record<string, string> = {
  formula_possible: "Возможны формулы — сверяйте с оригиналом",
  audio_transcription_required: "Запись ещё не расшифрована",
  approximate_timestamps:
    "Время фраз приблизительное: модель не вернула метки, они посчитаны по длине текста",
  manual_correction: "Есть страницы, исправленные вручную",
  source_refreshed: "Снимок источника обновлялся",
  layout_fallback: "Разметка восстановлена упрощённо: колонки могли перепутаться",
  unbalanced_display_math: "У выносных формул не сошлись знаки $$ — часть могла не отрисоваться",
  unbalanced_inline_math: "У формул в тексте не сошлись знаки $",
  unbalanced_braces: "В формулах не сошлись фигурные скобки",
  unbalanced_environment: "В формулах не закрыто окружение LaTeX",
  "route:partial": "Часть страниц — скан с тонким текстовым слоем",
  "route:broken": "У части страниц испорчен текстовый слой",
  "route:scan": "Есть страницы без текстового слоя",
  "route_fallback:local_ocr": "Страницы с ненадёжным слоем прочитаны локальным OCR",
  "route_fallback:cloud_page": "Страницы с ненадёжным слоем отданы модели целиком",
  text_layer_garbled: "В текстовом слое есть нечитаемые символы — сверяйтесь с оригиналом",
  text_layer_mojibake: "Текстовый слой в неверной кодировке — сверяйтесь с оригиналом",
  text_layer_partial: "Текстовый слой покрывает страницу лишь частично",
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
  image_descriptions: "Часть изображений описана моделью",
  missed_regions: "Модель пропустила участки страницы — они сохранены вырезами",
};

// Отметки для отладки конвейера, а не для человека: разрешение растра, число
// элементов, факт применения разметчика. Их место в логе.
const TECHNICAL_DIAGNOSTICS = new Set([
  "render_dpi",
  "structure_elements",
  "layout_markdown",
  "route",
  "text_chars",
  "text_quality",
  "raster_share",
  "pictures",
]);

/** Чем расшифрована запись: значение — модель, и в ней бывают двоеточия (`:free`). */
const ASR_SOURCE_LABEL: Record<string, string> = {
  asr_local: "Расшифровано локально",
  asr_cloud: "Расшифровано облаком, модель",
};

/** Строка диагностики по-русски или `null`, если её показывать не нужно. */
function diagnosticText(item: string): string | null {
  const colon = item.indexOf(":");
  const key = colon === -1 ? item : item.slice(0, colon);
  const value = colon === -1 ? undefined : item.slice(colon + 1);
  if (key in ASR_SOURCE_LABEL && value) return `${ASR_SOURCE_LABEL[key]}: ${value}`;
  if (item in DIAGNOSTIC_LABEL) return DIAGNOSTIC_LABEL[item];
  if (TECHNICAL_DIAGNOSTICS.has(key)) return null;
  if (value !== undefined && key in DIAGNOSTIC_PRESENCE) {
    // Ноль — это не факт, а его отсутствие: строку такое не заслуживает.
    return value === "0" ? null : DIAGNOSTIC_PRESENCE[key];
  }
  return DIAGNOSTIC_LABEL[item] ?? item;
}

/** «12 страниц» → «≈ 3 мин 12 с». Короткие операции тоже должны иметь оценку. */
function durationLabel(pages: number, mode: ParserMode): string {
  const seconds = Math.ceil(pages * SECONDS_PER_PAGE[mode]);
  if (seconds < 60) return `≈ ${seconds} с`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  if (minutes < 60) return remainder ? `≈ ${minutes} мин ${remainder} с` : `≈ ${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  return `≈ ${hours} ч ${minutes % 60} мин`;
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
  onStart: (command: LibraryProcessingCommand) => void;
  onControl: (action: "pause" | "resume" | "retry" | "cancel") => void;
  /** Поставить сборку: с разрешением на загрузку пакетов и, если её ещё нет, с точкой входа. */
  onTypstBuild: (downloadPackages: boolean, entrypoint?: string) => void;
  /** Дослать недостающий файл проекта по пути, который назвал компилятор. */
  onTypstAddFile: (file: File, targetPath: string) => void;
  onEditPage: () => void;
  onCleanupPage: () => void;
  onRemoveTimestamps: () => void;
  onFindHeaderFooter: () => void;
  onConfirmPageReview: () => void;
  onIndexMaterial: () => void;
  /** Поставлено описание изображений: перечитать карточку и задачи. */
  onImagesQueued?: () => void;
}

export function LibraryProcessingPanel({
  material,
  page,
  busy,
  readOnly,
  onStart,
  onControl,
  onTypstBuild,
  onTypstAddFile,
  onEditPage,
  onCleanupPage,
  onRemoveTimestamps,
  onFindHeaderFooter,
  onConfirmPageReview,
  onIndexMaterial,
  onImagesQueued,
}: LibraryProcessingPanelProps) {
  const presentation = getMaterialPresentation(material.presentation_kind);
  // У записи нет страниц и OCR: два своих способа — Whisper на процессоре и
  // внешняя модель речи. Режимы называются так же (`fast`/`cloud`), смысл другой.
  const isAudio = material.presentation_kind === "audio";
  // Режим не выбран, пока не пришли настройки: там лежит и список движков, и
  // выбранный пользователем режим по умолчанию (Параметры → Распознавание).
  const [mode, setMode] = useState<ParserMode | null>(null);
  const [ocr, setOcr] = useState<OcrSettingsRead | null>(null);
  const [scope, setScope] = useState<ProcessingScope>("all");
  const [range, setRange] = useState({ from: 1, to: material.page_count ?? 1 });

  const task = material.task;
  const running = task && (task.state === "running" || task.state === "queued" || task.state === "paused");
  const prepared = material.active_parse_revision > 0;
  const showOcrReview = !isAudio && material.parser_mode !== "fast";
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
        // Запись по умолчанию читается локально: облако уводит файл наружу и
        // стоит денег, поэтому его выбирают осознанно, а не по режиму страниц.
        setMode((current) => current ?? (isAudio ? "fast" : settings.default_mode));
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setMode((current) => current ?? "fast");
      });
    return () => controller.abort();
  }, [material.id, isAudio]);

  const ocrModes = isAudio ? (ocr?.speech ?? []) : (ocr?.engines ?? []);
  const selectedMode = ocrModes.find((item) => item.mode === mode);
  const modeUnavailable = Boolean(mode) && ocrModes.length > 0 && !selectedMode?.available;
  const cloud = ocr?.cloud ?? null;
  const speechCloud = ocr?.speech.find((item) => item.mode === "cloud") ?? null;
  // Что читает идущую задачу — режим, с которым она поставлена, а не тот, что выбран для следующей.
  const speechModelLabel = ocr?.speech.find(
    (item) => item.mode === (material.parser_mode ?? mode),
  )?.model_label;

  // Стратегия и режим изображений — выбор этого запуска: значения из
  // «Распознавания» только подставляются, а сам запуск снимает их в задачу.
  const [strategy, setStrategy] = useState<OcrCloudStrategy | null>(null);
  const [imageMode, setImageMode] = useState<OcrImageMode | null>(null);
  const runStrategy = strategy ?? cloud?.strategy ?? "auto";
  const imageModes = mode && !isAudio ? (ocr?.image_modes?.[mode] ?? []) : [];
  const runImageMode = imageModes.some((item) => item.value === imageMode)
    ? imageMode
    : (imageModes[0]?.value ?? null);
  const [estimate, setEstimate] = useState<ProcessingEstimateRead | null>(null);
  const [confirmUnknown, setConfirmUnknown] = useState(false);
  const [imagesOpen, setImagesOpen] = useState(false);

  // Сколько страниц уйдёт в работу при выбранной области запуска — от этого
  // считаются и время, и деньги.
  const plannedPages = processingScope === "range"
    ? Math.max(0, range.to - range.from + 1)
    : processingScope === "needs_review"
      ? reviewPages
      : pageCount;

  const rangeInvalid = scope === "range"
    && (range.from < 1 || range.to > pageCount || range.from > range.to);

  function runCommand(): LibraryProcessingCommand | null {
    if (!mode) return null;
    const base: LibraryProcessingCommand = processingScope === "range"
      ? { parser_mode: mode, scope: processingScope, page_from: range.from, page_to: range.to }
      : { parser_mode: mode, scope: canScope ? processingScope : "all" };
    if (isAudio) return base;
    return {
      ...base,
      cloud_strategy: mode === "cloud" ? runStrategy : null,
      image_mode: runImageMode,
    };
  }

  // Облачный запуск оценивает сервер по самим страницам: сколько уйдёт
  // целиком, сколько изображений, и верхнюю цену с потолком ответа. Эта же
  // верхняя цена становится пределом запуска.
  const estimateKey = mode === "cloud" && !isAudio && !rangeInvalid && material.capabilities.can_run_ocr
    ? JSON.stringify(runCommand())
    : null;
  useEffect(() => {
    setEstimate(null);
    setConfirmUnknown(false);
    if (!estimateKey || readOnly) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void estimateLibraryProcessing(material.id, JSON.parse(estimateKey), controller.signal)
        .then((value) => {
          if (!controller.signal.aborted) setEstimate(value);
        })
        .catch(() => undefined);
    }, 300);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [estimateKey, material.id, material.active_parse_revision, readOnly]);
  const priceBlocked = mode === "cloud" && estimate !== null && !estimate.price_known
    && !confirmUnknown;

  // Досылка недостающего файла: путь известен заранее, выбор — только сам файл.
  const missingFileInput = useRef<HTMLInputElement>(null);
  const [pendingPath, setPendingPath] = useState<string | null>(null);

  const backgroundTask: BackgroundTask | null = useMemo(() => {
    if (!task || task.state === "completed") return null;
    return {
      id: task.id,
      kind: material.presentation_kind === "typst" ? "typst_compile" : "parse",
      subject: material.display_name,
      unit: isAudio ? "минут" : "страниц",
      // У записи подпись — то, что реально читает; у страниц её подставляет реестр.
      detail: isAudio ? speechModelLabel : undefined,
      done: task.done,
      total: task.total,
      etaSeconds: estimateEtaSeconds(task.id, task.done, task.total, task.updated_at),
      state: task.state,
      finalizing: task.stage === "segment" && task.total > 0 && task.done === task.total,
      error: task.error ?? undefined,
    };
  }, [task, material.display_name, material.presentation_kind, isAudio, speechModelLabel]);

  // Технические отметки конвейера человеку не нужны: список чистится, а не
  // печатается как есть. Пустой после чистки — раздела нет вовсе.
  const diagnostics = useMemo(
    () => [...new Set(
      material.diagnostics
        // «Запись ещё не расшифрована» после расшифровки — уже неправда.
        .filter((item) => !(prepared && item === "audio_transcription_required"))
        .map(diagnosticText)
        .filter((item): item is string => item !== null),
    )],
    [material.diagnostics, prepared],
  );

  if (material.presentation_kind === "typst") {
    const issues = material.typst?.issues ?? [];
    const packageRequired = issues.some((issue) => issue.kind === "package");
    const entrypointCandidates = material.typst?.entrypoint_candidates ?? [];
    const missingPaths = [...new Set(
      issues.map((issue) => issue.missing_path).filter((path): path is string => Boolean(path)),
    )];
    return (
      <div className="inspector-content">
        <header className="inspector-section-head"><h3>Сборка Typst</h3></header>
        <p className="inspector-note">
          PDF собирается локально без системных шрифтов; текстовый поиск использует PDF,
          а модели получают исходный Typst-код.
        </p>

        {/* Та же строка задачи, что у разбора: прогресс и отмена нужны сборке
            ровно так же, иначе идущая работа выглядит как зависшая. */}
        {backgroundTask && (
          <TaskRow task={backgroundTask} onCancel={() => onControl("cancel")} />
        )}

        {material.error && (
          <ErrorState title="Сборка не удалась" message={material.error}>
            <p>Прошлая собранная версия осталась на месте.</p>
          </ErrorState>
        )}

        {issues.length > 0 && (
          <section className="inspector-section">
            <h4>Нужно внимание</h4>
            <ul className="inspector-list">
              {issues.map((issue, index) => (
                <li key={`${issue.kind}-${index}`}>
                  {issue.message}
                  {issue.path && <code> {issue.path}{issue.line ? `:${issue.line}` : ""}</code>}
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Файл кладётся ровно туда, где его искал компилятор, — путь известен
            из диагностики, поэтому выбирать место руками не нужно. */}
        {missingPaths.length > 0 && !readOnly && (
          <section className="inspector-section">
            <h4>Недостающие файлы</h4>
            <ul className="inspector-list">
              {missingPaths.map((path) => (
                <li key={path}>
                  <code>{path}</code>
                  <Button
                    variant="ghost"
                    disabled={busy}
                    onClick={() => {
                      setPendingPath(path);
                      missingFileInput.current?.click();
                    }}
                  >
                    <FileUp size={14} aria-hidden="true" /> Выбрать файл
                  </Button>
                </li>
              ))}
            </ul>
            <input
              ref={missingFileInput}
              className="materials-file-input"
              type="file"
              tabIndex={-1}
              aria-hidden="true"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file && pendingPath) onTypstAddFile(file, pendingPath);
              }}
            />
          </section>
        )}

        {/* Без точки входа собирать нечего: пока она не выбрана, кнопка сборки
            бессмысленна, а список `.typ` — единственное осмысленное действие. */}
        {entrypointCandidates.length > 0 && !readOnly && !running && (
          <Field label="Точка входа" hint="С какого файла начинается документ">
            <RadioCards
              label="Точка входа Typst-проекта"
              value=""
              layout="rows"
              onChange={(next) => onTypstBuild(false, next)}
              options={entrypointCandidates.map((path) => ({
                value: path,
                title: path.split("/").pop() ?? path,
                description: path,
              }))}
            />
          </Field>
        )}

        {entrypointCandidates.length === 0 && !readOnly && !running && (
          packageRequired ? (
            <Button disabled={busy} onClick={() => onTypstBuild(true)}>
              Скачать пакет и продолжить
            </Button>
          ) : (
            <Button variant="secondary" disabled={busy} onClick={() => onTypstBuild(false)}>
              <RotateCcw size={14} aria-hidden="true" /> Собрать заново
            </Button>
          )
        )}

        {material.typst?.compiler_version && (
          <p className="inspector-note">Компилятор Typst {material.typst.compiler_version}</p>
        )}
      </div>
    );
  }

  return (
    <div className="inspector-content">
      <header className="inspector-section-head">
        <h3>{presentation.processingTitle}</h3>
      </header>

      {!isAudio && material.presentation_kind !== "youtube" && material.parser_mode === "fast" && prepared && (
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
            {isAudio && task?.stage === "extract"
              ? "Расшифровываем запись"
              : (STAGE_LABEL[task?.stage ?? "queued"] ?? "Идёт обработка")}
            {!isAudio && task && task.total > 0 && task.stage === "extract"
              ? `: ${Math.min(task.done + 1, task.total)} из ${task.total}`
              : ""}
          </p>
          {task?.parser_mode && (
            <p className="inspector-note">
              Режим: {PARSER_MODE_TITLES[task.parser_mode]}
              {!isAudio && task.parser_mode === "cloud" && task.cloud_strategy && ` · ${STRATEGY_LABEL[task.cloud_strategy]}`}
              <br />
              Модель: {(isAudio ? speechModelLabel : task.model_id) ?? "не сохранена в запуске"}
              {!isAudio && task.image_mode && <><br />{IMAGE_MODE_LABEL[task.image_mode]}</>}
            </p>
          )}
          {/* Пауза у записи не нужна: локальный Whisper с середины не продолжит, а
              облачная расшифровка при сбое и так продолжается с готовых кусков. */}
          <TaskRow
            task={backgroundTask}
            onPause={isAudio ? undefined : () => onControl("pause")}
            onResume={isAudio ? undefined : () => onControl("resume")}
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
          {material.capabilities.can_run_ocr || isAudio ? (
            <>
              <RadioCards
                className="ocr-modes"
                label={isAudio ? "Способ расшифровки" : "Режим распознавания"}
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
                  <Link
                    to={isAudio
                      ? "/setup?section=ai&subsection=defaults"
                      : "/setup?section=ocr&subsection=engines"}
                  >
                    <Settings2 size={14} aria-hidden="true" />
                    {isAudio ? " Открыть параметры моделей" : " Открыть параметры распознавания"}
                  </Link>
                </p>
              )}

              {isAudio && mode === "cloud" && speechCloud?.available && (
                <p className="inspector-note">
                  Читать будет <b>{speechCloud.model_label}</b>
                  {speechCloud.provider_label ? ` · ${speechCloud.provider_label}` : ""}
                  {" — "}
                  <Link to="/setup?section=ai&subsection=defaults">сменить модель</Link>.
                </p>
              )}

              {isAudio && mode === "cloud" && speechCloud?.available && (
                <p className="inspector-note">
                  Запись уходит провайдеру кусками по несколько минут; цена зависит от
                  длины записи и тарифа модели. Готовые куски сохраняются: при сбое
                  «Повторить» не платит за них второй раз.
                </p>
              )}

              {isAudio && mode === "fast" && (
                <p className="inspector-note">
                  Локальная расшифровка идёт медленнее записи и на разговорной речи
                  ошибается заметно чаще облачной. Если результат плохой, расшифруйте
                  запись заново облаком.
                </p>
              )}

              {!isAudio && mode === "cloud" && cloud && (
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
                    value={runStrategy}
                    options={cloud.strategies.map((item) => ({
                      value: item.value,
                      title: item.title,
                      description: item.hint,
                    }))}
                    onChange={(next) => setStrategy(next as OcrCloudStrategy)}
                  />
                </div>
              )}

              {!isAudio && imageModes.length > 1 && (
                <Field label="Изображения" hint="Что делать с рисунками и схемами в этом запуске">
                  <RadioCards
                    className="image-modes"
                    label="Изображения"
                    layout="rows"
                    value={runImageMode}
                    options={imageModes.map((item) => ({
                      value: item.value,
                      title: item.title,
                      description: item.hint,
                    }))}
                    onChange={(next) => setImageMode(next as OcrImageMode)}
                  />
                </Field>
              )}
            </>
          ) : (
            <p className="inspector-note">
              {material.presentation_kind === "youtube"
                ? "Из видео получаем субтитры. Таймкоды можно убрать кнопкой ниже."
                : `${presentation.processingTitle} для этого источника выполняется целиком: страницы здесь нет, и режимы распознавания к нему не относятся.`}
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

          {!isAudio && mode && !rangeInvalid && plannedPages > 0 && (
            <p className="inspector-estimate">
              {plannedPages} стр. · {durationLabel(plannedPages, mode)}
              {mode === "cloud" && estimate && (
                estimate.price_known
                  ? ` · до ${estimate.requests_upper} запр. · обычно ${usdLabel(estimate.cost_typical_usd)}, не дороже ${usdLabel(estimate.cost_upper_usd)}`
                  : ` · до ${estimate.requests_upper} запр. · цена модели неизвестна`
              )}
              {mode === "cloud" && !estimate && estimateKey && " · считаем стоимость…"}
            </p>
          )}
          {mode === "cloud" && estimate && estimate.notes.length > 0 && (
            <ul className="inspector-list">
              {estimate.notes.map((note) => <li key={note}>{note}</li>)}
            </ul>
          )}
          {mode === "cloud" && estimate && !estimate.price_known && (
            <Checkbox
              checked={confirmUnknown}
              onCheckedChange={setConfirmUnknown}
              label="Запустить без оценки цены"
              disabled={busy}
            />
          )}

          <Button
            disabled={busy || !mode || !selectedMode?.available || rangeInvalid || priceBlocked}
            onClick={() => {
              const command = runCommand();
              if (!command) return;
              onStart(mode === "cloud" && estimate
                ? {
                  ...command,
                  max_cost_usd: estimate.cost_upper_usd,
                  confirm_unknown_price: confirmUnknown,
                }
                : command);
            }}
          >
            {prepared
              ? (
                <>
                  <RotateCcw size={14} aria-hidden="true" />
                  {isAudio ? " Расшифровать заново" : " Запустить заново"}
                </>
              )
              : (
                <>
                  <Play size={14} aria-hidden="true" />
                  {isAudio ? " Расшифровать запись" : " Подготовить материал"}
                </>
              )}
          </Button>
          {rangeInvalid && (
            <p className="inspector-error" role="alert">
              Диапазон должен укладываться в 1—{pageCount} и идти по возрастанию.
            </p>
          )}
        </>
      )}

      {prepared && !isAudio && (
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
              {material.presentation_kind === "youtube" && (
                <Tooltip label={page && !hasYoutubeTimestamps(page.markdown || page.text) ? "В тексте уже нет таймкодов." : "Откроет предпросмотр исправленного текста"}>
                  <span>
                    <Button variant="ghost" disabled={busy || !page || !hasYoutubeTimestamps(page.markdown || page.text)} onClick={onRemoveTimestamps}>
                      <Clock3 size={14} aria-hidden="true" /> Убрать таймкоды
                    </Button>
                  </span>
                </Tooltip>
              )}
            </div>
          )}
        </section>
      )}

      {prepared && !isAudio && material.images.total > 0 && (
        <section className="inspector-section">
          <h4>Изображения</h4>
          <p className="inspector-note">
            Всего {material.images.total}
            {material.images.described > 0 ? ` · описано ${material.images.described}` : ""}
            {material.images.needs_review > 0 ? ` · на проверку ${material.images.needs_review}` : ""}
            {material.images.service > 0 ? ` · служебных ${material.images.service}` : ""}
          </p>
          {!readOnly && material.images.describable > 0 && (
            <div className="inspector-actions">
              <Button
                variant="secondary"
                disabled={busy || Boolean(running)}
                onClick={() => setImagesOpen(true)}
              >
                <ImageIcon size={14} aria-hidden="true" /> Описать изображения ({material.images.describable})
              </Button>
            </div>
          )}
          <ImageDescriptionsDialog
            open={imagesOpen}
            material={{ id: material.id, display_name: material.display_name }}
            onOpenChange={setImagesOpen}
            onStarted={() => onImagesQueued?.()}
          />
        </section>
      )}

      {prepared && !readOnly && !running && (
        <section className="inspector-section">
          <h4>Поиск по содержимому</h4>
          <p className="inspector-note">Добавьте этот материал в активный индекс, чтобы искать в нём по смыслу.</p>
          <Button variant="secondary" disabled={busy} onClick={onIndexMaterial}>Добавить в индекс</Button>
        </section>
      )}

      {prepared && material.presentation_kind === "pdf" && pageCount >= 3 && !readOnly && (
        <section className="inspector-section">
          <h4>Весь документ</h4>
          <div className="inspector-actions">
            <Button variant="secondary" disabled={busy || Boolean(running)} onClick={onFindHeaderFooter}>
              <ScanLine size={14} aria-hidden="true" /> Найти колонтитулы
            </Button>
          </div>
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
