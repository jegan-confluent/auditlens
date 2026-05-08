"use client";

import { useEffect, useState } from "react";
import { getReadinessStatus, isAbortError } from "../lib/api";

type HeaderState = "loading" | "connected" | "degraded" | "down";

function labelForState(state: HeaderState) {
  if (state === "loading") return "Connecting…";
  if (state === "connected") return "Connected";
  if (state === "degraded") return "Degraded";
  return "Down";
}

export default function HeaderStatus() {
  const [state, setState] = useState<HeaderState>("loading");

  useEffect(() => {
    const controller = new AbortController();
    getReadinessStatus(controller.signal)
      .then((ready) => {
        if (ready.ok) setState("connected");
        else if (ready.status === 0) setState("down");
        else setState("degraded");
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setState("down");
      });
    return () => controller.abort();
  }, []);

  return <span className={`header-status ${state}`}>{labelForState(state)}</span>;
}
