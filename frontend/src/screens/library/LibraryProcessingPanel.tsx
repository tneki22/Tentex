import { Pencil, Play, RotateCcw, Settings2, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import type {
  LibraryMaterialDetailRead,
  MaterialPageRead,
  ParserMode,
  ProcessingScope,
} from "../../api/materials";
import { getOcrSettings, type OcrSettingsRead } from "../../api/ocr";
import { getMaterialPresentation } from "../../components/domain/material-viewer";
import { TaskRow } from "../../components/domain";
import type { BackgroundTask } from "../../components/domain";
import {
  Button,
  Disclosure,
  ErrorState,
  Field,
  RadioCards,
  StatusBadge,
} from "../../components/ui";

const STAGE_LABEL: Record<string, string> = {
  queued: "Ждём очереди",
  extract: "Разбираем страницы",
  segment: "Собираем блоки и фрагменты",
  complete: "Готово",
};

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

  const backgroundTask: BackgroundTask | null = useMemo(() => {
    if (!task || task.state === "completed") return null;
    return {
      id: task.id,
      kind: "parse",
      subject: material.original_name,
      unit: "страниц",
      done: task.done,
      total: task.total,
      etaMinutes: null,
      state: task.state,
      error: task.error ?? undefined,
    };
  }, [task, material.original_name]);

  const rangeInvalid = scope === "range"
    && (range.from < 1 || range.to > pageCount || range.from > range.to);

  return (
    <div className="inspector-content">
      <header className="inspector-section-head">
        <h3>{presentation.processingTitle}</h3>
        {material.parser_mode && prepared && (
          <StatusBadge tone="neutral">
            {material.parser_mode === "textbook" ? "Режим «Учебник»" : "Режим «Быстро»"}
          </StatusBadge>
        )}
      </header>

      <dl className="inspector-summary">
        <div><dt>Страниц</dt><dd>{pageCount}</dd></div>
        {material.capabilities.can_run_ocr && (
          <div><dt>Сканов</dt><dd>{material.scan_page_count}</dd></div>
        )}
        {showOcrReview && <div><dt>Нужно проверить</dt><dd>{reviewPages}</dd></div>}
      </dl>

      {material.parser_mode === "fast" && prepared && (
        <p className="inspector-note">
          «Быстро» распознаёт обычный текст. Формулы могут содержать ошибки — сверяйтесь с изображением.
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

      {material.diagnostics.length > 0 && (
        <section className="inspector-section">
          <h4>Диагностика</h4>
          <ul className="inspector-list">
            {material.diagnostics.map((item) => (
              <li key={item}>
                {item === "formula_possible" ? "Возможны формулы — сверяйте с оригиналом"
                  : item === "audio_transcription_required" ? "Нужна локальная расшифровка аудио"
                  : item === "manual_correction" ? "Есть страницы, исправленные вручную"
                  : item === "source_refreshed" ? "Снимок источника обновлялся"
                  : item === "layout_fallback" ? "Разметка восстановлена упрощённо"
                  : item}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
