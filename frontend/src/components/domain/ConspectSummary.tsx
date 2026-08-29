import { Crepe } from "@milkdown/crepe";
import { Milkdown, MilkdownProvider, useEditor } from "@milkdown/react";
import { useMemo } from "react";
import { Link } from "react-router";
import type { ConspectSummaryEntry } from "../../api/conspects";
import { useConspectSummary } from "../../hooks/useConspect";
import { CONSPECT_FEATURE_TEXT } from "./conspectEditorText";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { ErrorState } from "../ui/ErrorState";
import { LoadingState } from "../ui/LoadingState";

export interface ConspectSummaryProps {
  projectId: string;
  refreshKey?: number;
  showTopicIndex?: boolean;
}

// Тот же приём, что в ConspectEditor: изображение показываем, только если
// его адрес правда принадлежит conspect-images этого проекта.
const BLOCKED_IMAGE_PLACEHOLDER = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==";

function isOwnConspectImageUrl(url: string, projectId: string): boolean {
  const expectedPrefix = `/api/projects/${encodeURIComponent(projectId)}/conspect-images/`;
  return url.startsWith(expectedPrefix) && url.endsWith("/file");
}

function escapeHeadingTitle(title: string): string {
  const singleLine = title.replace(/\s+/g, " ").trim();
  // Ведущий маркер списка/цитаты/заголовка в самой формулировке темы не должен
  // сойти за разметку сводного документа.
  return singleLine.replace(/^([#>*+-]|\d+[.)])/, "\\$1");
}

function buildSummaryMarkdown(entries: ConspectSummaryEntry[]): string {
  return entries
    .map((entry) => `## ${entry.position}. ${escapeHeadingTitle(entry.title)}\n\n${entry.content_markdown}`)
    .join("\n\n---\n\n");
}

function ReadonlyConspectDocument({ projectId, markdown }: { projectId: string; markdown: string }) {
  useEditor((root) => {
    const crepe = new Crepe({
      root,
      defaultValue: markdown,
      featureConfigs: {
        ...CONSPECT_FEATURE_TEXT,
        [Crepe.Feature.ImageBlock]: {
          ...CONSPECT_FEATURE_TEXT[Crepe.Feature.ImageBlock],
          proxyDomURL: (url: string) =>
            isOwnConspectImageUrl(url, projectId) ? url : BLOCKED_IMAGE_PLACEHOLDER,
        },
      },
    });
    crepe.setReadonly(true);
    return crepe;
    // markdown в deps нарочно: Crepe неуправляем после монтирования, и это —
    // единственный способ показать документ следующего сохранения без
    // отдельного key на всё дерево.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [markdown]);

  return <Milkdown />;
}

export function ConspectSummary({ projectId, refreshKey = 0, showTopicIndex = false }: ConspectSummaryProps) {
  const { entries, loading, error, reload } = useConspectSummary(projectId, refreshKey);
  const markdown = useMemo(() => buildSummaryMarkdown(entries), [entries]);

  if (loading) return <LoadingState label="Загружаем сводный конспект" />;

  if (error) {
    return (
      <ErrorState message={error.message}>
        <Button variant="secondary" onClick={() => void reload()}>Повторить</Button>
      </ErrorState>
    );
  }

  if (entries.length === 0) {
    return (
      <EmptyState title="Пока нечего показать">
        <p>Появится, как только сохранится хоть один личный конспект темы.</p>
      </EmptyState>
    );
  }

  return (
    <div className="conspect-summary">
      {showTopicIndex && (
        <nav className="conspect-summary-index" aria-label="Темы со своим конспектом">
          {entries.map((entry) => (
            <Link
              key={entry.node_id}
              to={`/projects/${projectId}?topic=${entry.node_id}&tab=conspect`}
              className="conspect-summary-index-item"
            >
              {entry.position}. {entry.title}
            </Link>
          ))}
        </nav>
      )}
      <div className="conspect-summary-document">
        <MilkdownProvider>
          <ReadonlyConspectDocument projectId={projectId} markdown={markdown} />
        </MilkdownProvider>
      </div>
    </div>
  );
}
