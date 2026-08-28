import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { Link } from "react-router";
import { Minus, Plus, ScanLine } from "lucide-react";
import { materialPageImageUrl } from "../../api/materials";
import { IconButton, Tooltip } from "../ui";
import type { AnswerScanGroup } from "./answerPages";

/** Шаги масштаба в долях ширины панели: 1 — страница вписана по ширине. */
const ZOOM_STEPS = [1, 1.25, 1.5, 2, 3];

interface AnswerScanPagesProps {
  projectId: string;
  groups: AnswerScanGroup[];
  /** Компактная раскладка для узкой панели Рабочей области. */
  compact?: boolean;
}

/**
 * Страницы документа с ответом — вместо распознанного текста.
 *
 * Нужно, когда важен оригинальный вид: рукописная формула, схема, таблица,
 * которые распознавание передаёт хуже, чем скан. Поэтому здесь нет ни правки,
 * ни подсветки фрагментов: это просмотр исходника, а разбор живёт в Материалах.
 */
export function AnswerScanPages({ projectId, groups, compact = false }: AnswerScanPagesProps) {
  const [zoom, setZoom] = useState(1);
  const [failed, setFailed] = useState<string[]>([]);

  // Новый вопрос — новый набор страниц: ошибки прежнего к нему не относятся.
  useEffect(() => {
    setFailed([]);
  }, [groups.map((group) => `${group.materialId}:${group.pages.join(",")}`).join("|")]);

  const zoomIndex = ZOOM_STEPS.indexOf(zoom);

  return (
    <div className={`answer-scans ${compact ? "is-compact" : ""}`.trim()}>
      <div className="answer-scans-toolbar">
        <ScanLine size={14} aria-hidden="true" />
        <span>Страницы документа</span>
        <div className="answer-scans-zoom">
          <IconButton
            label="Мельче"
            disabled={zoomIndex <= 0}
            onClick={() => setZoom(ZOOM_STEPS[Math.max(0, zoomIndex - 1)])}
          >
            <Minus size={14} />
          </IconButton>
          <span>{Math.round(zoom * 100)}%</span>
          <IconButton
            label="Крупнее"
            disabled={zoomIndex >= ZOOM_STEPS.length - 1}
            onClick={() => setZoom(ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, zoomIndex + 1)])}
          >
            <Plus size={14} />
          </IconButton>
        </div>
      </div>

      <div className="answer-scans-scroll" style={{ "--answer-scan-zoom": zoom } as CSSProperties}>
        {groups.map((group) => group.pages.map((page) => {
          const key = `${group.materialId}:${page}`;
          return (
            <figure className="answer-scan-page" key={key}>
              {failed.includes(key) ? (
                <p className="answer-scan-missing">
                  У этого файла нет скана страницы {page} — только распознанный текст.
                </p>
              ) : (
                <Tooltip label="Открыть страницу в материалах">
                  <Link to={`/projects/${projectId}/materials/${group.materialId}?page=${page}`}>
                    <img
                      src={materialPageImageUrl(projectId, group.materialId, page)}
                      alt={`Страница ${page} — ${group.materialName}`}
                      loading="lazy"
                      onError={() => setFailed((current) => current.includes(key) ? current : [...current, key])}
                    />
                  </Link>
                </Tooltip>
              )}
              <figcaption>стр. {page} · {group.materialName}</figcaption>
            </figure>
          );
        }))}
      </div>
    </div>
  );
}
