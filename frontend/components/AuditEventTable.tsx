import { Fragment, useMemo, useState } from "react";
import type { AuditEvent } from "../lib/types";

const UNKNOWN_PRINCIPAL_LABELS = new Set(["unknown actor", "unknown user", "unknown service account", "unknown principal"]);
const SERVICE_ACCOUNT_TYPES = new Set(["service_account", "serviceaccount", "service-account"]);
const REASON_MAX_CHARS = 60;

function statusClass(event: AuditEvent) {
  if (["approved", "resolved", "false_positive"].includes(event.triage_status)) return "success";
  if (["acknowledged", "investigating"].includes(event.triage_status)) return "denied";
  if (event.signal_type === "action_required") return "failure";
  if (event.signal_type === "attention") return "denied";
  if (event.signal_type === "informational") return "success";
  if (event.impact_type === "destructive" || event.risk_level === "critical") return "failure";
  if (event.impact_type === "security_sensitive" || event.impact_type === "access_change" || event.is_denied) return "denied";
  if (event.impact_type === "constructive") return "success";
  const result = event.result.toLowerCase();
  if (event.is_denied || result.includes("denied")) return "denied";
  if (event.is_failure || result.includes("failure")) return "failure";
  if (result.includes("success")) return "success";
  return "neutral";
}

function impactLabel(event: AuditEvent) {
  if (event.triage_status && event.triage_status !== "open") {
    return event.triage_status.replace("_", " ");
  }
  return event.decision_label || "Info";
}

function decisionReason(event: AuditEvent): string {
  const reason = (event.decision_reason || event.signal_reason || "").trim();
  if (!reason) return "";
  if (reason.length <= REASON_MAX_CHARS) return reason;
  return `${reason.slice(0, REASON_MAX_CHARS - 1).trimEnd()}…`;
}

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
// distinct from the raw id and not one of the Unknown* placeholders. Some
// events get persisted with display_name == raw_id when enrichment hasn't
// run yet (cache cold, missing creds, missing IAM record); we must treat
// those as unenriched so the cell renders in italic grey rather than
// pretending the raw id is a name.
function isEnrichedDisplay(display: string, raw: string): boolean {
  if (!display) return false;
  if (display === raw) return false;
  if (display.startsWith("{") || display.startsWith("[")) return false;
  return !UNKNOWN_PRINCIPAL_LABELS.has(display.toLowerCase());
}

// Confluent's internal externalAccount actors arrive as raw JSON blobs in
// display_name (e.g. {"externalAccount":{"subject":"Confluent"}}). Anything
// starting with { or [ is one of these — relabel to a friendly platform tag.
function looksLikeJsonActor(value: string): boolean {
  return value.startsWith("{") || value.startsWith("[");
}

function displayActor(event: AuditEvent): ActorDisplay {
  const display = (event.actor_display_name || event.subject || event.actor || "").trim();
  const raw = (event.actor_raw_id || event.subject || event.actor || "").trim();
  const email = (event.actor_email || "").trim();

  // JSON-shaped display (Confluent platform externalAccount) wins before any
  // other classification — both display and the would-be primary are unreadable.
  if (looksLikeJsonActor(display) || looksLikeJsonActor(raw)) {
    return { primary: "Confluent (platform)", secondary: "", isServiceAccount: false, unenriched: false, isPlatform: true };
  }

  const isSA = isServiceAccount(event);
  const enriched = isEnrichedDisplay(display, raw);

  // Pick the most informative primary label, then add raw as secondary only
  // when it adds something (i.e. it's not the same string already shown).
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
// Prefers the human display name over the email — "Marcia Lima deleted X"
// reads more naturally than "mlima@confluent.io deleted X". The Who column
// uses a different priority (email first) because email is the more
// recognisable identifier when scanning a list of rows.
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
  if (event.source_ip) return event.source_ip;
  if (event.source_context) return `No source IP / context: ${event.source_context}`;
  return "No source IP in audit event";
}

function displaySummary(event: AuditEvent) {
  const summary = event.event_summary || event.summary || "";
  const raw = event.actor_raw_id || event.subject || event.actor || "";
  const { primary } = displayActor(event);
  return raw && primary && raw !== primary ? summary.replace(raw, primary) : summary;
}

// "[actor] [verb] [resource] on [cluster] in [environment]" sentence built
// from action_category + action. Returns "" for Data / unmapped categories so
// the caller falls back to event_title (Data activity is dominated by
// automated reads that don't tell a useful story in the table).
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
// merged into a fresh burst. Result/signal_type intentionally participate in
// the key so a Success+Failure mix stays as separate rows.
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
      current = { key: k, firstTs: Number.isNaN(ts) ? 0 : ts, events: [ev] };
    }
  }
  if (current) groups.push({ key: `${current.key}|${current.firstTs}`, events: current.events });
  return groups;
}

