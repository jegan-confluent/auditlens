"use client";

import { useEffect, useState } from "react";
import ErrorState from "../../components/ErrorState";
import LoadingState from "../../components/LoadingState";
import SystemStatusPanel from "../../components/SystemStatusPanel";
import { getSystemStatus } from "../../lib/api";
import type { SystemStatus } from "../../lib/types";

export default function SystemPage() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSystemStatus().then(setStatus).catch((err: Error) => setError(err.message));
  }, []);

  if (error) return <main className="page"><ErrorState message={error} /></main>;
  if (!status) return <main className="page"><LoadingState /></main>;

  return (
    <main className="page">
      <SystemStatusPanel status={status} />
      <section className="panel" style={{ marginTop: 16 }}>
        <h2>DB Health</h2>
        <pre>{JSON.stringify(status.db_health || {}, null, 2)}</pre>
      </section>
      <section className="panel" style={{ marginTop: 16 }}>
        <h2>Storage</h2>
        <pre>{JSON.stringify(status.storage_usage, null, 2)}</pre>
      </section>
    </main>
  );
}
