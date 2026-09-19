import { useEffect, useState } from "react";
import { getTopicSources, type LessonBlockCommand, type LessonBlockRead, type LessonSourceRangeRead } from "../../api/lessons";
import { listMaterials, type MaterialRead } from "../../api/materials";
import { EmptyState, ErrorState, LoadingState, SegmentedTabs, Select } from "../../components/ui";
import type { ProgramTreeNode } from "../programTree";
import { insertOptions, insertValue, parseInsertValue, type LessonInsertPoint } from "./lessonBlocks";
import { LessonOutlineTab } from "./LessonOutlineTab";
import { LessonPagesTab } from "./LessonPagesTab";
import { LessonSearchTab, useMaterialSearch } from "./LessonSearchTab";
import { LessonSourcePicker, type LessonPickerTarget } from "./LessonSourcePicker";
import { LessonSuggestedTab } from "./LessonSuggestedTab";
import { errorText } from "./lessonTree";

type PanelTab = "outline" | "pages" | "search" | "suggested";

const PANEL_TABS: Array<{ value: PanelTab; label: string }> = [
  { value: "search", label: "Поиск" },
  { value: "suggested", label: "Предложено" },
  { value: "pages", label: "Страницы" },
  { value: "outline", label: "Оглавление" },
];

interface LessonMaterialPanelProps {
  projectId: string;
  topic: ProgramTreeNode | null;
  busy: boolean;
  /** Урок уже создан в этой сессии — перечитать диапазоны после изменений. */
  refreshKey: number;
  onCreateFromRange(materialId: string): void;
  lessonId: string | null;
  /** `${materialId}#${page}` страниц открытого урока: уже добавленное помечается «в уроке». */
  lessonPages: Set<string>;
  blocks: LessonBlockRead[];
  insertPoint: LessonInsertPoint;
  onInsertPointChange(point: LessonInsertPoint): void;
  onAdd(command: Omit<LessonBlockCommand, "expected_revision">): Promise<boolean>;
}

/** Правая панель «Материал для урока»: четыре вкладки (записка §2). */
export function LessonMaterialPanel({
  projectId, topic, busy, refreshKey, onCreateFromRange, lessonId, lessonPages,
  blocks, insertPoint, onInsertPointChange, onAdd,
}: LessonMaterialPanelProps) {
  const [tab, setTab] = useState<PanelTab>("suggested");
  const [picker, setPicker] = useState<LessonPickerTarget | null>(null);
  const materials = useProjectMaterials(projectId);
  const studyTopic = topic && topic.node_type !== "section" ? topic : null;
  const ranges = useTopicRanges(projectId, studyTopic?.id ?? null, refreshKey);
  const search = useMaterialSearch(projectId, studyTopic?.id, studyTopic?.title ?? "");

  return (
    <div className="lessons-material-panel">
      <header className="lessons-panel-head">
        <h2>Материал для урока</h2>
        <SegmentedTabs label="Материал для урока" value={tab} tabs={PANEL_TABS} onChange={setTab} className="lessons-panel-tabs" />
        <label className="lessons-insert-row">
          <span>Куда вставить</span>
          <Select
            ariaLabel="Куда вставить в урок"
            value={insertValue(insertPoint)}
            options={insertOptions(blocks)}
            disabled={!lessonId}
            onValueChange={(value) => { if (value) onInsertPointChange(parseInsertValue(value)); }}
          />
        </label>
      </header>
      <div className="lessons-panel-body">
        {materials.error && <ErrorState message={materials.error} />}
        {!materials.error && !materials.items && <LoadingState label="Загружаем материалы проекта" />}
        {!materials.error && materials.items && (
          <>
            {tab === "search" && (
              <LessonSearchTab
                search={search}
                busy={busy}
                lessonId={lessonId}
                lessonPages={lessonPages}
                onOpenPlace={setPicker}
                onAdd={(command) => void onAdd(command)}
              />
            )}
            {tab === "pages" && (
              <LessonPagesTab
                projectId={projectId}
                materials={materials.items}
                ranges={ranges.items}
                busy={busy}
                lessonId={lessonId}
                lessonPages={lessonPages}
                onOpenPage={setPicker}
                onAdd={(command) => void onAdd(command)}
              />
            )}
            {tab === "outline" && (
              <LessonOutlineTab
                materials={materials.items}
                ranges={ranges.items}
                rangesError={ranges.error}
                hasTopic={Boolean(studyTopic)}
                busy={busy}
                lessonId={lessonId}
                onCreate={onCreateFromRange}
                onOpenPage={setPicker}
                onAdd={(command) => void onAdd(command)}
              />
            )}
            {tab === "suggested" && (
              studyTopic ? <LessonSuggestedTab
                projectId={projectId}
                topic={studyTopic}
                lessonId={lessonId}
                blocks={blocks}
                busy={busy}
                onAdd={onAdd}
              /> : <EmptyState title="Выберите тему"><p>Предложения прохода 2 показываются для выбранной темы урока.</p></EmptyState>
            )}
          </>
        )}
      </div>
      {picker && materials.items && (
        <LessonSourcePicker
          projectId={projectId}
          lessonId={lessonId}
          busy={busy}
          materials={materials.items}
          target={picker}
          places={tab === "search" ? search.places : []}
          terms={tab === "search" ? search.terms : []}
          lessonPages={lessonPages}
          blocks={blocks}
          insertPoint={insertPoint}
          onInsertPointChange={onInsertPointChange}
          onAdd={onAdd}
          onClose={() => setPicker(null)}
        />
      )}
    </div>
  );
}

/** Материалы проекта со страницами — их листает панель и открывает диалог. */
function useProjectMaterials(projectId: string) {
  const [items, setItems] = useState<MaterialRead[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    listMaterials(projectId, controller.signal)
      .then((loaded) => {
        if (controller.signal.aborted) return;
        setItems(loaded.filter((item) => (item.page_count ?? 0) > 0));
      })
      .catch((caught: unknown) => { if (!controller.signal.aborted) setError(errorText(caught, "Материалы не загрузились")); });
    return () => controller.abort();
  }, [projectId]);

  return { items, error };
}

/** Диапазоны темы из оглавления: нужны и вкладке «Оглавление», и первой странице «Страниц». */
function useTopicRanges(projectId: string, nodeId: string | null, refreshKey: number) {
  const [items, setItems] = useState<LessonSourceRangeRead[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!nodeId) {
      setItems(null);
      return;
    }
    const controller = new AbortController();
    setItems(null);
    setError("");
    getTopicSources(projectId, nodeId, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setItems(result.ranges); })
      .catch((caught: unknown) => { if (!controller.signal.aborted) setError(errorText(caught, "Диапазоны не загрузились")); });
    return () => controller.abort();
  }, [projectId, nodeId, refreshKey]);

  return { items, error };
}
