export default function EmptyState({ diagnostics }: { diagnostics?: string }) {
  return <div className="panel"><strong>No matching audit events found.</strong><p className="muted">{diagnostics || "Review active filters or system status."}</p></div>;
}
