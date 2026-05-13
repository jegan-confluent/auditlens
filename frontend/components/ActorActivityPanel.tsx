"use client";

import { useEffect, useMemo, useState } from "react";
import { getActorIpBaseline, getActorNarrative, getEvents, getSummary, isAbortError } from "../lib/api";
import type { ActorIpBaseline, ActorNarrative, AuditEvent, EventListResponse, NarrativeAnomaly, NarrativeChapter, SummaryResponse } from "../lib/types";

const UNKNOWN_PRINCIPAL_LABELS = new Set(["unknown actor", "unknown user", "unknown service account", "unknown principal"]);
const SERVICE_ACCOUNT_TYPES = new Set(["service_account", "serviceaccount", "service-account"]);

function isServiceAccountActor(event: AuditEvent): boolean {
  const type = (event.actor_type || event.subject_type || "").toLowerCase();
  if (SERVICE_ACCOUNT_TYPES.has(type)) return true;
  const raw = (event.actor_raw_id || event.actor || "").toLowerCase();
  return raw.startsWith("sa-") || raw.startsWith("user:sa-");
}

function actorTypeLabel(event: AuditEvent | null): string {
  if (!event) return "Actor";
  if (isServiceAccountActor(event)) return "Service Account";
  const type = (event.actor_type || event.subject_type || "").toLowerCase();
  if (type === "user") return "User";
  if (type === "api_key" || type === "apikey") return "API Key";
  return "User";
}

function looksLikeJson(v: string): boolean {
  return v.startsWith("{") || v.startsWith("[");
}

function actorPrimary(event: AuditEvent | null, fallback: string): string {
  if (looksLikeJson(fallback)) return "Confluent (platform)";
  if (!event) return fallback;
  const display = (event.actor_display_name || "").trim();
  const raw = (event.actor_raw_id || event.subject || event.actor || "").trim();
  const email = (event.actor_email || "").trim();
  if (looksLikeJson(display) || looksLikeJson(raw)) return "Confluent (platform)";
  if (display && display !== raw && !UNKNOWN_PRINCIPAL_LABELS.has(display.toLowerCase())) return display;
  if (email) return email;
  return raw || fallback;
}

function actorRawId(event: AuditEvent | null, fallback: string): string {
  if (!event) return fallback;
  return (event.actor_raw_id || event.subject || event.actor || fallback).trim();
}

