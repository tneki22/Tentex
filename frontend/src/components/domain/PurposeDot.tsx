/** Назначение работы на день: изучить, повторить или и то и другое. */

export type Purpose = "study" | "review" | "both" | "none";

export const purposeLabel: Record<Purpose, string> = {
  study: "Изучить",
  review: "Повторить",
  both: "Изучить и повторить",
  none: "Не назначен",
};

interface PurposeDotProps {
  purpose: Purpose;
  /** Подпись рядом с точкой. Без неё цвет остаётся единственным носителем смысла. */
  withLabel?: boolean;
  size?: number;
}

/**
 * Точка назначения.
 *
 * «И то и другое» — раздвоенная точка из двух цветов, а не третий оттенок:
 * вопрос действительно назначен дважды, и бирюзовый в системе уже занят
 * тоном `--tone-info`.
 */
export function PurposeDot({ purpose, withLabel = false, size = 8 }: PurposeDotProps) {
  return (
    <span className="purpose">
      <i
        className={`purpose-dot is-${purpose}`}
        style={{ width: size, height: size }}
        aria-hidden="true"
      />
      {withLabel ? <span>{purposeLabel[purpose]}</span> : <span className="sr-only">{purposeLabel[purpose]}</span>}
    </span>
  );
}

/** Назначение вопроса на дату по видам работы, которые на неё стоят. */
export function purposeOf(kinds: Iterable<string>): Purpose {
  let study = false;
  let review = false;
  for (const kind of kinds) {
    if (kind === "review") review = true;
    else study = true;
  }
  if (study && review) return "both";
  if (review) return "review";
  if (study) return "study";
  return "none";
}
