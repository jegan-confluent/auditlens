"use client";

import { useEffect, useState } from "react";
import { getReadinessStatus } from "../lib/api";

type HeaderState = "connected" | "degraded" | "down";

function labelForState(state: HeaderState) {
  if (state === "connected") return "Connected";
  if (state === "degraded") return "Degraded";
  return "Down";
}

export default function HeaderStatus() {
  const [state, setState] = useState<HeaderState>("degraded");

  useEffect(() => {
    let cancelled = false;
    getReadinessStatus().then((ready) => {
      if (cancelled) return;
      if (ready.ok) setState("connected");
      else if (ready.status === 0) setState("down");
      else setState("degraded");
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return <span className={`header-status ${state}`}>{labelForState(state)}</span>;
}
