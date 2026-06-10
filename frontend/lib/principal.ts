// Canonical principal display helpers — single source of truth for
// resolving raw audit actor IDs to a human-readable string.
//
// Priority order in displayActor():
//   1. actor_display_name (resolved IAM name, e.g. "Jegan Nagarajan")
//   2. actor_email        (e.g. "jnagarajan@confluent.io")
//   3. stripped prefix on raw actor / subject ("User:u-xxxx" → "u-xxxx")
//   4. raw actor as final fallback
//
// Helpers always return a non-null string. JSON-blob actors (the
// "externalAccount" pattern that Confluent's internal services emit)
// collapse to "Confluent (platform)" so the UI never renders a brace.

export const UNKNOWN_PRINCIPAL_LABELS = new Set([
  "unknown actor",
  "unknown user",
  "unknown service account",
  "unknown principal",
]);

export const SERVICE_ACCOUNT_TYPES = new Set([
  "service_account",
  "serviceaccount",
  "service-account",
]);

export type PrincipalLike = {
  actor?: string | null;
  actor_display_name?: string | null;
  actor_email?: string | null;
  actor_raw_id?: string | null;
  actor_type?: string | null;
  subject?: string | null;
  subject_type?: string | null;
};

export function looksLikeJsonActor(value: string | null | undefined): boolean {
  if (!value) return false;
  const trimmed = value.trim();
  return trimmed.startsWith("{") || trimmed.startsWith("[");
}

export function isUnknownLabel(value: string | null | undefined): boolean {
  if (!value) return false;
  return UNKNOWN_PRINCIPAL_LABELS.has(value.trim().toLowerCase());
}

// "User:u-abc" → "u-abc"; "ServiceAccount:sa-1" → "sa-1"; anything else
// returned verbatim.
export function stripPrincipalPrefix(value: string | null | undefined): string {
  const text = (value || "").trim();
  if (text.startsWith("User:")) return text.slice(5);
  if (text.startsWith("ServiceAccount:")) return text.slice(15);
  return text;
}

export function isEnrichedDisplay(
  display: string | null | undefined,
  raw: string | null | undefined,
): boolean {
  if (!display) return false;
  const d = display.trim();
  if (!d) return false;
  if (raw && d === raw) return false;
  if (looksLikeJsonActor(d)) return false;
  return !isUnknownLabel(d);
}

export function isServiceAccountActor(event: PrincipalLike): boolean {
  const type = (event.actor_type || event.subject_type || "").toLowerCase();
  if (SERVICE_ACCOUNT_TYPES.has(type)) return true;
  const raw = (event.actor_raw_id || event.actor || "").toLowerCase();
  return raw.startsWith("sa-") || raw.startsWith("user:sa-");
}

export function isPlatformActor(event: PrincipalLike): boolean {
  const display = (event.actor_display_name || "").trim();
  const raw = (event.actor_raw_id || event.subject || event.actor || "").trim();
  return looksLikeJsonActor(display) || looksLikeJsonActor(raw);
}

// Resolution priority — always returns a non-empty string.
export function displayActor(event: PrincipalLike): string {
  if (isPlatformActor(event)) return "Confluent (platform)";
  const display = (event.actor_display_name || "").trim();
  const raw = (event.actor_raw_id || event.subject || event.actor || "").trim();
  const email = (event.actor_email || "").trim();
  if (isEnrichedDisplay(display, raw)) return display;
  if (email) return email;
  const stripped = stripPrincipalPrefix(raw);
  if (stripped) return stripped;
  return event.actor || "Unknown actor";
}

// Raw principal ID for use as a tooltip / secondary label. Returns ""
// when there's nothing useful to surface beyond the primary display.
export function actorTooltip(event: PrincipalLike): string {
  const raw = (event.actor_raw_id || event.subject || event.actor || "").trim();
  if (!raw) return "";
  if (looksLikeJsonActor(raw)) return "";
  return raw;
}
