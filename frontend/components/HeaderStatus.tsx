"use client";

import { useEffect, useState } from "react";
import { getSystemStatus, isAbortError } from "../lib/api";
import type { SystemStatus } from "../lib/types";

type Tone = "loading" | "connected" | "degraded" | "critical" | "down" | "auth-off";

const POLL_INTERVAL_MS = 30_000;

type FetchState =
  | { kind: "loading" }
  | { kind: "ok"; status: SystemStatus }
  | { kind: "error" };

function compactNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

// The backend computes pipeline_status from kafka lag, db freshness, and
// forwarder write time. Mirror that decision in the header rather than
// re-deriving from raw lag/processing_rate, which produced false "Degraded"
// readings on idle systems where processing_rate=0 < SLOW threshold even
// though there was nothing to process.
function classify(state: FetchState): { tone: Tone; label: string } {
  if (state.kind === "loading") return { tone: "loading", label: "Connecting…" };
  if (state.kind === "error") return { tone: "down", label: "Down" };

  const status = state.status;
  const pipeline = status.pipeline_status ?? status.pipeline_lag?.status ?? "unknown";
  const lag = status.pipeline_lag?.kafka_consumer_lag_messages ?? status.consumer_lag ?? 0;
  const lagSuffix = lag > 0 ? ` · ${compactNumber(lag)} lag` : "";

  if (pipeline === "stalled") return { tone: "critical", label: `Stalled${lagSuffix}` };
  if (pipeline === "degraded") return { tone: "degraded", label: `Degraded${lagSuffix}` };
  if (pipeline === "unknown") {
    if (!status.auth_enabled) {
      return { tone: "auth-off", label: "Auth off" };
    }
    return { tone: "down", label: "Unknown" };
  }
  return { tone: "connected", label: "Connected" };
}

export default function HeaderStatus() {
  const [state, setState] = useState<FetchState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function tick() {
      const controller = new AbortController();
      try {
        const next = await getSystemStatus(controller.signal);
        if (!cancelled) setState({ kind: "ok", status: next });
      } catch (err) {
        if (isAbortError(err)) return;
        if (!cancelled) setState({ kind: "error" });
      } finally {
        if (!cancelled) timer = setTimeout(tick, POLL_INTERVAL_MS);
      }
    }

    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  const { tone, label } = classify(state);
  const tooltip =
    tone === "auth-off"
      ? "Authentication is disabled. Set API_AUTH_ENABLED=true to require login."
      : undefined;
  return (
    <span className={`header-status ${tone}`} title={tooltip}>
      {label}
    </span>
  );
}
