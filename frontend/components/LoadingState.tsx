export default function LoadingState({ label = "Loading" }: { label?: string }) {
  return <div className="panel muted">{label}</div>;
}
