import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { BookOpen, ExternalLink } from "lucide-react";
import type { LessonRefRead } from "../../../api/lessons";
import { materialPageImageUrl } from "../../../api/materials";
import { Popover } from "../../ui/Popover";
import { MarkdownView, type MarkdownOptions } from "../markdown/MarkdownView";

/**
 * Картинка из Markdown.
 *
 * `blob:` живёт только до перезагрузки вкладки: изображение, брошенное прямо в
 * редактор пояснения, после неё не открывается и раньше оставалось в тексте
 * строкой `![1.00](blob:…)`. Вместо мёртвой картинки — честная пометка;
 * изображения урока добавляются блоком «Медиа», у него файл на диске.
 */
function picture(alt: string, url: string, key: string): ReactNode {
  if (/^(https?:|\/api\/)/.test(url)) {
    return <img key={key} className="lesson-markdown-image" src={url} alt={alt} loading="lazy" />;
  }
  return <span key={key} className="lesson-markdown-missing">Изображение не сохранилось{alt ? `: ${alt}` : ""}</span>;
}

export function refPages(ref: Pick<LessonRefRead, "page_from" | "page_to">): string {
  return ref.page_from === ref.page_to ? `стр. ${ref.page_from}` : `стр. ${ref.page_from}–${ref.page_to}`;
}

/** Окно опоры `[S3]`: источник, страницы и сам лист — проверить утверждение глазами. */
function CitationPreview({ projectId, sourceRef: ref }: { projectId: string; sourceRef: LessonRefRead }) {
  const materialId = ref.material_id;
  return (
    <div className="lesson-citation-preview">
      <header>
        <span className="chat-source-id">{ref.citation_label}</span>
        <div>
          <strong>{ref.source_name}</strong>
          <small>{refPages(ref)}{ref.from_fragment_id ? " · с абзаца" : ""}</small>
        </div>
      </header>
      {materialId && ref.is_available ? (
        <>
          <img className="lesson-citation-page" src={materialPageImageUrl(projectId, materialId, ref.page_from)} alt={`${ref.source_name}, страница ${ref.page_from}`} loading="lazy" />
          <Link to={`/projects/${projectId}/materials/${materialId}?page=${ref.page_from}`}>
            Открыть страницу <ExternalLink size={13} aria-hidden="true" />
          </Link>
        </>
      ) : (
        <p className="lesson-source-notice"><BookOpen size={13} aria-hidden="true" /> Материал убран из проекта — остались имя и страницы.</p>
      )}
    </div>
  );
}

interface LessonMarkdownProps {
  text: string;
  className?: string;
  /** Опоры пояснения модели: `[S3]` в тексте открывает свою. Без них ссылки — текст. */
  citations?: LessonRefRead[];
  projectId?: string;
  /** Предложение модели ещё не в уроке: `[S3]` — метка с подписью куска, без окна. */
  citationTitles?: Record<string, string>;
}

/**
 * Пояснение урока в режиме чтения — тот же рендер, что у ответов чата.
 * Crepe пишет пустой абзац как `<br />` и экранирует знаки разметки `\*`:
 * общий разбор понимает и то и другое. Один Crepe на выбранном блоке, остальные — здесь (§3.7).
 */
export function LessonMarkdown({ text, className = "", citations, projectId, citationTitles }: LessonMarkdownProps) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  const options = useMemo<MarkdownOptions>(() => {
    const byLabel = new Map((citations ?? []).filter((ref) => ref.citation_label).map((ref) => [ref.citation_label!, ref]));
    if (citationTitles) {
      return {
        renderImage: picture,
        renderCitation: (id, key) => citationTitles[id]
          ? <span key={key} className="chat-citation is-static" title={citationTitles[id]}>{id}</span>
          : null,
      };
    }
    return {
      renderImage: picture,
      renderCitation: byLabel.size > 0 && projectId ? (id, key) => {
        const ref = byLabel.get(id);
        if (!ref) return null;
        return (
          <Popover
            key={key}
            side="right"
            align="start"
            className="popover-citation"
            open={openKey === key}
            onOpenChange={(open) => setOpenKey((current) => (open ? key : current === key ? null : current))}
            onCloseAutoFocus={(event) => event.preventDefault()}
            trigger={
              <button type="button" className="chat-citation" aria-label={`Опора ${id}: ${ref.source_name}, ${refPages(ref)}`} onClick={(event) => event.stopPropagation()}>
                {id}
              </button>
            }
          >
            <CitationPreview projectId={projectId} sourceRef={ref} />
          </Popover>
        );
      } : undefined,
    };
  }, [citations, projectId, openKey, citationTitles]);
  return <MarkdownView text={text} className={`lesson-markdown ${className}`.trim()} options={options} />;
}