function distinctNonEmpty(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  for (const v of values) {
    const s = (v || "").trim();
    if (s) seen.add(s);
  }
  return Array.from(seen);
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

const SIGNAL_LABELS: Record<string, string> = {
  action_required: "🔴 action required",
  attention: "🟡 attention",
  informational: "🟢 informational",
  noise: "⚪ noise",
};

const ANOMALY_SEVERITY_CLASS: Record<string, string> = {
  high: "anomaly-high",
  medium: "anomaly-medium",
  low: "anomaly-low",
};

function StoryChapter({ chapter }: { chapter: NarrativeChapter }) {
  return (
    <div className="story-chapter">
      <div className="story-chapter-header">
        <span className="story-chapter-category">{chapter.category}</span>
        <span className="story-chapter-count">{chapter.event_count} event{chapter.event_count === 1 ? "" : "s"}</span>
        <span className={`story-signal-badge signal-${chapter.peak_signal.replace("_", "-")}`}>
          {SIGNAL_LABELS[chapter.peak_signal] ?? chapter.peak_signal}
        </span>
      </div>
      {chapter.actions.length > 0 ? (
        <div className="story-chapter-detail">
          <span className="muted">Actions:</span>{" "}
          {chapter.actions.slice(0, 3).join(", ")}
        </div>
      ) : null}
      {chapter.resources.length > 0 ? (
        <div className="story-chapter-detail">
          <span className="muted">Resources:</span>{" "}
          {chapter.resources.slice(0, 3).join(", ")}
        </div>
      ) : null}
    </div>
  );
}

function StoryAnomaly({ anomaly }: { anomaly: NarrativeAnomaly }) {
  return (
    <div className={`story-anomaly ${ANOMALY_SEVERITY_CLASS[anomaly.severity] ?? ""}`}>
      ⚠ {anomaly.description}
    </div>
  );
}

type Props = {
  actorId: string | null;
  seedEvent?: AuditEvent | null;
  onClose: () => void;
  onApplyActorFilter: (actorId: string) => void;
};

export default function ActorActivityPanel({ actorId, seedEvent, onClose, onApplyActorFilter }: Props) {
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [events, setEvents] = useState<EventListResponse | null>(null);
  const [ipBaseline, setIpBaseline] = useState<ActorIpBaseline | null>(null);
  const [narrative, setNarrative] = useState<ActorNarrative | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"activity" | "story">("activity");

  // Esc to close
  useEffect(() => {
    if (!actorId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [actorId, onClose]);

  useEffect(() => {
    if (!actorId) {
      setSummary(null);
      setEvents(null);
      setError(null);
      setNarrative(null);
      setActiveTab("activity");
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setSummary(null);
    setEvents(null);
    setIpBaseline(null);
    setNarrative(null);

    const summaryParams = new URLSearchParams({ actor: actorId, time_window: "24h" });
    const eventsParams = new URLSearchParams({
      actor: actorId,
      time_window: "24h",
      limit: "10",
      mode: "decision",
    });

    Promise.all([
      getSummary(summaryParams, controller.signal),
      getEvents(eventsParams, controller.signal),
      getActorIpBaseline(actorId, controller.signal).catch(() => null),
      getActorNarrative(actorId, "24h", controller.signal).catch(() => null),
    ])
      .then(([sum, evs, ipb, narr]) => {
        setSummary(sum);
        setEvents(evs as EventListResponse);
        setIpBaseline(ipb);
        setNarrative(narr);
      })
      .catch((err: Error) => {
        if (isAbortError(err)) return;
        setError(err.message || "Unable to load actor details");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [actorId]);

  const headEvent = useMemo<AuditEvent | null>(() => {
    if (events?.items && events.items.length > 0) return events.items[0];
    return seedEvent || null;
  }, [events, seedEvent]);

  const recent = useMemo<AuditEvent[]>(() => {
    if (!events?.items) return [];
    return events.items
      .filter((e) => e.signal_type === "action_required" || e.signal_type === "attention")
      .slice(0, 5);
  }, [events]);

  const clustersTouched = useMemo(() => {
    if (!events?.items) return null;
    return distinctNonEmpty(events.items.map((e) => e.cluster_name || e.cluster_id || null)).length;
  }, [events]);
  const environmentsTouched = useMemo(() => {
    if (!events?.items) return null;
    return distinctNonEmpty(events.items.map((e) => e.environment_name || e.environment_id || null)).length;
  }, [events]);

  const topActions = useMemo(() => {
    if (!summary) return [];
    return Object.entries(summary.by_action_category || {})
      .filter(([_, count]) => count > 0)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5);
  }, [summary]);

  if (!actorId) return null;

  const primary = actorPrimary(headEvent, actorId);
  const raw = actorRawId(headEvent, actorId);
  const typeLabel = actorTypeLabel(headEvent);

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="drawer actor-activity-panel" role="dialog" aria-label="Actor activity">
        <div className="drawer-header">
          <div>
            <div className="eyebrow">Actor activity (24h)</div>
            <h2>
              {primary} <span className={`actor-badge ${typeLabel === "Service Account" ? "sa" : ""}`}>{typeLabel}</span>
            </h2>
            {raw && raw !== primary && !looksLikeJson(raw) ? <p className="muted">{raw}</p> : null}
          </div>
          <button onClick={onClose} aria-label="Close actor panel">×</button>
        </div>

        {/* Tab bar */}
        <div className="actor-panel-tabs" role="tablist">
          <button
            role="tab"
            aria-selected={activeTab === "activity"}
            className={`actor-panel-tab${activeTab === "activity" ? " active" : ""}`}
            onClick={() => setActiveTab("activity")}
          >
            Activity
          </button>
          <button
            role="tab"
            aria-selected={activeTab === "story"}
            className={`actor-panel-tab${activeTab === "story" ? " active" : ""}`}
            onClick={() => setActiveTab("story")}
          >
            Story
          </button>
        </div>

        {loading ? (
          <div className="actor-panel-skeleton">
            <div className="skeleton-card" />
            <div className="skeleton-card" />
            <div className="skeleton-card" />
          </div>
        ) : error ? (
          <p className="panel-error">Unable to load actor details — {error}</p>
        ) : summary && events ? (
          <>
            {/* Activity tab */}
            {activeTab === "activity" ? (
              <>
                <div className="actor-stat-grid">
                  <div className="actor-stat">
                    <div className="detail-label">Total events</div>
                    <strong>{summary.total_events.toLocaleString()}</strong>
                  </div>
                  <div className="actor-stat">
                    <div className="detail-label">Clusters touched</div>
                    <strong>{clustersTouched ?? "—"}</strong>
                  </div>
                  <div className="actor-stat">
                    <div className="detail-label">Environments touched</div>
                    <strong>{environmentsTouched ?? "—"}</strong>
                  </div>
                </div>

                <section className="actor-panel-section">
                  <div className="eyebrow">Top actions</div>
                  {topActions.length === 0 ? (
                    <p className="muted">No activity in the last 24 hours.</p>
                  ) : (
                    <ul className="actor-action-list">
                      {topActions.map(([cat, count]) => (
                        <li key={cat}>
                          <span>{cat}</span>
                          <strong>{count.toLocaleString()}</strong>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                <section className="actor-panel-section">
                  <div className="eyebrow">Signal breakdown</div>
                  <ul className="actor-signal-list">
                    <li><span>🔴 Action required</span><strong>{summary.action_required_count.toLocaleString()}</strong></li>
                    <li><span>🟡 Attention</span><strong>{summary.attention_count.toLocaleString()}</strong></li>
                    <li><span>🟢 Informational</span><strong>{summary.informational_count.toLocaleString()}</strong></li>
                  </ul>
                </section>

                <section className="actor-panel-section">
                  <div className="eyebrow">Recent important events</div>
                  {recent.length === 0 ? (
                    <p className="muted">No action-required or attention events in the last 24 hours.</p>
                  ) : (
                    <ul className="actor-recent-list">
                      {recent.map((ev) => (
                        <li key={ev.id}>
                          <span className="muted">{formatTime(ev.timestamp)}</span>
                          <span>{ev.event_title || ev.normalized_action || ev.action || "Activity"}</span>
                          <span className="muted">{ev.resource_display_name || ev.resource_name || ev.environment_name || "—"}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                {ipBaseline && ipBaseline.ips.length > 0 ? (
                  <section className="actor-panel-section">
                    <div className="eyebrow">
                      IP history
                      {ipBaseline.new_ips_last_24h > 0 ? (
                        <span className="ip-history-badge new"> {ipBaseline.new_ips_last_24h} new</span>
                      ) : null}
                    </div>
                    <ul className="actor-ip-list">
                      {ipBaseline.ips.slice(0, 8).map((entry) => (
                        <li key={entry.source_ip} className={`actor-ip-entry${entry.is_new ? " new-ip" : ""}${entry.is_trusted ? " trusted-ip" : ""}`}>
                          <span className="ip-icon" aria-label={entry.is_trusted ? "Trusted" : entry.is_new ? "New" : "Known"}>
                            {entry.is_trusted ? "✅" : entry.is_new ? "🔴" : "·"}
                          </span>
                          <span className="ip-addr">{entry.source_ip}</span>
                          <span className="ip-meta muted">
                            {entry.cloud_provider ? `${entry.cloud_provider}${entry.region ? ` · ${entry.region}` : ""}` : ""}
                            {entry.occurrence_count > 1 ? ` · ${entry.occurrence_count}×` : ""}
                          </span>
                        </li>
                      ))}
                    </ul>
                    {ipBaseline.total_ips > 8 ? (
                      <p className="muted" style={{ fontSize: 12, marginTop: 4 }}>+{ipBaseline.total_ips - 8} more IPs</p>
                    ) : null}
                  </section>
                ) : null}
              </>
            ) : null}

            {/* Story tab */}
            {activeTab === "story" ? (
              <div className="story-tab-content">
                {narrative ? (
                  <>
                    <p className="story-headline">{narrative.headline}</p>

                    {narrative.chapters.length > 0 ? (
                      <section className="actor-panel-section">
                        <div className="eyebrow">Chapters</div>
                        {narrative.chapters.map((ch) => (
                          <StoryChapter key={ch.category} chapter={ch} />
                        ))}
                      </section>
                    ) : (
                      <p className="muted">No activity chapters for this actor in the last 24 hours.</p>
                    )}

                    {narrative.anomalies.length > 0 ? (
                      <section className="actor-panel-section">
                        <div className="eyebrow">Anomalies</div>
                        {narrative.anomalies.map((a) => (
                          <StoryAnomaly key={a.type} anomaly={a} />
                        ))}
                      </section>
                    ) : (
                      <section className="actor-panel-section">
                        <div className="eyebrow">Anomalies</div>
                        <p className="muted">No anomalies detected.</p>
                      </section>
                    )}

                    <div className="story-footer muted">
                      Story generated at {new Date(narrative.generated_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} UTC
                      {" · "}
                      {narrative.total_events} total event{narrative.total_events === 1 ? "" : "s"},{" "}
                      {narrative.non_noise_count} meaningful
                    </div>
                  </>
                ) : (
                  <p className="muted">Story unavailable — narrative API did not respond in time.</p>
                )}
              </div>
            ) : null}

            <div className="actor-panel-footer">
              <button onClick={() => onApplyActorFilter(actorId)}>Filter events to this actor</button>
            </div>
          </>
        ) : null}
      </aside>
    </>
  );
}
