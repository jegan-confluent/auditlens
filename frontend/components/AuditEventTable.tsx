import { Fragment, useMemo, useState } from "react";
import type React from "react";
import type { AuditEvent } from "../lib/types";
import SignalBadge from "./SignalBadge";

const UNKNOWN_PRINCIPAL_LABELS = new Set(["unknown actor", "unknown user", "unknown service account", "unknown principal"]);
const SERVICE_ACCOUNT_TYPES = new Set(["service_account", "serviceaccount", "service-account"]);
const REASON_MAX_CHARS = 60;

function isServiceAccount(event: AuditEvent): boolean {
  const type = (event.actor_type || event.subject_type || "").toLowerCase();
  if (SERVICE_ACCOUNT_TYPES.has(type)) return true;
  const raw = (event.actor_raw_id || event.actor || "").toLowerCase();
  return raw.startsWith("sa-") || raw.startsWith("user:sa-");
}

function displayResource(event: AuditEvent) {
  if (event.resource_display_name && event.resource_display_name !== "-") return event.resource_display_name;
  if (event.resource_name && event.resource_name !== "-") return event.resource_name;
  return event.resource_display_short || event.resource_display || event.resource_type || "Unknown";
}

type ActorDisplay = { primary: string; secondary: string; isServiceAccount: boolean; unenriched: boolean; isPlatform: boolean };

// True only when actor_display_name holds a real human-readable name —
// distinct from the raw id and not one of the Unknown* placeholders.
function isEnrichedDisplay(display: string, raw: string): boolean {
  if (!display) return false;
  if (display === raw) return false;
  if (display.startsWith("{") || display.startsWith("[")) return false;
  return !UNKNOWN_PRINCIPAL_LABELS.has(display.toLowerCase());
}

// Confluent's internal externalAccount actors arrive as raw JSON blobs in
// display_name (e.g. {"externalAccount":{"subject":"Confluent"}}).
function looksLikeJsonActor(value: string): boolean {
  return value.startsWith("{") || value.startsWith("[");
}

function displayActor(event: AuditEvent): ActorDisplay {
  const display = (event.actor_display_name || event.subject || event.actor || "").trim();
  const raw = (event.actor_raw_id || event.subject || event.actor || "").trim();
  const email = (event.actor_email || "").trim();

  if (looksLikeJsonActor(display) || looksLikeJsonActor(raw)) {
    return { primary: "Confluent (platform)", secondary: "", isServiceAccount: false, unenriched: false, isPlatform: true };
  }

  const isSA = isServiceAccount(event);
  const enriched = isEnrichedDisplay(display, raw);

  let primary: string;
  let unenriched: boolean;
  if (enriched) {
    primary = display;
    unenriched = false;
  } else if (email) {
    primary = email;
    unenriched = false;
  } else {
    primary = raw || (isSA ? "Unknown service account" : "Unknown principal");
    unenriched = true;
  }
  const secondary = raw && raw !== primary ? raw : "";

  return { primary, secondary, isServiceAccount: isSA, unenriched, isPlatform: false };
}

// Best label for prose contexts (the plain-English sentence in the table).
function bestSentenceLabel(event: AuditEvent): string {
  const display = (event.actor_display_name || "").trim();
  const raw = (event.actor_raw_id || event.subject || event.actor || "").trim();
  const email = (event.actor_email || "").trim();
  if (looksLikeJsonActor(display) || looksLikeJsonActor(raw)) return "Confluent (platform)";
  if (isEnrichedDisplay(display, raw)) return display;
  if (email) return email;
  return raw || event.actor || "Unknown actor";
}

function displaySourceIp(event: AuditEvent) {
  if (event.source_ip && event.source_ip.trim()) return event.source_ip;
  return "—";
}

