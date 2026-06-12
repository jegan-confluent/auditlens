// Canonical signal-tier display mapping.
//
// Internal enum values (DB columns, API responses, classifier output) stay
// as `action_required` / `attention` / `informational` / `noise`. Only the
// human-readable labels rendered in the UI use the names below.

export const SIGNAL_DISPLAY_LABELS: Record<string, string> = {
  action_required: "Critical",
  attention: "High",
  informational: "Medium",
  noise: "Info",
};

export const SIGNAL_COLORS: Record<string, string> = {
  action_required: "red",
  attention: "amber",
  informational: "blue",
  noise: "gray",
};

export function getSignalLabel(signal: string): string {
  return SIGNAL_DISPLAY_LABELS[signal] ?? signal;
}
