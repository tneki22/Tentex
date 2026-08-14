type LoadingPlacement = "page" | "section";

export function LoadingState({
  label = "Загружаем",
  placement = "section",
}: {
  label?: string;
  placement?: LoadingPlacement;
}) {
  return (
    <div className={`loading-state loading-state--${placement}`} role="status">
      <span className="loading-orbit" aria-hidden="true" />
      <p>{label}</p>
    </div>
  );
}
