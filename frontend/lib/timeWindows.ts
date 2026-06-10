// Canonical time-window defaults shared across pages.
//
// Why one module: each page used to hardcode its own default ("24h",
// "12h", "1d", "7d") which made the dashboard / events / actor activity
// panel disagree on what "default" means. Pin it here.

export const DEFAULT_TIME_WINDOW = "24h" as const;

export const TIME_WINDOW_OPTIONS = [
  { label: "Last 1h", value: "1h" },
  { label: "Last 6h", value: "6h" },
  { label: "Last 24h", value: "24h" },
  { label: "Last 7d", value: "7d" },
  { label: "Last 30d", value: "30d" },
] as const;

export type TimeWindowOption = typeof TIME_WINDOW_OPTIONS[number]["value"];
