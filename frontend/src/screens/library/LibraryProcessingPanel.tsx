import { Pencil, Play, RotateCcw, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import type {
  LibraryMaterialDetailRead,
  MaterialPageRead,
  ProcessingScope,
} from "../../api/materials";
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

/**
 * Пять режимов распознавания. Недоступные не прячутся: скрытый вариант
 * выглядит как отсутствие функции, а не как «пока не подключено».
 */
const OCR_MODES = [
  {
    id: "fast",
    title: "Быстро",
    meta: "Локально · CPU",
    enabled: true,
    description: "Обычный текст, фотографии лекций и сканы без отправки данных.",
    reason: "",
  },
  {
    id: "textbook",
    title: "Учебник",
    meta: "Локально · GPU",
    enabled: false,
    description: "Сложная вёрстка, таблицы и печатные учебники.",
    reason: "Нужен совместимый локальный GPU runtime.",
  },
  {
    id: "cloud",
    title: "Облако",
    meta: "",
    enabled: false,
    description: "Недорогой облачный разбор PDF и документов.",
    reason: "Появится после подключения облачного распознавания.",
  },
  {
    id: "maximum",
    title: "Максимум",
    meta: "",
    enabled: false,
    description: "Структурированный текст, таблицы, иерархия и координаты.",
    reason: "Появится после подключения расширенного document parser.",
  },
  {
    id: "expert",
    title: "Эксперт",
    meta: "",
    enabled: false,
    description: "Дополнительная проверка сложных элементов и сомнительных формул.",
    reason: "Появится вместе с экспертной проверкой распознавания.",
  },
] as const;

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
  onStart: (command: { scope: ProcessingScope; page_from?: number; page_to?: number }) => void;
  onControl: (action: "pause" | "resume" | "retry") => void;
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
  const [mode, setMode] = useState<string>("fast");
  const [scope, setScope] = useState<ProcessingScope>("all");
  const [range, setRange] = useState({ from: 1, to: material.page_count ?? 1 });

  const task = material.task;
  const running = task && (task.state === "running" || task.state === "queued" || task.state === "paused");
  const prepared = material.active_parse_revision > 0;
  const reviewPages = material.ocr_low_page_count;
  const pageCount = material.page_count ?? 1;
  const canScope = material.capabilities.can_run_ocr && prepared && pageCount > 1;
  const currentPageState = page
    ? material.page_states.find((item) => item.page_number === page.page_number)
    : null;
  const currentNeedsReview = page?.quality === "ocr_low"
    && currentPageState?.reviewed_at === null;

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
        {material.parser_mode === "fast" && prepared && (
          <StatusBadge tone="neutral">Быстро · локально</StatusBadge>
        )}
      </header>

      <dl className="inspector-summary">
        <div><dt>Страниц</dt><dd>{pageCount}</dd></div>
        {material.capabilities.can_run_ocr && (
          <div><dt>Сканов</dt><dd>{material.scan_page_count}</dd></div>
        )}
        <div><dt>Нужно проверить</dt><dd>{reviewPages}</dd></div>
      </dl>

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
            <RadioCards
              className="ocr-modes"
              label="Режим распознавания"
              layout="rows"
              value={mode}
              options={OCR_MODES.map((item) => ({
                value: item.id,
                title: item.meta ? `${item.title} · ${item.meta}` : item.title,
                description: item.description,
                unavailableReason: item.enabled ? undefined : item.reason,
              }))}
              onChange={setMode}
            />
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
              value={scope}
              options={[
                {
                  value: "all",
                  title: "Весь документ",
                  description: `${pageCount} страниц заново`,
                },
                {
                  value: "needs_review",
                  title: "Только страницы, которые нужно проверить",
                  description: `${reviewPages} страниц`,
                  unavailableReason: reviewPages === 0
                    ? "Все страницы уже подготовлены без предупреждений."
                    : undefined,
                },
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
            disabled={busy || mode !== "fast" || rangeInvalid}
            onClick={() => onStart(
              scope === "range"
                ? { scope, page_from: range.from, page_to: range.to }
                : { scope: canScope ? scope : "all" },
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
