import { ExternalLink, Video } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  libraryFragmentAssetUrl,
  libraryPageImageUrl,
  librarySourceUrl,
  type LibraryMaterialDetailRead,
  type MaterialPageRead,
  type ParserMode,
} from "../../api/materials";
import { StructuredPage, TimedTranscript } from "../../components/domain/material-viewer";
import { EmptyState, LoadingState, Switch } from "../../components/ui";
import { AudioTranscriptView } from "./AudioTranscriptView";
import { WebSnapshotView } from "./WebSnapshotView";

/** Сохранённый текст источника: нужен только там, где он и есть содержимое. */
function useSourceText(materialId: string, enabled: boolean, revision: number | null) {
  const [text, setText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled) {
      setText(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    void fetch(librarySourceUrl(materialId, revision ?? undefined), { signal: controller.signal })
      .then((response) => (response.ok ? response.text() : Promise.reject(new Error("нет файла"))))
      .then((value) => {
        if (!controller.signal.aborted) setText(value);
      })
      .catch(() => {
        if (!controller.signal.aborted) setText(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [materialId, enabled, revision]);

  return { text, loading };
}

interface MaterialSourceViewProps {
  material: LibraryMaterialDetailRead;
  page: MaterialPageRead | null;
  pageNumber: number;
  revision: number | null;
  query: string;
  zoom: number;
  showRegions: boolean;
  focusedFragmentId: string | null;
  currentTime: number;
  onTimeUpdate: (seconds: number) => void;
  /** Замер «вписать страницу» идёт по этой области, а не по всей сцене:
      в режиме сравнения исходнику достаётся только половина ширины. */
  scrollRef?: (node: HTMLDivElement | null) => void;
}

/**
 * Левая половина сцены — исходное представление. Исчерпывающий switch по
 * `presentation_kind`: новый вид источника не соберётся молча как PDF.
 */
export function MaterialSourceView({
  material,
  page,
  pageNumber,
  revision,
  query,
  zoom,
  showRegions,
  focusedFragmentId,
  currentTime,
  onTimeUpdate,
  scrollRef,
}: MaterialSourceViewProps) {
  const audio = useRef<HTMLAudioElement>(null);
  const kind = material.presentation_kind;
  const needsText = kind === "plain_text" || kind === "web";
  const { text: sourceText, loading: sourceLoading } = useSourceText(
    material.id,
    needsText,
    revision,
  );

  useEffect(() => {
    if (kind !== "audio" || !audio.current) return;
    // Перемотка приходит из расшифровки: сегмент знает своё время, плеер — нет.
    if (Math.abs(audio.current.currentTime - currentTime) > 0.75) {
      audio.current.currentTime = currentTime;
    }
  }, [currentTime, kind]);

  switch (kind) {
    case "pdf":
    case "image":
      return (
        <div className="viewer-sheet-scroll" ref={scrollRef}>
          <div className="viewer-sheet" style={{ "--viewer-zoom": zoom } as CSSProperties}>
            <img
              src={libraryPageImageUrl(material.id, page?.page_number ?? pageNumber)}
              alt={`Исходное изображение страницы ${page?.page_number ?? pageNumber} — ${material.original_name}`}
            />
            {showRegions && page && (
              <div className="viewer-region-layer" aria-hidden="true">
                {page.fragments.map((fragment) => (
                  <span
                    key={fragment.id}
                    className={fragment.id === focusedFragmentId ? "is-focused" : ""}
                    style={{
                      left: `${fragment.bbox[0] * 100}%`,
                      top: `${fragment.bbox[1] * 100}%`,
                      width: `${(fragment.bbox[2] - fragment.bbox[0]) * 100}%`,
                      height: `${(fragment.bbox[3] - fragment.bbox[1]) * 100}%`,
                    }}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      );

    case "document":
      return (
        <div className="viewer-pane-scroll">
          {page
            ? (
              <StructuredPage
                showOcrReview={material.parser_mode !== "fast"}
                page={page}
                query={query}
                assetUrl={(fragmentId) => libraryFragmentAssetUrl(material.id, fragmentId)}
                focusedFragmentId={focusedFragmentId}
                className="is-document"
              />
            )
            : <LoadingState label="Открываем документ" />}
        </div>
      );

    case "plain_text":
      return (
        <div className="viewer-pane-scroll">
          {sourceLoading
            ? <LoadingState label="Открываем исходный текст" />
            : <pre className="source-plain">{sourceText ?? "Исходный файл не читается."}</pre>}
        </div>
      );

    case "web":
      return (
        <div className="viewer-pane-scroll">
          <WebSnapshotView material={material} snapshot={sourceText} loading={sourceLoading} />
        </div>
      );

    case "youtube":
      return (
        <div className="viewer-pane-scroll">
          <div className="youtube-source">
            <span className="youtube-badge"><Video size={16} aria-hidden="true" /> YouTube</span>
            <h2>{material.original_name}</h2>
            {material.retrieved_at && (
              <p className="youtube-meta">
                субтитры получены {new Date(material.retrieved_at).toLocaleDateString("ru-RU")}
              </p>
            )}
            {material.source_url && (
              <a className="youtube-link" href={material.source_url} target="_blank" rel="noreferrer">
                Открыть ролик
                <ExternalLink size={13} aria-hidden="true" />
              </a>
            )}
            <p className="youtube-note">
              Материалом считается сохранённая расшифровка: она читается без сети.
              Метка времени открывает ролик с нужного момента.
            </p>
          </div>
        </div>
      );

    case "audio":
      return (
        <div className="viewer-pane-scroll">
          <AudioTranscriptView ref={audio} material={material} onTimeUpdate={onTimeUpdate} />
        </div>
      );

    default: {
      const exhaustive: never = kind;
      throw new Error(`Неописанный вид источника: ${String(exhaustive)}`);
    }
  }
}

interface MaterialTextViewProps {
  material: LibraryMaterialDetailRead;
  parserMode?: ParserMode | null;
  page: MaterialPageRead | null;
  query: string;
  focusedFragmentId: string | null;
  currentTime: number;
  onSeek: (seconds: number) => void;
  processing?: boolean;
  /** У исходника ещё нет версии разбора, поэтому текстовой страницы быть не может. */
  needsPreparation?: boolean;
  zoom?: number;
  /** Предлагать тумблер «фото фрагментов»: только у основного текста, не в сравнении версий. */
  allowSourcePhotos?: boolean;
}

const SOURCE_PHOTO_KEY = "tentex-viewer-source-photos";

/** Правая половина сцены — подготовленный результат разбора. */
export function MaterialTextView({
  material,
  parserMode = material.parser_mode,
  page,
  query,
  focusedFragmentId,
  currentTime,
  onSeek,
  processing = false,
  needsPreparation = false,
  zoom = 1,
  allowSourcePhotos = false,
}: MaterialTextViewProps) {
  // Фотографии фрагментов есть только там, где страница — растр (PDF, скан).
  const canShowPhotos = allowSourcePhotos
    && (material.presentation_kind === "pdf" || material.presentation_kind === "image");
  // По умолчанию «Учебник» показывает фото с расшифровкой под ними; выбор запоминается.
  const [showPhotos, setShowPhotos] = useState<boolean>(() => {
    const stored = localStorage.getItem(SOURCE_PHOTO_KEY);
    if (stored === "on") return true;
    if (stored === "off") return false;
    return parserMode === "textbook";
  });

  function togglePhotos(next: boolean) {
    setShowPhotos(next);
    localStorage.setItem(SOURCE_PHOTO_KEY, next ? "on" : "off");
  }

  if (!page) {
    return (
      <div className="viewer-pane-scroll">
        {needsPreparation ? (
          <EmptyState title="Текст ещё не подготовлен">
            <p>Запустите распознавание в панели обработки справа.</p>
          </EmptyState>
        ) : (
          <LoadingState label={processing ? "Страница ещё обрабатывается" : "Открываем текст"} />
        )}
      </div>
    );
  }
  if (material.capabilities.has_timeline) {
    return (
      <div className="viewer-pane-scroll">
        <TimedTranscript
          fragments={page.fragments}
          currentTime={currentTime}
          query={query}
          onSeek={(seconds) => {
            if (material.presentation_kind === "youtube" && material.source_url) {
              window.open(
                `${material.source_url}${material.source_url.includes("?") ? "&" : "?"}t=${Math.floor(seconds)}`,
                "_blank",
                "noreferrer",
              );
              return;
            }
            onSeek(seconds);
          }}
        />
      </div>
    );
  }
  return (
    <div className="viewer-pane-scroll" style={{ "--viewer-text-zoom": zoom } as CSSProperties}>
      {canShowPhotos && (
        <div className="viewer-text-controls">
          <Switch
            label="Фото фрагментов с расшифровкой"
            checked={showPhotos}
            onCheckedChange={togglePhotos}
          />
        </div>
      )}
      <StructuredPage
        showOcrReview={parserMode !== "fast"}
        page={page}
        query={query}
        assetUrl={(fragmentId) => libraryFragmentAssetUrl(material.id, fragmentId)}
        focusedFragmentId={focusedFragmentId}
        pageImageUrl={canShowPhotos ? libraryPageImageUrl(material.id, page.page_number) : undefined}
        showSourceCrops={canShowPhotos && showPhotos}
      />
    </div>
  );
}
