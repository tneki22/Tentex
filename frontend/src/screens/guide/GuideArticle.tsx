import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Bot,
  BrainCircuit,
  CheckCircle2,
  Compass,
  Download,
  FilePenLine,
  FilePlus2,
  Files,
  FolderPlus,
  GraduationCap,
  HardDrive,
  Image as ImageIcon,
  Info,
  KeyRound,
  Lightbulb,
  ListTree,
  Mic,
  OctagonAlert,
  ScanText,
  Search,
  Sparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { MarkdownInline, MarkdownView, type MarkdownOptions } from "../../components/domain/markdown/MarkdownView";
import { GuideDiagram } from "./GuideDiagrams";
import type { CalloutTone, GuideBlock, GuideCardData } from "./guideDocument";
import type { FlatGuidePage } from "./guideSections";

/** Иконки карточек: в тексте страницы пишется `[FolderPlus] Заголовок`. */
const CARD_ICONS: Record<string, LucideIcon> = {
  BookOpen, Bot, BrainCircuit, Compass, Download, FilePenLine, FilePlus2, Files, FolderPlus, GraduationCap, HardDrive,
  Image: ImageIcon, KeyRound, ListTree, Mic, ScanText, Search, Sparkles,
};

const CALLOUTS: Record<CalloutTone, { icon: LucideIcon; title: string }> = {
  info: { icon: Info, title: "Заметка" },
  tip: { icon: Lightbulb, title: "Совет" },
  success: { icon: CheckCircle2, title: "Готово" },
  warning: { icon: AlertTriangle, title: "Важно" },
  danger: { icon: OctagonAlert, title: "Осторожно" },
};

/** Файлы рисунков лежат в `assets/`; в тексте на них ссылаются по имени. */
const ASSET_URLS = import.meta.glob<string>("./assets/*", { eager: true, query: "?url", import: "default" });

function assetUrl(src: string): string | null {
  if (/^(https?:)?\/\//.test(src)) return src;
  return ASSET_URLS[`./assets/${src}`] ?? null;
}

function picture(alt: string, src: string, key: string): ReactNode {
  const url = assetUrl(src);
  if (!url) return <span key={key} className="guide-missing">Рисунок «{src}» не найден в assets</span>;
  return <img key={key} className="guide-image" src={url} alt={alt} loading="lazy" />;
}

const MARKDOWN_OPTIONS: MarkdownOptions = { renderImage: picture };

function Prose({ text }: { text: string }) {
  return <MarkdownView className="guide-md" text={text} options={MARKDOWN_OPTIONS} />;
}

function Card({ card }: { card: GuideCardData }) {
  const Icon = (card.icon && CARD_ICONS[card.icon]) || null;
  const body = (
    <>
      {Icon && <span className="guide-card-icon"><Icon size={18} aria-hidden="true" /></span>}
      <span className="guide-card-title">{card.title}</span>
      {card.text && <span className="guide-card-text"><MarkdownInline text={card.text} /></span>}
      {card.to && <ArrowRight className="guide-card-arrow" size={15} aria-hidden="true" />}
    </>
  );
  return card.to
    ? <Link className="guide-card is-link" to={card.to}>{body}</Link>
    : <div className="guide-card">{body}</div>;
}

function Block({ block }: { block: GuideBlock }): ReactNode {
  switch (block.kind) {
    case "md":
      return <Prose text={block.text} />;
    case "heading":
      return <h3 id={block.id} className="guide-heading">{block.title}</h3>;
    case "callout": {
      const { icon: Icon, title } = CALLOUTS[block.tone];
      return (
        <aside className={`guide-callout is-${block.tone}`}>
          <Icon size={18} aria-hidden="true" />
          <div>
            <strong className="guide-callout-title">{block.title ?? title}</strong>
            <Prose text={block.text} />
          </div>
        </aside>
      );
    }
    case "cards":
      return <div className="guide-cards">{block.cards.map((card, index) => <Card key={index} card={card} />)}</div>;
    case "steps":
      return <div className="guide-steps"><Prose text={block.text} /></div>;
    case "diagram":
      return (
        <figure className="guide-figure is-diagram">
          <GuideDiagram name={block.name} />
          {block.caption && <figcaption><MarkdownInline text={block.caption} /></figcaption>}
        </figure>
      );
    case "figure": {
      const url = assetUrl(block.src);
      return (
        <figure className="guide-figure">
          {url
            ? <a href={url} target="_blank" rel="noopener noreferrer"><img className="guide-image" src={url} alt={block.alt} loading="lazy" /></a>
            : <span className="guide-missing">Рисунок «{block.src}» не найден в assets</span>}
          {block.caption && <figcaption><MarkdownInline text={block.caption} /></figcaption>}
        </figure>
      );
    }
  }
}

/** Страница, у которой ещё нет файла: в дереве она есть, текста пока нет. */
function Draft({ item }: { item: FlatGuidePage }) {
  const children = item.page.children ?? [];
  return (
    <div className="guide-draft">
      <FilePenLine size={22} aria-hidden="true" />
      <div>
        <strong>Раздел ещё пишется</strong>
        <p>Здесь будет «{item.page.title}». Пока можно перейти к соседним разделам через дерево слева.</p>
        {children.length > 0 && (
          <ul>
            {children.map((child) => (
              <li key={child.slug}><Link to={`/guide?section=${child.slug}`}>{child.title}</Link></li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

interface GuideArticleProps {
  item: FlatGuidePage;
  /** `null` — файла страницы нет. */
  blocks: GuideBlock[] | null;
  previous: FlatGuidePage | null;
  next: FlatGuidePage | null;
}

export function GuideArticle({ item, blocks, previous, next }: GuideArticleProps) {
  return (
    <article className="guide-article" key={item.page.slug}>
      <header className="guide-article-head">
        <p className="eyebrow">
          {item.group.title}{item.parent ? ` · ${item.parent.title}` : ""}
        </p>
        <h2>{item.page.title}</h2>
      </header>
      {blocks
        ? blocks.map((block, index) => <Block key={index} block={block} />)
        : <Draft item={item} />}
      <nav className="guide-pager" aria-label="Соседние разделы">
        {previous ? (
          <Link to={`/guide?section=${previous.page.slug}`} className="guide-pager-link is-previous">
            <small>Назад</small>
            <span>{previous.page.title}</span>
          </Link>
        ) : <span />}
        {next ? (
          <Link to={`/guide?section=${next.page.slug}`} className="guide-pager-link is-next">
            <small>Далее</small>
            <span>{next.page.title}</span>
          </Link>
        ) : <span />}
      </nav>
    </article>
  );
}
