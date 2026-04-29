"use client";

import type { AuditEvent } from "../lib/types";

export default function EventDetailDrawer({ event, onClose }: { event: AuditEvent | null; onClose: () => void }) {
  if (!event) return null;
  return (
    <aside className="drawer">
      <button onClick={onClose}>Close</button>
      <h2>{event.summary}</h2>
      <p className="muted">{event.timestamp}</p>
      <div className="grid">
        <div><div className="muted">Actor</div><strong>{event.actor}</strong></div>
        <div><div className="muted">Action</div><strong>{event.normalized_action}</strong></div>
        <div><div className="muted">Resource</div><strong>{event.resource_display}</strong></div>
        <div><div className="muted">Result</div><strong>{event.result}</strong></div>
      </div>
      <h3>Raw Payload</h3>
      <pre>{event.raw_payload_json || "Raw payload is available only from the detail endpoint."}</pre>
    </aside>
  );
}
