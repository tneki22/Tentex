import { Tabs } from "radix-ui";
import type {
  LibraryMaterialDetailRead,
  MaterialPageRead,
  MaterialRevisionRead,
  ParserMode,
  ProcessingScope,
} from "../../api/materials";
import { LibraryMaterialFilePanel } from "./LibraryMaterialFilePanel";
import { LibraryProcessingPanel } from "./LibraryProcessingPanel";
import { MaterialRevisionPanel } from "./MaterialRevisionPanel";

export type InspectorTab = "processing" | "revisions" | "file";

const TABS: Array<{ value: InspectorTab; label: string }> = [
  { value: "processing", label: "Обработка" },
  { value: "revisions", label: "Версии" },
  { value: "file", label: "Файл" },
];

interface LibraryMaterialInspectorProps {
  material: LibraryMaterialDetailRead;
  page: MaterialPageRead | null;
  revisions: MaterialRevisionRead[];
  selectedRevision: number | null;
  compareRevision: number | null;
  tab: InspectorTab;
  busy: boolean;
  readOnly: boolean;
  onTabChange: (tab: InspectorTab) => void;
  onSelectRevision: (revision: number | null) => void;
  onCompareRevision: (revision: number | null) => void;
  onStart: (command: {
    parser_mode: ParserMode;
    scope: ProcessingScope;
    page_from?: number;
    page_to?: number;
  }) => void;
  onControl: (action: "pause" | "resume" | "retry" | "cancel") => void;
  onTypstBuild: (downloadPackages: boolean, entrypoint?: string) => void;
  onTypstAddFile: (file: File, targetPath: string) => void;
  onEditPage: () => void;
  onCleanupPage: () => void;
  onConfirmPageReview: () => void;
  onRestore: (revision: number) => void;
  onAddToProject: () => void;
  onRefreshSource: () => void;
  onDelete: () => void;
}

/**
 * Правая колонка рабочей области: обработка, версии, файл. Порядок вкладок
 * постоянный — это три разговора об одном материале, а не список настроек.
 * Привязок здесь нет: они принадлежат проекту.
 */
export function LibraryMaterialInspector({
  material,
  page,
  revisions,
  selectedRevision,
  compareRevision,
  tab,
  busy,
  readOnly,
  onTabChange,
  onSelectRevision,
  onCompareRevision,
  onStart,
  onControl,
  onTypstBuild,
  onTypstAddFile,
  onEditPage,
  onCleanupPage,
  onConfirmPageReview,
  onRestore,
  onAddToProject,
  onRefreshSource,
  onDelete,
}: LibraryMaterialInspectorProps) {
  return (
    <aside className="library-inspector" aria-label="Обработка, версии и файл">
      <Tabs.Root
        className="inspector-tabs-root"
        value={tab}
        onValueChange={(next) => onTabChange(next as InspectorTab)}
      >
        <Tabs.List className="inspector-tabs" aria-label="Разделы инспектора">
          {TABS.map((item) => (
            <Tabs.Trigger key={item.value} value={item.value} className="inspector-tab">
              {item.label}
              {item.value === "revisions" && revisions.length > 0 && (
                <span className="inspector-tab-count">{revisions.length}</span>
              )}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        <div className="inspector-scroll">
          <Tabs.Content value="processing">
            <LibraryProcessingPanel
              material={material}
              page={page}
              busy={busy}
              readOnly={readOnly}
              onStart={onStart}
              onControl={onControl}
              onTypstBuild={onTypstBuild}
              onTypstAddFile={onTypstAddFile}
              onEditPage={onEditPage}
              onCleanupPage={onCleanupPage}
              onConfirmPageReview={onConfirmPageReview}
            />
          </Tabs.Content>
          <Tabs.Content value="revisions">
            <MaterialRevisionPanel
              material={material}
              revisions={revisions}
              selected={selectedRevision}
              compared={compareRevision}
              busy={busy}
              onSelect={onSelectRevision}
              onCompare={onCompareRevision}
              onRestore={onRestore}
            />
          </Tabs.Content>
          <Tabs.Content value="file">
            <LibraryMaterialFilePanel
              material={material}
              busy={busy}
              onAddToProject={onAddToProject}
              onRefreshSource={onRefreshSource}
              onDelete={onDelete}
            />
          </Tabs.Content>
        </div>
      </Tabs.Root>
    </aside>
  );
}
