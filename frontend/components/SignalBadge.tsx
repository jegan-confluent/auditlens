"use client";

import { getSignalLabel } from "../lib/signals";

const SIGNAL_CONFIG: Record<string, { color: string; bg: string; border: string }> = {
  action_required: { color: "var(--danger)", bg: "var(--danger-soft)", border: "#fecdca" },
  attention:       { color: "var(--warn)",   bg: "var(--warn-soft)",   border: "#fedf89" },
  informational:   { color: "var(--accent)", bg: "var(--accent-soft)", border: "#99c4c4" },
  noise:           { color: "var(--muted)",  bg: "#f2f4f7",            border: "var(--line)" },
};

export default function SignalBadge({
  signal,
  size = "sm",
}: {
  signal: string | null | undefined;
  size?: "sm" | "md";
}) {
  if (!signal) return null;
  const cfg = SIGNAL_CONFIG[signal];
  if (!cfg) return null;
  const pad = size === "md" ? "4px 10px" : "2px 7px";
  const fontSize = size === "md" ? 12 : 11;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        borderRadius: 999,
        padding: pad,
        fontSize,
        fontWeight: 700,
        letterSpacing: "0.04em",
        color: cfg.color,
        background: cfg.bg,
        border: `1px solid ${cfg.border}`,
        whiteSpace: "nowrap",
        lineHeight: 1.3,
      }}
    >
      {getSignalLabel(signal).toUpperCase()}
    </span>
  );
}
