export function LoadingState({ label = "Загружаем" }: { label?: string }) {
  return (
    <div className="loading-state" role="status">
      <span className="loading-line" />
      <p>{label}</p>
    </div>
  );
}
