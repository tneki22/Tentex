import { Image as ImageIcon, Play, Sparkles } from "lucide-react";
import { QualityBadge, SourceChip } from "../../components/domain";
import { Button, StatusBadge, Tooltip } from "../../components/ui";
import type { LessonBlockDemo, LessonDocumentDemo, LessonSourceRefDemo } from "./lessonsDemo";

interface LessonDocumentProps {
  document: LessonDocumentDemo;
  mode: "study" | "editor";
  selectedBlockId?: string | null;
  onSelectBlock?: (blockId: string) => void;
}

function Sources({ sourceRefs }: { sourceRefs: LessonSourceRefDemo[] }) {
  if (!sourceRefs.length) return null;
  return <div className="lessons-block-sources">{sourceRefs.map((source, index) => (
    <span className="lessons-block-source" key={`${source.fragmentId ?? "model"}-${index}`}>
      {source.origin === "model-knowledge" ? <><SourceChip source={{ kind: "none" }} /><span>Знания модели · без источника</span></> : <><SourceChip source={{ kind: "manual" }} /><span>{source.availability === "missing" ? "Источник недоступен" : `${source.material} · стр. ${source.page}`}</span>{source.quality && <QualityBadge quality={source.quality} />}</>}
    </span>
  ))}</div>;
}

function BlockBody({ block }: { block: LessonBlockDemo }) {
  switch (block.type) {
    case "rich-text": return <>{block.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}</>;
    case "callout": return <aside className={`lessons-callout is-${block.tone}`}><strong>{block.title}</strong><p>{block.body}</p></aside>;
    case "image": return <figure className={`lessons-image-placeholder ${block.assetState === "missing" ? "is-missing" : ""}`}><div role="img" aria-label={block.alt}><ImageIcon size={28} aria-hidden="true" /><span>{block.alt}</span></div><figcaption>{block.caption}</figcaption></figure>;
    case "diagram": return <figure className="lessons-diagram" aria-label={block.alt}><figcaption>{block.title}</figcaption><div>{block.preview.split("→").map((part) => <span key={part}>{part.trim()}</span>)}</div></figure>;
    case "sql-activity": return <section className="lessons-sql"><div><StatusBadge tone="info">SQL-задача · {block.dialect}</StatusBadge><p>{block.prompt}</p></div><textarea aria-label="SQL-решение" placeholder="SELECT …" readOnly /><div><Tooltip label="Будет доступно в Сессии"><span><Button variant="secondary" disabled><Play size={15} />Запустить</Button></span></Tooltip><Tooltip label="Будет доступно в Сессии"><span><Button disabled>Проверить</Button></span></Tooltip></div></section>;
  }
}

export function LessonDocument({ document, mode, selectedBlockId, onSelectBlock }: LessonDocumentProps) {
  return <article className={`lessons-document is-${mode}`}>
    {document.sections.map((section) => <section className="lessons-document-section" key={section.id}>
      <header><h2>{section.title}</h2><p>{section.objective}</p></header>
      {section.rows.map((row) => <div className={`lessons-row is-${row.preset}`} key={row.id}>
        {row.blocks.map((block) => {
          const selected = selectedBlockId === block.id;
          return <div className={`lessons-block is-${block.type} ${selected ? "is-selected" : ""}`.trim()} key={block.id}>
            {mode === "editor" && <button className="lessons-block-select" type="button" aria-pressed={selected} onClick={() => onSelectBlock?.(block.id)}><Sparkles size={14} aria-hidden="true" /><span>Выбрать блок</span></button>}
            <BlockBody block={block} />
            <Sources sourceRefs={block.sourceRefs} />
          </div>;
        })}
      </div>)}
    </section>)}
  </article>;
}
