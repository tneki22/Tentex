import { Crepe } from "@milkdown/crepe";
import { Milkdown, MilkdownProvider, useEditor } from "@milkdown/react";
import { Check, TriangleAlert } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { conspectImageUrl, uploadConspectImage } from "../../api/conspects";
import { useConspect } from "../../hooks/useConspect";
import { CONSPECT_FEATURE_TEXT } from "./conspectEditorText";
import { Button } from "../ui/Button";
import { ErrorState } from "../ui/ErrorState";
import { LoadingState } from "../ui/LoadingState";

export interface ConspectEditorProps {
  projectId: string;
  nodeId: string;
  onSaved?: () => void;
}

export interface ConspectEditorHandle {
  flush(): Promise<void>;
}

// Прозрачный пиксель: безопасная заглушка для заблокированного источника
// картинки — ничего не запрашивает по сети, в отличие от src="".
const BLOCKED_IMAGE_PLACEHOLDER = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==";

const CONSPECT_IMAGE_URL_PATTERN = /\/conspect-images\/([0-9a-fA-F-]{36})\/file/g;

function extractRetainedImageIds(markdown: string): string[] {
  const ids = new Set<string>();
  for (const match of markdown.matchAll(CONSPECT_IMAGE_URL_PATTERN)) {
    ids.add(match[1]);
  }
  return [...ids];
}

function isOwnConspectImageUrl(url: string, projectId: string): boolean {
  const expectedPrefix = `/api/projects/${encodeURIComponent(projectId)}/conspect-images/`;
  return url.startsWith(expectedPrefix) && url.endsWith("/file");
}

interface ConspectMilkdownProps {
  projectId: string;
  nodeId: string;
  initialMarkdown: string;
  readonly?: boolean;
  onMarkdownChange: (markdown: string, retainedImageIds: string[]) => void;
}

function ConspectMilkdown({
  projectId,
  nodeId,
  initialMarkdown,
  readonly = false,
  onMarkdownChange,
}: ConspectMilkdownProps) {
  useEditor((root) => {
    const crepe = new Crepe({
      root,
      defaultValue: initialMarkdown,
      featureConfigs: {
        ...CONSPECT_FEATURE_TEXT,
        [Crepe.Feature.ImageBlock]: {
          ...CONSPECT_FEATURE_TEXT[Crepe.Feature.ImageBlock],
          onUpload: async (file: File) => {
            const image = await uploadConspectImage(projectId, nodeId, file);
            return conspectImageUrl(projectId, image.id);
          },
          proxyDomURL: (url: string) =>
            isOwnConspectImageUrl(url, projectId) ? url : BLOCKED_IMAGE_PLACEHOLDER,
        },
      },
    });
    crepe.on((api) => {
      api.markdownUpdated((_ctx, markdown) => {
        onMarkdownChange(markdown, extractRetainedImageIds(markdown));
      });
    });
    if (readonly) crepe.setReadonly(true);
    return crepe;
    // Зависимости пустые нарочно: конфигурация читается один раз при монтировании,
    // а пересоздание редактора на смену темы/узла обеспечивает key снаружи.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <Milkdown />;
}

function ConspectSaveStatus({
  status,
  error,
  onReload,
}: {
  status: ReturnType<typeof useConspect>["status"];
  error: Error | null;
  onReload: () => void;
}) {
  if (status === "conflict") {
    return (
      <div className="conspect-editor-conflict" role="alert">
        <div className="conspect-save-status is-conflict">
          <TriangleAlert size={16} aria-hidden="true" />
          <span>Конспект изменили в другой вкладке — эта правка не сохранена.</span>
        </div>
        <Button variant="secondary" onClick={onReload}>Загрузить сохранённую версию</Button>
      </div>
    );
  }
  if (status === "error") {
    return (
      <div className="conspect-save-status is-error" role="status" aria-live="polite">
        <TriangleAlert size={16} aria-hidden="true" />
        <span>{error?.message ?? "Не удалось сохранить"}</span>
        <Button variant="secondary" onClick={onReload}>Повторить</Button>
      </div>
    );
  }
  if (status === "saving") {
    return (
      <div className="conspect-save-status is-saving" role="status" aria-live="polite">
        <span className="conspect-save-status-dot" aria-hidden="true" />
        <span>Сохранение…</span>
      </div>
    );
  }
  if (status === "saved") {
    return (
      <div className="conspect-save-status is-saved" role="status" aria-live="polite">
        <Check size={14} aria-hidden="true" />
        <span>Сохранено</span>
      </div>
    );
  }
  return null;
}

export const ConspectEditor = forwardRef<ConspectEditorHandle, ConspectEditorProps>(
  function ConspectEditor({ projectId, nodeId, onSaved }, ref) {
    const controller = useConspect(projectId, nodeId);
    const { status, error, flush, reload, scheduleSave, revision } = controller;

    useImperativeHandle(ref, () => ({ flush }), [flush]);

    const savedRevisionRef = useRef(0);
    useEffect(() => {
      if (status === "saved" && revision !== savedRevisionRef.current) {
        savedRevisionRef.current = revision;
        onSaved?.();
      }
    }, [status, revision, onSaved]);

    if (status === "loading") {
      return <LoadingState label="Загружаем конспект" />;
    }

    if (status === "error" && controller.hydrationVersion === 0) {
      // hydrationVersion растёт только при успешной загрузке — если она ещё
      // нулевая, редактору нечего показать: это ошибка первого GET, а не
      // ошибка последующего сохранения уже открытого конспекта.
      return (
        <ErrorState message={error?.message ?? "Не удалось загрузить конспект"}>
          <Button variant="secondary" onClick={() => void reload()}>Повторить</Button>
        </ErrorState>
      );
    }

    return (
      <div className="conspect-editor conspect-editor-fade-enter">
        <ConspectSaveStatus status={status} error={error} onReload={() => void reload()} />
        <div className="conspect-editor-surface">
          <MilkdownProvider>
            <ConspectMilkdown
              key={`${projectId}:${nodeId}:${controller.hydrationVersion}`}
              projectId={projectId}
              nodeId={nodeId}
              initialMarkdown={controller.content}
              onMarkdownChange={scheduleSave}
            />
          </MilkdownProvider>
        </div>
      </div>
    );
  },
);
