export default function ErrorState({ message, systemState }: { message: string; systemState?: string | null }) {
  const title = systemState ? "System degraded" : "API unreachable";
  const detail = systemState ? `System state: ${systemState}. ${message}` : message;
  return (
    <div className="panel error-state">
      <strong>{title}</strong>
      <p className="muted">{detail}</p>
    </div>
  );
}
