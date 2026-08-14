interface BrandMarkProps {
  /** Сторона плашки в пикселях. По умолчанию — размер в панели установки. */
  size?: number;
}

/**
 * Знак Tentex: две стрелки навстречу друг другу.
 *
 * Это покрытие в обе стороны — чего в программе нет и что из материала никуда
 * не разнесено. Единственная мысль, которой продукт отличается от аналогов, и
 * единственное место, где она нарисована.
 *
 * Цвета берутся токенами: в тёмной теме `--accent` светлеет, а `--on-accent`
 * темнеет, поэтому знак читается в обеих темах без отдельных правил.
 */
export function BrandMark({ size = 26 }: BrandMarkProps) {
  return (
    <svg
      className="brand-mark"
      width={size}
      height={size}
      viewBox="0 0 26 26"
      fill="none"
      aria-hidden="true"
    >
      <rect width="26" height="26" rx="8" fill="var(--accent)" />
      <path
        d="M7.5 10.5 11 13 7.5 15.5"
        stroke="var(--on-accent)"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Вторая сторона приглушена: покрытие редко закрыто одинаково с обеих */}
      <path
        d="M18.5 10.5 15 13 18.5 15.5"
        stroke="var(--on-accent)"
        strokeOpacity="0.5"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
