import { Dialog, Disclosure } from "../../components/ui";
import { TopicMaterialFinder, type FinderTopic } from "../../components/domain";

interface TopicMaterialsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  /** Темы программы, к которым ещё не привязан материал, в порядке дерева. */
  topics: Array<FinderTopic & { number: string }>;
  hasProjectMaterials: boolean;
  onAttached: () => void;
}

/**
 * «Материалы к темам» свободного проекта: консультант, который читает пробелы.
 * По каждой теме без материала — подсказка ИИ и находки Библиотеки; подбор
 * запускается, только когда тему раскрыли, чтобы не гонять поиск по всем сразу.
 */
export function TopicMaterialsDialog({
  open, onOpenChange, projectId, topics, hasProjectMaterials, onAttached,
}: TopicMaterialsDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      className="topic-materials-dialog"
      title="Материалы к темам"
      description={topics.length
        ? "Темы без материала — обычное состояние свободного изучения. Раскройте тему: подскажем, что есть в Библиотеке и где искать ещё."
        : "У каждой темы программы уже есть материал."}
    >
      <div className="topic-materials-list">
        {topics.map((topic) => (
          <Disclosure key={topic.id} summary={`${topic.number} ${topic.title}`} className="topic-materials-row">
            <TopicMaterialFinder
              projectId={projectId}
              topic={topic}
              hasProjectMaterials={hasProjectMaterials}
              onAttached={onAttached}
            />
          </Disclosure>
        ))}
      </div>
    </Dialog>
  );
}