function formatTimeRange(events: AuditEvent[]): string {
  if (events.length === 0) return "";
  const first = new Date(events[0].timestamp);
  const last = new Date(events[events.length - 1].timestamp);
  // events arrive newest-first, so events[0] is the latest, events[last] is
  // the earliest. Display "earliest — latest" to read naturally.
  const fmt = (d: Date) => d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (first.getTime() === last.getTime()) return first.toLocaleString();
  return `${fmt(last)} — ${fmt(first)}`;
}

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
      <td colSpan={6}>
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
  const reason = decisionReason(event);
  const triaged = event.triage_status && event.triage_status !== "open";
  const resourceText = displayResource(event);
  const plainEng = plainEnglishSummary(event, resourceText);
  const isExpanded = options.expandedId === event.id;
  const childClass = options.groupedChild ? " event-row-grouped-child" : "";
  const onActor = options.onActorClick;
  return (
    <Fragment>
      <tr onClick={() => options.onToggleExpand(event)} className={`event-row signal-${event.signal_type}${isExpanded ? " expanded" : ""}${childClass}`}>
        <td className="nowrap">{new Date(event.timestamp).toLocaleString()}</td>
        <td className="decision-cell">
          <span className={`status ${statusClass(event)}`}>{impactLabel(event)}</span>
          {triaged ? (
            <span className="decision-reason">triaged</span>
          ) : reason ? (
            <span className="decision-reason" title={event.decision_reason || event.signal_reason || ""}>{reason}</span>
          ) : null}
        </td>
        <td
          className={`identity-cell${actor.unenriched ? " unenriched" : ""}${onActor ? " identity-clickable" : ""}`}
          title={actor.secondary || actor.primary}
          onClick={onActor ? (e) => { e.stopPropagation(); onActor(event); } : undefined}
        >
          <strong>
            {actor.primary}
            {actor.isServiceAccount ? <span className="actor-badge sa" title="Service account">SA</span> : null}
          </strong>
          {actor.secondary ? <span>{actor.secondary}</span> : null}
        </td>
        <td className="summary-cell">
          {plainEng ? (
            <strong>{plainEng}</strong>
          ) : (
            <>
              <strong>{event.event_title || event.normalized_action}</strong>
              <span>{displaySummary(event)}</span>
            </>
          )}
        </td>
        <td className="resource-cell" title={event.resource_scope ? `${resourceText}\n${event.resource_scope}` : resourceText}>{resourceText}</td>
        <td className="truncate-cell" title={displaySourceIp(event)}>{displaySourceIp(event)}</td>
      </tr>
      {isExpanded ? (
        <ExpandedEventRow
          event={event}
          detail={options.expandedDetail}
          loading={options.expandedLoading}
          error={options.expandedError}
        />
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
  const reason = decisionReason(head);
  const triaged = head.triage_status && head.triage_status !== "open";
  const onActor = onActorClick;
  return (
    <tr onClick={onToggle} className={`event-row event-row-group signal-${head.signal_type}${expanded ? " expanded" : ""}`}>
      <td className="nowrap">
        <span className="group-toggle" aria-label={expanded ? "Collapse group" : "Expand group"}>{expanded ? "▼" : "▶"}</span>
        {" "}{formatTimeRange(group.events)}
      </td>
      <td className="decision-cell">
        <span className={`status ${statusClass(head)}`}>{impactLabel(head)}</span>
        {triaged ? (
          <span className="decision-reason">triaged</span>
        ) : reason ? (
          <span className="decision-reason" title={head.decision_reason || head.signal_reason || ""}>{reason}</span>
        ) : null}
      </td>
      <td
        className={`identity-cell${actor.unenriched ? " unenriched" : ""}${onActor ? " identity-clickable" : ""}`}
        title={actor.secondary || actor.primary}
        onClick={onActor ? (e) => { e.stopPropagation(); onActor(head); } : undefined}
      >
        <strong>
          {actor.primary}
          <span className="actor-badge group-count" title={`${group.events.length} events grouped`}>×{group.events.length}</span>
          {actor.isServiceAccount ? <span className="actor-badge sa" title="Service account">SA</span> : null}
        </strong>
        {actor.secondary ? <span>{actor.secondary}</span> : null}
      </td>
      <td className="summary-cell">
        {plainEng ? (
          <strong>{plainEng}</strong>
        ) : (
          <>
            <strong>{head.event_title || head.normalized_action}</strong>
            <span>{displaySummary(head)}</span>
          </>
        )}
      </td>
      <td className="resource-cell" title={head.resource_scope ? `${resourceText}\n${head.resource_scope}` : resourceText}>{resourceText}</td>
      <td className="truncate-cell" title={displaySourceIp(head)}>{displaySourceIp(head)}</td>
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
            <th>Time</th>
            <th>Decision</th>
            <th>Who</th>
            <th>What happened</th>
            <th>Resource</th>
            <th>Source/IP</th>
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
