import type { AuditEvent } from "../lib/types";

export default function AuditEventTable({ events, onSelect }: { events: AuditEvent[]; onSelect: (event: AuditEvent) => void }) {
  return (
    <div className="panel">
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Result</th>
            <th>Actor</th>
            <th>Action</th>
            <th>Resource</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <tr key={event.id} onClick={() => onSelect(event)}>
              <td>{new Date(event.timestamp).toLocaleString()}</td>
              <td><span className={`status ${event.result === "Failure" ? "failure" : ""}`}>{event.result}</span></td>
              <td>{event.actor}</td>
              <td>{event.action_category}</td>
              <td>{event.resource_display}</td>
              <td>{event.summary}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
