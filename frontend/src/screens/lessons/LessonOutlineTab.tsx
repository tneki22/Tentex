import { useEffect, useMemo, useState } from "react";
import { FilePlus2, Plus } from "lucide-react";
import { SOURCE_ROLE_LABELS, type LessonBlockCommand, type LessonSourceRangeRead } from "../../api/lessons";
import type { MaterialRead } from "../../api/materials";
import { Button, ErrorState, IconButton, LoadingState, Select } from "../../components/ui";
import { LessonOutlineList, outlineSections } from "./LessonOutlineList";
import type { LessonPickerTarget } from "./LessonSourcePicker";
import { pagesLabel } from "./LessonSourcesDialog";

interface LessonOutlineTabProps {
  materials: MaterialRead[];
  ranges: LessonSourceRangeRead[] | null;
  rangesError: string;
  /** Тема не изучаемая (раздел) — диапазонов у неё не бывает. */
  hasTopic: boolean;
  busy: boolean;
  lessonId: string | null;
  onCreate(materialId: string): void;
  onOpenPage(target: LessonPickerTarget): void;
  onAdd(command: Omit<LessonBlockCommand, "expected_revision">): void;
}

/**
 * Оглавление учебника целиком, а не только диапазон текущей темы.
 *
 * Диапазон темы повторяет «Быстрый урок», и сам по себе вкладки не стоит.
 * Ценность в соседях: пример из другого параграфа, сводная таблица в конце
 * главы, введение раздела — их видно только в полном оглавлении источника.
 */
export function LessonOutlineTab({
  materials, ranges, rangesError, hasTopic, busy, lessonId, onCreate, onOpenPage, onAdd,
}: LessonOutlineTabProps) {
  const [materialId, setMaterialId] = useState<string | null>(null);
  const preferred = ranges?.find((item) => materials.some((material) => material.id === item.material_id))?.material_id
    ?? materials[0]?.id ?? null;

  useEffect(() => { setMaterialId(preferred); }, [preferred]);

  const material = materials.find((item) => item.id === materialId) ?? materials[0] ?? null;
  const pageCount = material?.page_count ?? 1;
  const sections = useMemo(
    () => (material ? outlineSections(material.outline, pageCount) : []),
    [material, pageCount],
  );
  const range = ranges?.find((item) => item.material_id === material?.id) ?? null;

  if (rangesError) return <ErrorState message={rangesError} />;
  if (materials.length === 0) return <p className="lessons-panel-hint">В проекте нет материалов со страницами.</p>;

  return (
    <div className="lessons-outline-tab">
      <section className="lessons-outline-topic">
        <h3>Страницы темы из оглавления</h3>
        {!hasTopic && <p className="lessons-panel-hint">Выберите тему — здесь появятся её страницы из оглавления.</p>}
        {hasTopic && !ranges && <LoadingState label="Загружаем диапазоны темы" />}
        {hasTopic && ranges?.length === 0 && (
          <p className="lessons-panel-hint">У темы нет страниц из оглавления — соберите урок из пунктов ниже.</p>
        )}
        {hasTopic && ranges && ranges.length > 0 && (
          <ul className="lessons-outline-list">
            {ranges.map((item) => (
              <li key={item.material_id}>
                <div className="lessons-outline-title">
                  <strong>{item.source_name}</strong>
                  <span>{SOURCE_ROLE_LABELS[item.source_role]}</span>
                </div>
                <p>
                  Оглавление: {pagesLabel(item.outline_page_from, item.outline_page_to)}
                  {(item.page_from !== item.outline_page_from || item.page_to !== item.outline_page_to
                    || item.starts_at_heading || item.ends_mid_page) && (
                    <> · уточнено: {pagesLabel(item.page_from, item.page_to)}
                      {item.starts_at_heading ? ", с заголовка" : ""}{item.ends_mid_page ? ", до следующего пункта" : ""}</>
                  )}
                </p>
                {!item.is_parsed && <p className="lessons-panel-hint">Материал не разобран: урок пойдёт по страницам, без привязок.</p>}
                <div className="lessons-outline-actions">
                  <Button variant="secondary" disabled={busy} onClick={() => onCreate(item.material_id)}>
                    <FilePlus2 size={14} />Новый урок из диапазона
                  </Button>
                  <Button
                    variant="ghost"
                    disabled={!lessonId || busy}
                    onClick={() => onAdd({ operation: "add_outline", material_id: item.material_id, page_from: item.page_from, page_to: item.page_to })}
                  >
                    <Plus size={14} />Добавить всё в урок
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="lessons-outline-source">
        <h3>Оглавление источника</h3>
        {materials.length > 1 && (
          <Select
            ariaLabel="Источник оглавления"
            value={material?.id ?? null}
            options={materials.map((item) => ({ value: item.id, label: item.display_name || item.original_name }))}
            onValueChange={(value) => { if (value) setMaterialId(value); }}
          />
        )}
        <LessonOutlineList
          sections={sections}
          page={range?.page_from ?? 1}
          onPick={(page) => material && onOpenPage({ materialId: material.id, page })}
          renderAction={(section) => (
            <IconButton
              label={`Добавить «${section.item.title}» в урок · ${pagesLabel(section.pageFrom, section.pageTo)}`}
              disabled={!lessonId || busy || !material}
              onClick={() => material && onAdd({
                operation: "add_page", material_id: material.id,
                page_from: section.pageFrom, page_to: section.pageTo,
              })}
            >
              <Plus size={15} />
            </IconButton>
          )}
        />
      </section>
    </div>
  );
}