// "[actor] [verb] [resource] on [cluster] in [environment]" sentence built
// from action_category + action.
function plainEnglishSummary(event: AuditEvent, resourceText: string): string {
  const cat = (event.action_category || "").trim();
  const action = (event.action || event.normalized_action || "").trim();
  const compact = action.replace(/[^a-zA-Z0-9]/g, "").toLowerCase();
  const cleanResource = resourceText && resourceText !== "Unknown" ? resourceText : "";
  const fallbackResource = cleanResource || "a resource";
  const actorLabel = bestSentenceLabel(event);

  let phrase = "";
  if (cat === "Delete") {
    phrase = `${actorLabel} deleted ${fallbackResource}`;
  } else if (cat === "Create") {
    phrase = `${actorLabel} created ${fallbackResource}`;
  } else if (cat === "Modify") {
    phrase = `${actorLabel} updated config on ${fallbackResource}`;
  } else if (cat === "Security") {
    if (compact.includes("revoke")) phrase = `${actorLabel} revoked access on ${fallbackResource}`;
    else if (compact.includes("grant") || compact.includes("bindrole")) phrase = `${actorLabel} granted access on ${fallbackResource}`;
    else if (compact.includes("createacl")) phrase = `${actorLabel} created ACL on ${fallbackResource}`;
    else if (compact.includes("deleteacl")) phrase = `${actorLabel} deleted ACL on ${fallbackResource}`;
    else phrase = `${actorLabel} changed access on ${fallbackResource}`;
  } else if (cat === "API Key") {
    const target = cleanResource ? ` for ${cleanResource}` : "";
    if (compact.includes("delete")) phrase = `${actorLabel} deleted API key${target}`;
    else if (compact.includes("create")) phrase = `${actorLabel} created API key${target}`;
    else if (compact.includes("rotate")) phrase = `${actorLabel} rotated API key${target}`;
    else if (compact.includes("update")) phrase = `${actorLabel} updated API key${target}`;
    else phrase = `${actorLabel} changed API key${target}`;
  } else {
    return "";
  }

  const cluster = (event.cluster_name || "").trim();
  const env = (event.environment_name || "").trim();
  if (cluster) phrase += ` on ${cluster}`;
  if (env) phrase += ` in ${env}`;
  return phrase;
}

// Sequential grouping: walk events in display order (newest first) and run
// adjacent events with the same key into a single group. The 60-min ceiling
// is measured from the run's first (newest) event so old activity never gets
// merged into a fresh burst.
const GROUP_WINDOW_MS = 60 * 60 * 1000;

type EventGroup = {
  key: string;
  events: AuditEvent[];
};

function buildGroupKey(e: AuditEvent): string {
  const actor = e.actor_raw_id || e.actor || "";
  const action = e.action || e.normalized_action || "";
  const resource = e.resource_name || "";
  const env = e.environment_id || e.environment_name || "";
  const signal = e.signal_type || "";
  const result = e.result || "";
  return `${actor}|${action}|${resource}|${env}|${signal}|${result}`;
}

function groupConsecutive(events: AuditEvent[]): EventGroup[] {
  const groups: EventGroup[] = [];
  let current: { key: string; firstTs: number; events: AuditEvent[] } | null = null;
  for (const ev of events) {
    const k = buildGroupKey(ev);
    const ts = Date.parse(ev.timestamp);
    const within = current && current.key === k && !Number.isNaN(ts) && current.firstTs - ts <= GROUP_WINDOW_MS;
    if (current && within) {
      current.events.push(ev);
    } else {
      if (current) groups.push({ key: `${current.key}|${current.firstTs}`, events: current.events });
      current = { key: k, firstTs: Number.isNaN(ts) ? Date.now() : ts, events: [ev] };
    }
  }
  if (current) groups.push({ key: `${current.key}|${current.firstTs}`, events: current.events });
  return groups;
}

