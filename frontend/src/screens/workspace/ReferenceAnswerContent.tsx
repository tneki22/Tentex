import type { CSSProperties, ReactNode } from "react";
import { legacyBoundImages, type ReferenceAnswerMedia } from "./referenceAnswerMedia";

export type { ReferenceAnswerMedia } from "./referenceAnswerMedia";

const MARKER = /\[(изображение|файл): ([^\]\r\n]+)\]|\[Изображение\]/g;
const LIST_ITEM = /^([ \t]*)(?:([-*+])|(\d+)[.)])\s+(.+)$/;

function indentation(value: string): number {
  return Array.from(value).reduce((total, character) => total + (character === "\t" ? 4 : 1), 0);
}

function indentStyle(value: string): CSSProperties {
  return { paddingInlineStart: `calc(${indentation(value)} * var(--space-1))` };
}

function mediaNode(media: ReferenceAnswerMedia, key: string): ReactNode {
  if (media.kind === "image") {
    return <img className="workspace-reference-media" src={media.url} alt={media.alt} loading="lazy" key={key} />;
  }
  return <a className="workspace-reference-file" href={media.url} download={media.label ?? undefined} key={key}>{media.label ?? "Скачать файл"}</a>;
}

function inlineContent(
  text: string,
  media: ReferenceAnswerMedia[],
  legacyImageIndex: { current: number },
  sourceMaterialId: string | null,
): ReactNode[] {
  const content: ReactNode[] = [];
  let cursor = 0;
  const boundImages = legacyBoundImages(media, sourceMaterialId);

  for (const match of text.matchAll(MARKER)) {
    const marker = match[0];
    const start = match.index ?? 0;
    if (start > cursor) content.push(text.slice(cursor, start));
    const kind = match[1] as "изображение" | "файл" | undefined;
    const label = match[2];
    const resolved = kind
      ? media.find((item) => item.kind === (kind === "изображение" ? "image" : "file") && item.label === label)
      : boundImages[legacyImageIndex.current++];
    content.push(resolved ? mediaNode(resolved, `${start}-${marker}`) : marker);
    cursor = start + marker.length;
  }
  if (cursor < text.length) content.push(text.slice(cursor));
  return content;
}

export function ReferenceAnswerContent({
  text,
  media,
  sourceMaterialId,
}: {
  text: string;
  media: ReferenceAnswerMedia[];
  sourceMaterialId: string | null;
}) {
  const blocks: ReactNode[] = [];
  let list: { ordered: boolean; indent: string; start: number; items: string[] } | null = null;
  const legacyImageIndex = { current: 0 };

  const flushList = () => {
    if (!list) return;
    const Tag = list.ordered ? "ol" : "ul";
    blocks.push(
      <Tag className="workspace-reference-list" start={list.ordered ? list.start : undefined} style={indentStyle(list.indent)} key={`list-${blocks.length}`}>
        {list.items.map((item, index) => <li key={index}>{inlineContent(item, media, legacyImageIndex, sourceMaterialId)}</li>)}
      </Tag>,
    );
    list = null;
  };

  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) {
      flushList();
      blocks.push(<p className="workspace-reference-paragraph is-blank" aria-hidden="true" key={`blank-${blocks.length}`}> </p>);
      continue;
    }
    const item = line.match(LIST_ITEM);
    if (item) {
      const indent = item[1];
      const ordered = Boolean(item[3]);
      if (!list || list.ordered !== ordered || list.indent !== indent) {
        flushList();
        list = { ordered, indent, start: ordered ? Number(item[3]) : 1, items: [] };
      }
      list.items.push(item[4]);
      continue;
    }
    flushList();
    const leading = line.match(/^[ \t]*/)?.[0] ?? "";
    blocks.push(<p className="workspace-reference-paragraph" style={indentStyle(leading)} key={`paragraph-${blocks.length}`}>{inlineContent(line.slice(leading.length), media, legacyImageIndex, sourceMaterialId)}</p>);
  }
  flushList();
  return <div className="workspace-reference-text">{blocks}</div>;
}
