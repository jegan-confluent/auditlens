"use client";

import { useCallback, useEffect, useState } from "react";
import {
  generateAISummary,
  getAISummaryHealth,
  isAbortError,
  type AISummaryHealth,
  type AuditSummaryAI,
} from "../lib/api";

type HealthBand = "healthy" | "elevated" | "critical";

const HEALTH_LABELS: Record<HealthBand, string> = {
  healthy: "Healthy",
  elevated: "Elevated",
  critical: "Critical",
};

function HealthBadge({ band }: { band: HealthBand | null | undefined }) {
  if (!band) return null;
  return (
    <span className={`ai-health-pill ai-health-pill-${band}`} aria-label={`AI health: ${HEALTH_LABELS[band]}`}>
      {HEALTH_LABELS[band]}
    </span>
  );
}

function PanelSkeleton() {
  return (
    <div className="panel ai-summary-panel" aria-busy="true">
      <div className="ai-summary-header">
        <span className="ai-summary-title">AI insights</span>
      </div>
      <div className="skeleton wide" style={{ height: 18, marginTop: 8 }} />
      <div className="skeleton" style={{ height: 12, marginTop: 14 }} />
      <div className="skeleton wide" style={{ height: 12, marginTop: 6 }} />
      <div className="skeleton" style={{ height: 12, marginTop: 6, width: "60%" }} />
    </div>
  );
}

function DisabledBanner({ message }: { message: string }) {
  return (
    <div className="panel ai-summary-panel ai-summary-disabled" role="note">
      <span className="ai-summary-title">AI insights</span>
      <p className="muted" style={{ margin: "6px 0 0", fontSize: 13 }}>
        {message}
      </p>
    </div>
  );
}

function formatGeneratedAt(iso: string | null | undefined): string {
  if (!iso) return "";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "";
  const ageS = Math.max(0, (Date.now() - ts) / 1000);
  if (ageS < 60) return "just now";
  if (ageS < 3600) return `${Math.round(ageS / 60)}m ago`;
  if (ageS < 86400) return `${Math.round(ageS / 3600)}h ago`;
  return new Date(ts).toLocaleString();
}

export default function AISummaryPanel({ windowHours = 24 }: { windowHours?: number }) {
  const [health, setHealth] = useState<AISummaryHealth | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [summary, setSummary] = useState<AuditSummaryAI | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSummary = useCallback(
    (force: boolean, signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      generateAISummary(windowHours, force, signal)
        .then((data) => {
          setSummary(data);
          if (data.status === "error") {
            setError(data.message ?? "AI summary failed.");
          }
        })
        .catch((err: unknown) => {
          if (isAbortError(err)) return;
          setError(err instanceof Error ? err.message : String(err));
        })
        .finally(() => {
          setLoading(false);
        });
    },
    [windowHours],
  );

  useEffect(() => {
    const controller = new AbortController();
    getAISummaryHealth(controller.signal)
      .then((data) => {
        setHealth(data);
        if (data.enabled && data.configured) {
          loadSummary(false, controller.signal);
        }
      })
      .catch((err: unknown) => {
        if (isAbortError(err)) return;
        setHealthError(err instanceof Error ? err.message : String(err));
      });
    return () => controller.abort();
  }, [loadSummary]);

  if (healthError) {
    return (
      <div className="panel ai-summary-panel" role="alert">
        <span className="ai-summary-title">AI insights</span>
        <p className="panel-error" style={{ marginTop: 8 }}>
          AI health check failed — {healthError}
        </p>
      </div>
    );
  }

  if (!health) {
    return <PanelSkeleton />;
  }

  if (!health.enabled) {
    return (
      <DisabledBanner
        message={
          health.message ?? "AI insights disabled — set CLAUDE_API_KEY to enable."
        }
      />
    );
  }

  if (!health.configured) {
    return (
      <DisabledBanner
        message={
          health.message ??
          "AI insights disabled — set CLAUDE_API_KEY to enable."
        }
      />
    );
  }

  if (loading && !summary) {
    return <PanelSkeleton />;
  }

  if (!summary && error) {
    return (
      <div className="panel ai-summary-panel" role="alert">
        <span className="ai-summary-title">AI insights</span>
        <p className="panel-error" style={{ marginTop: 8 }}>
          {error}
        </p>
        <button
          type="button"
          className="ai-summary-refresh"
          onClick={() => loadSummary(true)}
        >
          Try again
        </button>
      </div>
    );
  }

  if (!summary) {
    return <PanelSkeleton />;
  }

  const isError = summary.status === "error";
  const generated = formatGeneratedAt(summary.generated_at);
  const latency = summary.latency_ms != null ? `${summary.latency_ms} ms` : null;

  return (
    <div className="panel ai-summary-panel" role="region" aria-label="AI insights">
      <div className="ai-summary-header">
        <span className="ai-summary-title">AI insights</span>
        <HealthBadge band={summary.health ?? null} />
        <button
          type="button"
          className="ai-summary-refresh"
          onClick={() => loadSummary(true)}
          disabled={loading}
          aria-label="Refresh AI summary"
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {isError ? (
        <p className="panel-error" style={{ marginTop: 8 }}>
          {summary.message ?? "AI summary failed."}
        </p>
      ) : (
        <>
          {summary.headline ? (
            <h3 className="ai-summary-headline">{summary.headline}</h3>
          ) : null}

          {summary.summary ? (
            <p className="ai-summary-body">{summary.summary}</p>
          ) : null}

          {summary.top_risk ? (
            <div className="ai-summary-top-risk" role="note">
              <strong>Top risk: </strong>
              <span>{summary.top_risk}</span>
            </div>
          ) : null}

          {summary.anomalies && summary.anomalies.length > 0 ? (
            <div className="ai-summary-section">
              <span className="ai-summary-section-label">Anomalies</span>
              <ul className="ai-summary-list">
                {summary.anomalies.map((item, idx) => (
                  <li key={`${idx}-${item.slice(0, 40)}`}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {summary.recommended_actions && summary.recommended_actions.length > 0 ? (
            <div className="ai-summary-section">
              <span className="ai-summary-section-label">Recommended actions</span>
              <ol className="ai-summary-list">
                {summary.recommended_actions.map((item, idx) => (
                  <li key={`${idx}-${item.slice(0, 40)}`}>{item}</li>
                ))}
              </ol>
            </div>
          ) : null}
        </>
      )}

      <div className="ai-summary-footer">
        Generated by Claude
        {summary.model_used ? ` · ${summary.model_used}` : ""}
        {latency ? ` · ${latency}` : ""}
        {generated ? ` · ${generated}` : ""}
        {summary.confidence ? ` · ${summary.confidence} confidence` : ""}
      </div>
    </div>
  );
}
