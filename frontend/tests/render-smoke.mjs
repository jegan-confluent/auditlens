import fs from "node:fs";

const required = [
  "app/dashboard/page.tsx",
  "app/events/page.tsx",
  "app/layout-lab/page.tsx",
  "app/system/page.tsx",
  "components/DecisionBanner.tsx",
  "components/NarrativeStrip.tsx",
  "components/SignalSummaryPanel.tsx",
  "components/FilterBar.tsx",
  "components/AuditEventTable.tsx",
  "components/EventDetailDrawer.tsx",
  "components/EmptyState.tsx",
  "components/ErrorState.tsx",
  "lib/eventFilters.ts"
];

for (const file of required) {
  if (!fs.existsSync(new URL(`../${file}`, import.meta.url))) {
    throw new Error(`Missing frontend file: ${file}`);
  }
}

const filtersSource = fs.readFileSync(new URL("../lib/eventFilters.ts", import.meta.url), "utf8");
if (!filtersSource.includes('params.set("signal_type", value.trim())')) {
  throw new Error("Action Needed quick filter must use signal_type=action_required");
}
if (!filtersSource.includes('params.set("mode", value.trim())')) {
  throw new Error("Mode filter must be passed through as a backend query param");
}
if (!filtersSource.includes('params.set("hide_noise", "true")')) {
  throw new Error("Hide Noise quick filter must use hide_noise=true");
}
if (!filtersSource.includes('impact_type')) {
  throw new Error("Impact filters must be backend-backed query params");
}
const filterBarSource = fs.readFileSync(new URL("../components/FilterBar.tsx", import.meta.url), "utf8");
if (!filterBarSource.includes('label: "Review", patch: { mode: "decision", signal: "attention"')) {
  throw new Error("Review quick filter must use mode-aware attention filters");
}
if (!filtersSource.includes('key === "hide_noise"') || !filtersSource.includes('value === "true"')) {
  throw new Error("Clear/show-noise state must remove signal_type and hide_noise params");
}

const drawerSource = fs.readFileSync(new URL("../components/EventDetailDrawer.tsx", import.meta.url), "utf8");
if (!drawerSource.includes("<details className=\"raw-payload\">")) {
  throw new Error("Raw payload must remain collapsed behind details");
}
for (const text of ["Resource Type", "Environment", "Region"]) {
  if (!drawerSource.includes(text)) {
    throw new Error(`Drawer missing context field: ${text}`);
  }
}

const tableSource = fs.readFileSync(new URL("../components/AuditEventTable.tsx", import.meta.url), "utf8");
if (!tableSource.includes("resource_display_short")) {
  throw new Error("Table must prefer resource_display_short");
}
if (!tableSource.includes("event.resource_name && event.resource_name !==")) {
  throw new Error("Table must prefer primary resource_name when available");
}
if (!tableSource.includes("actor_display_name") || !tableSource.includes("actor_raw_id")) {
  throw new Error("Table must show enriched actor display with raw ID fallback");
}
if (!tableSource.includes("No source IP / context:") || !tableSource.includes("No source IP in audit event")) {
  throw new Error("Source/IP column must clearly label missing IP fallback");
}
if (!tableSource.includes("triage_status")) {
  throw new Error("Table must render triage status");
}

const apiSource = fs.readFileSync(new URL("../lib/api.ts", import.meta.url), "utf8");
if (!apiSource.includes("/triage") || !apiSource.includes("updateEventTriage")) {
  throw new Error("Frontend must support triage lifecycle updates");
}

if (tableSource.includes("Unknown source") || drawerSource.includes("Unknown source")) {
  throw new Error("UI must not use misleading Unknown source label");
}

const decisionSource = fs.readFileSync(new URL("../components/DecisionBanner.tsx", import.meta.url), "utf8");
for (const text of ["Critical activity detected", "Changes detected", "Investigate critical events", "Show changes to review", "Show full audit trail"]) {
  if (!decisionSource.includes(text)) {
    throw new Error(`Decision banner missing CTA/copy: ${text}`);
  }
}

const signalSource = fs.readFileSync(new URL("../components/SignalSummaryPanel.tsx", import.meta.url), "utf8");
if (!signalSource.includes("Filter by this activity") || !signalSource.includes("filterPreview") || !signalSource.includes("Open details only")) {
  throw new Error("Flow cards must show filter preview and truthful action copy");
}

const eventsSource = fs.readFileSync(new URL("../app/events/page.tsx", import.meta.url), "utf8");
if (!eventsSource.includes("Decision mode. Routine informational activity is hidden.") || !eventsSource.includes("Show all activity") || !eventsSource.includes("Back to decision mode")) {
  throw new Error("Events page must expose decision mode and audit trail controls");
}
if (!eventsSource.includes("Show only destructive changes")) {
  throw new Error("Events page must expose destructive activity CTA");
}
const emptySource = fs.readFileSync(new URL("../components/EmptyState.tsx", import.meta.url), "utf8");
if (!emptySource.includes("Show all activity") || !emptySource.includes("Reset to decision mode")) {
  throw new Error("Empty state must explain filter recovery actions");
}
if (!filtersSource.includes('mode: "decision"') || !filtersSource.includes('mode: "audit_trail"')) {
  throw new Error("Default filters must expose decision and audit trail modes");
}
if (!filtersSource.includes('limit: "50"')) {
  throw new Error("Events page must fetch only 50 rows initially");
}
if (!filtersSource.includes("Decision mode") || !filtersSource.includes("Full audit trail mode")) {
  throw new Error("Active filter labels must be human-readable");
}
if (!eventsSource.includes("Decision mode is active. Routine informational activity is hidden.") || !eventsSource.includes("Full audit trail mode is active. Routine read/list activity is included.")) {
  throw new Error("Events page must explain mode visibility");
}

console.log("frontend smoke checks passed");
