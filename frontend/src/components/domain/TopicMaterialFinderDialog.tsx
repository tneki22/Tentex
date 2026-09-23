import { Dialog } from "../ui";
import { TopicMaterialFinder, type FinderTopic } from "./TopicMaterialFinder";

interface TopicMaterialFinderDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  topic: FinderTopic;
  hasProjectMaterials?: boolean;
  onAttached?: (materialId: string) => void;
  onFindOnline?: () => void;
}

/** Подбор материала для одной темы там, где нет места под встроенный блок: пустой урок. */
export function TopicMaterialFinderDialog({
  open, onOpenChange, projectId, topic, hasProjectMaterials, onAttached, onFindOnline,
}: TopicMaterialFinderDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      className="topic-materials-dialog"
      title={`Материал к теме «${topic.title}»`}
      description="Что есть в Библиотеке и где искать ещё. Подключённый материал появится в поиске урока."
    >
      {open && (
        <TopicMaterialFinder
          projectId={projectId}
          topic={topic}
          hasProjectMaterials={hasProjectMaterials}
          onAttached={onAttached}
          onFindOnline={onFindOnline}
        />
      )}
    </Dialog>
  );
}
