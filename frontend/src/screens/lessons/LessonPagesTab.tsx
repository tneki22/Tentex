import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Crop, Plus } from "lucide-react";
import type { LessonBlockCommand, LessonSourceRangeRead } from "../../api/lessons";
import { materialPageImageUrl, type MaterialRead } from "../../api/materials";
import { PageNumberInput } from "../../components/domain/material-viewer";
import { Button, Disclosure, IconButton, Select, StatusBadge } from "../../components/ui";
import { LessonOutlineList, outlineSections } from "./LessonOutlineList";
import type { LessonPickerTarget } from "./LessonSourcePicker";

/** Виды со своим листом: у остальных страница показывается только текстом в диалоге. */
const RASTER_KINDS = new Set(["pdf", "image", "typst"]);

interface LessonPagesTabProps {
  projectId: string;
  materials: MaterialRead[];
  /** Диапазоны темы из оглавления: с них открывается нужная страница, а не первая. */
  ranges: LessonSourceRangeRead[] | null;
  busy: boolean;
  lessonId: string | null;
  lessonPages: Set<string>;
  onOpenPage(target: LessonPickerTarget): void;
  onAdd(command: Omit<LessonBlockCommand, "expected_revision">): void;
}

/**
 * Листание источника: выбор материала, его оглавление и страница.
 *
 * Точный выбор — абзацы, блок, область — живёт в диалоге на всю ширину окна:
 * в панели шириной 320–560 px по вырванным из вёрстки строкам не понять, что
 * берёшь.
 */
export function LessonPagesTab({
  projectId, materials, ranges, busy, lessonId, lessonPages, onOpenPage, onAdd,
}: LessonPagesTabProps) {
  const start = useMemo(() => startingPlace(materials, ranges), [materials, ranges]);
  const [materialId, setMaterialId] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const current = materials.find((item) => item.id === materialId) ?? materials[0] ?? null;
  // Список пунктов должен быть устойчив по ссылке: по его смене оглавление
  // прокручивается к текущему месту, а не на каждый кадр.
  const sections = useMemo(
    () => (current ? outlineSections(current.outline, current.page_count ?? 1) : []),
    [current],
  );

  // Тема сменилась — открываем её страницу из оглавления, а не ту, где остались.
  useEffect(() => {
    if (!start) return;
    setMaterialId(start.materialId);
    setPage(start.page);
  }, [start]);

  if (!current) return <p className="lessons-panel-hint">В проекте нет материалов со страницами.</p>;
  const material = current;
  const pageCount = material.page_count ?? 1;
  const inLesson = lessonPages.has(`${material.id}#${page}`);
  const raster = RASTER_KINDS.has(material.presentation_kind);
  const range = ranges?.find((item) => item.material_id === material.id);

  return (
    <div className="lessons-pages-tab">
      <Select
        ariaLabel="Источник"
        value={material.id}
        options={materials.map((item) => ({ value: item.id, label: item.display_name || item.original_name }))}
        onValueChange={(value) => {
          if (!value) return;
          setMaterialId(value);
          const next = ranges?.find((item) => item.material_id === value);
          setPage(next?.page_from ?? 1);
        }}
      />

      <Disclosure summary={`Оглавление источника${sections.length > 0 ? ` · ${sections.length}` : ""}`} className="lessons-outline-drop">
        <LessonOutlineList sections={sections} page={page} onPick={(target) => setPage(clamp(target, pageCount))} />
      </Disclosure>

      <div className="lessons-pages-nav">
        <IconButton label="Предыдущая страница" disabled={page <= 1} onClick={() => setPage(page - 1)}>
          <ChevronLeft size={15} />
        </IconButton>
        <PageNumberInput page={page} pageCount={pageCount} onPageChange={(next) => setPage(clamp(next, pageCount))} />
        <IconButton label="Следующая страница" disabled={page >= pageCount} onClick={() => setPage(page + 1)}>
          <ChevronRight size={15} />
        </IconButton>
      </div>

      <div className="lessons-pages-marks">
        {inLesson && <StatusBadge tone="info">в уроке</StatusBadge>}
        {range && page >= range.page_from && page <= range.page_to && <StatusBadge tone="success">страница темы</StatusBadge>}
      </div>

      {raster
        ? <img className="lessons-pages-image" src={materialPageImageUrl(projectId, material.id, page)} alt={`${material.display_name}, страница ${page}`} />
        : <p className="lessons-panel-hint">У этого формата нет исходного листа — откройте страницу, чтобы выбрать абзацы по подготовленному тексту.</p>}

      <div className="lessons-outline-actions">
        <Button
          variant="secondary"
          disabled={!lessonId || busy}
          onClick={() => onAdd({ operation: "add_page", material_id: material.id, page_from: page })}
        >
          <Plus size={14} />Добавить страницу
        </Button>
        <Button onClick={() => onOpenPage({ materialId: material.id, page })}>
          <Crop size={14} />Выбрать на странице…
        </Button>
      </div>
    </div>
  );
}

const clamp = (page: number, pageCount: number) => Math.min(Math.max(1, page), pageCount);

/** Источник и страница по умолчанию: основной источник темы и начало её диапазона. */
function startingPlace(
  materials: MaterialRead[],
  ranges: LessonSourceRangeRead[] | null,
): { materialId: string; page: number } | null {
  if (materials.length === 0) return null;
  const range = ranges?.find((item) => materials.some((material) => material.id === item.material_id));
  if (range) return { materialId: range.material_id, page: range.page_from };
  return { materialId: materials[0].id, page: 1 };
}