function formatTimeRange(events: AuditEvent[]): string {
  if (events.length === 0) return "";
  const first = new Date(events[0].timestamp);
  const last = new Date(events[events.length - 1].timestamp);
  const fmt = (d: Date) => d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (first.getTime() === last.getTime()) return first.toLocaleString();
  return `${fmt(last)} — ${fmt(first)}`;
}

function resolveClientTool(tool: string | null | undefined): string | null {
  if (!tool || !tool.trim()) return null;
  const t = tool.trim();
  if (t === "unknown") return null;
  if (t.startsWith("confluent-") || t.startsWith("adminclient-")) return null;
  return t;
}

function riskBadgeStyle(riskLevel: string): React.CSSProperties {
  const bg = riskLevel === "critical" ? "#b42318"
    : riskLevel === "high" ? "#b54708"
    : riskLevel === "medium" ? "#ca8a04"
    : "#9ca3af";
  return { display: "inline-block", marginLeft: 4, padding: "1px 5px", borderRadius: 3, fontSize: "0.65em", fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase" as const, color: "#fff", background: bg, verticalAlign: "middle" };
}

// Phase 8 A2: signal border color
function signalBorderColor(signalType: string): string {
  if (signalType === "action_required") return "#ef4444";
  if (signalType === "attention") return "#f59e0b";
  if (signalType === "informational") return "#22c55e";
  if (signalType === "noise") return "#9ca3af";
  return "#e5e7eb";
}

// Phase 8 A2: compact relative time for table rows
function formatRelativeCompact(iso: string): string {
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "—";
  const seconds = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// Keep decisionReason — still used in ExpandedEventRow indirectly via detail data
function decisionReason(event: AuditEvent): string {
  const reason = (event.decision_reason || event.signal_reason || "").trim();
  if (!reason) return "";
  if (reason.length <= REASON_MAX_CHARS) return reason;
  return `${reason.slice(0, REASON_MAX_CHARS - 1).trimEnd()}…`;
}

// Keep to suppress unused-variable TS error — decisionReason used in ExpandedEventRow
void decisionReason;

function ExpandedEventRow({ event, detail, loading, error }: {
  event: AuditEvent;
  detail: AuditEvent | null;
  loading: boolean;
  error: string | null;
}) {
  const data = detail || event;
  const reason = (data.decision_reason || data.signal_reason || "").trim();
  const recommended = (data.recommended_action || "").trim();
  const resourceText = displayResource(data);
  return (
    <tr className="event-row-expanded">
      <td colSpan={4}>
        <div className="expanded-block">
          {loading ? <p className="muted">Loading details…</p> : null}
          {error ? <p className="panel-error">Could not load detail — {error}</p> : null}
          <div className="expanded-why">
            <strong>Why this matters:</strong> <span>{reason || data.decision_label || "Audit activity"}</span>
            {recommended ? <div className="expanded-recommended">→ Recommended: {recommended}</div> : null}
          </div>
          <div className="expanded-grid">
            <div><span className="muted">Resource:</span>{" "}<strong>{resourceText}</strong>{data.resource_type ? <span className="muted"> ({data.resource_type})</span> : null}</div>
            <div><span className="muted">Cluster:</span>{" "}<strong>{data.cluster_name || data.cluster_id || "—"}</strong>{"  "}<span className="muted">Environment:</span>{" "}<strong>{data.environment_name || data.environment_id || "—"}</strong></div>
            <div><span className="muted">Source IP:</span>{" "}<strong>{data.source_ip || "—"}</strong>{"  "}<span className="muted">Time:</span>{" "}<strong>{new Date(data.timestamp).toLocaleString()}</strong></div>
            <div><span className="muted">Triage:</span>{" "}<strong>{data.triage_status || "open"}</strong></div>
          </div>
          <details className="expanded-tech">
            <summary>Technical details ▸</summary>
            <div className="expanded-grid expanded-grid-tech">
              <div><span className="muted">Signal type:</span> {data.signal_type || "—"}</div>
              <div><span className="muted">Risk level:</span> {data.risk_level || "—"}</div>
              <div><span className="muted">Impact:</span> {data.impact_type || "—"}</div>
              <div><span className="muted">Resource family:</span> {data.resource_family || "—"}</div>
              <div><span className="muted">Resource scope:</span> {data.resource_scope || "—"}</div>
              <div><span className="muted">Actor source:</span> {data.actor_source || "—"} ({data.actor_confidence || "—"})</div>
              <div><span className="muted">Client ID:</span> {data.client_id || "—"}</div>
              <div><span className="muted">Request ID:</span> {data.request_id || "—"}</div>
              <div><span className="muted">Fingerprint:</span> <code>{data.event_fingerprint}</code></div>
            </div>
          </details>
        </div>
      </td>
    </tr>
  );
}

type RowOptions = {
  expandedId: number | null;
  expandedDetail: AuditEvent | null;
  expandedLoading: boolean;
  expandedError: string | null;
  onToggleExpand: (event: AuditEvent) => void;
  onActorClick?: (event: AuditEvent) => void;
  groupedChild?: boolean;
};

function EventRow({ event, options }: { event: AuditEvent; options: RowOptions }) {
  const actor = displayActor(event);
  const resourceText = displayResource(event);
  const plainEng = plainEnglishSummary(event, resourceText);
  const isExpanded = options.expandedId === event.id;
  const childClass = options.groupedChild ? " event-row-grouped-child" : "";
  const onActor = options.onActorClick;
  const borderColor = signalBorderColor(event.signal_type);
  return (
    <Fragment>
      <tr onClick={() => options.onToggleExpand(event)} className={`event-row signal-${event.signal_type}${isExpanded ? " expanded" : ""}${childClass}`}>
        <td className="event-what-cell" style={{ borderLeft: `3px solid ${borderColor}` }}>
          <strong className="event-what-title">{plainEng || event.event_title || event.normalized_action}</strong>
          <div className="event-resource-secondary">{resourceText}</div>
        </td>
        <td style={{ width: 90, verticalAlign: "middle" }}>
          <SignalBadge signal={event.signal_type} />
          {event.signal_type === "action_required" && event.risk_level && event.risk_level !== "unknown" && event.risk_level !== "-" ? (
            <span style={riskBadgeStyle(event.risk_level)}>{event.risk_level}</span>
          ) : null}
        </td>
        <td className="event-actor-time-cell">
          <div
            className={`event-actor-name${actor.unenriched ? " unenriched" : ""}${onActor ? " identity-clickable" : ""}`}
            title={actor.secondary || actor.primary}
            onClick={onActor ? (e) => { e.stopPropagation(); onActor(event); } : undefined}
          >
            {actor.primary}
            {actor.isServiceAccount ? <span className="actor-badge sa" title="Service account">SA</span> : null}
          </div>
          <div className="event-relative-time">{formatRelativeCompact(event.timestamp)}</div>
          <div className="event-source-ip">{displaySourceIp(event)}</div>
          {resolveClientTool(event.client_tool) ? (
            <div style={{ fontSize: "0.72em", color: "var(--muted)", marginTop: 1 }}>via {resolveClientTool(event.client_tool)}</div>
          ) : null}
        </td>
        <td className="event-client-tool-cell" style={{ textAlign: "right", fontSize: "0.75em", color: "var(--muted)", whiteSpace: "nowrap" }}>
          {resolveClientTool(event.client_tool) || null}
        </td>
      </tr>
      {isExpanded ? (
        <ExpandedEventRow event={event} detail={options.expandedDetail} loading={options.expandedLoading} error={options.expandedError} />
      ) : null}
    </Fragment>
  );
}

function GroupRow({ group, expanded, onToggle, onActorClick }: {
  group: EventGroup;
  expanded: boolean;
  onToggle: () => void;
  onActorClick?: (event: AuditEvent) => void;
}) {
  const head = group.events[0];
  const actor = displayActor(head);
  const resourceText = displayResource(head);
  const plainEng = plainEnglishSummary(head, resourceText);
  const borderColor = signalBorderColor(head.signal_type);
  const onActor = onActorClick;
  return (
    <tr onClick={onToggle} className={`event-row event-row-group signal-${head.signal_type}${expanded ? " expanded" : ""}`}>
      <td className="event-what-cell" style={{ borderLeft: `3px solid ${borderColor}` }}>
        <span className="group-toggle" aria-label={expanded ? "Collapse group" : "Expand group"}>{expanded ? "▼" : "▶"}</span>
        {" "}
        <strong className="event-what-title">{plainEng || head.event_title || head.normalized_action}</strong>
        <div className="event-resource-secondary">{formatTimeRange(group.events)}</div>
      </td>
      <td style={{ width: 90, verticalAlign: "middle" }}>
        <SignalBadge signal={head.signal_type} />
      </td>
      <td className="event-actor-time-cell">
        <div
          className={`event-actor-name${actor.unenriched ? " unenriched" : ""}${onActor ? " identity-clickable" : ""}`}
          title={actor.secondary || actor.primary}
          onClick={onActor ? (e) => { e.stopPropagation(); onActor(head); } : undefined}
        >
          {actor.primary}
          <span className="actor-badge group-count" title={`${group.events.length} events grouped`}>×{group.events.length}</span>
          {actor.isServiceAccount ? <span className="actor-badge sa" title="Service account">SA</span> : null}
        </div>
        <div className="event-relative-time">{formatRelativeCompact(head.timestamp)}</div>
      </td>
      <td className="event-client-tool-cell" style={{ textAlign: "right", fontSize: "0.75em", color: "var(--muted)", whiteSpace: "nowrap" }}>
        {head.client_tool || null}
      </td>
    </tr>
  );
}

export default function AuditEventTable({
  events,
  groupSimilar = false,
  expandedId,
  expandedDetail,
  expandedLoading,
  expandedError,
  onToggleExpand,
  onActorClick,
}: {
  events: AuditEvent[];
  groupSimilar?: boolean;
  expandedId: number | null;
  expandedDetail: AuditEvent | null;
  expandedLoading: boolean;
  expandedError: string | null;
  onToggleExpand: (event: AuditEvent) => void;
  onActorClick?: (event: AuditEvent) => void;
}) {
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const groups = useMemo(() => (groupSimilar ? groupConsecutive(events) : null), [events, groupSimilar]);

  const toggleGroup = (key: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const rowOptions: RowOptions = { expandedId, expandedDetail, expandedLoading, expandedError, onToggleExpand, onActorClick };

  return (
    <div className="panel table-panel">
      <table className="event-table">
        <thead>
          <tr>
            <th>Event</th>
            <th style={{ width: 90 }}>Signal</th>
            <th style={{ textAlign: "right" }}>Who / When</th>
            <th style={{ textAlign: "right" }}>Client</th>
          </tr>
        </thead>
        <tbody>
          {groups
            ? groups.map((group) => {
                if (group.events.length === 1) {
                  const ev = group.events[0];
                  return <EventRow key={ev.id} event={ev} options={rowOptions} />;
                }
                const isExpanded = expandedGroups.has(group.key);
                return (
                  <Fragment key={group.key}>
                    <GroupRow
                      group={group}
                      expanded={isExpanded}
                      onToggle={() => toggleGroup(group.key)}
                      onActorClick={onActorClick}
                    />
                    {isExpanded
                      ? group.events.map((ev) => (
                          <EventRow key={ev.id} event={ev} options={{ ...rowOptions, groupedChild: true }} />
                        ))
                      : null}
                  </Fragment>
                );
              })
            : events.map((event) => <EventRow key={event.id} event={event} options={rowOptions} />)}
        </tbody>
      </table>
    </div>
  );
}
