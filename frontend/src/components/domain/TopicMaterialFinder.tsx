import { useEffect, useState } from "react";
import { Globe, GraduationCap, UploadCloud } from "lucide-react";
import { Link } from "react-router";
import { attachLibraryMaterial } from "../../api/materials";
import { suggestMaterialsForNodes, type MaterialSuggestion, type MaterialSuggestions } from "../../api/materialSuggestions";
import type { MaterialKindHint } from "../../api/projects";
import { Button } from "../ui";
import { MaterialHint } from "./MaterialHint";
import { MaterialSuggestionList } from "./MaterialSuggestionList";

export interface FinderTopic {
  id: string;
  title: string;
  material_search_queries: string[];
  material_kind: MaterialKindHint | null;
}

interface TopicMaterialFinderProps {
  projectId: string;
  topic: FinderTopic;
  /** Первый подключённый материал проекта становится основным. */
  hasProjectMaterials: boolean;
  onAttached?: (materialId: string) => void;
  /** Поиск в интернете по явной кнопке; не передан — кнопки нет. */
  onFindOnline?: () => void;
}

/**
 * Где взять материал для темы без него: подсказка ИИ, материалы Библиотеки,
 * найденные по теме без модели, и пути дальше — искать в материалах проекта,
 * в интернете или загрузить своё. Подключение не привязывает материал к теме:
 * это делает урок, собранный из найденного.
 */
export function TopicMaterialFinder({
  projectId, topic, hasProjectMaterials, onAttached, onFindOnline,
}: TopicMaterialFinderProps) {
  const [result, setResult] = useState<MaterialSuggestions | null>(null);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [attached, setAttached] = useState<Set<string>>(new Set());
  const [attachError, setAttachError] = useState("");

  useEffect(() => {
    const abort = new AbortController();
    setResult(null);
    setError("");
    suggestMaterialsForNodes(projectId, [topic.id], abort.signal)
      .then((value) => setResult(value.by_node[topic.id] ?? null))
      .catch((caught) => {
        if (!abort.signal.aborted) setError(caught instanceof Error ? caught.message : "Подбор не удался");
      });
    return () => abort.abort();
  }, [projectId, topic.id, reloadKey]);

  async function attach(item: MaterialSuggestion) {
    setBusyId(item.material_id);
    setAttachError("");
    try {
      await attachLibraryMaterial(item.material_id, {
        project_id: projectId,
        source_role: hasProjectMaterials || attached.size > 0 ? "additional" : "main",
        purposes: ["study_source"],
      });
      setAttached((current) => new Set(current).add(item.material_id));
      onAttached?.(item.material_id);
    } catch (caught) {
      setAttachError(caught instanceof Error ? caught.message : "Не удалось подключить материал");
    } finally {
      setBusyId(null);
    }
  }

  const lessonsLink = `/projects/${projectId}/lessons?topic=${encodeURIComponent(topic.id)}`;

  return (
    <div className="topic-material-finder">
      <MaterialHint queries={topic.material_search_queries} kind={topic.material_kind} />
      <section className="topic-material-finder-library" aria-label="Подходит из Библиотеки">
        <h4>Из Библиотеки</h4>
        {!result && !error && <p className="topic-material-finder-note" role="status">Ищем в Библиотеке…</p>}
        {error && (
          <p className="topic-material-finder-note is-error" role="alert">
            {error} <Button variant="ghost" onClick={() => setReloadKey((key) => key + 1)}>Повторить</Button>
          </p>
        )}
        {result && result.items.length === 0 && (
          <p className="topic-material-finder-note">В Библиотеке нет подходящего — найдите в интернете или загрузите своё.</p>
        )}
        {result && result.items.length > 0 && (
          <MaterialSuggestionList items={result.items} attachedIds={attached} busyId={busyId} onAttach={(item) => void attach(item)} />
        )}
        {result?.words_only && result.items.length > 0 && (
          <p className="topic-material-finder-note">Подбор шёл по словам: активного поискового индекса нет.</p>
        )}
        {attachError && <p className="inline-error" role="alert">{attachError}</p>}
        {attached.size > 0 && (
          <p className="topic-material-finder-note is-success">
            Материал в проекте. Чтобы тема получила его, <Link to={lessonsLink}>соберите урок из найденного</Link>.
          </p>
        )}
      </section>
      <div className="topic-material-finder-actions">
        <Link className="secondary-button" to={lessonsLink}><GraduationCap size={15} />Искать в материалах проекта</Link>
        {onFindOnline && <Button variant="secondary" onClick={onFindOnline}><Globe size={15} />Найти в интернете</Button>}
        <Link className="text-button" to={`/projects/${projectId}/materials`}><UploadCloud size={15} />Загрузить своё</Link>
      </div>
    </div>
  );
}
