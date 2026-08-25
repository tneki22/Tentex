export interface ReferenceAnswerMedia {
  kind: "image" | "file";
  source: "binding" | "attachment";
  materialId?: string;
  label: string | null;
  url: string;
  alt: string;
}

export function attachmentImageLabel(fileName: string, attachmentId: string): string {
  return `вложение · ${fileName} · ${attachmentId}`;
}

export function canonicalImageMedia(
  media: ReferenceAnswerMedia[],
  label: string,
): ReferenceAnswerMedia | undefined {
  return media.find((item) => item.kind === "image" && item.label === label);
}

export function legacyBoundImages(
  media: ReferenceAnswerMedia[],
  sourceMaterialId: string | null,
): ReferenceAnswerMedia[] {
  return media.filter((item) => item.kind === "image"
    && item.source === "binding"
    && (!sourceMaterialId || item.materialId === sourceMaterialId));
}
