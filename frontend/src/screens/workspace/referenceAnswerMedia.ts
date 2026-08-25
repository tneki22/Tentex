export interface ReferenceAnswerMedia {
  kind: "image" | "file";
  source: "binding" | "attachment";
  materialId?: string;
  label: string | null;
  url: string;
  alt: string;
}

export function legacyBoundImages(
  media: ReferenceAnswerMedia[],
  sourceMaterialId: string | null,
): ReferenceAnswerMedia[] {
  return media.filter((item) => item.kind === "image"
    && item.source === "binding"
    && (!sourceMaterialId || item.materialId === sourceMaterialId));
}
