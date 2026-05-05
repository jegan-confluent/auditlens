export default function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className="panel loading-state" aria-busy="true">
      <div className="skeleton wide" />
      <div className="skeleton" />
      <span className="muted">{label}</span>
    </div>
  );
}
