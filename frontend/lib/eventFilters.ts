export type EventFilters = {
  mode: "decision" | "audit_trail";
  time_window: string;
  resource_type: string;
  resource: string;
  cluster_name: string;
  environment_name: string;
  action_category: string;
  actor: string;
  result: string;
  signal: string;
  hide_noise: string;
  impact_type: string;
};

// Default landing state = "Needs Attention": last 12h, decision-mode, only
// action_required + attention signals, with routine noise hidden. The user
// can switch to the full audit trail with a single click.
export const defaultFilters: EventFilters = {
  mode: "decision",
  time_window: "12h",
  resource_type: "",
  resource: "",
  cluster_name: "",
  environment_name: "",
  action_category: "",
  actor: "",
  result: "",
  signal: "action_required,attention",
  hide_noise: "true",
  impact_type: ""
};

export const allActivityFilters: EventFilters = {
  mode: "audit_trail",
  time_window: "7d",
  resource_type: "",
  resource: "",
  cluster_name: "",
  environment_name: "",
  action_category: "",
  actor: "",
  result: "",
  signal: "",
  hide_noise: "false",
  impact_type: ""
};

const RESULT_TO_QUERY: Record<string, { result?: string; is_denied?: string }> = {
  Success: { result: "Success" },
  Failure: { result: "Failure" },
  // The DB stores result in {Success, Failure} — denied events carry
  // is_denied=true in addition to is_failure. We translate the "Denied"
  // dropdown selection into the boolean filter so the user gets exactly
  // those rows.
  Denied: { is_denied: "true" }
};

// Backend `time_window` only accepts Nm/Nh (regex ^[1-9][0-9]*[mh]$). The UI
// exposes 7d / 30d for ergonomics; translate to hours before sending.
function encodeTimeWindow(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "";
  if (trimmed.endsWith("d")) {
    const days = Number(trimmed.slice(0, -1));
    if (Number.isFinite(days) && days > 0) {
      return `${Math.round(days * 24)}h`;
    }
  }
  return trimmed;
}

export function paramsFromFilters(filters: EventFilters, offset = 0) {
  const params = new URLSearchParams({ limit: "50", offset: String(offset) });
  Object.entries(filters).forEach(([key, value]) => {
    if (key === "mode") {
      if (value.trim()) params.set("mode", value.trim());
      return;
    }
    if (key === "signal") {
      if (value.trim()) params.set("signal_type", value.trim());
      return;
    }
    if (key === "hide_noise") {
      if (value === "true") params.set("hide_noise", "true");
      return;
    }
    if (key === "result") {
      const trimmed = value.trim();
      if (!trimmed) return;
      const mapped = RESULT_TO_QUERY[trimmed];
      if (mapped?.result) params.set("result", mapped.result);
      if (mapped?.is_denied) params.set("is_denied", mapped.is_denied);
      return;
    }
    if (key === "time_window") {
      const encoded = encodeTimeWindow(value);
      if (encoded) params.set("time_window", encoded);
      return;
    }
    if (value.trim()) params.set(key, value.trim());
  });
  return params;
}

export function summaryParamsFromFilters(filters: EventFilters) {
  const params = paramsFromFilters(filters, 0);
  params.delete("limit");
  params.delete("offset");
  return params;
}

export function activeFilterLabels(filters: EventFilters) {
  const labelFor = (key: string, value: string) => {
    if (key === "mode" && value === "decision") return "Decision mode";
    if (key === "mode" && value === "audit_trail") return "Full audit trail mode";
    if (key === "time_window" && value === "1h") return "Last hour";
    if (key === "time_window" && value === "6h") return "Last 6 hours";
    if (key === "time_window" && value === "12h") return "Last 12 hours";
    if (key === "time_window" && value === "24h") return "Last 24 hours";
    if (key === "time_window" && value === "7d") return "Last 7 days";
    if (key === "time_window" && value === "30d") return "Last 30 days";
    if (key === "time_window" && value.endsWith("h")) return `Last ${value.slice(0, -1)} hours`;
    if (key === "time_window" && value.endsWith("d")) return `Last ${value.slice(0, -1)} days`;
    if (key === "signal" && value === "action_required,attention") return "Needs attention";
    if (key === "signal" && value === "action_required") return "Action needed";
    if (key === "signal" && value === "attention") return "Needs review";
    if (key === "signal" && value === "informational") return "Informational";
    if (key === "signal" && value === "noise") return "Noise";
    if (key === "hide_noise" && value === "true") return "Routine noise hidden";
    if (key === "impact_type" && value === "destructive") return "Destructive activity";
    if (key === "impact_type" && value === "configuration_change") return "Configuration changes";
    if (key === "impact_type" && value === "access_change") return "Access changes";
    if (key === "cluster_name") return `Cluster: ${value}`;
    if (key === "environment_name") return `Environment: ${value}`;
    return `${key.replace("_", " ")}: ${value}`;
  };
  return Object.entries(filters)
    .filter(([key, value]) => value && !(key === "hide_noise" && value === "false"))
    .map(([key, value]) => labelFor(key, value));
}

export function applyQuickFilter(filters: EventFilters, patch: Partial<EventFilters>) {
  return { ...filters, ...patch };
}
