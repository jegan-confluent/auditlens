"use client";

import { useEffect, useState } from "react";
import { getForwarderHealth, isAbortError } from "../lib/api";
import type { ForwarderHealth } from "../lib/types";

type Tone = "loading" | "connected" | "degraded" | "critical" | "down";

const POLL_INTERVAL_MS = 30_000;
const HIGH_LAG_THRESHOLD = 100_000;
const SLOW_PROCESSING_THRESHOLD = 10;

function compactNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function classify(health: ForwarderHealth | null): { tone: Tone; label: string } {
  if (health === null) return { tone: "loading", label: "Connecting…" };

  const errorOnFetch = !!health.error;
  const consumerState = health.observability?.consumer_runtime?.consumer_state;
  const apiAlive = !errorOnFetch && health.status === "healthy";

  // Down: API call to forwarder failed entirely OR consumer can't connect.
  if (errorOnFetch || consumerState === "down" || consumerState === "disconnected") {
    return { tone: "down", label: "Down" };
  }

  const lag = typeof health.consumer_lag === "number" ? health.consumer_lag : 0;
  const rate = typeof health.processing_rate === "number" ? health.processing_rate : 0;
  const storageMode = health.observability?.persistence_storage?.storage_mode;
  const dbWriterState = health.observability?.db_writer?.db_writer_state;

  const storageCritical = storageMode === "critical" || storageMode === "emergency";
  const dbWriterDown = health.observability?.db_writer?.enabled === true && dbWriterState !== "connected";

  if (storageCritical || dbWriterDown || !apiAlive) {
    return { tone: "critical", label: lag > 0 ? `Critical · ${compactNumber(lag)} lag` : "Critical" };
  }

  if (lag > HIGH_LAG_THRESHOLD || rate < SLOW_PROCESSING_THRESHOLD || storageMode === "warning") {
    return { tone: "degraded", label: lag > HIGH_LAG_THRESHOLD ? `Degraded · ${compactNumber(lag)} lag` : "Degraded" };
  }

  return { tone: "connected", label: "Connected" };
}

export default function HeaderStatus() {
  const [health, setHealth] = useState<ForwarderHealth | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function tick() {
      const controller = new AbortController();
      try {
        const next = await getForwarderHealth(controller.signal);
        if (!cancelled) setHealth(next);
      } catch (err) {
        if (isAbortError(err)) return;
        if (!cancelled) setHealth({ status: "unknown", error: String(err) });
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

  const { tone, label } = classify(health);
  return <span className={`header-status ${tone}`}>{label}</span>;
}
