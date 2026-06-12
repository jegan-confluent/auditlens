"use client";

import { useEffect, useState } from "react";
import ErrorState from "../../components/ErrorState";
import LoadingState from "../../components/LoadingState";
import {
  getAccessTransparency,
  isAbortError,
  type AccessTransparencyResponse,
  type AccessTransparencyEvent,
} from "../../lib/api";

const PAGE_LIMIT = 50;

function formatTimestamp(value: string): string {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

export default function AccessTransparencyPage() {
  const [data, setData] = useState<AccessTransparencyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getAccessTransparency(PAGE_LIMIT, offset, controller.signal)
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((err: Error) => {
        if (isAbortError(err)) return;
        setError(err.message);
        setLoading(false);
      });
    return () => controller.abort();
  }, [offset]);

  return (
    <main className="page">
      <header style={{ marginBottom: 16 }}>
        <h1>Access Transparency</h1>
        <p className="muted">
          Confluent personnel access to your resources. Each row records the operator,
          the accessed resource, and the business justification — required for DORA,
          SOX, GDPR and similar compliance frameworks.
        </p>
      </header>

      {loading && <LoadingState />}
      {error && <ErrorState message={error} />}

      {!loading && !error && data && (
        <>
          {data.items.length === 0 ? (
            <div className="panel empty-state" style={{ textAlign: "left" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <span aria-hidden style={{ fontSize: 18 }}>🔒</span>
                <strong>No Access Transparency events recorded</strong>
              </div>
              <p className="muted">
                Access Transparency captures when Confluent personnel access your
                Dedicated cluster resources. Events only appear if:
              </p>
              <ol className="muted" style={{ paddingLeft: 20, margin: "8px 0" }}>
                <li>You are on a Confluent Dedicated cluster (not Serverless/Basic).</li>
                <li>Access Transparency is enabled in your Confluent Cloud organisation.</li>
              </ol>
              <p className="muted" style={{ marginBottom: 4 }}>To enable:</p>
              <ul className="muted" style={{ paddingLeft: 20, margin: "0 0 8px 0" }}>
                <li>Go to confluent.cloud → Administration → Security.</li>
                <li>Enable &quot;Access Transparency&quot; under Audit Logging.</li>
                <li>Contact Confluent Support to activate operator-access event delivery to your audit log topic.</li>
              </ul>
              <p className="muted">
                Once enabled, operator access events will appear here automatically
                within the next polling window.
              </p>
              <p style={{ marginTop: 12 }}>
                <a
                  href="https://docs.confluent.io/cloud/current/security/audit-log/access-transparency.html"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  View Confluent docs ↗
                </a>
              </p>
            </div>
          ) : (
            <>
              <div className="muted" style={{ marginBottom: 8, fontSize: 12 }}>
                Showing {data.items.length} of {data.total} event(s)
              </div>
              <table className="audit-table" style={{ width: "100%" }}>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Operator</th>
                    <th>Resource</th>
                    <th>Justification</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((row: AccessTransparencyEvent) => (
                    <tr key={row.id}>
                      <td style={{ whiteSpace: "nowrap" }}>{formatTimestamp(row.timestamp)}</td>
                      <td title={row.actor || undefined}>
                        {row.at_operator
                          || row.actor_display_name
                          || row.actor_email
                          || row.actor
                          || "—"}
                      </td>
                      <td>{row.resource_name || "—"}</td>
                      <td>{row.at_justification || <span className="muted">not provided</span>}</td>
                      <td>{row.result}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.total > PAGE_LIMIT && (
                <nav style={{ display: "flex", gap: 8, marginTop: 12 }}>
                  <button
                    type="button"
                    onClick={() => setOffset(Math.max(0, offset - PAGE_LIMIT))}
                    disabled={offset === 0}
                  >
                    ← Prev
                  </button>
                  <button
                    type="button"
                    onClick={() => setOffset(offset + PAGE_LIMIT)}
                    disabled={offset + PAGE_LIMIT >= data.total}
                  >
                    Next →
                  </button>
                </nav>
              )}
            </>
          )}
        </>
      )}
    </main>
  );
}
