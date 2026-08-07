/**
 * Откуда взялся узел программы. Пять источников из FR-G23 плюс честное
 * «источника нет».
 *
 * Все нейтральные, кроме последнего: различать оглавление и каталог цветом
 * незачем, значимо только отсутствие источника — там модель говорит, что
 * ничем не подтверждена.
 */
export type ProgramSource =
  | { kind: "outline" }
  | { kind: "pass1"; pages: string }
  | { kind: "catalog"; layer: 1 | 2 | 4 }
  | { kind: "import" }
  | { kind: "manual" }
  | { kind: "none" };

function describe(source: ProgramSource): { text: string; unverified: boolean } {
  switch (source.kind) {
    case "outline":
      return { text: "оглавление", unverified: false };
    case "pass1":
      return { text: `проход 1 · ${source.pages}`, unverified: false };
    case "catalog":
      return { text: `каталог, слой ${source.layer}`, unverified: false };
    case "import":
      return { text: "импорт", unverified: false };
    case "manual":
      return { text: "вручную", unverified: false };
    case "none":
      return { text: "источника нет", unverified: true };
  }
}

export function SourceChip({ source }: { source: ProgramSource }) {
  const { text, unverified } = describe(source);
  return (
    <span className={`source-chip ${unverified ? "is-unverified" : ""}`.trim()}>{text}</span>
  );
}
